from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, StatementError

from app.db.models import (
    Batch,
    Job,
    JobQueue,
    JobStatus,
    PipelineRun,
    Project,
    User,
)
from app.jobs.queue import (
    JobOwnershipLostError,
    claim_next,
    complete,
    enqueue,
    heartbeat,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing import Literal

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


@dataclass
class ClaimJobs:
    factory: async_sessionmaker[AsyncSession]
    job_ids: list[UUID] = field(default_factory=list)

    async def clock(self) -> datetime:
        async with self.factory() as session:
            value = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(value, datetime)
        return value

    async def add(
        self,
        *,
        queue: JobQueue = JobQueue.SANDBOX,
        status: JobStatus = JobStatus.QUEUED,
        attempts: int = 0,
        max_attempts: int = 3,
        created_at: datetime | None = None,
        run_after: datetime | None = None,
        job_id: UUID | None = None,
        last_error: str | None = None,
        serial_key: str | None = None,
    ) -> Job:
        """Commit a test job so independent claim connections can see it."""
        selected_id = job_id if job_id is not None else uuid4()
        self.job_ids.append(selected_id)
        async with self.factory.begin() as session:
            now = await session.scalar(select(func.clock_timestamp()))
            assert isinstance(now, datetime)
            job = Job(
                id=selected_id,
                queue=queue,
                kind="profile",
                payload={"test_job": str(selected_id)},
                serial_key=serial_key,
                status=status,
                attempts=attempts,
                max_attempts=max_attempts,
                created_at=created_at if created_at is not None else now,
                run_after=run_after if run_after is not None else now - timedelta(seconds=1),
                last_error=last_error,
            )
            if status == JobStatus.RUNNING:
                job.locked_by = "existing-claim-worker"
                job.lease_expires_at = now + timedelta(minutes=5)
            if status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
                job.finished_at = now
            session.add(job)
            await session.flush()
        return job


@pytest.fixture
async def claim_jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ClaimJobs]:
    """Own committed test jobs without deleting or claiming unrelated queued work."""
    async with session_factory() as observer:
        queued_id = await observer.scalar(
            select(Job.id).where(Job.status == JobStatus.QUEUED).limit(1)
        )
    assert queued_id is None, "Claim tests require a test database with no pre-existing queued jobs"
    scenario = ClaimJobs(session_factory)
    try:
        yield scenario
    finally:
        if scenario.job_ids:
            async with session_factory.begin() as cleanup:
                await cleanup.execute(delete(Job).where(Job.id.in_(scenario.job_ids)))


async def _claim_with_two_workers(claim_jobs: ClaimJobs, queue: JobQueue) -> list[Job | None]:
    barrier = asyncio.Barrier(2)

    async def claim(worker_id: str) -> Job | None:
        await barrier.wait()
        return await claim_next(
            claim_jobs.factory,
            queue=queue,
            worker_id=worker_id,
            lease_seconds=60,
        )

    tasks = [
        asyncio.create_task(claim("claim-worker-0")),
        asyncio.create_task(claim("claim-worker-1")),
    ]
    try:
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
        return list(results)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
async def test_claim_empty_queue_returns_none(claim_jobs: ClaimJobs, queue: JobQueue) -> None:
    result = await asyncio.wait_for(
        claim_next(claim_jobs.factory, queue=queue, worker_id="claim-worker", lease_seconds=60),
        timeout=10,
    )
    assert result is None


@pytest.mark.parametrize(
    ("queue", "lease_seconds"),
    [(JobQueue.SANDBOX, 30), (JobQueue.PUBLISHER, 90)],
)
async def test_claim_commits_ownership_and_returns_readable_job(
    claim_jobs: ClaimJobs, queue: JobQueue, lease_seconds: int
) -> None:
    original = await claim_jobs.add(queue=queue)
    before = await claim_jobs.clock()
    claimed = await asyncio.wait_for(
        claim_next(
            claim_jobs.factory,
            queue=queue,
            worker_id="claim-owner",
            lease_seconds=lease_seconds,
        ),
        timeout=10,
    )
    after = await claim_jobs.clock()

    assert claimed is not None
    assert claimed.id == original.id
    assert claimed.queue == queue
    assert claimed.kind == original.kind
    assert claimed.payload == original.payload
    assert claimed.status == JobStatus.RUNNING
    assert claimed.attempts == 1
    assert claimed.max_attempts == original.max_attempts
    assert claimed.locked_by == "claim-owner"
    assert claimed.lease_expires_at is not None
    assert claimed.lease_expires_at.tzinfo is not None
    assert before + timedelta(seconds=lease_seconds) <= claimed.lease_expires_at
    assert claimed.lease_expires_at <= after + timedelta(seconds=lease_seconds)
    assert claimed.created_at == original.created_at
    assert claimed.run_after == original.run_after
    assert claimed.serial_key is None
    assert claimed.idempotency_key is None
    assert claimed.run_id is None
    assert claimed.result is None
    assert claimed.last_error is None
    assert claimed.finished_at is None
    assert claimed.delivered is False

    async with claim_jobs.factory.begin() as observer:
        stored = await observer.scalar(
            select(Job).where(Job.id == original.id).with_for_update(nowait=True, of=Job)
        )
        assert stored is not None
        assert stored.status == JobStatus.RUNNING
        assert stored.attempts == 1
        assert stored.locked_by == "claim-owner"
        assert stored.lease_expires_at == claimed.lease_expires_at


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
async def test_claim_only_selects_the_requested_queue(
    claim_jobs: ClaimJobs, queue: JobQueue
) -> None:
    old_time = datetime(2000, 1, 1, tzinfo=UTC)
    other_queue = JobQueue.PUBLISHER if queue == JobQueue.SANDBOX else JobQueue.SANDBOX
    unrelated = await claim_jobs.add(queue=other_queue, created_at=old_time)
    expected = await claim_jobs.add(queue=queue, created_at=old_time + timedelta(seconds=1))

    claimed = await claim_next(
        claim_jobs.factory, queue=queue, worker_id="claim-worker", lease_seconds=60
    )
    assert claimed is not None
    assert claimed.id == expected.id

    async with claim_jobs.factory() as observer:
        untouched = await observer.get(Job, unrelated.id)
        assert untouched is not None
        assert untouched.status == JobStatus.QUEUED
        assert untouched.attempts == 0
        assert untouched.locked_by is None
        assert untouched.lease_expires_at is None


