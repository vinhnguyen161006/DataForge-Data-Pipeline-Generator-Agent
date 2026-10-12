from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Batch,
    Job,
    JobQueue,
    JobStatus,
    PipelineRun,
    Project,
    User,
)
from app.jobs.queue import enqueue

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


@pytest.fixture
async def queue_run(db_session: AsyncSession) -> PipelineRun:
    user = User(email=f"queue-{uuid4().hex}@example.com", password_hash=uuid4().hex)
    db_session.add(user)
    await db_session.flush()

    project = Project(
        slug=f"queue-{uuid4().hex}",
        name="Queue integration project",
        created_by=user.id,
    )
    db_session.add(project)
    await db_session.flush()

    batch = Batch(project_id=project.id)
    db_session.add(batch)
    await db_session.flush()

    run = PipelineRun(
        project_id=project.id,
        batch_id=batch.id,
        request_text="Build the queue integration pipeline",
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
async def test_enqueue_creates_job_with_initial_defaults(
    db_session: AsyncSession, queue: JobQueue
) -> None:
    payload = {"batch": "example", "options": {"threads": 2}, "models": ["orders"]}
    job = await enqueue(db_session, queue=queue, kind="profile", payload=payload)

    assert isinstance(job.id, UUID)
    assert job.queue == queue
    assert job.kind == "profile"
    assert job.payload == payload
    assert job.status == JobStatus.QUEUED
    assert job.attempts == 0
    assert job.max_attempts == 3
    assert job.run_id is None
    assert job.serial_key is None
    assert job.idempotency_key is None
    assert job.locked_by is None
    assert job.lease_expires_at is None
    assert job.result is None
    assert job.last_error is None
    assert job.finished_at is None
    assert job.delivered is False
    assert job.created_at.tzinfo is not None
    assert job.run_after.tzinfo is not None
    db_now = await db_session.scalar(select(func.clock_timestamp()))
    assert isinstance(db_now, datetime)
    assert job.created_at <= db_now
    assert job.run_after <= db_now

    await db_session.refresh(job)
    assert job.payload == payload
    assert job.status == JobStatus.QUEUED


async def test_enqueue_preserves_explicit_fields_and_run_reference(
    db_session: AsyncSession, queue_run: PipelineRun
) -> None:
    key = f"enqueue-{uuid4().hex}"
    serial_key = f"pipeline:{queue_run.project_id}"
    payload = {"run_id": str(queue_run.id), "enabled": True, "optional": None}
    job = await enqueue(
        db_session,
        queue=JobQueue.SANDBOX,
        kind="dbt_build",
        payload=payload,
        run_id=queue_run.id,
        serial_key=serial_key,
        idempotency_key=key,
        max_attempts=7,
    )

    await db_session.refresh(job)
    assert job.queue == JobQueue.SANDBOX
    assert job.kind == "dbt_build"
    assert job.payload == payload
    assert job.run_id == queue_run.id
    assert job.serial_key == serial_key
    assert job.idempotency_key == key
    assert job.max_attempts == 7
    assert job.attempts == 0


async def test_enqueue_accepts_one_maximum_attempt(db_session: AsyncSession) -> None:
    job = await enqueue(
        db_session, queue=JobQueue.SANDBOX, kind="profile", payload={}, max_attempts=1
    )
    assert job.max_attempts == 1
    assert job.attempts == 0


async def test_enqueue_without_key_creates_distinct_jobs(db_session: AsyncSession) -> None:
    first = await enqueue(db_session, queue=JobQueue.SANDBOX, kind="profile", payload={})
    second = await enqueue(db_session, queue=JobQueue.SANDBOX, kind="profile", payload={})

    assert first.id != second.id
    count = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.id.in_([first.id, second.id]))
    )
    assert count == 2


