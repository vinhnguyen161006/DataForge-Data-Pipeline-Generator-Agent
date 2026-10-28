"""Startup recovery through new application lifespans and PostgreSQL checkpoint pools."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url

from app import main
from app.agents.schemas import ModelerOutput
from app.api.routes import health, runs
from app.core.config import ApiSettings
from app.db.checkpointer import open_postgres_checkpointer
from app.db.models import PipelineRun, RunStatus
from app.db.session import make_engine
from app.graph.context import GraphContext
from app.services import runs as service
from tests.integration.test_graph_design_gate import AMOUNT_QUESTION, fake_hash
from tests.integration.test_job_delivery import delivery as delivery
from tests.integration.test_run_creation import creation as creation
from tests.integration.test_run_creation import creation_password_hash as creation_password_hash

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from uuid import UUID

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from app.agents.llm import StructuredLLM
    from tests.integration.test_job_delivery import Delivery

pytestmark = pytest.mark.integration


@dataclass
class StartupApps:
    scenario: Delivery
    settings: ApiSettings
    engines: list[AsyncEngine] = field(default_factory=list)
    savers: list[AsyncPostgresSaver] = field(default_factory=list)
    closed_savers: list[AsyncPostgresSaver] = field(default_factory=list)

    @asynccontextmanager
    async def open_saver(self, conn_string: str) -> AsyncIterator[AsyncPostgresSaver]:
        async with open_postgres_checkpointer(conn_string) as saver:
            self.savers.append(saver)
            try:
                yield saver
            finally:
                self.closed_savers.append(saver)

    def app(self) -> FastAPI:
        app = FastAPI(lifespan=main.make_lifespan(self.settings, self.open_saver))
        app.include_router(runs.router, prefix="/api")
        app.include_router(health.router, prefix="/api")
        return app

    async def poll(self, app: FastAPI, run_id: UUID) -> dict[str, object]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://startup.test"
        ) as client:
            response = await client.get(
                f"/api/projects/{self.scenario.base.project_id}/runs/{run_id}",
                headers=self.scenario.base.headers["engineer"],
            )
            assert response.status_code == 200, response.text
            assert (await client.get("/api/health")).status_code == 200
            return dict(response.json())


@pytest.fixture
def startup_apps(
    delivery: Delivery, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> StartupApps:
    conn_string = make_url(database_url).set(drivername="postgresql").render_as_string(False)
    apps = StartupApps(
        delivery,
        ApiSettings(
            _env_file=None,
            app_database_url=database_url,
            checkpoint_database_url=conn_string,
            job_delivery_enabled=True,
            job_delivery_interval_seconds=0.1,
            job_delivery_startup_timeout_seconds=30,
        ),
    )

    def engine(url: str) -> AsyncEngine:
        result = make_engine(url).execution_options(
            schema_translate_map={None: delivery.base.schema}
        )
        apps.engines.append(result)
        return result

    def context(factory: async_sessionmaker[AsyncSession], llm: StructuredLLM) -> GraphContext:
        return GraphContext(
            sessionmaker=factory,
            propose_design=delivery.modeler,
            hash_design=fake_hash,
            check_design=lambda design: [],
            check_modeler_output=lambda output: [],
        )

    monkeypatch.setattr(main, "make_engine", engine)
    monkeypatch.setattr(main, "make_llm", lambda settings: None)
    monkeypatch.setattr(main, "make_graph_context", context)
    return apps


async def unstarted_run(scenario: Delivery) -> UUID:
    async with scenario.base.factory() as session:
        return await service.start_run(
            session,
            project_id=scenario.base.project_id,
            batch_id=scenario.base.batch_id,
            request_text="Recover this committed run",
        )


async def corrupt_projection(scenario: Delivery, run_id: UUID) -> None:
    async with scenario.base.factory.begin() as session:
        run = await session.get(PipelineRun, run_id)
        assert run is not None
        run.status = RunStatus.RUNNING
        run.pending = None
        run.interrupt_id = None
        run.current_step = None


async def test_startup_recovers_unstarted_run_before_first_poll(startup_apps: StartupApps) -> None:
    scenario = startup_apps.scenario
    run_id = await unstarted_run(scenario)
    app = startup_apps.app()
    async with LifespanManager(app, startup_timeout=40):
        body = await startup_apps.poll(app, run_id)
        assert body["status"] == RunStatus.WAITING_JOB.value
        jobs = await scenario.base.jobs(run_id)
        assert len(jobs) == 1
        assert body["pending"] == {"kind": "job", "job_id": str(jobs[0].id), "job_kind": "profile"}
        assert app.state.sessionmaker is not scenario.base.factory
        assert app.state.graph is not scenario.base.graph
        assert scenario.modeler.calls == []
    assert startup_apps.closed_savers == startup_apps.savers


async def test_startup_restores_waiting_job_without_enqueuing_again(
    startup_apps: StartupApps,
) -> None:
    scenario = startup_apps.scenario
    run_id, job = await scenario.begin()
    before = await scenario.base.row(run_id)
    pending = before.pending
    await corrupt_projection(scenario, run_id)
    app = startup_apps.app()
    async with LifespanManager(app, startup_timeout=40):
        body = await startup_apps.poll(app, run_id)
        assert body["status"] == RunStatus.WAITING_JOB.value
        assert body["pending"] == pending
        assert [item.id for item in await scenario.base.jobs(run_id)] == [job.id]
        assert scenario.modeler.calls == []


async def test_startup_delivers_offline_worker_result_before_first_poll(
    startup_apps: StartupApps,
) -> None:
    scenario = startup_apps.scenario
    run_id, job = await scenario.begin()
    await scenario.finish(job)
    app = startup_apps.app()
    async with LifespanManager(app, startup_timeout=40):
        body = await startup_apps.poll(app, run_id)
        assert body["status"] == RunStatus.WAITING_DESIGN_APPROVAL.value
        await scenario.assert_gate(run_id, job.id)
        assert (await scenario.base.counts())["approvals"] == 0


@pytest.mark.parametrize("clarification", [False, True], ids=["design_gate", "clarification"])
async def test_startup_preserves_human_interrupt_without_resuming(
    startup_apps: StartupApps, clarification: bool
) -> None:
    scenario = startup_apps.scenario
    if clarification:
        scenario.modeler.outputs = [ModelerOutput(questions=[AMOUNT_QUESTION])]
    run_id, job = await scenario.begin()
    await scenario.finish(job)
    await scenario.deliver()
    before = await scenario.base.row(run_id)
    expected_status = before.status.value
    expected_pending = before.pending
    expected_interrupt = before.interrupt_id
    counts = await scenario.base.counts()
    calls = len(scenario.modeler.calls)
    await corrupt_projection(scenario, run_id)
    app = startup_apps.app()
    async with LifespanManager(app, startup_timeout=40):
        body = await startup_apps.poll(app, run_id)
        assert body["status"] == expected_status
        assert body["pending"] == expected_pending
        assert body["interrupt_id"] == expected_interrupt
        assert await scenario.base.counts() == counts
        assert len(scenario.modeler.calls) == calls
        assert counts["approvals"] == 0


@pytest.mark.parametrize("finished", [False, True], ids=["unstarted", "finished_profile"])
async def test_two_startups_and_repeated_recovery_do_not_duplicate_work(
    startup_apps: StartupApps, finished: bool
) -> None:
    scenario = startup_apps.scenario
    if finished:
        run_id, job = await scenario.begin()
        await scenario.finish(job)
    else:
        run_id = await unstarted_run(scenario)
    apps = [startup_apps.app(), startup_apps.app()]
    async with AsyncExitStack() as stack:
        results = await asyncio.gather(
            *(stack.enter_async_context(LifespanManager(app, startup_timeout=40)) for app in apps),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        assert len(startup_apps.engines) == 2
        assert startup_apps.engines[0] is not startup_apps.engines[1]
        assert startup_apps.savers[0] is not startup_apps.savers[1]
        assert apps[0].state.sessionmaker is not apps[1].state.sessionmaker
        assert apps[0].state.graph is not apps[1].state.graph
        bodies = await asyncio.gather(*(startup_apps.poll(app, run_id) for app in apps))
        assert bodies[0] == bodies[1]
        counts = await scenario.base.counts()
        await asyncio.gather(
            *(
                service.recover_pending_runs(
                    app.state.sessionmaker, app.state.graph, app.state.graph_context
                )
                for app in apps
            )
        )
        assert await scenario.base.counts() == counts
        assert len(await scenario.base.jobs(run_id)) == 1
        assert counts["approvals"] == 0
        if finished:
            assert len(scenario.modeler.calls) == 1
            assert counts["design_versions"] == 1
            await scenario.assert_gate(run_id, job.id)
        else:
            assert scenario.modeler.calls == []
            assert counts["design_versions"] == 0
    assert len(startup_apps.closed_savers) == 2