@pytest.mark.parametrize(
    ("job_status", "attempts", "max_attempts", "future"),
    [
        (JobStatus.QUEUED, 0, 3, True),
        (JobStatus.QUEUED, 1, 1, False),
        (JobStatus.QUEUED, 3, 3, False),
        (JobStatus.QUEUED, 4, 3, False),
        (JobStatus.RUNNING, 1, 3, False),
        (JobStatus.SUCCEEDED, 1, 3, False),
        (JobStatus.FAILED, 1, 3, False),
    ],
    ids=["future", "budget-one", "budget-three", "over-budget", "running", "succeeded", "failed"],
)
async def test_claim_skips_ineligible_older_jobs(
    claim_jobs: ClaimJobs,
    job_status: JobStatus,
    attempts: int,
    max_attempts: int,
    future: bool,
) -> None:
    old_time = datetime(2000, 1, 1, tzinfo=UTC)
    now = await claim_jobs.clock()
    run_after = now + timedelta(hours=1) if future else now - timedelta(seconds=1)
    ineligible = await claim_jobs.add(
        status=job_status,
        attempts=attempts,
        max_attempts=max_attempts,
        created_at=old_time,
        run_after=run_after,
    )
    eligible = await claim_jobs.add(created_at=old_time + timedelta(seconds=1))

    claimed = await claim_next(
        claim_jobs.factory,
        queue=JobQueue.SANDBOX,
        worker_id="claim-worker",
        lease_seconds=60,
    )
    assert claimed is not None
    assert claimed.id == eligible.id
    remaining = await claim_next(
        claim_jobs.factory,
        queue=JobQueue.SANDBOX,
        worker_id="claim-worker-again",
        lease_seconds=60,
    )
    assert remaining is None

    async with claim_jobs.factory() as observer:
        untouched = await observer.get(Job, ineligible.id)
        assert untouched is not None
        assert untouched.status == job_status
        assert untouched.attempts == attempts
        assert untouched.max_attempts == max_attempts
        assert untouched.run_after == run_after
        assert untouched.locked_by == ineligible.locked_by
        assert untouched.lease_expires_at == ineligible.lease_expires_at


async def test_claim_uses_final_available_attempt_and_retains_previous_error(
    claim_jobs: ClaimJobs,
) -> None:
    original = await claim_jobs.add(
        attempts=2, max_attempts=3, last_error="Previous execution failed"
    )
    claimed = await claim_next(
        claim_jobs.factory,
        queue=JobQueue.SANDBOX,
        worker_id="last-attempt-worker",
        lease_seconds=60,
    )

    assert claimed is not None
    assert claimed.id == original.id
    assert claimed.attempts == 3
    assert claimed.max_attempts == 3
    assert claimed.status == JobStatus.RUNNING
    assert claimed.last_error == "Previous execution failed"
    assert claimed.finished_at is None
    second = await claim_next(
        claim_jobs.factory,
        queue=JobQueue.SANDBOX,
        worker_id="another-worker",
        lease_seconds=60,
    )
    assert second is None
    async with claim_jobs.factory() as observer:
        stored = await observer.get(Job, original.id)
        assert stored is not None
        assert stored.attempts == 3
        assert stored.locked_by == "last-attempt-worker"


async def test_claim_orders_by_creation_time_before_id(claim_jobs: ClaimJobs) -> None:
    smaller_id, larger_id = sorted([uuid4(), uuid4()])
    old_time = datetime(2000, 1, 1, tzinfo=UTC)
    newer = await claim_jobs.add(job_id=smaller_id, created_at=old_time + timedelta(seconds=1))
    older = await claim_jobs.add(job_id=larger_id, created_at=old_time)

    first = await claim_next(
        claim_jobs.factory, queue=JobQueue.SANDBOX, worker_id="worker-1", lease_seconds=60
    )
    second = await claim_next(
        claim_jobs.factory, queue=JobQueue.SANDBOX, worker_id="worker-2", lease_seconds=60
    )
    assert first is not None
    assert second is not None
    assert first.id == older.id
    assert second.id == newer.id


async def test_claim_orders_equal_creation_times_by_id(claim_jobs: ClaimJobs) -> None:
    smaller_id, larger_id = sorted([uuid4(), uuid4()])
    same_time = datetime(2000, 1, 1, tzinfo=UTC)
    await claim_jobs.add(job_id=larger_id, created_at=same_time)
    await claim_jobs.add(job_id=smaller_id, created_at=same_time)

    first = await claim_next(
        claim_jobs.factory, queue=JobQueue.SANDBOX, worker_id="worker-1", lease_seconds=60
    )
    second = await claim_next(
        claim_jobs.factory, queue=JobQueue.SANDBOX, worker_id="worker-2", lease_seconds=60
    )
    assert first is not None
    assert second is not None
    assert first.id == smaller_id
    assert second.id == larger_id


async def test_claim_cannot_see_a_job_until_its_seed_transaction_commits(
    claim_jobs: ClaimJobs,
) -> None:
    job_id = uuid4()
    claim_jobs.job_ids.append(job_id)
    async with claim_jobs.factory() as writer:
        writer.add(
            Job(id=job_id, queue=JobQueue.SANDBOX, kind="profile", payload={"committed": False})
        )
        await writer.flush()

        invisible = await asyncio.wait_for(
            claim_next(
                claim_jobs.factory,
                queue=JobQueue.SANDBOX,
                worker_id="before-commit-worker",
                lease_seconds=60,
            ),
            timeout=10,
        )
        assert invisible is None
        await writer.commit()

    visible = await claim_next(
        claim_jobs.factory,
        queue=JobQueue.SANDBOX,
        worker_id="after-commit-worker",
        lease_seconds=60,
    )
    assert visible is not None
    assert visible.id == job_id
    assert visible.attempts == 1
    assert visible.locked_by == "after-commit-worker"


@pytest.mark.parametrize(
    ("worker_id", "message"),
    [
        ("", "worker_id must not be empty"),
        ("   ", "worker_id must not be empty"),
        ("\t", "worker_id must not be empty"),
        ("w" * 129, "worker_id must not exceed 128 characters"),
    ],
    ids=["empty", "spaces", "tab", "too-long"],
)
async def test_claim_rejects_invalid_worker_id_without_changing_job(
    claim_jobs: ClaimJobs, worker_id: str, message: str
) -> None:
    original = await claim_jobs.add()
    with pytest.raises(ValueError, match=message):
        await claim_next(
            claim_jobs.factory,
            queue=JobQueue.SANDBOX,
            worker_id=worker_id,
            lease_seconds=60,
        )

    async with claim_jobs.factory() as observer:
        stored = await observer.get(Job, original.id)
        assert stored is not None
        assert stored.status == JobStatus.QUEUED
        assert stored.attempts == 0
        assert stored.locked_by is None
        assert stored.lease_expires_at is None


@pytest.mark.parametrize("lease_seconds", [0, -1, -300])
async def test_claim_rejects_nonpositive_lease_without_changing_job(
    claim_jobs: ClaimJobs, lease_seconds: int
) -> None:
    original = await claim_jobs.add()
    with pytest.raises(ValueError, match="lease_seconds must be positive"):
        await claim_next(
            claim_jobs.factory,
            queue=JobQueue.SANDBOX,
            worker_id="claim-worker",
            lease_seconds=lease_seconds,
        )

    async with claim_jobs.factory() as observer:
        stored = await observer.get(Job, original.id)
        assert stored is not None
        assert stored.status == JobStatus.QUEUED
        assert stored.attempts == 0
        assert stored.locked_by is None
        assert stored.lease_expires_at is None


