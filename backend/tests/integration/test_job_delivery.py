"""Durable worker-result delivery across stale projections, crashes and multiple API pools."""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.agents.schemas import ModelerOutput
from app.core.config import WorkerSettings
from app.db.checkpointer import open_postgres_checkpointer
from app.db.models import DesignVersion, Job, JobQueue, JobStatus, RunStatus
from app.db.session import make_engine, make_sessionmaker
from app.graph.builder import build_graph
from app.graph.context import GraphContext
from app.jobs import queue
from app.services import runs as service
from tests.designs import minimal_design, minimal_profile
from tests.integration.test_graph_design_gate import ScriptedModeler, fake_hash
from tests.integration.test_run_creation import creation as creation
from tests.integration.test_run_creation import creation_password_hash as creation_password_hash
from worker.main import poll_jobs

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.graph.builder import PipelineGraph
    from tests.integration.test_run_creation import RunCreationScenario

pytestmark = pytest.mark.integration


class ProcessCrash(BaseException):
    """Stop at a persistence boundary without invoking application exception handlers."""


@dataclass
class Delivery:
    base: RunCreationScenario
    modeler: ScriptedModeler
    context: GraphContext

    async def begin(self) -> tuple[UUID, Job]:
        response = await self.base.create()
        assert response.status_code == 200, response.text
        run_id = UUID(response.json()["id"])
        return run_id, (await self.base.jobs(run_id))[0]

    async def finish(self, job: Job, *, failed: bool = False) -> None:
        async with self.base.factory.begin() as session:
            stored = await session.get(Job, job.id)
            assert stored is not None
            stored.status = JobStatus.FAILED if failed else JobStatus.SUCCEEDED
            stored.result = None if failed else minimal_profile().model_dump(mode="json")
            stored.last_error = "child_failed" if failed else None
            stored.finished_at = func.clock_timestamp()

    async def deliver(self) -> int:
        return await service.deliver_finished_jobs(self.base.factory, self.base.graph, self.context)

    async def job(self, job_id: UUID) -> Job:
        async with self.base.factory() as session:
            job = await session.get(Job, job_id)
        assert job is not None
        return job

    async def assert_gate(self, run_id: UUID, job_id: UUID) -> None:
        run = await self.base.row(run_id)
        assert run.status is RunStatus.WAITING_DESIGN_APPROVAL
        assert run.pending is not None
        assert run.pending["kind"] == "design_gate"
        assert run.interrupt_id is not None
        assert (await self.job(job_id)).delivered
        assert len(self.modeler.calls) == 1
        assert len(await self.base.jobs(run_id)) == 1
        async with self.base.factory() as session:
            versions = list(
                await session.scalars(select(DesignVersion).where(DesignVersion.run_id == run_id))
            )
        assert len(versions) == 1


@pytest.fixture
def delivery(creation: RunCreationScenario) -> Delivery:
    modeler = ScriptedModeler([ModelerOutput(design=minimal_design()) for _ in range(4)])
    context = GraphContext(
        sessionmaker=creation.factory,
        propose_design=modeler,
        hash_design=fake_hash,
        check_design=lambda design: [],
        check_modeler_output=lambda output: [],
    )
    creation.app.state.graph_context = context
    return Delivery(creation, modeler, context)


@asynccontextmanager
async def another_api(
    scenario: Delivery, database_url: str
) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], PipelineGraph, GraphContext]]:
    engine = make_engine(database_url)
    try:
        isolated = engine.execution_options(schema_translate_map={None: scenario.base.schema})
        factory = make_sessionmaker(isolated)
        conn_string = make_url(database_url).set(drivername="postgresql").render_as_string(False)
        async with open_postgres_checkpointer(conn_string) as saver:
            context = GraphContext(
                sessionmaker=factory,
                propose_design=scenario.modeler,
                hash_design=fake_hash,
                check_design=lambda design: [],
                check_modeler_output=lambda output: [],
            )
            yield factory, build_graph(saver), context
    finally:
        await engine.dispose()


async def test_stale_running_projection_still_delivers_to_checkpoint(delivery: Delivery) -> None:
    run_id, job = await delivery.begin()
    await delivery.finish(job)
    await service._mark_job_resuming(delivery.base.factory, run_id)
    assert await delivery.deliver() == 1
    await delivery.assert_gate(run_id, job.id)


