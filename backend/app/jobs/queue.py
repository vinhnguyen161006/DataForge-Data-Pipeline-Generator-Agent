import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Job, JobQueue


class JobOwnershipLostError(RuntimeError):
    """The worker no longer owns the specified job attempt."""


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
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    *,
    worker_id: str,
    attempt: int,
    lease_seconds: int,
) -> None:
    """TODO: extend the lease only for the matching live job attempt.

    Raise JobOwnershipLostError when ownership is no longer valid.
    """
    raise NotImplementedError


async def complete(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    result: dict[str, Any],
    *,
    worker_id: str,
    attempt: int,
) -> None:
    """TODO: complete only the matching live job attempt.

    Store the result, release ownership, and set finished_at.
    Raise JobOwnershipLostError when ownership is no longer valid.
    """
    raise NotImplementedError


async def fail(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    error: str,
    *,
    worker_id: str,
    attempt: int,
    retryable: bool,
    backoff: timedelta = timedelta(seconds=30),
) -> None:
    """TODO: retry or fail only the matching live job attempt.

    Release ownership without incrementing attempts.
    Raise JobOwnershipLostError when ownership is no longer valid.
    """
    raise NotImplementedError


async def reclaim_expired(factory: async_sessionmaker[AsyncSession], queue: JobQueue) -> int:
    """TODO: return jobs with an expired lease to the queue (or fail them when out of attempts)."""
    raise NotImplementedError