async def test_claim_accepts_worker_id_at_column_length_limit(claim_jobs: ClaimJobs) -> None:
    original = await claim_jobs.add()
    worker_id = "w" * 128
    claimed = await claim_next(
        claim_jobs.factory, queue=JobQueue.SANDBOX, worker_id=worker_id, lease_seconds=60
    )
    assert claimed is not None
    assert claimed.id == original.id
    assert claimed.locked_by == worker_id


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
async def test_two_workers_never_claim_the_same_job(claim_jobs: ClaimJobs, queue: JobQueue) -> None:
    original = await claim_jobs.add(queue=queue)
    results = await _claim_with_two_workers(claim_jobs, queue)
    winners = [job for job in results if job is not None]

    assert len(winners) == 1
    assert sum(job is None for job in results) == 1
    assert winners[0].id == original.id
    for worker_index, result in enumerate(results):
        if result is not None:
            assert result.locked_by == f"claim-worker-{worker_index}"
            assert result.attempts == 1

    async with claim_jobs.factory() as observer:
        stored = await observer.get(Job, original.id)
        assert stored is not None
        assert stored.status == JobStatus.RUNNING
        assert stored.attempts == 1
        assert stored.locked_by == winners[0].locked_by
        assert stored.lease_expires_at == winners[0].lease_expires_at


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
async def test_claim_two_workers_receive_distinct_jobs(
    claim_jobs: ClaimJobs, queue: JobQueue
) -> None:
    first = await claim_jobs.add(queue=queue)
    second = await claim_jobs.add(queue=queue)
    expected_ids = {first.id, second.id}
    results = await _claim_with_two_workers(claim_jobs, queue)

    for worker_index, result in enumerate(results):
        assert result is not None
        assert result.locked_by == f"claim-worker-{worker_index}"
        assert result.status == JobStatus.RUNNING
        assert result.attempts == 1
    assert {job.id for job in results if job is not None} == expected_ids

    async with claim_jobs.factory() as observer:
        stored = list(await observer.scalars(select(Job).where(Job.id.in_(expected_ids))))
        assert len(stored) == 2
        assert {job.locked_by for job in stored} == {"claim-worker-0", "claim-worker-1"}
        assert all(job.status == JobStatus.RUNNING for job in stored)
        assert all(job.attempts == 1 for job in stored)
        assert all(job.lease_expires_at is not None for job in stored)


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
async def test_claim_skips_locked_oldest_job_before_lock_is_released(
    claim_jobs: ClaimJobs, queue: JobQueue
) -> None:
    old_time = datetime(2000, 1, 1, tzinfo=UTC)
    oldest = await claim_jobs.add(queue=queue, created_at=old_time)
    next_job = await claim_jobs.add(queue=queue, created_at=old_time + timedelta(seconds=1))

    async with claim_jobs.factory() as blocker:
        locked = await blocker.scalar(
            select(Job).where(Job.id == oldest.id).with_for_update(of=Job)
        )
        assert locked is not None
        assert blocker.in_transaction()

        claimed = await asyncio.wait_for(
            claim_next(
                claim_jobs.factory,
                queue=queue,
                worker_id="skip-locked-worker",
                lease_seconds=60,
            ),
            timeout=10,
        )

        assert blocker.in_transaction()
        assert claimed is not None
        assert claimed.id == next_job.id
        assert claimed.attempts == 1
        async with claim_jobs.factory() as observer:
            untouched = await observer.get(Job, oldest.id)
            assert untouched is not None
            assert untouched.status == JobStatus.QUEUED
            assert untouched.attempts == 0
            assert untouched.locked_by is None
            assert untouched.lease_expires_at is None
        await blocker.rollback()

    next_claim = await claim_next(
        claim_jobs.factory,
        queue=queue,
        worker_id="released-lock-worker",
        lease_seconds=60,
    )
    assert next_claim is not None
    assert next_claim.id == oldest.id
    assert next_claim.attempts == 1


async def test_claim_returns_none_when_all_candidates_are_locked(claim_jobs: ClaimJobs) -> None:
    original = await claim_jobs.add()
    async with claim_jobs.factory() as blocker:
        locked = await blocker.scalar(
            select(Job).where(Job.id == original.id).with_for_update(of=Job)
        )
        assert locked is not None
        unavailable = await asyncio.wait_for(
            claim_next(
                claim_jobs.factory,
                queue=JobQueue.SANDBOX,
                worker_id="waiting-worker",
                lease_seconds=60,
            ),
            timeout=10,
        )
        assert unavailable is None
        assert blocker.in_transaction()
        async with claim_jobs.factory() as observer:
            untouched = await observer.get(Job, original.id)
            assert untouched is not None
            assert untouched.status == JobStatus.QUEUED
            assert untouched.attempts == 0
        await blocker.rollback()

    available = await claim_next(
        claim_jobs.factory,
        queue=JobQueue.SANDBOX,
        worker_id="after-release-worker",
        lease_seconds=60,
    )
    assert available is not None
    assert available.id == original.id
    assert available.attempts == 1


