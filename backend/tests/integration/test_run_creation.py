"""Run creation through real HTTP routes, committed sessions and persistent checkpoints."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.routes import batches, runs
from app.core.config import get_api_settings
from app.core.security import create_access_token, hash_password
from app.db.checkpointer import open_postgres_checkpointer
from app.db.models import (
    Approval,
    Base,
    Batch,
    DesignVersion,
    Job,
    JobQueue,
    JobStatus,
    PipelineRun,
    Project,
    ProjectMember,
    ProjectRole,
    RunStatus,
    SourceFile,
    User,
)
from app.db.session import make_engine, make_sessionmaker
from app.graph import design_store
from app.graph.builder import build_graph
from app.graph.context import GraphContext
from app.ingest.sniff import CsvReadConfig
from app.ingest.storage import Storage
from app.jobs import queue
from app.services import runs as service

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from httpx import Response
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
    from starlette.types import Message, Receive, Scope, Send

    from app.agents.schemas import DataDesign, ModelerOutput
    from app.graph.builder import PipelineGraph
    from app.profiler.schemas import DataProfile

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "upload"


@dataclass
class UnexpectedModeler:
    calls: int = 0

    async def __call__(
        self,
        *,
        request_text: str,
        profile: DataProfile,
        answers: list[dict[str, str]],
        returned_design: DataDesign | None,
        reviewer_feedback: str | None,
    ) -> ModelerOutput:
        self.calls += 1
        raise AssertionError("Run creation must stop at the profile job interrupt")


async def _prepare_batch(
    client: AsyncClient, project_id: UUID, headers: dict[str, str], *, ready: bool = True
) -> UUID:
    base = f"/api/projects/{project_id}/batches"
    created = await client.post(
        base, headers=headers, json={"required_files": ["customers.csv", "orders.csv"]}
    )
    assert created.status_code == 200, created.text
    batch_id = UUID(created.json()["id"])
    for name in ("customers.csv", "orders.csv"):
        uploaded = await client.post(
            f"{base}/{batch_id}/files",
            headers=headers,
            files={"file": (name, (FIXTURES / "complete" / name).read_bytes(), "text/csv")},
        )
        assert uploaded.status_code == 200, uploaded.text
        confirmed = await client.put(
            f"{base}/{batch_id}/files/{uploaded.json()['id']}/read-config",
            headers=headers,
            json={"read_config": CsvReadConfig(null_tokens=["", "NA"]).model_dump(mode="json")},
        )
        assert confirmed.status_code == 200, confirmed.text
    if ready:
        published = await client.post(f"{base}/{batch_id}/ready", headers=headers)
        assert published.status_code == 200, published.text
    return batch_id


@dataclass
class RunCreationScenario:
    app: FastAPI
    client: AsyncClient
    factory: async_sessionmaker[AsyncSession]
    storage: Storage
    project_id: UUID
    batch_id: UUID
    headers: dict[str, dict[str, str]]
    graph: PipelineGraph
    context: GraphContext
    checkpointer: AsyncPostgresSaver
    modeler: UnexpectedModeler
    schema: str

    async def create(
        self,
        *,
        batch_id: UUID | None = None,
        request_text: Any = "Analyze customer orders",
        actor: str = "engineer",
    ) -> Response:
        return await self.client.post(
            f"/api/projects/{self.project_id}/runs",
            headers=self.headers[actor],
            json={
                "batch_id": str(batch_id or self.batch_id),
                "request_text": request_text,
            },
        )

    async def row(self, run_id: UUID) -> PipelineRun:
        async with self.factory() as session:
            run = await session.get(PipelineRun, run_id)
        assert run is not None
        return run

    async def jobs(self, run_id: UUID) -> list[Job]:
        async with self.factory() as session:
            return list(await session.scalars(select(Job).where(Job.run_id == run_id)))

    async def counts(self) -> dict[str, int]:
        async with self.factory() as session:
            return {
                model.__tablename__: int(
                    await session.scalar(select(func.count()).select_from(model)) or 0
                )
                for model in (PipelineRun, Job, DesignVersion, Approval)
            }


@pytest.fixture(scope="module")
def creation_password_hash() -> str:
    return hash_password(secrets.token_urlsafe(24))


@pytest.fixture
async def creation(
    database_engine: AsyncEngine,
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    creation_password_hash: str,
) -> AsyncIterator[RunCreationScenario]:
    """Isolate global recovery scans in a disposable application schema."""
    schema = f"run_creation_{uuid4().hex}"
    async with database_engine.begin() as connection:
        await connection.execute(CreateSchema(schema))
    try:
        isolated_engine = database_engine.execution_options(schema_translate_map={None: schema})
        async with isolated_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = make_sessionmaker(isolated_engine)
        secret = secrets.token_urlsafe(48)
        storage = Storage(tmp_path / "storage")
        monkeypatch.setenv("DATAFORGE_STORAGE_ROOT", str(storage.root))
        monkeypatch.setenv("DATAFORGE_JWT_SECRET", secret)
        get_api_settings.cache_clear()
        users = [uuid4() for _ in range(3)]
        project_id = uuid4()
        async with factory.begin() as session:
            session.add_all(
                [
                    User(
                        id=user,
                        email=f"run-creation-{user.hex}@example.test",
                        password_hash=creation_password_hash,
                    )
                    for user in users
                ]
            )
            await session.flush()
            session.add(
                Project(
                    id=project_id,
                    slug=f"run-creation-{project_id.hex}",
                    name="Run creation",
                    created_by=users[0],
                )
            )
            await session.flush()
            session.add_all(
                [
                    ProjectMember(
                        project_id=project_id, user_id=users[0], role=ProjectRole.ENGINEER
                    ),
                    ProjectMember(
                        project_id=project_id, user_id=users[1], role=ProjectRole.REVIEWER
                    ),
                ]
            )
        headers = {
            actor: {"Authorization": f"Bearer {create_access_token(user, secret, 10)}"}
            for actor, user in zip(("engineer", "reviewer", "outsider"), users, strict=True)
        }
        headers["anonymous"] = {}
        conn_string = make_url(database_url).set(drivername="postgresql").render_as_string(False)
        async with open_postgres_checkpointer(conn_string) as saver:
            modeler = UnexpectedModeler()
            context = GraphContext(sessionmaker=factory, propose_design=modeler)
            graph = build_graph(saver)
            app = FastAPI()
            app.state.sessionmaker = factory
            app.state.graph = graph
            app.state.graph_context = context
            app.include_router(batches.router, prefix="/api")
            app.include_router(runs.router, prefix="/api")
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app, raise_app_exceptions=False),
                    base_url="http://run-creation.test",
                ) as client:
                    batch_id = await _prepare_batch(client, project_id, headers["engineer"])
                    yield RunCreationScenario(
                        app,
                        client,
                        factory,
                        storage,
                        project_id,
                        batch_id,
                        headers,
                        graph,
                        context,
                        saver,
                        modeler,
                        schema,
                    )
            finally:
                async with factory() as session:
                    run_ids = list(await session.scalars(select(PipelineRun.id)))
                for run_id in run_ids:
                    await saver.adelete_thread(str(run_id))
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        get_api_settings.cache_clear()


async def test_ready_batch_creates_committed_run_job_and_checkpoint(
    creation: RunCreationScenario,
) -> None:
    response = await creation.create(request_text="  Analyze customer orders  ")
    assert response.status_code == 200, response.text
    body = response.json()
    run_id = UUID(body["id"])
    assert body["status"] == "running"
    assert body["current_step"] is None
    assert body["pending"] is None
    assert body["error"] is None
    run = await creation.row(run_id)
    assert run.project_id == creation.project_id
    assert run.batch_id == creation.batch_id
    assert run.request_text == "Analyze customer orders"
    assert run.status == RunStatus.WAITING_JOB
    assert run.current_step == "profile"
    jobs = await creation.jobs(run_id)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.queue == JobQueue.SANDBOX
    assert job.kind == "profile"
    assert job.status == JobStatus.QUEUED
    assert job.idempotency_key == f"profile:{run_id}"
    assert job.payload["batch_id"] == str(creation.batch_id)
    assert job.payload["schema_version"] == 1
    assert job.payload["project_id"] == str(creation.project_id)
    async with creation.factory() as session:
        batch = await session.get(Batch, creation.batch_id)
        assert batch is not None
        assert job.payload["manifest_sha256"] == batch.manifest_sha256
    assert "files" not in job.payload
    snapshot = await creation.graph.aget_state(service.thread_config(run_id))
    assert snapshot.values["run_id"] == str(run_id)
    assert snapshot.values["project_id"] == str(creation.project_id)
    assert snapshot.values["batch_id"] == str(creation.batch_id)
    assert snapshot.tasks[0].interrupts[0].value == run.pending
    assert run.pending == {"kind": "job", "job_id": str(job.id), "job_kind": "profile"}
    assert creation.modeler.calls == 0
    assert await creation.counts() == {
        "pipeline_runs": 1,
        "jobs": 1,
        "design_versions": 0,
        "approvals": 0,
    }


@pytest.mark.parametrize("request_text", ["", "   ", "\t\n", None, 42, []])
async def test_creation_rejects_empty_or_invalid_requirements_without_side_effects(
    creation: RunCreationScenario, request_text: Any
) -> None:
    before = await creation.counts()
    response = await creation.create(request_text=request_text)
    assert response.status_code == 422
    assert any(error["loc"] == ["body", "request_text"] for error in response.json()["detail"])
    assert await creation.counts() == before
    assert creation.modeler.calls == 0


@pytest.mark.parametrize(
    ("actor", "status"), [("anonymous", 401), ("reviewer", 403), ("outsider", 403)]
)
async def test_creation_requires_project_engineer_even_for_a_valid_ready_batch(
    creation: RunCreationScenario, actor: str, status: int
) -> None:
    before = await creation.counts()
    response = await creation.create(actor=actor)
    assert response.status_code == status
    assert await creation.counts() == before


async def test_creation_rejects_an_uploading_batch(creation: RunCreationScenario) -> None:
    batch_id = await _prepare_batch(
        creation.client, creation.project_id, creation.headers["engineer"], ready=False
    )
    before = await creation.counts()
    response = await creation.create(batch_id=batch_id)
    assert response.status_code == 409
    assert response.json() == {"detail": "Batch is not ready"}
    assert await creation.counts() == before


@pytest.mark.parametrize(
    "damage",
    [
        "missing-manifest",
        "invalid-manifest",
        "changed-manifest-bytes",
        "missing-marker",
        "changed-marker",
        "missing-raw",
        "changed-raw",
        "unfinished-raw",
        "changed-config",
        "unconfirmed-file",
        "changed-required-files",
        "changed-db-digest",
        "legacy-ready-batch",
    ],
)
async def test_creation_rejects_inconsistent_ready_snapshots_without_creating_a_run(
    creation: RunCreationScenario, damage: str
) -> None:
    before = await creation.counts()
    manifest = creation.storage.manifest_path(creation.project_id, creation.batch_id)
    marker = creation.storage.marker_path(creation.project_id, creation.batch_id)
    raw = creation.storage.raw_path(creation.project_id, creation.batch_id, "customers.csv")
    if damage == "missing-manifest":
        manifest.unlink()
    elif damage == "invalid-manifest":
        manifest.write_bytes(b"{")
    elif damage == "changed-manifest-bytes":
        manifest.write_bytes(manifest.read_bytes() + b"\n")
    elif damage == "missing-marker":
        marker.unlink()
    elif damage == "changed-marker":
        marker.write_text("0" * 64 + "\n", encoding="ascii")
    elif damage == "missing-raw":
        raw.unlink()
    elif damage == "changed-raw":
        raw.write_bytes(raw.read_bytes() + b"999,unexpected,record\n")
    elif damage == "unfinished-raw":
        (raw.parent / ".orders.csv.unfinished.part").write_bytes(b"partial")
    else:
        async with creation.factory.begin() as session:
            batch = await session.get(Batch, creation.batch_id)
            assert batch is not None
            if damage == "changed-required-files":
                batch.required_files = ["customers.csv", "different.csv"]
            elif damage == "changed-db-digest":
                batch.manifest_sha256 = "0" * 64
            elif damage == "legacy-ready-batch":
                batch.manifest_sha256 = None
            else:
                source = await session.scalar(
                    select(SourceFile).where(
                        SourceFile.batch_id == creation.batch_id,
                        SourceFile.filename == "customers.csv",
                    )
                )
                assert source is not None
                if damage == "changed-config":
                    source.read_config = {**source.read_config, "null_tokens": ["changed"]}
                else:
                    source.read_config_confirmed = False
    response = await creation.create()
    assert response.status_code == 409, response.text
    assert await creation.counts() == before
    assert creation.modeler.calls == 0


async def test_creation_reports_storage_outage_without_creating_a_run(
    creation: RunCreationScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = creation.storage.manifest_path(creation.project_id, creation.batch_id)
    original_read = Path.read_bytes

    def failing_read(path: Path) -> bytes:
        if path == manifest:
            raise OSError("Injected manifest read failure")
        return original_read(path)

    before = await creation.counts()
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", failing_read)
        response = await creation.create()
    assert response.status_code == 503
    assert await creation.counts() == before


async def test_http_response_and_committed_run_precede_background_graph_execution(
    creation: RunCreationScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    response_sent = asyncio.Event()
    background_started = asyncio.Event()
    release_background = asyncio.Event()
    original_drive = service.drive_run
    observed_ids: list[UUID] = []

    async def delayed_drive(
        factory: async_sessionmaker[AsyncSession],
        graph: PipelineGraph,
        context: GraphContext,
        run_id: UUID,
    ) -> None:
        assert response_sent.is_set()
        assert factory is creation.factory
        async with factory() as observer:
            run = await observer.get(PipelineRun, run_id)
            assert run is not None
            assert run.status == RunStatus.RUNNING
        observed_ids.append(run_id)
        background_started.set()
        await release_background.wait()
        await original_drive(factory, graph, context, run_id)

    async def tracked_app(scope: Scope, receive: Receive, send: Send) -> None:
        async def tracked_send(message: Message) -> None:
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                response_sent.set()

        await creation.app(scope, receive, tracked_send)

    with monkeypatch.context() as patch:
        patch.setattr(service, "drive_run", delayed_drive)
        async with AsyncClient(
            transport=ASGITransport(app=tracked_app), base_url="http://run-ordering.test"
        ) as client:
            pending = asyncio.create_task(
                client.post(
                    f"/api/projects/{creation.project_id}/runs",
                    headers=creation.headers["engineer"],
                    json={
                        "batch_id": str(creation.batch_id),
                        "request_text": "Analyze customer orders",
                    },
                )
            )
            try:
                await asyncio.wait_for(background_started.wait(), timeout=5)
                assert response_sent.is_set()
                assert not pending.done()
                assert len(observed_ids) == 1
                assert await creation.jobs(observed_ids[0]) == []
                assert creation.modeler.calls == 0
            finally:
                release_background.set()
                response = await asyncio.wait_for(pending, timeout=10)
    assert response.status_code == 200
    assert UUID(response.json()["id"]) == observed_ids[0]
    assert len(await creation.jobs(observed_ids[0])) == 1


async def test_repeated_http_creation_intentionally_creates_independent_runs(
    creation: RunCreationScenario,
) -> None:
    first = await creation.create()
    second = await creation.create()
    assert first.status_code == second.status_code == 200
    first_id, second_id = UUID(first.json()["id"]), UUID(second.json()["id"])
    assert first_id != second_id
    first_jobs, second_jobs = await creation.jobs(first_id), await creation.jobs(second_id)
    assert len(first_jobs) == len(second_jobs) == 1
    assert first_jobs[0].id != second_jobs[0].id
    assert first_jobs[0].idempotency_key != second_jobs[0].idempotency_key
    assert (await creation.row(first_id)).batch_id == (await creation.row(second_id)).batch_id
    for run_id in (first_id, second_id):
        state = await creation.graph.aget_state(service.thread_config(run_id))
        assert state.values["run_id"] == str(run_id)


async def test_concurrent_http_creation_keeps_run_job_and_checkpoint_identities_separate(
    creation: RunCreationScenario,
) -> None:
    responses = await asyncio.gather(
        creation.create(request_text="Analyze customer regions"),
        creation.create(request_text="Analyze customer orders"),
    )
    assert all(response.status_code == 200 for response in responses)
    ids = {UUID(response.json()["id"]) for response in responses}
    assert len(ids) == 2
    for run_id in ids:
        run = await creation.row(run_id)
        jobs = await creation.jobs(run_id)
        state = await creation.graph.aget_state(service.thread_config(run_id))
        assert len(jobs) == 1
        assert state.values["request_text"] == run.request_text
        assert state.tasks[0].interrupts[0].value["job_id"] == str(jobs[0].id)
    assert (await creation.counts())["jobs"] == 2


async def test_profile_node_replay_reuses_the_original_job(
    creation: RunCreationScenario,
) -> None:
    response = await creation.create()
    assert response.status_code == 200
    run_id = UUID(response.json()["id"])
    original = (await creation.jobs(run_id))[0]
    async with creation.factory.begin() as session:
        job = await session.get(Job, original.id)
        assert job is not None
        job.status = JobStatus.FAILED
        job.last_error = "Injected worker profile failure"
    await service.drive_run(
        creation.factory,
        creation.graph,
        creation.context,
        run_id,
        Command(
            resume={
                "job_id": str(original.id),
                "status": "failed",
                "error": "Injected worker profile failure",
            }
        ),
    )
    jobs = await creation.jobs(run_id)
    assert [job.id for job in jobs] == [original.id]
    assert jobs[0].idempotency_key == f"profile:{run_id}"
    run = await creation.row(run_id)
    assert run.status == RunStatus.FAILED
    assert run.pending is None
    assert creation.modeler.calls == 0


@dataclass
class RunExecution:
    factory: async_sessionmaker[AsyncSession]
    graph: PipelineGraph
    context: GraphContext
    modeler: UnexpectedModeler


@asynccontextmanager
async def _fresh_execution(
    creation: RunCreationScenario, database_url: str
) -> AsyncIterator[RunExecution]:
    engine = make_engine(database_url).execution_options(
        schema_translate_map={None: creation.schema}
    )
    try:
        factory = make_sessionmaker(engine)
        conn_string = make_url(database_url).set(drivername="postgresql").render_as_string(False)
        async with open_postgres_checkpointer(conn_string) as saver:
            modeler = UnexpectedModeler()
            context = GraphContext(sessionmaker=factory, propose_design=modeler)
            yield RunExecution(factory, build_graph(saver), context, modeler)
    finally:
        await engine.dispose()


async def _skip_kickoff(
    factory: async_sessionmaker[AsyncSession],
    graph: PipelineGraph,
    context: GraphContext,
    run_id: UUID,
) -> None:
    """Inject the crash window after commit and before the first graph invocation."""


async def test_recovery_starts_the_same_committed_run_when_background_kickoff_was_lost(
    creation: RunCreationScenario,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(service, "drive_run", _skip_kickoff)
        response = await creation.create()
    assert response.status_code == 200
    run_id = UUID(response.json()["id"])
    assert (await creation.row(run_id)).status == RunStatus.RUNNING
    assert await creation.jobs(run_id) == []
    assert not (await creation.graph.aget_state(service.thread_config(run_id))).values

    async with _fresh_execution(creation, database_url) as restarted:
        recovered = await service.recover_pending_runs(
            restarted.factory, restarted.graph, restarted.context
        )
        assert recovered == 1
        run = await creation.row(run_id)
        jobs = await creation.jobs(run_id)
        assert run.status == RunStatus.WAITING_JOB
        assert len(jobs) == 1
        assert jobs[0].run_id == run_id
        assert run.pending == {"kind": "job", "job_id": str(jobs[0].id), "job_kind": "profile"}
        assert (await creation.counts())["pipeline_runs"] == 1
        await service.recover_pending_runs(restarted.factory, restarted.graph, restarted.context)
        assert [job.id for job in await creation.jobs(run_id)] == [jobs[0].id]
        assert restarted.modeler.calls == 0


async def test_recovery_reads_the_same_job_interrupt_after_closing_execution_resources(
    creation: RunCreationScenario,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(service, "drive_run", _skip_kickoff)
        response = await creation.create()
    assert response.status_code == 200
    run_id = UUID(response.json()["id"])
    async with _fresh_execution(creation, database_url) as first:
        await service.drive_run(first.factory, first.graph, first.context, run_id)
        before = await first.graph.aget_state(service.thread_config(run_id))
        pending = (await creation.row(run_id)).pending
        original_jobs = await creation.jobs(run_id)
        assert first.modeler.calls == 0

    async def unexpected_enqueue(*args: Any, **kwargs: Any) -> Job:
        raise AssertionError("Recovery must preserve an existing job interrupt")

    async with _fresh_execution(creation, database_url) as restarted:
        after = await restarted.graph.aget_state(service.thread_config(run_id))
        assert after.values == before.values
        assert after.tasks[0].interrupts[0].value == pending
        assert after.config["configurable"]["thread_id"] == str(run_id)
        with monkeypatch.context() as patch:
            patch.setattr(queue, "enqueue", unexpected_enqueue)
            assert (
                await service.recover_pending_runs(
                    restarted.factory, restarted.graph, restarted.context
                )
                == 1
            )
        restored = await creation.row(run_id)
        assert restored.status == RunStatus.WAITING_JOB
        assert restored.pending == pending
        assert [job.id for job in await creation.jobs(run_id)] == [original_jobs[0].id]
        assert restarted.modeler.calls == 0


async def test_recovery_reuses_a_job_committed_before_its_first_checkpoint(
    creation: RunCreationScenario,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(service, "drive_run", _skip_kickoff)
        response = await creation.create()
    assert response.status_code == 200
    run_id = UUID(response.json()["id"])
    async with creation.factory.begin() as session:
        payload = await design_store.profile_job_payload(session, creation.batch_id)
        existing = await queue.enqueue(
            session,
            queue=JobQueue.SANDBOX,
            kind="profile",
            payload=payload,
            run_id=run_id,
            idempotency_key=f"profile:{run_id}",
        )
        job_id = existing.id
    assert not (await creation.graph.aget_state(service.thread_config(run_id))).values
    async with _fresh_execution(creation, database_url) as restarted:
        await service.recover_pending_runs(restarted.factory, restarted.graph, restarted.context)
        assert [job.id for job in await creation.jobs(run_id)] == [job_id]
        run = await creation.row(run_id)
        assert run.status == RunStatus.WAITING_JOB
        assert run.pending is not None
        assert run.pending["job_id"] == str(job_id)
        assert restarted.modeler.calls == 0


async def test_failed_run_commit_does_not_schedule_graph_or_create_records(
    creation: RunCreationScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_commit(session: AsyncSession) -> None:
        raise RuntimeError("Injected run commit failure")

    kickoff_ids: list[UUID] = []

    async def record_kickoff(
        factory: async_sessionmaker[AsyncSession],
        graph: PipelineGraph,
        context: GraphContext,
        run_id: UUID,
    ) -> None:
        kickoff_ids.append(run_id)

    before = await creation.counts()
    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", failing_commit)
        patch.setattr(service, "drive_run", record_kickoff)
        response = await creation.create()
    assert response.status_code == 500
    assert await creation.counts() == before
    assert kickoff_ids == []


async def test_ambiguous_successful_commit_preserves_a_recoverable_run(
    creation: RunCreationScenario,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_commit = AsyncSession.commit

    async def commit_then_fail(session: AsyncSession) -> None:
        await original_commit(session)
        raise RuntimeError("Injected lost acknowledgement after commit")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", commit_then_fail)
        response = await creation.create()
    assert response.status_code == 500
    assert (await creation.counts())["pipeline_runs"] == 1
    async with creation.factory() as session:
        run_id = await session.scalar(select(PipelineRun.id))
    assert run_id is not None
    assert await creation.jobs(run_id) == []
    async with _fresh_execution(creation, database_url) as restarted:
        await service.recover_pending_runs(restarted.factory, restarted.graph, restarted.context)
    assert (await creation.row(run_id)).status == RunStatus.WAITING_JOB
    assert len(await creation.jobs(run_id)) == 1
    assert (await creation.counts())["pipeline_runs"] == 1


async def test_graph_kickoff_failure_marks_the_committed_run_failed(
    creation: RunCreationScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_enqueue(*args: Any, **kwargs: Any) -> Job:
        raise RuntimeError("Injected profile enqueue failure")

    with monkeypatch.context() as patch:
        patch.setattr(queue, "enqueue", failing_enqueue)
        response = await creation.create()
    assert response.status_code == 200
    run_id = UUID(response.json()["id"])
    run = await creation.row(run_id)
    assert run.status == RunStatus.FAILED
    assert run.pending is None
    assert run.error is not None
    assert "Injected profile enqueue failure" in run.error
    assert await creation.jobs(run_id) == []
    assert (
        await service.recover_pending_runs(creation.factory, creation.graph, creation.context) == 0
    )
    assert creation.modeler.calls == 0


async def test_created_run_can_be_polled_without_advancing_its_job_or_checkpoint(
    creation: RunCreationScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await creation.create()
    assert created.status_code == 200
    run_id = UUID(created.json()["id"])
    original_run = await creation.row(run_id)
    original_jobs = await creation.jobs(run_id)
    original_counts = await creation.counts()
    before = await creation.graph.aget_state(service.thread_config(run_id))
    mocks = []
    with monkeypatch.context() as patch:
        for name in (
            "start_run",
            "drive_run",
            "resume_run",
            "sync_run",
            "deliver_finished_jobs",
            "recover_pending_runs",
        ):
            mock = AsyncMock(side_effect=AssertionError(f"Polling must not call {name}"))
            patch.setattr(service, name, mock)
            mocks.append(mock)
        for target, name in (
            (queue, "enqueue"),
            (creation.graph, "ainvoke"),
            (creation.graph, "aget_state"),
        ):
            mock = AsyncMock(side_effect=AssertionError(f"Polling must not call {name}"))
            patch.setattr(target, name, mock)
            mocks.append(mock)
        responses = [
            await creation.client.get(
                f"/api/projects/{creation.project_id}/runs/{run_id}",
                headers=creation.headers[actor],
            )
            for actor in ("engineer", "reviewer", "engineer")
        ]
        for mock in mocks:
            mock.assert_not_called()

    assert all(response.status_code == 200 for response in responses)
    assert all(response.json() == responses[0].json() for response in responses)
    body = responses[0].json()
    assert body["status"] == "waiting_job"
    assert body["pending"] == {
        "kind": "job",
        "job_id": str(original_jobs[0].id),
        "job_kind": "profile",
    }
    current_run = await creation.row(run_id)
    assert current_run.status == original_run.status
    assert current_run.pending == original_run.pending
    assert current_run.updated_at == original_run.updated_at
    assert await creation.counts() == original_counts
    assert [job.id for job in await creation.jobs(run_id)] == [original_jobs[0].id]
    after = await creation.graph.aget_state(service.thread_config(run_id))
    assert after.config == before.config
    assert after.values == before.values
    assert after.tasks[0].interrupts == before.tasks[0].interrupts
    assert creation.modeler.calls == 0
