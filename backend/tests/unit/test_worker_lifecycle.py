"""Lease supervision, cancellation and terminal-write coordination without subprocess timing."""

from __future__ import annotations

import asyncio
import errno
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import WorkerSettings
from app.db.models import Job
from app.jobs import queue
from app.jobs.queue import JobOwnershipLostError
from tests.designs import minimal_profile
from tests.profile_jobs import make_profile_job
from worker import lifecycle, main
from worker.runner import ProfileExecutionError

if TYPE_CHECKING:
    from pathlib import Path

    from app.ingest.storage import Storage


@dataclass
class Harness:
    factory: async_sessionmaker[AsyncSession]
    storage: Storage
    settings: WorkerSettings
    job: Job
    shutdown: asyncio.Event
    heartbeat: AsyncMock
    complete: AsyncMock
    fail: AsyncMock

    async def execute(self) -> None:
        await lifecycle.execute_job(
            self.factory, self.storage, self.settings, self.job, shutdown=self.shutdown
        )


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    storage, prepared = make_profile_job(tmp_path)
    heartbeat = AsyncMock()
    complete = AsyncMock()
    fail = AsyncMock()
    monkeypatch.setattr(queue, "heartbeat", heartbeat)
    monkeypatch.setattr(queue, "complete", complete)
    monkeypatch.setattr(queue, "fail", fail)
    monkeypatch.setattr(lifecycle, "prepare_profile_job", AsyncMock(return_value=prepared))
    monkeypatch.setattr(
        lifecycle, "run_profile", lambda *args, **kwargs: minimal_profile().model_dump(mode="json")
    )
    return Harness(
        async_sessionmaker(expire_on_commit=False),
        storage,
        WorkerSettings(
            _env_file=None,
            worker_id="worker-test",
            lease_seconds=2,
            heartbeat_interval_seconds=0.02,
            database_timeout_seconds=0.1,
        ),
        Job(id=uuid4(), run_id=uuid4(), kind="profile", attempts=3),
        asyncio.Event(),
        heartbeat,
        complete,
        fail,
    )


async def test_success_uses_claimed_attempt_and_plain_profile(harness: Harness) -> None:
    await harness.execute()
    harness.heartbeat.assert_awaited()
    harness.complete.assert_awaited_once_with(
        harness.factory,
        harness.job.id,
        minimal_profile().model_dump(mode="json"),
        worker_id="worker-test",
        attempt=3,
    )
    harness.fail.assert_not_awaited()