@pytest.mark.parametrize(
    ("running_queue", "waiting_queue"),
    [
        (JobQueue.SANDBOX, JobQueue.SANDBOX),
        (JobQueue.SANDBOX, JobQueue.PUBLISHER),
        (JobQueue.PUBLISHER, JobQueue.SANDBOX),
        (JobQueue.PUBLISHER, JobQueue.PUBLISHER),
    ],
)
async def test_serial_key_blocks_parallel_runs_of_one_pipeline(
    claim_jobs: ClaimJobs, running_queue: JobQueue, waiting_queue: JobQueue
) -> None:
    key = f"pipeline:{uuid4()}"
    running = await claim_jobs.add(
        queue=running_queue, status=JobStatus.RUNNING, attempts=1, serial_key=key
    )
    waiting = await claim_jobs.add(queue=waiting_queue, serial_key=key)

    claimed = await claim_next(
        claim_jobs.factory, queue=waiting_queue, worker_id="serial-worker", lease_seconds=60
    )
    assert claimed is None

    async with claim_jobs.factory() as observer:
        stored_running = await observer.get(Job, running.id)
        stored_waiting = await observer.get(Job, waiting.id)
        assert stored_running is not None
        assert stored_running.status == JobStatus.RUNNING
        assert stored_running.attempts == 1
        assert stored_running.locked_by == running.locked_by
        assert stored_running.lease_expires_at == running.lease_expires_at
        assert stored_waiting is not None
        assert stored_waiting.status == JobStatus.QUEUED
        assert stored_waiting.attempts == 0
        assert stored_waiting.locked_by is None
        assert stored_waiting.lease_expires_at is None


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
async def test_serial_key_allows_only_one_of_two_queued_jobs_to_be_claimed(
    claim_jobs: ClaimJobs, queue: JobQueue
) -> None:
    key = f"pipeline:{uuid4()}"
    old_time = datetime(2000, 1, 1, tzinfo=UTC)
    first = await claim_jobs.add(queue=queue, serial_key=key, created_at=old_time)
    second = await claim_jobs.add(
        queue=queue, serial_key=key, created_at=old_time + timedelta(seconds=1)
    )

    first_claim = await claim_next(
        claim_jobs.factory, queue=queue, worker_id="serial-first", lease_seconds=60
    )
    second_claim = await claim_next(
        claim_jobs.factory, queue=queue, worker_id="serial-second", lease_seconds=60
    )
    assert first_claim is not None
    assert first_claim.id == first.id
    assert first_claim.serial_key == key
    assert first_claim.attempts == 1
    assert second_claim is None

    async with claim_jobs.factory() as observer:
        stored = await observer.get(Job, second.id)
        assert stored is not None
        assert stored.status == JobStatus.QUEUED
        assert stored.attempts == 0
        assert stored.locked_by is None
        assert stored.lease_expires_at is None


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
@pytest.mark.parametrize("available_has_key", [False, True], ids=["null-key", "different-key"])
async def test_serial_key_blocked_oldest_job_does_not_hide_available_work(
    claim_jobs: ClaimJobs, queue: JobQueue, available_has_key: bool
) -> None:
    key = f"pipeline:{uuid4()}"
    old_time = datetime(2000, 1, 1, tzinfo=UTC)
    await claim_jobs.add(queue=queue, status=JobStatus.RUNNING, attempts=1, serial_key=key)
    blocked = await claim_jobs.add(queue=queue, serial_key=key, created_at=old_time)
    available_key = f"{key}:another" if available_has_key else None
    available = await claim_jobs.add(
        queue=queue,
        serial_key=available_key,
        created_at=old_time + timedelta(seconds=1),
    )

    claimed = await claim_next(
        claim_jobs.factory, queue=queue, worker_id="available-worker", lease_seconds=60
    )
    assert claimed is not None
    assert claimed.id == available.id
    assert claimed.serial_key == available_key

    async with claim_jobs.factory() as observer:
        untouched = await observer.get(Job, blocked.id)
        assert untouched is not None
        assert untouched.status == JobStatus.QUEUED
        assert untouched.attempts == 0
        assert untouched.locked_by is None
        assert untouched.lease_expires_at is None


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
async def test_serial_key_distinct_keys_can_be_claimed_concurrently(
    claim_jobs: ClaimJobs, queue: JobQueue
) -> None:
    prefix = f"pipeline:{uuid4()}"
    first = await claim_jobs.add(queue=queue, serial_key=f"{prefix}:1")
    second = await claim_jobs.add(queue=queue, serial_key=f"{prefix}:2")
    results = await _claim_with_two_workers(claim_jobs, queue)

    assert {job.id for job in results if job is not None} == {first.id, second.id}
    assert all(job is not None for job in results)
    async with claim_jobs.factory() as observer:
        jobs = list(await observer.scalars(select(Job).where(Job.id.in_([first.id, second.id]))))
        assert len(jobs) == 2
        assert {job.serial_key for job in jobs} == {first.serial_key, second.serial_key}
        assert all(job.status == JobStatus.RUNNING for job in jobs)
        assert all(job.attempts == 1 for job in jobs)


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
async def test_serial_key_expired_running_job_keeps_key_until_recovery(
    claim_jobs: ClaimJobs, queue: JobQueue
) -> None:
    key = f"pipeline:{uuid4()}"
    running = await claim_jobs.add(
        queue=queue, status=JobStatus.RUNNING, attempts=1, serial_key=key
    )
    waiting = await claim_jobs.add(queue=queue, serial_key=key)
    async with claim_jobs.factory.begin() as session:
        await session.execute(
            update(Job)
            .where(Job.id == running.id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )

    claimed = await claim_next(
        claim_jobs.factory, queue=queue, worker_id="expired-key-worker", lease_seconds=60
    )
    assert claimed is None

    async with claim_jobs.factory() as observer:
        stored_running = await observer.get(Job, running.id)
        stored_waiting = await observer.get(Job, waiting.id)
        assert stored_running is not None
        assert stored_running.status == JobStatus.RUNNING
        assert stored_running.attempts == 1
        assert stored_running.locked_by == running.locked_by
        assert stored_waiting is not None
        assert stored_waiting.status == JobStatus.QUEUED
        assert stored_waiting.attempts == 0


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
@pytest.mark.parametrize(
    "released_status",
    [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.QUEUED],
    ids=["complete-state", "fail-state", "reclaim-state"],
)
async def test_serial_key_is_released_when_running_status_is_removed(
    claim_jobs: ClaimJobs, queue: JobQueue, released_status: JobStatus
) -> None:
    """Simulate release states; real fail and reclaim integration will be added in D6 and D7."""
    key = f"pipeline:{uuid4()}"
    running = await claim_jobs.add(
        queue=queue, status=JobStatus.RUNNING, attempts=1, serial_key=key
    )
    waiting = await claim_jobs.add(queue=queue, serial_key=key)
    blocked = await claim_next(
        claim_jobs.factory, queue=queue, worker_id="before-release-worker", lease_seconds=60
    )
    assert blocked is None

    async with claim_jobs.factory.begin() as session:
        await session.execute(
            update(Job)
            .where(Job.id == running.id)
            .values(
                status=released_status,
                locked_by=None,
                lease_expires_at=None,
                finished_at=(
                    func.clock_timestamp() if released_status != JobStatus.QUEUED else None
                ),
                run_after=func.clock_timestamp() + timedelta(hours=1),
            )
        )

    claimed = await claim_next(
        claim_jobs.factory, queue=queue, worker_id="after-release-worker", lease_seconds=60
    )
    assert claimed is not None
    assert claimed.id == waiting.id
    assert claimed.serial_key == key
    assert claimed.attempts == 1
    async with claim_jobs.factory() as observer:
        previous = await observer.get(Job, running.id)
        assert previous is not None
        assert previous.status == released_status
        assert previous.attempts == 1
        assert previous.locked_by is None
        assert previous.lease_expires_at is None


async def test_serial_key_empty_string_is_a_shared_key(claim_jobs: ClaimJobs) -> None:
    await claim_jobs.add(status=JobStatus.RUNNING, attempts=1, serial_key="")
    waiting = await claim_jobs.add(serial_key="")
    claimed = await claim_next(
        claim_jobs.factory,
        queue=JobQueue.SANDBOX,
        worker_id="empty-key-worker",
        lease_seconds=60,
    )
    assert claimed is None
    async with claim_jobs.factory() as observer:
        stored = await observer.get(Job, waiting.id)
        assert stored is not None
        assert stored.status == JobStatus.QUEUED
        assert stored.attempts == 0


async def test_serial_key_unique_index_rejects_a_second_running_row_across_queues(
    claim_jobs: ClaimJobs,
) -> None:
    key = f"pipeline:{uuid4()}"
    running = await claim_jobs.add(
        queue=JobQueue.SANDBOX,
        status=JobStatus.RUNNING,
        attempts=1,
        serial_key=key,
    )
    waiting = await claim_jobs.add(queue=JobQueue.PUBLISHER, serial_key=key)

    with pytest.raises(IntegrityError, match="uq_jobs_running_serial_key"):
        async with claim_jobs.factory.begin() as session:
            await session.execute(
                update(Job)
                .where(Job.id == waiting.id)
                .values(
                    status=JobStatus.RUNNING,
                    attempts=1,
                    locked_by="index-violation-worker",
                    lease_expires_at=func.clock_timestamp() + timedelta(seconds=60),
                )
            )

    async with claim_jobs.factory() as observer:
        stored_running = await observer.get(Job, running.id)
        stored_waiting = await observer.get(Job, waiting.id)
        assert stored_running is not None
        assert stored_running.status == JobStatus.RUNNING
        assert stored_waiting is not None
        assert stored_waiting.status == JobStatus.QUEUED
        assert stored_waiting.attempts == 0
        assert stored_waiting.locked_by is None
        assert stored_waiting.lease_expires_at is None


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
async def test_serial_key_two_claiming_workers_commit_only_one_running_job(
    claim_jobs: ClaimJobs, queue: JobQueue
) -> None:
    key = f"pipeline:{uuid4()}"
    first = await claim_jobs.add(queue=queue, serial_key=key)
    second = await claim_jobs.add(queue=queue, serial_key=key)
    results = await _claim_with_two_workers(claim_jobs, queue)
    winners = [job for job in results if job is not None]

    assert len(winners) == 1
    assert sum(job is None for job in results) == 1
    assert winners[0].id in {first.id, second.id}
    async with claim_jobs.factory() as observer:
        jobs = list(await observer.scalars(select(Job).where(Job.id.in_([first.id, second.id]))))
        running = [job for job in jobs if job.status == JobStatus.RUNNING]
        queued = [job for job in jobs if job.status == JobStatus.QUEUED]
        assert len(running) == 1
        assert len(queued) == 1
        assert running[0].id == winners[0].id
        assert running[0].attempts == 1
        assert queued[0].attempts == 0
        assert queued[0].locked_by is None
        assert queued[0].lease_expires_at is None


async def _wait_for_serial_index_blocker(
    claim_jobs: ClaimJobs,
    *,
    blocker_pid: int,
    claim_task: asyncio.Task[Job | None],
) -> int:
    """Wait until a claim UPDATE is blocked by the uncommitted running serial key."""
    async with asyncio.timeout(10):
        while True:
            if claim_task.done():
                claim_task.result()
                pytest.fail("The claim finished before reaching the serial-key index conflict")

            async with claim_jobs.factory() as observer:
                waiter_pid = await observer.scalar(
                    text(
                        "SELECT pid FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock' "
                        "AND query LIKE 'UPDATE jobs SET%' "
                        "AND :blocker_pid = ANY(pg_blocking_pids(pid)) "
                        "LIMIT 1"
                    ),
                    {"blocker_pid": blocker_pid},
                )
            if isinstance(waiter_pid, int):
                return waiter_pid
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("waiting_queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
@pytest.mark.parametrize(
    "first_commits", [True, False], ids=["winner-commits", "winner-rolls-back"]
)
async def test_serial_key_index_race_rolls_back_loser_or_allows_claim_after_rollback(
    claim_jobs: ClaimJobs, waiting_queue: JobQueue, first_commits: bool
) -> None:
    key = f"pipeline:{uuid4()}"
    old_time = datetime(2000, 1, 1, tzinfo=UTC)
    first = await claim_jobs.add(queue=JobQueue.SANDBOX, serial_key=key, created_at=old_time)
    waiting = await claim_jobs.add(
        queue=waiting_queue, serial_key=key, created_at=old_time + timedelta(seconds=1)
    )
    independent = await claim_jobs.add(
        queue=waiting_queue,
        serial_key=f"{key}:independent",
        created_at=old_time + timedelta(seconds=2),
    )
    claim_task: asyncio.Task[Job | None] | None = None

    try:
        async with claim_jobs.factory() as owner:
            blocker_pid = await owner.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(blocker_pid, int)
            locked = await owner.scalar(
                select(Job).where(Job.id == first.id).with_for_update(of=Job)
            )
            assert locked is not None
            now = await owner.scalar(select(func.clock_timestamp()))
            assert isinstance(now, datetime)
            locked.status = JobStatus.RUNNING
            locked.attempts = 1
            locked.locked_by = "uncommitted-key-owner"
            locked.lease_expires_at = now + timedelta(minutes=5)
            await owner.flush()

            claim_task = asyncio.create_task(
                claim_next(
                    claim_jobs.factory,
                    queue=waiting_queue,
                    worker_id="serial-race-worker",
                    lease_seconds=60,
                )
            )
            waiter_pid = await _wait_for_serial_index_blocker(
                claim_jobs, blocker_pid=blocker_pid, claim_task=claim_task
            )
            assert waiter_pid != blocker_pid

            if first_commits:
                await owner.commit()
            else:
                await owner.rollback()

            result = await asyncio.wait_for(claim_task, timeout=10)
            if first_commits:
                assert result is None
            else:
                assert result is not None
                assert result.id == waiting.id
                assert result.attempts == 1
                assert result.locked_by == "serial-race-worker"

        async with claim_jobs.factory() as observer:
            first_stored = await observer.get(Job, first.id)
            waiting_stored = await observer.get(Job, waiting.id)
            independent_stored = await observer.get(Job, independent.id)
            assert first_stored is not None
            assert waiting_stored is not None
            assert independent_stored is not None
            assert independent_stored.status == JobStatus.QUEUED
            assert independent_stored.attempts == 0
            if first_commits:
                assert first_stored.status == JobStatus.RUNNING
                assert first_stored.attempts == 1
                assert waiting_stored.status == JobStatus.QUEUED
                assert waiting_stored.attempts == 0
                assert waiting_stored.locked_by is None
                assert waiting_stored.lease_expires_at is None
            else:
                assert first_stored.status == JobStatus.QUEUED
                assert first_stored.attempts == 0
                assert first_stored.locked_by is None
                assert first_stored.lease_expires_at is None
                assert waiting_stored.status == JobStatus.RUNNING
                assert waiting_stored.attempts == 1

            running_count = await observer.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.serial_key == key, Job.status == JobStatus.RUNNING)
            )
            assert running_count == 1

        next_poll = await claim_next(
            claim_jobs.factory,
            queue=waiting_queue,
            worker_id="next-poll-worker",
            lease_seconds=60,
        )
        assert next_poll is not None
        assert next_poll.id == independent.id
        assert next_poll.attempts == 1
    finally:
        if claim_task is not None:
            if not claim_task.done():
                claim_task.cancel()
            await asyncio.gather(claim_task, return_exceptions=True)