async def test_enqueue_same_key_returns_one_job(db_session: AsyncSession) -> None:
    key = f"enqueue-{uuid4().hex}"
    first = await enqueue(
        db_session, queue=JobQueue.SANDBOX, kind="profile", payload={}, idempotency_key=key
    )
    second = await enqueue(
        db_session, queue=JobQueue.SANDBOX, kind="profile", payload={}, idempotency_key=key
    )

    assert first.id == second.id
    count = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.idempotency_key == key)
    )
    assert count == 1


async def test_enqueue_distinct_keys_allow_same_payload_and_serial_key(
    db_session: AsyncSession,
) -> None:
    serial_key = f"pipeline:{uuid4()}"
    jobs = [
        await enqueue(
            db_session,
            queue=JobQueue.SANDBOX,
            kind="dbt_build",
            payload={"version": 1},
            serial_key=serial_key,
            idempotency_key=f"enqueue-{uuid4().hex}",
        )
        for _ in range(2)
    ]

    assert jobs[0].id != jobs[1].id
    assert all(job.serial_key == serial_key for job in jobs)
    assert all(job.status == JobStatus.QUEUED for job in jobs)


@pytest.mark.parametrize("job_status", list(JobStatus))
async def test_enqueue_duplicate_preserves_existing_job_and_execution_state(
    db_session: AsyncSession, queue_run: PipelineRun, job_status: JobStatus
) -> None:
    key = f"enqueue-{uuid4().hex}"
    serial_key = f"pipeline:{uuid4()}"
    first = await enqueue(
        db_session,
        queue=JobQueue.SANDBOX,
        kind="dbt_build",
        payload={"version": 1},
        run_id=queue_run.id,
        serial_key=serial_key,
        idempotency_key=key,
        max_attempts=5,
    )
    first.status = job_status
    first.attempts = 2
    first.run_after = datetime.now(UTC) + timedelta(minutes=5)
    first.last_error = "Previous attempt failed"
    if job_status == JobStatus.RUNNING:
        first.locked_by = "queue-test-worker"
        first.lease_expires_at = datetime.now(UTC) + timedelta(minutes=10)
    if job_status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
        first.finished_at = datetime.now(UTC)
        first.delivered = True
    if job_status == JobStatus.SUCCEEDED:
        first.result = {"rows": 42}
    await db_session.flush()

    original_id = first.id
    original_run_after = first.run_after
    original_lease = first.lease_expires_at
    original_finished_at = first.finished_at
    second = await enqueue(
        db_session,
        queue=JobQueue.PUBLISHER,
        kind="publish",
        payload={"version": 999},
        serial_key=f"pipeline:{uuid4()}",
        idempotency_key=key,
        max_attempts=9,
    )

    assert second.id == original_id
    await db_session.refresh(second)
    assert second.queue == JobQueue.SANDBOX
    assert second.kind == "dbt_build"
    assert second.payload == {"version": 1}
    assert second.run_id == queue_run.id
    assert second.serial_key == serial_key
    assert second.idempotency_key == key
    assert second.max_attempts == 5
    assert second.status == job_status
    assert second.attempts == 2
    assert second.run_after == original_run_after
    assert second.last_error == "Previous attempt failed"
    assert second.locked_by == ("queue-test-worker" if job_status == JobStatus.RUNNING else None)
    assert second.lease_expires_at == original_lease
    assert second.finished_at == original_finished_at
    assert second.delivered == (job_status in (JobStatus.SUCCEEDED, JobStatus.FAILED))
    assert second.result == ({"rows": 42} if job_status == JobStatus.SUCCEEDED else None)
    count = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.idempotency_key == key)
    )
    assert count == 1


