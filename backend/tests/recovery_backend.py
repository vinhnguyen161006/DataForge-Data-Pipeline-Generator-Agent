"""Independent application lifetimes over committed recovery data and native profile jobs."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import event, select
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from app import main
from app.core.config import WorkerSettings, get_api_settings
from app.core.security import create_access_token
from app.db.checkpointer import open_postgres_checkpointer
from app.db.models import (
    Approval,
    Base,
    Batch,
    BatchStatus,
    DesignVersion,
    Job,
    JobQueue,
    JobStatus,
    PipelineRun,
    Project,
    ProjectMember,
    ProjectRole,
    RunResumeIntent,
    SourceFile,
    User,
)
from app.db.session import make_engine, make_sessionmaker
from app.graph.context import GraphContext
from app.jobs import queue
from app.profiler.schemas import DataProfile
from app.services.runs import job_delivery_loop, thread_config
from tests.designs import minimal_design
from tests.integration.test_run_decisions import small_graph
from tests.profile_jobs import make_profile_job
from worker.lifecycle import execute_job

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

    import pytest
    from fastapi import FastAPI
    from httpx import Response
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from sqlalchemy.engine import Engine
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from app.agents.llm import StructuredLLM
    from app.agents.schemas import DataDesign, ModelerOutput
    from app.graph.builder import PipelineGraph


def registration_design() -> DataDesign:
    design = minimal_design()
    design.facts[0].source_tables = ["studentregistration"]
    design.keys[0].table = "studentregistration"
    return design


@dataclass
class Lifetime:
    generation: int
    events: list[str] = field(default_factory=list)
    engine_count: int = 0
    saver_count: int = 0
    graph_count: int = 0
    context_count: int = 0
    checked_out: set[int] = field(default_factory=set)
    disposed_without_checkouts: bool = False
    engine_disposed: bool = False
    saver_closed: bool = False
    client_closed: bool = False
    delivery_stopped: bool = False

    def assert_closed(self) -> None:
        assert self.engine_count == self.saver_count == self.graph_count == self.context_count == 1
        assert not self.checked_out
        assert self.disposed_without_checkouts
        assert self.engine_disposed
        assert self.saver_closed
        assert self.client_closed
        assert self.delivery_stopped
        assert self.events.index("client_closed") < self.events.index("delivery_stopped")
        assert self.events.index("delivery_stopped") < self.events.index("saver_closed")
        assert self.events.index("saver_closed") < self.events.index("engine_disposed")


@dataclass(frozen=True)
class RunEvidence:
    run_id: UUID
    view: dict[str, Any]
    thread_id: str
    checkpoint_values: dict[str, Any]
    interrupts: list[dict[str, Any]]
    records: dict[str, list[dict[str, Any]]]
    modeler_calls: int
    codegen_runs: tuple[str, ...]
    worker_executions: int


class RecoveryModeler:
    def __init__(self, scenario: RecoveryScenario, outputs: Sequence[ModelerOutput]) -> None:
        self.scenario = scenario
        self.outputs = list(outputs)

    async def __call__(
        self,
        *,
        request_text: str,
        profile: DataProfile,
        answers: list[dict[str, str]],
        returned_design: DataDesign | None,
        reviewer_feedback: str | None,
    ) -> ModelerOutput:
        self.scenario.modeler_calls.append(
            {
                "generation": self.scenario.current_lifetime().generation,
                "returned_design": (
                    returned_design.model_dump(mode="json") if returned_design else None
                ),
                "reviewer_feedback": reviewer_feedback,
            }
        )
        if not self.outputs:
            raise AssertionError("Recovery must not call the Modeler without a new decision")
        return self.outputs.pop(0)


@dataclass
class Backend:
    scenario: RecoveryScenario
    lifetime: Lifetime
    app: FastAPI | None
    client: AsyncClient | None

    def application(self) -> FastAPI:
        if self.app is None:
            raise RuntimeError("This application lifetime is closed")
        return self.app

    def http(self) -> AsyncClient:
        if self.client is None:
            raise RuntimeError("This HTTP client lifetime is closed")
        return self.client

    def factory(self) -> async_sessionmaker[AsyncSession]:
        result: async_sessionmaker[AsyncSession] = self.application().state.sessionmaker
        return result

    def graph(self) -> PipelineGraph:
        result: PipelineGraph = self.application().state.graph
        return result

    def path(self, run_id: UUID | None = None) -> str:
        base = f"/api/projects/{self.scenario.project_id}/runs"
        return f"{base}/{run_id}" if run_id is not None else base

    async def view(self, run_id: UUID) -> dict[str, Any]:
        response = await self.http().get(self.path(run_id), headers=self.scenario.headers)
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        assert result["status"] != "failed", result
        return result

    async def records(self, run_id: UUID) -> dict[str, list[dict[str, Any]]]:
        factory = self.factory()
        async with factory() as session:
            jobs = list(
                await session.scalars(select(Job).where(Job.run_id == run_id).order_by(Job.id))
            )
            designs = list(
                await session.scalars(
                    select(DesignVersion)
                    .where(DesignVersion.run_id == run_id)
                    .order_by(DesignVersion.version)
                )
            )
            approvals = list(
                await session.scalars(
                    select(Approval)
                    .where(Approval.run_id == run_id)
                    .order_by(Approval.created_at, Approval.id)
                )
            )
            intents = list(
                await session.scalars(
                    select(RunResumeIntent)
                    .where(RunResumeIntent.run_id == run_id)
                    .order_by(RunResumeIntent.created_at, RunResumeIntent.id)
                )
            )
        return deepcopy(
            {
                "jobs": [
                    {
                        "id": str(row.id),
                        "status": row.status.value,
                        "attempts": row.attempts,
                        "delivered": row.delivered,
                        "result": row.result,
                        "last_error": row.last_error,
                    }
                    for row in jobs
                ],
                "designs": [
                    {
                        "id": str(row.id),
                        "version": row.version,
                        "content": row.content,
                        "hash": row.content_hash,
                        "edited": row.edited_by_user,
                    }
                    for row in designs
                ],
                "approvals": [
                    {
                        "id": str(row.id),
                        "decision": row.decision.value,
                        "actor_id": str(row.approver_id),
                        "fingerprint": row.fingerprint,
                        "parts": row.fingerprint_parts,
                        "comment": row.comment,
                    }
                    for row in approvals
                ],
                "intents": [
                    {
                        "id": str(row.id),
                        "interrupt_id": row.interrupt_id,
                        "actor_id": str(row.actor_id),
                        "payload": row.payload,
                        "delivered": row.delivered,
                    }
                    for row in intents
                ],
            }
        )

    async def evidence(self, run_id: UUID) -> RunEvidence:
        view = await self.view(run_id)
        snapshot = await self.graph().aget_state(thread_config(run_id))
        return RunEvidence(
            run_id=run_id,
            view=deepcopy({key: value for key, value in view.items() if key != "updated_at"}),
            thread_id=str(snapshot.config["configurable"]["thread_id"]),
            checkpoint_values=deepcopy(snapshot.values),
            interrupts=[
                {"id": item.id, "value": deepcopy(item.value)}
                for task in snapshot.tasks
                for item in task.interrupts
            ],
            records=await self.records(run_id),
            modeler_calls=len(self.scenario.modeler_calls),
            codegen_runs=tuple(self.scenario.codegen_runs),
            worker_executions=self.scenario.worker_executions,
        )

    async def wait_for_gate(
        self, run_id: UUID, *, version: int = 1, timeout_seconds: float = 30
    ) -> dict[str, Any]:
        async with asyncio.timeout(timeout_seconds):
            for _ in range(600):
                view = await self.view(run_id)
                records = await self.records(run_id)
                pending = view["pending"]
                if (
                    view["status"] == "waiting_design_approval"
                    and pending["version"] == version
                    and len(records["jobs"]) == 1
                    and records["jobs"][0]["delivered"]
                    and all(row["delivered"] for row in records["intents"])
                ):
                    return view
                await asyncio.sleep(0.05)
        raise AssertionError("The run did not reach its expected design gate")

    async def reach_gate(self) -> RunEvidence:
        response = await self.http().post(
            self.path(),
            headers=self.scenario.headers,
            json={"batch_id": str(self.scenario.batch_id), "request_text": "Count registrations"},
        )
        assert response.status_code == 200, response.text
        run_id = UUID(response.json()["id"])
        view = await self.view(run_id)
        assert view["status"] == "waiting_job", view
        settings = WorkerSettings(
            _env_file=None,
            worker_id="recovery-worker",
            lease_seconds=60,
            heartbeat_interval_seconds=1,
            database_timeout_seconds=5,
            run_timeout_seconds=20,
            run_cpu_seconds=10,
            run_max_file_mb=32,
        )
        job = await queue.claim_next(
            self.factory(),
            queue=JobQueue.SANDBOX,
            worker_id=settings.worker_id,
            lease_seconds=settings.lease_seconds,
        )
        assert job is not None
        assert str(job.id) == view["pending"]["job_id"]
        self.scenario.worker_executions += 1
        async with asyncio.timeout(30):
            await execute_job(
                self.factory(), self.scenario.storage, settings, job, shutdown=asyncio.Event()
            )
        records = await self.records(run_id)
        assert records["jobs"][0]["status"] == JobStatus.SUCCEEDED.value, records
        profile = DataProfile.model_validate(records["jobs"][0]["result"])
        assert [(row.name, row.row_count) for row in profile.tables] == [("studentregistration", 3)]
        await self.wait_for_gate(run_id)
        before = await self.evidence(run_id)
        assert before.thread_id == str(run_id)
        assert before.checkpoint_values["batch_id"] == str(self.scenario.batch_id)
        assert before.checkpoint_values["project_id"] == str(self.scenario.project_id)
        assert before.interrupts == [
            {"id": before.view["interrupt_id"], "value": before.view["pending"]}
        ]
        assert before.codegen_runs == ()
        assert before.modeler_calls == before.worker_executions == 1
        assert len(before.records["designs"]) == 1
        assert before.records["approvals"] == before.records["intents"] == []
        return before

    async def decide(self, run_id: UUID, body: dict[str, Any]) -> Response:
        return await self.http().post(
            f"{self.path(run_id)}/design-decision",
            headers=self.scenario.headers,
            json=body,
        )

    async def wait_for_codegen(self, run_id: UUID) -> None:
        async with asyncio.timeout(10):
            for _ in range(200):
                await self.view(run_id)
                records = await self.records(run_id)
                if (
                    self.scenario.codegen_runs == [str(run_id)]
                    and records["intents"]
                    and all(row["delivered"] for row in records["intents"])
                ):
                    return
                await asyncio.sleep(0.05)
        raise AssertionError("The accepted design did not reach the codegen probe")


class RecoveryScenario:
    def __init__(self, database_url: str, root: Path, password_hash: str) -> None:
        self.database_url = database_url
        self.checkpoint_url = (
            make_url(database_url).set(drivername="postgresql").render_as_string(False)
        )
        self.schema = "run_recovery_" + uuid4().hex
        self.storage, request = make_profile_job(
            root,
            {
                "studentRegistration.csv": (
                    "code_module,code_presentation,id_student,date_registration\n"
                    "AAA,2026J,00001,0\nAAA,2026J,00002,1\nBBB,2026J,00003,2\n"
                )
            },
        )
        self.manifest = request.manifest
        self.project_id = request.identity.project_id
        self.batch_id = request.identity.batch_id
        self.engineer_id = uuid4()
        self.password_hash = password_hash
        self.secret = secrets.token_urlsafe(48)
        self.headers = {
            "Authorization": f"Bearer {create_access_token(self.engineer_id, self.secret, 30)}"
        }
        self.schema_created = False
        self.metadata_created = False
        self.lifetimes: list[Lifetime] = []
        self.active: Lifetime | None = None
        self.outputs: Sequence[ModelerOutput] = ()
        self.modeler_calls: list[dict[str, Any]] = []
        self.codegen_runs: list[str] = []
        self.worker_executions = 0

    async def initialize(self) -> None:
        engine = make_engine(self.database_url).execution_options(
            schema_translate_map={None: self.schema}
        )
        try:
            async with engine.begin() as connection:
                await connection.execute(CreateSchema(self.schema))
            self.schema_created = True
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            self.metadata_created = True
            async with make_sessionmaker(engine).begin() as session:
                session.add(
                    User(
                        id=self.engineer_id,
                        email=uuid4().hex + "@example.test",
                        password_hash=self.password_hash,
                    )
                )
                await session.flush()
                session.add(
                    Project(
                        id=self.project_id,
                        slug=uuid4().hex,
                        name="Restart recovery",
                        created_by=self.engineer_id,
                    )
                )
                await session.flush()
                session.add(
                    ProjectMember(
                        project_id=self.project_id,
                        user_id=self.engineer_id,
                        role=ProjectRole.ENGINEER,
                    )
                )
                session.add(
                    Batch(
                        id=self.batch_id,
                        project_id=self.project_id,
                        status=BatchStatus.READY,
                        required_files=self.manifest.required_files,
                        manifest_sha256=self.manifest.digest(),
                    )
                )
                await session.flush()
                session.add_all(
                    [
                        SourceFile(
                            id=source.file_id,
                            batch_id=self.batch_id,
                            filename=source.filename,
                            storage_path=str(
                                self.storage.raw_path(
                                    self.project_id, self.batch_id, source.filename
                                )
                            ),
                            sha256=source.sha256,
                            size_bytes=source.size_bytes,
                            read_config=source.read_config.model_dump(mode="json"),
                            read_config_confirmed=True,
                        )
                        for source in self.manifest.files
                    ]
                )
        finally:
            await engine.dispose()

    async def cleanup(self) -> None:
        if not self.schema_created:
            return
        engine = make_engine(self.database_url).execution_options(
            schema_translate_map={None: self.schema}
        )
        try:
            if self.metadata_created:
                factory = make_sessionmaker(engine)
                async with factory() as session:
                    run_ids = list(await session.scalars(select(PipelineRun.id)))
                async with open_postgres_checkpointer(self.checkpoint_url) as saver:
                    for run_id in run_ids:
                        await saver.adelete_thread(str(run_id))
            async with engine.begin() as connection:
                await connection.execute(DropSchema(self.schema, cascade=True))
        finally:
            await engine.dispose()

    def current_lifetime(self) -> Lifetime:
        if self.active is None:
            raise RuntimeError("No application lifetime is active")
        return self.active

    def engine(self, url: str) -> AsyncEngine:
        life = self.current_lifetime()
        life.engine_count += 1
        engine = make_engine(url).execution_options(schema_translate_map={None: self.schema})

        def checkout(connection: object, record: object, proxy: object) -> None:
            life.checked_out.add(id(record))

        def checkin(connection: object, record: object) -> None:
            life.checked_out.discard(id(record))

        def disposed(engine: Engine) -> None:
            life.disposed_without_checkouts = not life.checked_out
            life.engine_disposed = True
            life.events.append("engine_disposed")

        event.listen(engine.sync_engine.pool, "checkout", checkout)
        event.listen(engine.sync_engine.pool, "checkin", checkin)
        event.listen(engine.sync_engine, "engine_disposed", disposed)
        return engine

    @asynccontextmanager
    async def saver(self, conn_string: str) -> AsyncIterator[AsyncPostgresSaver]:
        life = self.current_lifetime()
        pool: AsyncConnectionPool[Any] | None = None
        try:
            async with open_postgres_checkpointer(conn_string) as saver:
                life.saver_count += 1
                connection = saver.conn
                assert isinstance(connection, AsyncConnectionPool)
                pool = connection
                yield saver
        finally:
            if pool is not None:
                life.saver_closed = pool.closed
                life.events.append("saver_closed")

    def graph(self, saver: BaseCheckpointSaver[str]) -> PipelineGraph:
        self.current_lifetime().graph_count += 1
        return small_graph(saver, self.codegen_runs)

    def context(
        self, factory: async_sessionmaker[AsyncSession], llm: StructuredLLM
    ) -> GraphContext:
        self.current_lifetime().context_count += 1
        return GraphContext(
            sessionmaker=factory,
            propose_design=RecoveryModeler(self, self.outputs),
        )

    async def delivery(self, *args: Any, **kwargs: Any) -> None:
        life = self.current_lifetime()
        try:
            await job_delivery_loop(*args, **kwargs)
        finally:
            life.delivery_stopped = True
            life.events.append("delivery_stopped")

    def configure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        values = {
            "DATAFORGE_APP_DATABASE_URL": self.database_url,
            "DATAFORGE_CHECKPOINT_DATABASE_URL": self.checkpoint_url,
            "DATAFORGE_STORAGE_ROOT": str(self.storage.root),
            "DATAFORGE_JWT_SECRET": self.secret,
            "DATAFORGE_JOB_DELIVERY_ENABLED": "true",
            "DATAFORGE_JOB_DELIVERY_INTERVAL_SECONDS": "0.02",
            "DATAFORGE_JOB_DELIVERY_STARTUP_TIMEOUT_SECONDS": "30",
        }
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(main, "make_engine", self.engine)
        monkeypatch.setattr(main, "build_graph", self.graph)
        monkeypatch.setattr(main, "make_graph_context", self.context)
        monkeypatch.setattr(main, "make_llm", lambda settings: None)
        monkeypatch.setattr(main, "job_delivery_loop", self.delivery)
        get_api_settings.cache_clear()

    @asynccontextmanager
    async def backend(self, outputs: Sequence[ModelerOutput] = ()) -> AsyncIterator[Backend]:
        assert self.active is None
        for previous in self.lifetimes:
            previous.assert_closed()
        life = Lifetime(generation=len(self.lifetimes) + 1)
        self.lifetimes.append(life)
        self.active = life
        self.outputs = outputs
        backend = Backend(self, life, None, None)
        get_api_settings.cache_clear()
        app = main.create_app(open_checkpointer=self.saver)
        backend.app = app
        try:
            async with LifespanManager(app, startup_timeout=40):
                client = AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://recovery.test"
                )
                backend.client = client
                try:
                    async with client:
                        assert (await client.get("/api/health")).status_code == 200
                        yield backend
                finally:
                    life.client_closed = client.is_closed
                    life.events.append("client_closed")
        finally:
            backend.app = None
            backend.client = None
            self.outputs = ()
            self.active = None
            get_api_settings.cache_clear()