class DriverConstraintError(Exception):
    """Represent driver metadata for an unrelated database error."""

    def __init__(self, sqlstate: str, constraint_name: str) -> None:
        super().__init__("Unrelated database constraint violation")
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name


@pytest.mark.parametrize(
    ("sqlstate", "constraint_name"),
    [
        ("23505", "uq_jobs_idempotency_key"),
        ("23503", "fk_jobs_run_id_pipeline_runs"),
        ("23503", "uq_jobs_running_serial_key"),
    ],
    ids=["other-unique-index", "foreign-key", "wrong-sqlstate"],
)
async def test_serial_key_claim_propagates_unrelated_integrity_errors(
    claim_jobs: ClaimJobs,
    monkeypatch: pytest.MonkeyPatch,
    sqlstate: str,
    constraint_name: str,
) -> None:
    original = await claim_jobs.add(serial_key=f"pipeline:{uuid4()}")
    driver_error = DriverConstraintError(sqlstate, constraint_name)
    adapted_error = RuntimeError("Adapted database error")
    adapted_error.__cause__ = driver_error
    failure = IntegrityError("UPDATE jobs", None, adapted_error)

    async def reject_flush(_session: AsyncSession, _objects: object = None) -> None:
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(claim_jobs.factory.class_, "flush", reject_flush)
        with pytest.raises(IntegrityError) as captured:
            await claim_next(
                claim_jobs.factory,
                queue=JobQueue.SANDBOX,
                worker_id="unexpected-error-worker",
                lease_seconds=60,
            )
        assert captured.value is failure

    async with claim_jobs.factory() as observer:
        stored = await observer.get(Job, original.id)
        assert stored is not None
        assert stored.status == JobStatus.QUEUED
        assert stored.attempts == 0
        assert stored.locked_by is None
        assert stored.lease_expires_at is None


