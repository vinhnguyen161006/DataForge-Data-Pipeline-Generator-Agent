import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Job, JobQueue


async def enqueue(
    session: AsyncSession,
    *,
    queue: JobQueue,
    kind: str,
    payload: dict[str, Any],
    run_id: uuid.UUID | None = None,
    serial_key: str | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
) -> Job:
    """TODO: insert a job; return the existing job when idempotency_key already exists."""
    raise NotImplementedError


async def claim_next(
    factory: async_sessionmaker[AsyncSession],
    *,
    queue: JobQueue,
    worker_id: str,
    lease_seconds: int,
) -> Job | None:
    """TODO: claim the oldest runnable job with UPDATE ... FOR UPDATE SKIP LOCKED.

    Skip jobs whose serial_key already has a running job; treat a violation of
    uq_jobs_running_serial_key as "nothing claimed" and let the next poll retry.
    """
    raise NotImplementedError


async def heartbeat(
    factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID, worker_id: str, lease_seconds: int
) -> None:
    """TODO: extend lease_expires_at while this worker still owns the job."""
    raise NotImplementedError


async def complete(
    factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID, result: dict[str, Any]
) -> None:
    """TODO: mark the job succeeded, store result, release the lease."""
    raise NotImplementedError


async def fail(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    error: str,
    *,
    retryable: bool,
    backoff: timedelta = timedelta(seconds=30),
) -> None:
    """TODO: requeue with backoff while attempts remain and error is retryable, else fail."""
    raise NotImplementedError


async def reclaim_expired(factory: async_sessionmaker[AsyncSession], queue: JobQueue) -> int:
    """TODO: return jobs with an expired lease to the queue (or fail them when out of attempts)."""
    raise NotImplementedError