@pytest.mark.parametrize("max_attempts", [0, -1, -10])
async def test_enqueue_rejects_invalid_attempt_budget_without_losing_pending_work(
    db_session: AsyncSession, max_attempts: int
) -> None:
    valid = await enqueue(db_session, queue=JobQueue.SANDBOX, kind="profile", payload={})
    valid_id = valid.id
    invalid_key = f"enqueue-invalid-{uuid4().hex}"

    with pytest.raises(ValueError, match="max_attempts must be at least 1"):
        await enqueue(
            db_session,
            queue=JobQueue.SANDBOX,
            kind="profile",
            payload={},
            idempotency_key=invalid_key,
            max_attempts=max_attempts,
        )

    assert db_session.is_active
    assert await db_session.get(Job, valid_id) is not None
    count = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.idempotency_key == invalid_key)
    )
    assert count == 0


async def test_enqueue_duplicate_keeps_session_and_unrelated_pending_work_usable(
    db_session: AsyncSession,
) -> None:
    key = f"enqueue-{uuid4().hex}"
    first = await enqueue(
        db_session, queue=JobQueue.SANDBOX, kind="profile", payload={}, idempotency_key=key
    )
    unrelated = await enqueue(
        db_session, queue=JobQueue.PUBLISHER, kind="metabase_sync", payload={}
    )
    unrelated_id = unrelated.id
    duplicate = await enqueue(
        db_session, queue=JobQueue.SANDBOX, kind="profile", payload={}, idempotency_key=key
    )

    assert duplicate.id == first.id
    assert db_session.is_active
    assert await db_session.scalar(select(1)) == 1
    assert await db_session.get(Job, unrelated_id) is not None
    third = await enqueue(db_session, queue=JobQueue.SANDBOX, kind="profile", payload={})
    count = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.id.in_([first.id, unrelated_id, third.id]))
    )
    assert count == 3


async def test_enqueue_propagates_unrelated_foreign_key_violation(
    db_session: AsyncSession,
) -> None:
    key = f"enqueue-{uuid4().hex}"
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await enqueue(
                db_session,
                queue=JobQueue.SANDBOX,
                kind="dbt_build",
                payload={},
                run_id=uuid4(),
                idempotency_key=key,
            )

    assert db_session.is_active
    count = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.idempotency_key == key)
    )
    assert count == 0


@pytest.mark.parametrize("commit", [False, True], ids=["caller-rollback", "caller-commit"])
async def test_enqueue_leaves_commit_and_rollback_to_the_caller(
    session_factory: async_sessionmaker[AsyncSession], commit: bool
) -> None:
    key = f"enqueue-transaction-{uuid4().hex}"
    try:
        async with session_factory() as writer:
            job = await enqueue(
                writer,
                queue=JobQueue.SANDBOX,
                kind="profile",
                payload={"transaction": "caller"},
                idempotency_key=key,
            )
            job_id = job.id
            assert writer.in_transaction()
            assert await writer.get(Job, job_id) is not None
            async with session_factory() as observer:
                assert await observer.get(Job, job_id) is None

            if commit:
                await writer.commit()
            else:
                await writer.rollback()

        async with session_factory() as observer:
            stored = await observer.get(Job, job_id)
            if commit:
                assert stored is not None
                assert stored.payload == {"transaction": "caller"}
            else:
                assert stored is None
    finally:
        async with session_factory.begin() as cleanup:
            await cleanup.execute(delete(Job).where(Job.idempotency_key == key))


async def test_enqueue_returns_a_job_committed_by_another_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    key = f"enqueue-committed-{uuid4().hex}"
    try:
        async with session_factory.begin() as writer:
            original = await enqueue(
                writer,
                queue=JobQueue.SANDBOX,
                kind="profile",
                payload={"source": "first"},
                idempotency_key=key,
            )
            original_id = original.id

        async with session_factory.begin() as reader:
            duplicate = await enqueue(
                reader,
                queue=JobQueue.SANDBOX,
                kind="profile",
                payload={"source": "second"},
                idempotency_key=key,
            )
            assert duplicate.id == original_id
            assert duplicate.payload == {"source": "first"}
            assert reader.is_active

        async with session_factory() as observer:
            jobs = list(await observer.scalars(select(Job).where(Job.idempotency_key == key)))
            assert len(jobs) == 1
            assert jobs[0].id == original_id
            assert jobs[0].payload == {"source": "first"}
    finally:
        async with session_factory.begin() as cleanup:
            await cleanup.execute(delete(Job).where(Job.idempotency_key == key))


