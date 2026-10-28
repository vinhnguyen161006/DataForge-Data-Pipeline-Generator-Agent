"""Supervise one owned sandbox attempt without blocking lease renewal."""

from __future__ import annotations

import asyncio
import errno
import logging
import threading
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

from app.jobs import queue
from app.services.batches import BatchError
from worker.duckdb_runtime import DuckDBLimits
from worker.profile_preparation import prepare_profile_job
from worker.runner import ProfileExecutionError, run_profile
from worker.sandbox import Limits

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.config import WorkerSettings
    from app.db.models import Job
    from app.ingest.storage import Storage

logger = logging.getLogger(__name__)


async def wait_for_stop(stop: asyncio.Event, seconds: float) -> bool:
    """Return whether shutdown was requested before the polling deadline."""
    try:
        async with asyncio.timeout(seconds):
            await stop.wait()
    except TimeoutError:
        return False
    return True


def failure_policy(exc: Exception) -> tuple[str, bool]:
    """Expose bounded error codes and retry only known temporary failures."""
    if isinstance(exc, ProfileExecutionError):
        return f"profile_{exc.code}", False
    if isinstance(exc, BatchError):
        return "invalid_profile_batch", False
    if isinstance(exc, ValueError):
        return "invalid_profile_input", False
    if isinstance(exc, OSError):
        return "profile_io_error", exc.errno in {errno.EAGAIN, errno.EBUSY, errno.ETIMEDOUT}
    return "profile_internal_error", False


class OwnedAttempt:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        storage: Storage,
        settings: WorkerSettings,
        job: Job,
    ) -> None:
        self.factory = factory
        self.storage = storage
        self.settings = settings
        self.job = job
        self.runner_stop = threading.Event()
        self.heartbeat_stop = asyncio.Event()
        self.heartbeat_ready = asyncio.Event()
        self.database_lock = asyncio.Lock()
        self.runner_task: asyncio.Task[dict[str, Any]] | None = None

    async def heartbeat(self) -> None:
        while not self.heartbeat_stop.is_set():
            async with self.database_lock:
                if self.heartbeat_stop.is_set():
                    return
                async with asyncio.timeout(self.settings.database_timeout_seconds):
                    await queue.heartbeat(
                        self.factory,
                        self.job.id,
                        worker_id=self.settings.worker_id,
                        attempt=self.job.attempts,
                        lease_seconds=self.settings.lease_seconds,
                    )
                self.heartbeat_ready.set()
            await wait_for_stop(self.heartbeat_stop, self.settings.heartbeat_interval_seconds)

    async def run(self) -> dict[str, Any]:
        await self.heartbeat_ready.wait()
        if self.job.kind != "profile":
            raise ValueError("Unsupported sandbox job kind")
        async with self.factory() as session:
            prepared = await prepare_profile_job(
                session,
                self.storage,
                job_id=self.job.id,
                worker_id=self.settings.worker_id,
                attempt=self.job.attempts,
            )
        limits = Limits(
            timeout_seconds=self.settings.run_timeout_seconds,
            memory_mb=self.settings.run_memory_mb,
            cpu_seconds=self.settings.run_cpu_seconds,
            max_file_mb=self.settings.run_max_file_mb,
            max_processes=self.settings.run_max_processes,
        )
        duckdb_limits = DuckDBLimits(
            threads=self.settings.duckdb_threads,
            memory_mb=self.settings.duckdb_memory_mb,
            max_temp_mb=self.settings.duckdb_max_temp_mb,
        )
        self.runner_task = asyncio.create_task(
            asyncio.to_thread(
                run_profile,
                prepared,
                limits,
                storage=self.storage,
                duckdb_limits=duckdb_limits,
                stop_event=self.runner_stop,
            )
        )
        return await asyncio.shield(self.runner_task)

    async def stop_work(self, work: asyncio.Task[dict[str, Any]]) -> None:
        self.runner_stop.set()
        if not work.done():
            work.cancel()
        with suppress(Exception, asyncio.CancelledError):
            await work
        if self.runner_task is not None:
            with suppress(Exception, asyncio.CancelledError):
                await self.runner_task

    async def finish(
        self,
        heartbeat: asyncio.Task[None],
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        retryable: bool = False,
    ) -> None:
        async with self.database_lock:
            if heartbeat.done():
                heartbeat.result()
            async with asyncio.timeout(self.settings.database_timeout_seconds):
                if error is None:
                    if result is None:
                        raise ValueError("A successful job requires a result")
                    await queue.complete(
                        self.factory,
                        self.job.id,
                        result,
                        worker_id=self.settings.worker_id,
                        attempt=self.job.attempts,
                    )
                else:
                    await queue.fail(
                        self.factory,
                        self.job.id,
                        error,
                        worker_id=self.settings.worker_id,
                        attempt=self.job.attempts,
                        retryable=retryable,
                    )
            self.heartbeat_stop.set()

    async def cleanup(
        self,
        work: asyncio.Task[dict[str, Any]],
        heartbeat: asyncio.Task[None],
        shutdown: asyncio.Task[bool],
    ) -> None:
        await self.stop_work(work)
        self.heartbeat_stop.set()
        with suppress(Exception, asyncio.CancelledError):
            await heartbeat
        shutdown.cancel()
        with suppress(asyncio.CancelledError):
            await shutdown


async def execute_job(
    factory: async_sessionmaker[AsyncSession],
    storage: Storage,
    settings: WorkerSettings,
    job: Job,
    *,
    shutdown: asyncio.Event,
) -> None:
    """Run one claim; abandon uncertain ownership and leave recovery to the queue."""
    attempt = OwnedAttempt(factory, storage, settings, job)
    heartbeat = asyncio.create_task(attempt.heartbeat())
    work = asyncio.create_task(attempt.run())
    stopping = asyncio.create_task(shutdown.wait())
    fields = {
        "job_id": str(job.id),
        "run_id": str(job.run_id),
        "worker_id": settings.worker_id,
        "attempt": job.attempts,
    }
    logger.info("Sandbox job started", extra=fields)
    try:
        done, _ = await asyncio.wait(
            {work, heartbeat, stopping}, return_when=asyncio.FIRST_COMPLETED
        )
        if heartbeat in done:
            heartbeat.result()
        if shutdown.is_set():
            await attempt.stop_work(work)
            await attempt.finish(heartbeat, error="worker_shutdown", retryable=True)
            logger.info("Sandbox job released during shutdown", extra=fields)
            return
        try:
            result = work.result()
        except (queue.JobOwnershipLostError, SQLAlchemyError, TimeoutError):
            raise
        except Exception as exc:
            error, retryable = failure_policy(exc)
            if job.kind != "profile":
                error = "unsupported_job_kind"
            await attempt.finish(heartbeat, error=error, retryable=retryable)
            logger.warning("Sandbox job failed", extra={**fields, "error_code": error})
        else:
            await attempt.finish(heartbeat, result=result)
            logger.info("Sandbox job completed", extra=fields)
    except queue.JobOwnershipLostError:
        logger.warning("Sandbox job ownership lost", extra=fields)
    except (SQLAlchemyError, TimeoutError):
        logger.warning(
            "Sandbox job database outcome is uncertain; leaving lease recovery", extra=fields
        )
    finally:
        cleanup = asyncio.create_task(attempt.cleanup(work, heartbeat, stopping))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise
