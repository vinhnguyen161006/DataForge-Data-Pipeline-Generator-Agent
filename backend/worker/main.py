"""Poll the sandbox queue and supervise one owned attempt at a time."""

import asyncio
import logging
import signal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import WorkerSettings
from app.core.logging import configure_logging
from app.db.models import JobQueue
from app.db.session import make_engine, make_sessionmaker
from app.ingest.storage import Storage
from app.jobs import queue
from worker.lifecycle import execute_job, wait_for_stop

logger = logging.getLogger(__name__)


async def poll_jobs(
    factory: async_sessionmaker[AsyncSession],
    storage: Storage,
    settings: WorkerSettings,
    *,
    shutdown: asyncio.Event,
) -> None:
    """Reclaim and claim committed jobs; queue policies own all retries."""
    while not shutdown.is_set():
        try:
            async with asyncio.timeout(settings.database_timeout_seconds):
                await queue.reclaim_expired(factory, JobQueue.SANDBOX)
                if shutdown.is_set():
                    break
                job = await queue.claim_next(
                    factory,
                    queue=JobQueue.SANDBOX,
                    worker_id=settings.worker_id,
                    lease_seconds=settings.lease_seconds,
                )
            if job is not None:
                await execute_job(factory, storage, settings, job, shutdown=shutdown)
                continue
        except (SQLAlchemyError, TimeoutError):
            logger.warning("Sandbox queue unavailable; retrying after poll interval")
        await wait_for_stop(shutdown, settings.poll_interval_seconds)


async def run_forever(settings: WorkerSettings, *, shutdown: asyncio.Event | None = None) -> None:
    """Own database resources and translate process signals into graceful shutdown."""
    configure_logging(settings.log_level)
    stop = shutdown if shutdown is not None else asyncio.Event()
    engine = make_engine(settings.app_database_url)
    installed: list[signal.Signals] = []
    loop = asyncio.get_running_loop()
    try:
        if shutdown is None:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop.set)
                installed.append(sig)
        await poll_jobs(
            make_sessionmaker(engine),
            Storage(settings.storage_root),
            settings,
            shutdown=stop,
        )
    finally:
        for sig in installed:
            loop.remove_signal_handler(sig)
        await engine.dispose()


def main() -> None:
    asyncio.run(run_forever(WorkerSettings()))


if __name__ == "__main__":
    main()