async def test_unsupported_kind_is_terminal(harness: Harness) -> None:
    harness.job.kind = "dbt_build"
    await harness.execute()
    assert harness.fail.await_args is not None
    assert harness.fail.await_args.args[2] == "unsupported_job_kind"
    assert harness.fail.await_args.kwargs == {
        "worker_id": "worker-test",
        "attempt": 3,
        "retryable": False,
    }
    harness.complete.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (ValueError("private payload"), "invalid_profile_input", False),
        (ProfileExecutionError("timeout"), "profile_timeout", False),
        (ProfileExecutionError("child_failed"), "profile_child_failed", False),
        (OSError(errno.EAGAIN, "busy"), "profile_io_error", True),
        (OSError(errno.ENOENT, "missing"), "profile_io_error", False),
        (RuntimeError("unexpected"), "profile_internal_error", False),
    ],
)
async def test_runner_failures_use_queue_policy_without_local_retry(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    code: str,
    retryable: bool,
) -> None:
    calls = 0

    def broken(*args: object, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise error

    monkeypatch.setattr(lifecycle, "run_profile", broken)
    await harness.execute()
    assert calls == 1
    assert harness.fail.await_args is not None
    assert harness.fail.await_args.args[2] == code
    assert harness.fail.await_args.kwargs["retryable"] is retryable
    harness.complete.assert_not_awaited()


def blocked_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[asyncio.Event, threading.Event]:
    started = asyncio.Event()
    ended = threading.Event()
    loop = asyncio.get_running_loop()

    def blocked(*args: object, **kwargs: Any) -> dict[str, Any]:
        stop: threading.Event = kwargs["stop_event"]
        loop.call_soon_threadsafe(started.set)
        try:
            if not stop.wait(5):
                raise RuntimeError("Runner was not stopped")
            raise ProfileExecutionError("cancelled")
        finally:
            ended.set()

    monkeypatch.setattr(lifecycle, "run_profile", blocked)
    return started, ended


async def test_heartbeat_runs_during_preparation(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, prepared = make_profile_job(harness.storage.root / "other")

    async def prepare(*args: object, **kwargs: Any) -> object:
        await asyncio.sleep(0.15)
        assert harness.heartbeat.await_count >= 3
        return prepared

    monkeypatch.setattr(lifecycle, "prepare_profile_job", prepare)
    await harness.execute()
    harness.complete.assert_awaited_once()


async def test_lost_heartbeat_stops_runner_without_terminal_write(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, ended = blocked_runner(monkeypatch)

    async def beat(*args: object, **kwargs: Any) -> None:
        if harness.heartbeat.await_count > 1:
            await started.wait()
            raise JobOwnershipLostError("Lost attempt")

    harness.heartbeat.side_effect = beat
    await asyncio.wait_for(harness.execute(), timeout=2)
    assert ended.is_set()
    harness.complete.assert_not_awaited()
    harness.fail.assert_not_awaited()


async def test_heartbeat_database_timeout_stops_runner(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, ended = blocked_runner(monkeypatch)

    async def beat(*args: object, **kwargs: Any) -> None:
        if harness.heartbeat.await_count > 1:
            await started.wait()
            await asyncio.Event().wait()

    harness.heartbeat.side_effect = beat
    await asyncio.wait_for(harness.execute(), timeout=2)
    assert ended.is_set()
    harness.fail.assert_not_awaited()
    harness.complete.assert_not_awaited()


async def test_shutdown_waits_for_runner_then_releases_job(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, ended = blocked_runner(monkeypatch)
    task = asyncio.create_task(harness.execute())
    await asyncio.wait_for(started.wait(), timeout=2)
    harness.shutdown.set()
    await asyncio.wait_for(task, timeout=2)
    assert ended.is_set()
    assert harness.fail.await_args is not None
    assert harness.fail.await_args.args[2] == "worker_shutdown"
    assert harness.fail.await_args.kwargs["retryable"] is True
    harness.complete.assert_not_awaited()


async def test_task_cancellation_joins_thread_and_leaves_lease_recovery(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, ended = blocked_runner(monkeypatch)
    task = asyncio.create_task(harness.execute())
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ended.is_set()
    harness.fail.assert_not_awaited()
    harness.complete.assert_not_awaited()


async def test_uncertain_complete_does_not_fail_or_repeat_runner(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    harness.complete.side_effect = SQLAlchemyError("private database credentials")
    await harness.execute()
    harness.complete.assert_awaited_once()
    harness.fail.assert_not_awaited()
    assert "private database credentials" not in caplog.text


async def test_stale_complete_does_not_fall_back_to_fail(harness: Harness) -> None:
    harness.complete.side_effect = JobOwnershipLostError("Attempt was replaced")
    await harness.execute()
    harness.fail.assert_not_awaited()


async def test_terminal_write_stops_heartbeat_without_reporting_lost_ownership(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    terminal = False

    async def beat(*args: object, **kwargs: Any) -> None:
        if terminal:
            raise JobOwnershipLostError("Terminal")

    async def complete(*args: object, **kwargs: Any) -> None:
        nonlocal terminal
        await asyncio.sleep(0.06)
        terminal = True

    harness.heartbeat.side_effect = beat
    harness.complete.side_effect = complete
    await harness.execute()
    assert terminal
    assert "ownership lost" not in caplog.text
    harness.fail.assert_not_awaited()


async def test_polling_retries_database_outage_and_can_be_stopped(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    async def reclaim(*args: object, **kwargs: Any) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SQLAlchemyError("unavailable")
        harness.shutdown.set()
        return 0

    claim = AsyncMock()
    monkeypatch.setattr(queue, "reclaim_expired", reclaim)
    monkeypatch.setattr(queue, "claim_next", claim)
    harness.settings.poll_interval_seconds = 0.01
    await main.poll_jobs(
        harness.factory, harness.storage, harness.settings, shutdown=harness.shutdown
    )
    assert calls == 2
    claim.assert_not_awaited()


async def test_run_forever_disposes_engine_after_cancellation(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = AsyncMock()
    polling = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(main, "make_engine", lambda url: engine)
    monkeypatch.setattr(main, "make_sessionmaker", lambda engine: harness.factory)
    monkeypatch.setattr(main, "configure_logging", lambda level: None)
    monkeypatch.setattr(main, "poll_jobs", polling)
    with pytest.raises(asyncio.CancelledError):
        await main.run_forever(harness.settings, shutdown=harness.shutdown)
    engine.dispose.assert_awaited_once()


@pytest.mark.parametrize(
    "values",
    [
        {"worker_id": " "},
        {"poll_interval_seconds": 0},
        {"heartbeat_interval_seconds": float("inf")},
        {"heartbeat_interval_seconds": 299},
        {"database_timeout_seconds": 300},
        {"run_timeout_seconds": 0},
        {"duckdb_threads": 0},
        {"duckdb_memory_mb": 2048},
    ],
)
def test_invalid_worker_budgets_are_rejected(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        WorkerSettings(_env_file=None, **values)