async def _start_lifecycle_job(
    claim_jobs: ClaimJobs,
    *,
    queue: JobQueue = JobQueue.SANDBOX,
    worker_id: str = "lifecycle-worker",
    lease_seconds: int = 60,
    serial_key: str | None = None,
    attempts: int = 0,
    last_error: str | None = None,
) -> Job:
    seeded = await claim_jobs.add(
        queue=queue, serial_key=serial_key, attempts=attempts, last_error=last_error
    )
    claimed = await claim_next(
        claim_jobs.factory, queue=queue, worker_id=worker_id, lease_seconds=lease_seconds
    )
    assert claimed is not None
    assert claimed.id == seeded.id
    return claimed


async def _read_lifecycle_job(claim_jobs: ClaimJobs, job_id: UUID) -> Job:
    async with claim_jobs.factory() as session:
        job = await session.get(Job, job_id)
        assert job is not None
    return job


def _job_state(job: Job) -> dict[str, object]:
    """Capture persisted fields to detect any mutation after an ownership rejection."""
    return {column.name: getattr(job, column.name) for column in Job.__table__.columns}


async def _apply_worker_update(
    claim_jobs: ClaimJobs,
    job_id: UUID,
    *,
    operation: Literal["heartbeat", "complete"],
    worker_id: str = "lifecycle-worker",
    attempt: int = 1,
) -> None:
    if operation == "heartbeat":
        await heartbeat(
            claim_jobs.factory,
            job_id,
            worker_id=worker_id,
            attempt=attempt,
            lease_seconds=300,
        )
    else:
        await complete(
            claim_jobs.factory,
            job_id,
            {"source": "worker-update"},
            worker_id=worker_id,
            attempt=attempt,
        )


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
async def test_heartbeat_commits_extended_lease_without_changing_other_fields(
    claim_jobs: ClaimJobs, queue: JobQueue
) -> None:
    original = await _start_lifecycle_job(
        claim_jobs,
        queue=queue,
        serial_key=f"pipeline:{uuid4()}",
        attempts=1,
        last_error="Previous execution failed",
    )
    previous = _job_state(original)
    before = await claim_jobs.clock()
    await heartbeat(
        claim_jobs.factory,
        original.id,
        worker_id="lifecycle-worker",
        attempt=original.attempts,
        lease_seconds=300,
    )
    after = await claim_jobs.clock()

    async with claim_jobs.factory.begin() as observer:
        stored = await observer.scalar(
            select(Job).where(Job.id == original.id).with_for_update(nowait=True, of=Job)
        )
        assert stored is not None
        assert stored.lease_expires_at is not None
        assert original.lease_expires_at is not None
        assert stored.lease_expires_at > original.lease_expires_at
        assert before + timedelta(seconds=300) <= stored.lease_expires_at
        assert stored.lease_expires_at <= after + timedelta(seconds=300)
        expected = {**previous, "lease_expires_at": stored.lease_expires_at}
        assert _job_state(stored) == expected


async def test_heartbeat_never_shortens_an_existing_longer_lease(claim_jobs: ClaimJobs) -> None:
    original = await _start_lifecycle_job(claim_jobs, lease_seconds=300)
    previous = _job_state(original)
    await heartbeat(
        claim_jobs.factory,
        original.id,
        worker_id="lifecycle-worker",
        attempt=original.attempts,
        lease_seconds=30,
    )
    stored = await _read_lifecycle_job(claim_jobs, original.id)
    assert _job_state(stored) == previous


@pytest.mark.parametrize("lease_seconds", [0, -1, -300])
async def test_heartbeat_rejects_nonpositive_lease_without_changing_job(
    claim_jobs: ClaimJobs, lease_seconds: int
) -> None:
    original = await _start_lifecycle_job(claim_jobs)
    previous = _job_state(original)
    with pytest.raises(ValueError, match="lease_seconds must be positive"):
        await heartbeat(
            claim_jobs.factory,
            original.id,
            worker_id="lifecycle-worker",
            attempt=original.attempts,
            lease_seconds=lease_seconds,
        )

    stored = await _read_lifecycle_job(claim_jobs, original.id)
    assert _job_state(stored) == previous


@pytest.mark.parametrize("operation", ["heartbeat", "complete"])
@pytest.mark.parametrize(
    ("worker_id", "attempt_delta"),
    [("another-worker", 0), ("lifecycle-worker", -1), ("lifecycle-worker", 1)],
    ids=["wrong-worker", "old-attempt", "future-attempt"],
)
async def test_worker_update_rejects_wrong_claim_identity_without_mutation(
    claim_jobs: ClaimJobs,
    operation: Literal["heartbeat", "complete"],
    worker_id: str,
    attempt_delta: int,
) -> None:
    original = await _start_lifecycle_job(claim_jobs)
    previous = _job_state(original)
    with pytest.raises(JobOwnershipLostError):
        await _apply_worker_update(
            claim_jobs,
            original.id,
            operation=operation,
            worker_id=worker_id,
            attempt=original.attempts + attempt_delta,
        )

    stored = await _read_lifecycle_job(claim_jobs, original.id)
    assert _job_state(stored) == previous


@pytest.mark.parametrize("operation", ["heartbeat", "complete"])
@pytest.mark.parametrize("missing_lease", [False, True], ids=["expired-lease", "null-lease"])
async def test_worker_update_rejects_expired_or_missing_lease_without_mutation(
    claim_jobs: ClaimJobs, operation: Literal["heartbeat", "complete"], missing_lease: bool
) -> None:
    original = await _start_lifecycle_job(claim_jobs)
    async with claim_jobs.factory.begin() as session:
        await session.execute(
            update(Job)
            .where(Job.id == original.id)
            .values(
                lease_expires_at=(
                    None if missing_lease else func.clock_timestamp() - timedelta(seconds=1)
                )
            )
        )

    previous = _job_state(await _read_lifecycle_job(claim_jobs, original.id))
    with pytest.raises(JobOwnershipLostError):
        await _apply_worker_update(
            claim_jobs, original.id, operation=operation, attempt=original.attempts
        )

    stored = await _read_lifecycle_job(claim_jobs, original.id)
    assert _job_state(stored) == previous