async def _wait_for_enqueue_blocker(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    blocker_pid: int,
    waiter_pid: int,
    enqueue_task: asyncio.Task[UUID],
) -> None:
    """Wait for PostgreSQL to confirm a real transaction lock dependency."""
    async with asyncio.timeout(10):
        while True:
            if enqueue_task.done():
                enqueue_task.result()
                pytest.fail("The concurrent enqueue returned before the first transaction ended")

            async with session_factory() as observer:
                blocked = await observer.scalar(
                    text("SELECT :blocker_pid = ANY(pg_blocking_pids(:waiter_pid))"),
                    {"blocker_pid": blocker_pid, "waiter_pid": waiter_pid},
                )
            if blocked:
                return
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("first_commits", [True, False], ids=["first-commits", "first-rolls-back"])
async def test_enqueue_concurrent_same_key_respects_first_transaction_outcome(
    session_factory: async_sessionmaker[AsyncSession], first_commits: bool
) -> None:
    key = f"enqueue-race-{uuid4().hex}"
    second_pid_ready: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    second_task: asyncio.Task[UUID] | None = None

    async def enqueue_second() -> UUID:
        async with session_factory.begin() as second:
            second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(second_pid, int)
            second_pid_ready.set_result(second_pid)
            job = await enqueue(
                second,
                queue=JobQueue.SANDBOX,
                kind="profile",
                payload={"source": "second"},
                idempotency_key=key,
            )
            return job.id

    try:
        async with session_factory() as first:
            first_pid = await first.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(first_pid, int)
            original = await enqueue(
                first,
                queue=JobQueue.SANDBOX,
                kind="profile",
                payload={"source": "first"},
                idempotency_key=key,
            )
            original_id = original.id
            second_task = asyncio.create_task(enqueue_second())
            second_pid = await asyncio.wait_for(second_pid_ready, timeout=10)
            assert second_pid != first_pid

            await _wait_for_enqueue_blocker(
                session_factory,
                blocker_pid=first_pid,
                waiter_pid=second_pid,
                enqueue_task=second_task,
            )

            if first_commits:
                await first.commit()
            else:
                await first.rollback()

            second_id = await asyncio.wait_for(second_task, timeout=10)
            if first_commits:
                assert second_id == original_id
            else:
                assert second_id != original_id

        async with session_factory() as observer:
            jobs = list(await observer.scalars(select(Job).where(Job.idempotency_key == key)))
            assert len(jobs) == 1
            assert jobs[0].id == second_id
            expected_source = "first" if first_commits else "second"
            assert jobs[0].payload == {"source": expected_source}
            assert jobs[0].status == JobStatus.QUEUED
            assert jobs[0].attempts == 0
    finally:
        if second_task is not None:
            if not second_task.done():
                second_task.cancel()
            await asyncio.gather(second_task, return_exceptions=True)
        async with session_factory.begin() as cleanup:
            await cleanup.execute(delete(Job).where(Job.idempotency_key == key))


@pytest.mark.skip(reason="TODO")
async def test_two_workers_never_claim_the_same_job(database_url: str) -> None:
    """TODO: two sessions call claim_next concurrently on one queued job; exactly one wins."""


@pytest.mark.skip(reason="TODO")
async def test_serial_key_blocks_parallel_runs_of_one_pipeline(database_url: str) -> None:
    """TODO: with one running job for a serial_key, a second job with that key stays queued."""


@pytest.mark.skip(reason="TODO")
async def test_expired_lease_is_reclaimed(database_url: str) -> None:
    """TODO: a running job with an expired lease is requeued, or failed when out of attempts."""
