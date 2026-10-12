import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

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
    """Claim the oldest runnable job while respecting global serial keys.

    Commit ownership before returning the job.
    Return None when no candidate is available or a serial-key race is lost.
    """
    if not worker_id.strip():
        raise ValueError("worker_id must not be empty")

    if len(worker_id) > 128:
        raise ValueError("worker_id must not exceed 128 characters")

    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")

    running_job = aliased(Job)
    running_with_same_key = (
        select(running_job.id)
        .where(
            running_job.status == JobStatus.RUNNING,
            running_job.serial_key == Job.serial_key,
        )
        .correlate(Job)
        .exists()
    )

    try:
        async with factory.begin() as session:
            statement = (
                select(Job)
                .where(
                    Job.queue == queue,
                    Job.status == JobStatus.QUEUED,
                    Job.run_after <= func.clock_timestamp(),
                    Job.attempts < Job.max_attempts,
                    or_(
                        Job.serial_key.is_(None),
                        ~running_with_same_key,
                    ),
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

    except IntegrityError as exc:
        if _is_running_serial_conflict(exc):
            return None
        raise

    return job


def _is_running_serial_conflict(exc: IntegrityError) -> bool:
    """Identify a running serial-key unique violation from the asyncpg driver."""
    driver_error = getattr(exc.orig, "__cause__", None)
    return (
        getattr(driver_error, "sqlstate", None) == "23505"
        and getattr(driver_error, "constraint_name", None) == "uq_jobs_running_serial_key"
    )


async def _lock_job(session: AsyncSession, job_id: uuid.UUID) -> None:
    """Lock the job row before evaluating live ownership."""
    locked_id: uuid.UUID | None = await session.scalar(
        select(Job.id).where(Job.id == job_id).with_for_update(of=Job)
    )

    if locked_id is None:
        raise JobOwnershipLostError("Job no longer exists")


async def heartbeat(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    *,
    worker_id: str,
    attempt: int,
    lease_seconds: int,
) -> None:
    """Renew the lease only for the matching live job attempt.

    Never shorten an existing lease.
    Raise JobOwnershipLostError when ownership is no longer valid.
    """
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")

    async with factory.begin() as session:
        await _lock_job(session, job_id)

        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING,
                Job.locked_by == worker_id,
                Job.attempts == attempt,
                Job.lease_expires_at > func.clock_timestamp(),
            )
            .values(
                lease_expires_at=func.greatest(
                    Job.lease_expires_at,
                    func.clock_timestamp() + timedelta(seconds=lease_seconds),
                ),
            )
            .returning(Job.id)
            .execution_options(synchronize_session=False)
        )

        updated_id: uuid.UUID | None = await session.scalar(statement)

        if updated_id is None:
            raise JobOwnershipLostError("The worker no longer owns this job attempt")


async def complete(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    result: dict[str, Any],
    *,
    worker_id: str,
    attempt: int,
) -> None:
    """Complete only the matching live job attempt.

    Store the result, release ownership, and set finished_at.
    Raise JobOwnershipLostError when ownership is no longer valid.
    """
    async with factory.begin() as session:
        await _lock_job(session, job_id)

        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING,
                Job.locked_by == worker_id,
                Job.attempts == attempt,
                Job.lease_expires_at > func.clock_timestamp(),
            )
            .values(
                status=JobStatus.SUCCEEDED,
                result=result,
                finished_at=func.clock_timestamp(),
                locked_by=None,
                lease_expires_at=None,
                delivered=False,
            )
            .returning(Job.id)
            .execution_options(synchronize_session=False)
        )

        updated_id: uuid.UUID | None = await session.scalar(statement)

        if updated_id is None:
            raise JobOwnershipLostError("The worker no longer owns this job attempt")


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
    """Retry or fail only the matching live job attempt.

    Release ownership without incrementing attempts.
    Raise JobOwnershipLostError when ownership is no longer valid.
    """
    if backoff < timedelta(0):
        raise ValueError("backoff must not be negative")

    async with factory.begin() as session:
        await _lock_job(session, job_id)

        max_attempts: int = (
            await session.execute(select(Job.max_attempts).where(Job.id == job_id))
        ).scalar_one()

        should_retry = retryable and attempt < max_attempts

        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING,
                Job.locked_by == worker_id,
                Job.attempts == attempt,
                Job.lease_expires_at > func.clock_timestamp(),
            )
            .values(
                status=JobStatus.QUEUED if should_retry else JobStatus.FAILED,
                run_after=(func.clock_timestamp() + backoff if should_retry else Job.run_after),
                last_error=error,
                locked_by=None,
                lease_expires_at=None,
                finished_at=None if should_retry else func.clock_timestamp(),
                result=None,
                delivered=False,
            )
            .returning(Job.id)
            .execution_options(synchronize_session=False)
        )

        updated_id: uuid.UUID | None = await session.scalar(statement)

        if updated_id is None:
            raise JobOwnershipLostError("The worker no longer owns this job attempt")


async def reclaim_expired(factory: async_sessionmaker[AsyncSession], queue: JobQueue) -> int:
    """TODO: return jobs with an expired lease to the queue (or fail them when out of attempts)."""
    raise NotImplementedError