@pytest.mark.parametrize("operation", ["heartbeat", "complete"])
@pytest.mark.parametrize("job_status", [JobStatus.QUEUED, JobStatus.SUCCEEDED, JobStatus.FAILED])
async def test_worker_update_rejects_nonrunning_job_without_mutation(
    claim_jobs: ClaimJobs,
    operation: Literal["heartbeat", "complete"],
    job_status: JobStatus,
) -> None:
    original = await claim_jobs.add(status=job_status, attempts=1)
    previous = _job_state(original)
    with pytest.raises(JobOwnershipLostError):
        await _apply_worker_update(
            claim_jobs,
            original.id,
            operation=operation,
            worker_id="existing-claim-worker",
            attempt=original.attempts,
        )

    stored = await _read_lifecycle_job(claim_jobs, original.id)
    assert _job_state(stored) == previous


@pytest.mark.parametrize("operation", ["heartbeat", "complete"])
async def test_worker_update_rejects_missing_job(
    claim_jobs: ClaimJobs, operation: Literal["heartbeat", "complete"]
) -> None:
    missing_id = uuid4()
    with pytest.raises(JobOwnershipLostError):
        await _apply_worker_update(claim_jobs, missing_id, operation=operation)

    async with claim_jobs.factory() as observer:
        assert await observer.get(Job, missing_id) is None


@pytest.mark.parametrize("queue", [JobQueue.SANDBOX, JobQueue.PUBLISHER])
async def test_complete_commits_result_and_releases_ownership(
    claim_jobs: ClaimJobs, queue: JobQueue
) -> None:
    original = await _start_lifecycle_job(
        claim_jobs,
        queue=queue,
        serial_key=f"pipeline:{uuid4()}",
        attempts=1,
        last_error="Previous execution failed",
    )
    result = {"rows": 42, "models": ["orders"], "metrics": {"seconds": 1.25}, "error": None}
    previous = _job_state(original)
    before = await claim_jobs.clock()
    await complete(
        claim_jobs.factory,
        original.id,
        result,
        worker_id="lifecycle-worker",
        attempt=original.attempts,
    )
    after = await claim_jobs.clock()

    async with claim_jobs.factory.begin() as observer:
        stored = await observer.scalar(
            select(Job).where(Job.id == original.id).with_for_update(nowait=True, of=Job)
        )
        assert stored is not None
        assert stored.finished_at is not None
        assert before <= stored.finished_at <= after
        assert stored.attempts == original.attempts
        assert stored.serial_key == original.serial_key
        assert stored.last_error == original.last_error
        expected = {
            **previous,
            "status": JobStatus.SUCCEEDED,
            "result": result,
            "finished_at": stored.finished_at,
            "locked_by": None,
            "lease_expires_at": None,
            "delivered": False,
        }
        assert _job_state(stored) == expected


async def test_complete_rejects_duplicate_completion_and_preserves_delivered_result(
    claim_jobs: ClaimJobs,
) -> None:
    original = await _start_lifecycle_job(claim_jobs)
    await complete(
        claim_jobs.factory,
        original.id,
        {"source": "accepted"},
        worker_id="lifecycle-worker",
        attempt=original.attempts,
    )
    async with claim_jobs.factory.begin() as session:
        await session.execute(update(Job).where(Job.id == original.id).values(delivered=True))
    accepted = _job_state(await _read_lifecycle_job(claim_jobs, original.id))

    with pytest.raises(JobOwnershipLostError):
        await complete(
            claim_jobs.factory,
            original.id,
            {"source": "duplicate"},
            worker_id="lifecycle-worker",
            attempt=original.attempts,
        )

    stored = await _read_lifecycle_job(claim_jobs, original.id)
    assert stored.result == {"source": "accepted"}
    assert stored.delivered is True
    assert _job_state(stored) == accepted


async def test_complete_invalid_result_rolls_back_and_keeps_claim_usable(
    claim_jobs: ClaimJobs,
) -> None:
    original = await _start_lifecycle_job(claim_jobs)
    previous = _job_state(original)
    with pytest.raises(StatementError, match="JSON serializable"):
        await complete(
            claim_jobs.factory,
            original.id,
            {"unsupported": object()},
            worker_id="lifecycle-worker",
            attempt=original.attempts,
        )

    stored = await _read_lifecycle_job(claim_jobs, original.id)
    assert _job_state(stored) == previous
    await complete(
        claim_jobs.factory,
        original.id,
        {"source": "valid-retry"},
        worker_id="lifecycle-worker",
        attempt=original.attempts,
    )
    succeeded = await _read_lifecycle_job(claim_jobs, original.id)
    assert succeeded.status == JobStatus.SUCCEEDED
    assert succeeded.result == {"source": "valid-retry"}
    assert succeeded.attempts == original.attempts


@pytest.mark.parametrize(
    ("running_queue", "waiting_queue"),
    [
        (JobQueue.SANDBOX, JobQueue.SANDBOX),
        (JobQueue.SANDBOX, JobQueue.PUBLISHER),
        (JobQueue.PUBLISHER, JobQueue.SANDBOX),
        (JobQueue.PUBLISHER, JobQueue.PUBLISHER),
    ],
)
async def test_complete_releases_serial_key_for_a_real_next_claim(
    claim_jobs: ClaimJobs, running_queue: JobQueue, waiting_queue: JobQueue
) -> None:
    key = f"pipeline:{uuid4()}"
    original = await _start_lifecycle_job(claim_jobs, queue=running_queue, serial_key=key)
    waiting = await claim_jobs.add(queue=waiting_queue, serial_key=key)
    blocked = await claim_next(
        claim_jobs.factory,
        queue=waiting_queue,
        worker_id="waiting-key-worker",
        lease_seconds=60,
    )
    assert blocked is None

    await complete(
        claim_jobs.factory,
        original.id,
        {"source": "serial-key-owner"},
        worker_id="lifecycle-worker",
        attempt=original.attempts,
    )
    next_claim = await claim_next(
        claim_jobs.factory,
        queue=waiting_queue,
        worker_id="waiting-key-worker",
        lease_seconds=60,
    )
    assert next_claim is not None
    assert next_claim.id == waiting.id
    assert next_claim.attempts == 1
    assert next_claim.serial_key == key

    previous = await _read_lifecycle_job(claim_jobs, original.id)
    assert previous.status == JobStatus.SUCCEEDED
    assert previous.serial_key == key
    assert previous.locked_by is None
    assert previous.lease_expires_at is None


