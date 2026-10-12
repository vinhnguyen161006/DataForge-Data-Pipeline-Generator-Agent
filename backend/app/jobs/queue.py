import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Job, JobQueue, JobStatus

if TYPE_CHECKING:
    from datetime import datetime


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
    """Insert a queued job within the caller's transaction.

    Return the existing job unchanged when its idempotency key already exists.
    The caller controls commit and rollback.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    statement = insert(Job).values(
        queue=queue,
        kind=kind,
        payload=payload,
        run_id=run_id,
        serial_key=serial_key,
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
        status=JobStatus.QUEUED,
        attempts=0,
        delivered=False,
    )

    if idempotency_key is not None:
        statement = statement.on_conflict_do_nothing(
            index_elements=[Job.idempotency_key],
        )

    job: Job | None = await session.scalar(statement.returning(Job))

    if job is not None:
        return job

    if idempotency_key is None:
        raise RuntimeError("Job insertion returned no row")

    existing: Job | None = await session.scalar(
        select(Job).where(Job.idempotency_key == idempotency_key)
    )

    if existing is None:
        raise RuntimeError("The conflicting job could not be found")

    return existing


async def claim_next(
    factory: async_sessionmaker[AsyncSession],
    *,
    queue: JobQueue,
    worker_id: str,
    lease_seconds: int,
) -> Job | None:
    """Claim the oldest runnable job without a serial key.

    Commit ownership before returning the job.
    Serial-key scheduling will be added in D4.
    """
    if not worker_id.strip():
        raise ValueError("worker_id must not be empty")

    if len(worker_id) > 128:
        raise ValueError("worker_id must not exceed 128 characters")

    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")

    async with factory.begin() as session:
        statement = (
            select(Job)
            .where(
                Job.queue == queue,
                Job.status == JobStatus.QUEUED,
                Job.run_after <= func.clock_timestamp(),
                Job.attempts < Job.max_attempts,
                Job.serial_key.is_(None),
            )
            .order_by(Job.created_at, Job.id)
            .limit(1)
            .with_for_update(skip_locked=True, of=Job)
        )

        job: Job | None = await session.scalar(statement)

        if job is None:
            return None

        db_now: datetime = (await session.execute(select(func.clock_timestamp()))).scalar_one()

        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.locked_by = worker_id
        job.lease_expires_at = db_now + timedelta(seconds=lease_seconds)

        await session.flush()

    return job


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
