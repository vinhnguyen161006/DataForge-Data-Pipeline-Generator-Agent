"""Real PostgreSQL claims, lease renewal and subprocess shutdown through the worker loop."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import func, update

from app.core.config import WorkerSettings
from app.db.models import Job, JobQueue, JobStatus
from app.jobs import queue
from app.jobs.queue import JobOwnershipLostError
from app.profiler.schemas import DataProfile
from tests.integration.test_worker_profile import profile_job as profile_job
from worker import lifecycle
from worker.main import poll_jobs
from worker.runner import ProfileExecutionError, run_profile
from worker.sandbox import run_sandboxed

if TYPE_CHECKING:
    from pathlib import Path

    from tests.integration.test_worker_profile import Scenario
    from worker.profile_protocol import PreparedProfileJob
    from worker.sandbox import Limits

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "linux", reason="Linux confined profile child"),
]


def settings() -> WorkerSettings:
    return WorkerSettings(
        _env_file=None,
        worker_id="profile-test",
        lease_seconds=30,
        heartbeat_interval_seconds=0.1,
        database_timeout_seconds=5.0,
        poll_interval_seconds=0.01,
        run_timeout_seconds=20,
        run_cpu_seconds=10,
        run_max_file_mb=32,
    )


async def job_row(scenario: Scenario) -> Job:
    async with scenario.factory() as session:
        job = await session.get(Job, scenario.request.identity.job_id)
    assert job is not None
    return job


def stop_after_complete(monkeypatch: pytest.MonkeyPatch, stop: asyncio.Event) -> None:
    complete = queue.complete

    async def finish(*args: Any, **kwargs: Any) -> None:
        await complete(*args, **kwargs)
        stop.set()

    monkeypatch.setattr(queue, "complete", finish)


async def test_worker_loop_runs_real_profile_and_persists_plain_result(
    profile_job: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = asyncio.Event()
    stop_after_complete(monkeypatch, stop)
    await asyncio.wait_for(
        poll_jobs(profile_job.factory, profile_job.storage, settings(), shutdown=stop), 20
    )
    job = await job_row(profile_job)
    assert job.status is JobStatus.SUCCEEDED
    assert job.attempts == 1
    assert job.locked_by is None
    assert job.lease_expires_at is None
    assert job.delivered is False
    profile = DataProfile.model_validate(job.result)
    assert {table.name: table.row_count for table in profile.tables} == {
        "customers": 2,
        "orders": 3,
    }
    identity = profile_job.request.identity
    workspace = (
        profile_job.storage.workspace_dir(identity.project_id, identity.run_id, identity.job_id)
        / "attempt-0001"
    )
    assert (workspace / "profile.json").is_file()
    assert list(workspace.rglob("*.duckdb"))


async def test_heartbeat_prevents_reclaim_after_initial_lease_expires(
    profile_job: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    release = threading.Event()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def delayed(job: PreparedProfileJob, limits: Limits, **kwargs: Any) -> dict[str, Any]:
        loop.call_soon_threadsafe(started.set)
        if not release.wait(15):
            raise RuntimeError("Test did not release runner")
        return run_profile(job, limits, **kwargs)

    monkeypatch.setattr(lifecycle, "run_profile", delayed)
    stop_after_complete(monkeypatch, stop)
    config = settings()
    config.lease_seconds = 3
    config.database_timeout_seconds = 1.0
    task = asyncio.create_task(
        poll_jobs(profile_job.factory, profile_job.storage, config, shutdown=stop)
    )
    try:
        await asyncio.wait_for(started.wait(), 5)
        await asyncio.sleep(3.2)
        assert await queue.reclaim_expired(profile_job.factory, JobQueue.SANDBOX) == 0
        assert (
            await queue.claim_next(
                profile_job.factory, queue=JobQueue.SANDBOX, worker_id="competitor", lease_seconds=2
            )
            is None
        )
        job = await job_row(profile_job)
        assert job.status is JobStatus.RUNNING
        assert job.attempts == 1
        assert job.lease_expires_at is not None
        assert job.lease_expires_at > datetime.now(UTC)
    finally:
        release.set()
        stop.set()
        await asyncio.wait_for(task, 15)


@pytest.mark.parametrize("reason", ["shutdown", "ownership"])
async def test_supervisor_reaps_real_child_before_returning(
    profile_job: Scenario, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reason: str
) -> None:
    child_root = tmp_path / "blocking-child"
    child_root.mkdir()
    pid_file = child_root / "pid.txt"
    stop = asyncio.Event()
    started = asyncio.Event()
    loop = asyncio.get_running_loop()
    process_id: list[int] = []

    def blocking(job: PreparedProfileJob, limits: Limits, **kwargs: Any) -> dict[str, Any]:
        def report_started() -> None:
            for _ in range(100):
                if pid_file.exists():
                    process_id.append(int(pid_file.read_text()))
                    loop.call_soon_threadsafe(started.set)
                    return
                if kwargs["stop_event"].wait(0.02):
                    return

        reporter = threading.Thread(target=report_started)
        reporter.start()
        try:
            outcome = run_sandboxed(
                [
                    sys.executable,
                    "-c",
                    "import os,time; from pathlib import Path; "
                    "Path('pid.txt').write_text(str(os.getpid())); time.sleep(60)",
                ],
                workspace=child_root,
                limits=limits,
                stop_event=kwargs["stop_event"],
            )
            assert outcome.cancelled
            raise ProfileExecutionError("cancelled")
        finally:
            reporter.join()

    monkeypatch.setattr(lifecycle, "run_profile", blocking)
    job = await profile_job.claim()
    task = asyncio.create_task(
        lifecycle.execute_job(
            profile_job.factory, profile_job.storage, settings(), job, shutdown=stop
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 5)
        if reason == "shutdown":
            stop.set()
        else:
            async with profile_job.factory.begin() as session:
                await session.execute(
                    update(Job)
                    .where(Job.id == job.id)
                    .values(lease_expires_at=func.clock_timestamp())
                )
            assert await queue.reclaim_expired(profile_job.factory, JobQueue.SANDBOX) == 1
            replacement = None
            for _ in range(50):
                replacement = await queue.claim_next(
                    profile_job.factory,
                    queue=JobQueue.SANDBOX,
                    worker_id="replacement",
                    lease_seconds=30,
                )
                if replacement is not None:
                    break
                await asyncio.sleep(0.01)
            assert replacement is not None
            assert replacement.attempts == 2
        await asyncio.wait_for(task, 5)
    finally:
        stop.set()
        await asyncio.wait_for(task, 5)
    assert len(process_id) == 1
    with pytest.raises(ProcessLookupError):
        os.kill(process_id[0], 0)
    stored = await job_row(profile_job)
    assert stored.result is None
    if reason == "shutdown":
        assert stored.status is JobStatus.QUEUED
        assert stored.last_error == "worker_shutdown"
    else:
        assert stored.status is JobStatus.RUNNING
        assert stored.locked_by == "replacement"
        with pytest.raises(JobOwnershipLostError):
            await queue.complete(
                profile_job.factory, job.id, {}, worker_id="profile-test", attempt=1
            )


async def test_expired_claim_is_reclaimed_and_run_in_new_attempt_workspace(
    profile_job: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = await profile_job.claim()
    async with profile_job.factory.begin() as session:
        await session.execute(
            update(Job).where(Job.id == old.id).values(lease_expires_at=func.clock_timestamp())
        )
    stop = asyncio.Event()
    stop_after_complete(monkeypatch, stop)
    await asyncio.wait_for(
        poll_jobs(profile_job.factory, profile_job.storage, settings(), shutdown=stop), 20
    )
    stored = await job_row(profile_job)
    assert stored.status is JobStatus.SUCCEEDED
    assert stored.attempts == 2
    identity = profile_job.request.identity
    workspace = profile_job.storage.workspace_dir(
        identity.project_id, identity.run_id, identity.job_id
    )
    assert (workspace / "attempt-0002" / "profile.json").is_file()
    assert not (workspace / "attempt-0001").exists()