@pytest.mark.parametrize("operation", ["heartbeat", "complete"])
@pytest.mark.parametrize("reuse_worker_id", [False, True], ids=["new-worker", "same-worker-id"])
async def test_worker_update_from_old_attempt_cannot_modify_a_new_claim(
    claim_jobs: ClaimJobs,
    operation: Literal["heartbeat", "complete"],
    reuse_worker_id: bool,
) -> None:
    """Simulate recovery until reclaim_expired is implemented in D7."""
    original = await _start_lifecycle_job(
        claim_jobs, worker_id="old-claim-worker", serial_key=f"pipeline:{uuid4()}"
    )
    old_attempt = original.attempts
    async with claim_jobs.factory.begin() as session:
        await session.execute(
            update(Job)
            .where(Job.id == original.id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    async with claim_jobs.factory.begin() as session:
        await session.execute(
            update(Job)
            .where(Job.id == original.id)
            .values(
                status=JobStatus.QUEUED,
                locked_by=None,
                lease_expires_at=None,
                run_after=func.clock_timestamp() - timedelta(seconds=1),
            )
        )

    new_worker_id = "old-claim-worker" if reuse_worker_id else "new-claim-worker"
    new_claim = await claim_next(
        claim_jobs.factory,
        queue=JobQueue.SANDBOX,
        worker_id=new_worker_id,
        lease_seconds=60,
    )
    assert new_claim is not None
    assert new_claim.id == original.id
    assert new_claim.attempts == old_attempt + 1
    current = _job_state(new_claim)

    with pytest.raises(JobOwnershipLostError):
        await _apply_worker_update(
            claim_jobs,
            original.id,
            operation=operation,
            worker_id="old-claim-worker",
            attempt=old_attempt,
        )
    stored = await _read_lifecycle_job(claim_jobs, original.id)
    assert _job_state(stored) == current

    await complete(
        claim_jobs.factory,
        new_claim.id,
        {"source": "new-claim"},
        worker_id=new_worker_id,
        attempt=new_claim.attempts,
    )
    accepted = _job_state(await _read_lifecycle_job(claim_jobs, original.id))
    with pytest.raises(JobOwnershipLostError):
        await complete(
            claim_jobs.factory,
            original.id,
            {"source": "late-old-claim"},
            worker_id="old-claim-worker",
            attempt=old_attempt,
        )
    succeeded = await _read_lifecycle_job(claim_jobs, original.id)
    assert succeeded.result == {"source": "new-claim"}
    assert succeeded.attempts == new_claim.attempts
    assert _job_state(succeeded) == accepted


async def test_heartbeat_racing_complete_cannot_revive_a_succeeded_job(
    claim_jobs: ClaimJobs,
) -> None:
    original = await _start_lifecycle_job(claim_jobs)
    barrier = asyncio.Barrier(2)

    async def renew() -> None:
        await barrier.wait()
        await heartbeat(
            claim_jobs.factory,
            original.id,
            worker_id="lifecycle-worker",
            attempt=original.attempts,
            lease_seconds=300,
        )

    async def finish() -> None:
        await barrier.wait()
        await complete(
            claim_jobs.factory,
            original.id,
            {"source": "concurrent-complete"},
            worker_id="lifecycle-worker",
            attempt=original.attempts,
        )

    tasks = [asyncio.create_task(renew()), asyncio.create_task(finish())]
    try:
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=10)
        assert results[1] is None
        assert results[0] is None or isinstance(results[0], JobOwnershipLostError)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    stored = await _read_lifecycle_job(claim_jobs, original.id)
    assert stored.status == JobStatus.SUCCEEDED
    assert stored.result == {"source": "concurrent-complete"}
    assert stored.attempts == original.attempts
    assert stored.locked_by is None
    assert stored.lease_expires_at is None
    assert stored.finished_at is not None


async def _wait_for_lifecycle_lock(
    claim_jobs: ClaimJobs,
    *,
    blocker_pid: int,
    operation_task: asyncio.Task[None],
) -> None:
    """Observe a real row-lock wait before releasing the blocking transaction."""
    async with asyncio.timeout(10):
        while True:
            if operation_task.done():
                operation_task.result()
                pytest.fail("The worker update returned while its job row was still locked")

            async with claim_jobs.factory() as observer:
                waiting = await observer.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock' "
                        "AND query LIKE 'SELECT jobs.id%' "
                        "AND :blocker_pid = ANY(pg_blocking_pids(pid)))"
                    ),
                    {"blocker_pid": blocker_pid},
                )
            if waiting:
                return
            await asyncio.sleep(0.01)


async def _wait_for_db_deadline(claim_jobs: ClaimJobs, deadline: datetime) -> None:
    """Wait for a timer event and confirm expiry using the database clock."""
    loop = asyncio.get_running_loop()
    async with asyncio.timeout(10):
        while True:
            db_now = await claim_jobs.clock()
            remaining_seconds = (deadline - db_now).total_seconds()
            if remaining_seconds <= 0:
                return

            wake_up = asyncio.Event()
            timer = loop.call_later(remaining_seconds, wake_up.set)
            try:
                await wake_up.wait()
            finally:
                timer.cancel()


@pytest.mark.parametrize("operation", ["heartbeat", "complete"])
async def test_worker_update_rechecks_lease_after_waiting_for_unchanged_row_lock(
    claim_jobs: ClaimJobs, operation: Literal["heartbeat", "complete"]
) -> None:
    """Expire the lease while blocked without changing the row during the lock wait."""
    original = await _start_lifecycle_job(claim_jobs)
    async with claim_jobs.factory.begin() as session:
        await session.execute(
            update(Job)
            .where(Job.id == original.id)
            .values(lease_expires_at=func.clock_timestamp() + timedelta(seconds=1))
        )
    shortened = await _read_lifecycle_job(claim_jobs, original.id)
    deadline = shortened.lease_expires_at
    assert deadline is not None
    previous = _job_state(shortened)
    operation_task: asyncio.Task[None] | None = None

    try:
        async with claim_jobs.factory() as blocker:
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(blocker_pid, int)
            locked = await blocker.scalar(
                select(Job).where(Job.id == original.id).with_for_update(of=Job)
            )
            assert locked is not None
            operation_task = asyncio.create_task(
                _apply_worker_update(
                    claim_jobs, original.id, operation=operation, attempt=original.attempts
                )
            )
            await _wait_for_lifecycle_lock(
                claim_jobs, blocker_pid=blocker_pid, operation_task=operation_task
            )
            await _wait_for_db_deadline(claim_jobs, deadline)
            assert blocker.in_transaction()
            await blocker.rollback()

            with pytest.raises(JobOwnershipLostError):
                await asyncio.wait_for(operation_task, timeout=10)
    finally:
        if operation_task is not None:
            if not operation_task.done():
                operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)

    stored = await _read_lifecycle_job(claim_jobs, original.id)
    assert _job_state(stored) == previous


@pytest.mark.skip(reason="TODO")
async def test_expired_lease_is_reclaimed(database_url: str) -> None:
    """TODO: a running job with an expired lease is requeued, or failed when out of attempts."""