async def test_crash_after_projection_commit_is_recovered_by_another_api(
    delivery: Delivery, monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    run_id, job = await delivery.begin()
    await delivery.finish(job)
    original = service._mark_job_resuming

    async def crash(*args: Any, **kwargs: Any) -> None:
        await original(*args, **kwargs)
        raise ProcessCrash

    with monkeypatch.context() as patch:
        patch.setattr(service, "_mark_job_resuming", crash)
        with pytest.raises(ProcessCrash):
            await delivery.deliver()
    assert not (await delivery.job(job.id)).delivered
    async with another_api(delivery, database_url) as (factory, graph, context):
        assert await service.deliver_finished_jobs(factory, graph, context) == 1
    await delivery.assert_gate(run_id, job.id)


@pytest.mark.parametrize("after_commit", [False, True])
async def test_crash_at_acknowledgement_does_not_repeat_modeler(
    delivery: Delivery,
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    after_commit: bool,
) -> None:
    run_id, job = await delivery.begin()
    await delivery.finish(job)
    original = service._mark_delivered

    async def crash(*args: Any, **kwargs: Any) -> None:
        if after_commit:
            await original(*args, **kwargs)
        raise ProcessCrash

    with monkeypatch.context() as patch:
        patch.setattr(service, "_mark_delivered", crash)
        with pytest.raises(ProcessCrash):
            await delivery.deliver()
    pending = (await delivery.base.row(run_id)).pending
    async with another_api(delivery, database_url) as (factory, graph, context):
        assert await service.deliver_finished_jobs(factory, graph, context) == 0
    await delivery.assert_gate(run_id, job.id)
    assert (await delivery.base.row(run_id)).pending == pending


async def test_crash_after_checkpoint_before_projection_sync_preserves_gate(
    delivery: Delivery, monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    run_id, job = await delivery.begin()
    await delivery.finish(job)
    with monkeypatch.context() as patch:
        patch.setattr(service, "sync_run", crash_sync)
        with pytest.raises(ProcessCrash):
            await delivery.deliver()
    assert (await delivery.base.row(run_id)).status is RunStatus.RUNNING
    async with another_api(delivery, database_url) as (factory, graph, context):
        await service.deliver_finished_jobs(factory, graph, context)
    await delivery.assert_gate(run_id, job.id)


async def crash_sync(*args: Any, **kwargs: Any) -> RunStatus:
    raise ProcessCrash


async def test_crash_between_profile_checkpoint_and_modeler_continues_without_resume(
    delivery: Delivery, database_url: str
) -> None:
    run_id, job = await delivery.begin()
    await delivery.finish(job)

    async def crash_modeler(**kwargs: Any) -> ModelerOutput:
        raise ProcessCrash

    crashing_context = GraphContext(
        sessionmaker=delivery.base.factory, propose_design=crash_modeler
    )
    with pytest.raises(ProcessCrash):
        await service.deliver_finished_jobs(
            delivery.base.factory, delivery.base.graph, crashing_context
        )
    snapshot = await delivery.base.graph.aget_state(service.thread_config(run_id))
    assert str(job.id) in snapshot.values["consumed_job_ids"]
    assert len(delivery.modeler.calls) == 0
    async with another_api(delivery, database_url) as (factory, graph, context):
        await service.deliver_finished_jobs(factory, graph, context)
    await delivery.assert_gate(run_id, job.id)


async def test_two_api_pools_deliver_once(delivery: Delivery, database_url: str) -> None:
    run_id, job = await delivery.begin()
    await delivery.finish(job)
    async with another_api(delivery, database_url) as (factory, graph, context):
        counts = await asyncio.gather(
            delivery.deliver(),
            service.deliver_finished_jobs(factory, graph, context),
        )
    assert sum(counts) == 1
    await delivery.assert_gate(run_id, job.id)


async def test_mismatched_job_kind_is_not_acknowledged(delivery: Delivery) -> None:
    run_id, job = await delivery.begin()
    await delivery.finish(job)
    async with delivery.base.factory.begin() as session:
        stored = await session.get(Job, job.id)
        assert stored is not None
        stored.kind = "dbt_build"
    assert await delivery.deliver() == 0
    assert not (await delivery.job(job.id)).delivered
    assert (await delivery.base.row(run_id)).status is RunStatus.WAITING_JOB
    assert delivery.modeler.calls == []


async def test_unrelated_job_is_not_acknowledged(delivery: Delivery) -> None:
    run_id, expected = await delivery.begin()
    async with delivery.base.factory.begin() as session:
        other = Job(
            queue=JobQueue.SANDBOX,
            kind="profile",
            payload=expected.payload,
            run_id=run_id,
            status=JobStatus.SUCCEEDED,
            result=minimal_profile().model_dump(mode="json"),
            finished_at=func.clock_timestamp(),
        )
        session.add(other)
    assert await delivery.deliver() == 0
    assert not (await delivery.job(other.id)).delivered
    assert delivery.modeler.calls == []


async def test_missing_checkpoint_keeps_result_for_recovery(delivery: Delivery) -> None:
    async with delivery.base.factory() as session:
        run_id = await service.start_run(
            session,
            project_id=delivery.base.project_id,
            batch_id=delivery.base.batch_id,
            request_text="Not started",
        )
    async with delivery.base.factory.begin() as session:
        job = Job(
            run_id=run_id,
            queue=JobQueue.SANDBOX,
            kind="profile",
            payload={},
            status=JobStatus.SUCCEEDED,
            result=minimal_profile().model_dump(mode="json"),
            finished_at=func.clock_timestamp(),
        )
        session.add(job)
    assert await delivery.deliver() == 0
    assert not (await delivery.job(job.id)).delivered


async def test_invalid_profile_is_rejected_without_resuming_and_other_runs_continue(
    delivery: Delivery,
) -> None:
    bad_run, bad_job = await delivery.begin()
    good_run, good_job = await delivery.begin()
    await delivery.finish(bad_job)
    await delivery.finish(good_job)
    async with delivery.base.factory.begin() as session:
        stored = await session.get(Job, bad_job.id)
        assert stored is not None
        stored.result = {"unexpected": "invalid"}
    assert await delivery.deliver() == 1
    assert not (await delivery.job(bad_job.id)).delivered
    assert (await delivery.base.row(bad_run)).status is RunStatus.WAITING_JOB
    await delivery.assert_gate(good_run, good_job.id)


async def test_failed_job_receipt_is_durable_and_does_not_call_modeler(delivery: Delivery) -> None:
    run_id, job = await delivery.begin()
    await delivery.finish(job, failed=True)
    assert await delivery.deliver() == 1
    assert await delivery.deliver() == 0
    assert (await delivery.job(job.id)).delivered
    run = await delivery.base.row(run_id)
    assert run.status is RunStatus.FAILED
    assert run.error == "Profiling failed: child_failed"
    assert delivery.modeler.calls == []


async def test_profile_node_rejects_outcome_for_another_job(delivery: Delivery) -> None:
    run_id, job = await delivery.begin()
    snapshot = await delivery.base.graph.aget_state(service.thread_config(run_id))
    interrupt_id = snapshot.tasks[0].interrupts[0].id
    with pytest.raises(ValueError, match="does not match"):
        await delivery.base.graph.ainvoke(
            Command(
                resume={
                    interrupt_id: {
                        "job_id": str(uuid4()),
                        "status": JobStatus.SUCCEEDED.value,
                        "result": minimal_profile().model_dump(mode="json"),
                    }
                }
            ),
            service.thread_config(run_id),
            context=delivery.context,
        )
    assert delivery.modeler.calls == []
    assert len(await delivery.base.jobs(run_id)) == 1
    assert not (await delivery.job(job.id)).delivered


@pytest.mark.skipif(sys.platform != "linux", reason="Linux confined profile child")
async def test_real_worker_and_delivery_loop_reach_gate(
    delivery: Delivery, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, job = await delivery.begin()
    stop = asyncio.Event()
    delivered = asyncio.Event()
    original_mark = service._mark_delivered
    original = queue.complete

    async def complete(*args: Any, **kwargs: Any) -> None:
        await original(*args, **kwargs)
        stop.set()

    async def mark(*args: Any, **kwargs: Any) -> None:
        await original_mark(*args, **kwargs)
        delivered.set()

    monkeypatch.setattr(service, "_mark_delivered", mark)
    monkeypatch.setattr(queue, "complete", complete)
    config = WorkerSettings(
        _env_file=None,
        worker_id="end-to-end-worker",
        poll_interval_seconds=0.01,
        run_timeout_seconds=20,
        run_cpu_seconds=10,
    )
    worker = asyncio.create_task(
        poll_jobs(delivery.base.factory, delivery.base.storage, config, shutdown=stop)
    )
    api = asyncio.create_task(
        service.job_delivery_loop(
            delivery.base.factory,
            delivery.base.graph,
            delivery.context,
            interval_seconds=0.02,
        )
    )
    try:
        async with asyncio.timeout(20):
            await worker
            await delivered.wait()
        await delivery.assert_gate(run_id, job.id)
        stored = await delivery.job(job.id)
        assert stored.result is not None
        assert {table["name"] for table in stored.result["tables"]} == {"customers", "orders"}
    finally:
        stop.set()
        await worker
        api.cancel()
        with pytest.raises(asyncio.CancelledError):
            await api


async def test_unrelated_full_delivery_batch_does_not_starve_matching_job(
    delivery: Delivery,
) -> None:
    run_id, job = await delivery.begin()
    await delivery.finish(job)
    async with delivery.base.factory.begin() as session:
        session.add_all(
            [
                Job(
                    id=UUID(int=index + 1),
                    run_id=run_id,
                    queue=JobQueue.SANDBOX,
                    kind="profile",
                    payload={},
                    status=JobStatus.SUCCEEDED,
                    result=minimal_profile().model_dump(mode="json"),
                    finished_at=func.clock_timestamp(),
                )
                for index in range(service.DELIVERY_BATCH_SIZE)
            ]
        )
    assert await delivery.deliver() == 1
    run = await delivery.base.row(run_id)
    assert run.status is RunStatus.WAITING_DESIGN_APPROVAL
    assert (await delivery.job(job.id)).delivered
    assert len(delivery.modeler.calls) == 1


async def test_resume_failure_is_not_acknowledged_before_consumption(
    delivery: Delivery, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, job = await delivery.begin()
    await delivery.finish(job)
    with monkeypatch.context() as patch:
        patch.setattr(
            delivery.base.graph, "ainvoke", AsyncMock(side_effect=RuntimeError("Unavailable"))
        )
        assert await delivery.deliver() == 0
    assert not (await delivery.job(job.id)).delivered
    assert (await delivery.base.row(run_id)).status is RunStatus.FAILED
    assert await delivery.deliver() == 1
    await delivery.assert_gate(run_id, job.id)
