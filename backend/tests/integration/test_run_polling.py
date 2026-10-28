"""Read-only polling through authenticated routes and independent PostgreSQL sessions."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, event, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import modeler
from app.agents.schemas import ClarificationQuestion
from app.api.routes import runs
from app.core.config import get_api_settings
from app.core.security import create_access_token, hash_password
from app.db.models import (
    Approval,
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
    User,
)
from app.graph.interrupts import ClarificationRequest, DesignGateRequest, JobWait
from app.jobs import queue
from app.services import runs as service
from tests.designs import minimal_design

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from httpx import Response
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

pytestmark = pytest.mark.integration
FIXED_UPDATED_AT = datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
PUBLIC_FAILURE = "The run failed. Use the run ID when reporting this issue."
WAITING_STATES = (
    RunStatus.WAITING_JOB,
    RunStatus.WAITING_CLARIFICATION,
    RunStatus.WAITING_DESIGN_APPROVAL,
)


@dataclass
class RunPollingScenario:
    client: AsyncClient
    factory: async_sessionmaker[AsyncSession]
    project_ids: tuple[UUID, UUID]
    batch_ids: tuple[UUID, UUID]
    run_ids: tuple[UUID, UUID]
    job_ids: tuple[UUID, UUID]
    design_ids: tuple[UUID, UUID]
    user_ids: tuple[UUID, UUID, UUID]
    headers: dict[str, dict[str, str]]

    def pending(self, status: RunStatus, index: int = 0) -> dict[str, Any] | None:
        if status == RunStatus.WAITING_JOB:
            return JobWait(job_id=self.job_ids[index], job_kind="profile").model_dump(mode="json")
        if status == RunStatus.WAITING_CLARIFICATION:
            return ClarificationRequest(
                questions=[
                    ClarificationQuestion(
                        topic="metric",
                        question="Should withdrawals be excluded?",
                        why="The profile cannot determine this business rule",
                        options=["Include withdrawals", "Exclude withdrawals"],
                    )
                ]
            ).model_dump(mode="json")
        if status == RunStatus.WAITING_DESIGN_APPROVAL:
            return DesignGateRequest(
                design_version_id=self.design_ids[index],
                version=1,
                design=minimal_design(),
                edited_by_user=False,
            ).model_dump(mode="json")
        return None

    async def set_state(
        self,
        status: RunStatus,
        *,
        index: int = 0,
        pending: Any = None,
        step: str | None = "profile",
        error: str | None = None,
    ) -> None:
        async with self.factory.begin() as session:
            await session.execute(
                update(PipelineRun)
                .where(PipelineRun.id == self.run_ids[index])
                .values(
                    status=status,
                    current_step=step,
                    pending=pending,
                    error=error,
                    updated_at=FIXED_UPDATED_AT,
                )
            )

    async def get(
        self,
        *,
        actor: str = "engineer",
        project_id: UUID | str | None = None,
        run_id: UUID | str | None = None,
    ) -> Response:
        project = self.project_ids[0] if project_id is None else project_id
        run = self.run_ids[0] if run_id is None else run_id
        return await self.client.get(
            f"/api/projects/{project}/runs/{run}", headers=self.headers[actor]
        )

    async def persisted(self) -> dict[str, list[dict[str, Any]]]:
        statements = [
            (
                "runs",
                select(PipelineRun.__table__)
                .where(PipelineRun.project_id.in_(self.project_ids))
                .order_by(PipelineRun.id),
            ),
            (
                "jobs",
                select(Job.__table__).where(Job.run_id.in_(self.run_ids)).order_by(Job.id),
            ),
            (
                "designs",
                select(DesignVersion.__table__)
                .where(DesignVersion.run_id.in_(self.run_ids))
                .order_by(DesignVersion.id),
            ),
            (
                "approvals",
                select(Approval.__table__)
                .where(Approval.project_id.in_(self.project_ids))
                .order_by(Approval.id),
            ),
        ]
        async with self.factory() as observer:
            result = {}
            for name, statement in statements:
                rows = (await observer.execute(statement)).mappings()
                result[name] = [dict(row) for row in rows]
            return result


@pytest.fixture(scope="module")
def polling_password_hash() -> str:
    return hash_password(secrets.token_urlsafe(24))


@pytest.fixture(autouse=True)
def forbid_polling_workflow_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Fail if a polling request attempts orchestration, queueing or an LLM call."""
    mocks = []
    for name in (
        "start_run",
        "drive_run",
        "resume_run",
        "sync_run",
        "deliver_finished_jobs",
        "deliver_resume_intents",
        "recover_pending_runs",
    ):
        mock = AsyncMock(side_effect=AssertionError(f"Polling must not call {name}"))
        monkeypatch.setattr(service, name, mock)
        mocks.append(mock)
    for target, name in ((queue, "enqueue"), (modeler, "propose_design")):
        mock = AsyncMock(side_effect=AssertionError(f"Polling must not call {name}"))
        monkeypatch.setattr(target, name, mock)
        mocks.append(mock)
    yield
    for mock in mocks:
        mock.assert_not_called()


@pytest.fixture
async def polling(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    polling_password_hash: str,
) -> AsyncIterator[RunPollingScenario]:
    secret = secrets.token_urlsafe(48)
    monkeypatch.setenv("DATAFORGE_JWT_SECRET", secret)
    get_api_settings.cache_clear()
    user_ids = (uuid4(), uuid4(), uuid4())
    project_ids = (uuid4(), uuid4())
    batch_ids = (uuid4(), uuid4())
    run_ids = (uuid4(), uuid4())
    job_ids = (uuid4(), uuid4())
    design_ids = (uuid4(), uuid4())
    app = FastAPI()
    app.state.sessionmaker = session_factory
    app.include_router(runs.router, prefix="/api")
    try:
        async with session_factory.begin() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        email=f"run-polling-{user_id.hex}@example.test",
                        password_hash=polling_password_hash,
                    )
                    for user_id in user_ids
                ]
            )
            await session.flush()
            session.add_all(
                [
                    Project(
                        id=project_id,
                        name=f"Polling project {index}",
                        slug=f"run-polling-{project_id.hex}",
                        created_by=user_ids[0],
                    )
                    for index, project_id in enumerate(project_ids)
                ]
            )
            await session.flush()
            session.add_all(
                [
                    ProjectMember(project_id=project_id, user_id=user_ids[index], role=role)
                    for project_id in project_ids
                    for index, role in enumerate((ProjectRole.ENGINEER, ProjectRole.REVIEWER))
                ]
            )
            session.add_all(
                [
                    Batch(id=batch_id, project_id=project_id, required_files=["customers.csv"])
                    for batch_id, project_id in zip(batch_ids, project_ids, strict=True)
                ]
            )
            await session.flush()
            session.add_all(
                [
                    PipelineRun(
                        id=run_id,
                        project_id=project_ids[index],
                        batch_id=batch_ids[index],
                        request_text=f"Private requirement for project {index}",
                        status=RunStatus.RUNNING,
                        current_step="profile",
                        updated_at=FIXED_UPDATED_AT,
                    )
                    for index, run_id in enumerate(run_ids)
                ]
            )
            await session.flush()
            content = minimal_design().model_dump(mode="json")
            session.add_all(
                [
                    DesignVersion(
                        id=design_ids[index],
                        run_id=run_id,
                        version=1,
                        content=content,
                        content_hash=hashlib.sha256(
                            json.dumps(content, sort_keys=True).encode("utf-8")
                        ).hexdigest(),
                        edited_by_user=False,
                    )
                    for index, run_id in enumerate(run_ids)
                ]
            )
            session.add_all(
                [
                    Job(
                        id=job_ids[index],
                        run_id=run_id,
                        queue=JobQueue.SANDBOX,
                        kind="profile",
                        payload={
                            "batch_id": str(batch_ids[index]),
                            "internal_note": "Private job input",
                        },
                        status=JobStatus.QUEUED,
                    )
                    for index, run_id in enumerate(run_ids)
                ]
            )
        headers = {
            actor: {"Authorization": f"Bearer {create_access_token(user_id, secret, 10)}"}
            for actor, user_id in zip(("engineer", "reviewer", "outsider"), user_ids, strict=True)
        }
        headers["anonymous"] = {}
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://run-polling.test",
        ) as client:
            yield RunPollingScenario(
                client,
                session_factory,
                project_ids,
                batch_ids,
                run_ids,
                job_ids,
                design_ids,
                user_ids,
                headers,
            )
    finally:
        async with session_factory.begin() as cleanup:
            await cleanup.execute(delete(Approval).where(Approval.project_id.in_(project_ids)))
            await cleanup.execute(delete(DesignVersion).where(DesignVersion.run_id.in_(run_ids)))
            await cleanup.execute(delete(Job).where(Job.run_id.in_(run_ids)))
            await cleanup.execute(
                delete(PipelineRun).where(PipelineRun.project_id.in_(project_ids))
            )
            await cleanup.execute(delete(Batch).where(Batch.project_id.in_(project_ids)))
            await cleanup.execute(
                delete(ProjectMember).where(ProjectMember.project_id.in_(project_ids))
            )
            await cleanup.execute(delete(Project).where(Project.id.in_(project_ids)))
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        get_api_settings.cache_clear()


@pytest.mark.parametrize("actor", ["engineer", "reviewer"])
@pytest.mark.parametrize("status", list(RunStatus))
async def test_members_can_poll_each_public_run_status(
    polling: RunPollingScenario, actor: str, status: RunStatus
) -> None:
    pending = polling.pending(status)
    step = {
        RunStatus.WAITING_CLARIFICATION: "clarify",
        RunStatus.WAITING_DESIGN_APPROVAL: "design_gate",
        RunStatus.WAITING_CODE_APPROVAL: "code_gate",
    }.get(status, "profile")
    await polling.set_state(status, pending=pending, step=step)
    response = await polling.get(actor=actor)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "id",
        "status",
        "current_step",
        "pending",
        "error",
        "updated_at",
        "interrupt_id",
    }
    assert body["id"] == str(polling.run_ids[0])
    assert body["status"] == status.value
    assert body["current_step"] == step
    assert body["pending"] == pending
    assert body["error"] == (PUBLIC_FAILURE if status == RunStatus.FAILED else None)
    assert datetime.fromisoformat(body["updated_at"]) == FIXED_UPDATED_AT
    assert "request_text" not in body
    assert "batch_id" not in body
    assert "payload" not in response.text


@pytest.mark.parametrize(("actor", "status"), [("anonymous", 401), ("outsider", 403)])
async def test_polling_requires_authentication_and_project_membership(
    polling: RunPollingScenario, actor: str, status: int
) -> None:
    response = await polling.get(actor=actor)
    assert response.status_code == status
    if status == 401:
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("actor", ["engineer", "reviewer"])
@pytest.mark.parametrize("project_index", [0, 1])
async def test_polling_rejects_a_run_under_the_wrong_project_even_with_both_memberships(
    polling: RunPollingScenario, actor: str, project_index: int
) -> None:
    response = await polling.get(
        actor=actor,
        project_id=polling.project_ids[project_index],
        run_id=polling.run_ids[1 - project_index],
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found in this project"}


@pytest.mark.parametrize("actor", ["engineer", "reviewer"])
async def test_polling_returns_not_found_for_an_unknown_run(
    polling: RunPollingScenario, actor: str
) -> None:
    response = await polling.get(actor=actor, run_id=uuid4())
    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found in this project"}


@pytest.mark.parametrize("field", ["project_id", "run_id"])
async def test_polling_validates_url_identifiers(polling: RunPollingScenario, field: str) -> None:
    if field == "project_id":
        response = await polling.get(project_id="invalid-project-id")
    else:
        response = await polling.get(run_id="invalid-run-id")
    assert response.status_code == 422
    assert any(error["loc"] == ["path", field] for error in response.json()["detail"])


@pytest.mark.parametrize("actor", ["engineer", "reviewer"])
async def test_polling_rechecks_membership_for_an_existing_token(
    polling: RunPollingScenario, actor: str
) -> None:
    role = ProjectRole.ENGINEER if actor == "engineer" else ProjectRole.REVIEWER
    index = 0 if actor == "engineer" else 1
    async with polling.factory.begin() as session:
        membership = await session.get(
            ProjectMember, (polling.project_ids[0], polling.user_ids[index], role)
        )
        assert membership is not None
        await session.delete(membership)
    response = await polling.get(actor=actor)
    assert response.status_code == 403


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "empty",
        "string",
        "list",
        "unknown-kind",
        "missing-job-id",
        "invalid-job-id",
        "missing-job-kind",
        "mismatched-kind",
        "empty-questions",
        "invalid-question-topic",
        "incomplete-design",
        "invalid-design-version",
    ],
)
async def test_invalid_persisted_pending_returns_a_fixed_server_error(
    polling: RunPollingScenario, damage: str
) -> None:
    status = RunStatus.WAITING_JOB
    pending: Any = polling.pending(status)
    assert isinstance(pending, dict)
    if damage == "missing":
        pending = None
    elif damage == "empty":
        pending = {}
    elif damage == "string":
        pending = "private-token-in-malformed-pending"
    elif damage == "list":
        pending = ["private-token-in-malformed-pending"]
    elif damage == "unknown-kind":
        pending["kind"] = "private-unknown-kind"
    elif damage == "missing-job-id":
        pending.pop("job_id")
    elif damage == "invalid-job-id":
        pending["job_id"] = "private-token-in-invalid-uuid"
    elif damage == "missing-job-kind":
        pending.pop("job_kind")
    elif damage == "mismatched-kind":
        pending = polling.pending(RunStatus.WAITING_CLARIFICATION)
    elif damage in {"empty-questions", "invalid-question-topic"}:
        status = RunStatus.WAITING_CLARIFICATION
        pending = polling.pending(status)
        assert isinstance(pending, dict)
        if damage == "empty-questions":
            pending["questions"] = []
        else:
            pending["questions"][0]["topic"] = "private-invalid-topic"
    else:
        status = RunStatus.WAITING_DESIGN_APPROVAL
        pending = polling.pending(status)
        assert isinstance(pending, dict)
        if damage == "incomplete-design":
            pending["design"] = {"raw_rows": [["private-row-value"]]}
        else:
            pending["version"] = "private-invalid-version"

    await polling.set_state(status, pending=pending)
    before = await polling.persisted()
    response = await polling.get()
    assert response.status_code == 500
    assert response.json() == {"detail": "Run state is unavailable"}
    assert await polling.persisted() == before


@pytest.mark.parametrize("status", WAITING_STATES)
async def test_polling_removes_undeclared_internal_fields_from_nested_pending(
    polling: RunPollingScenario, status: RunStatus
) -> None:
    clean = polling.pending(status)
    assert isinstance(clean, dict)
    pending = copy.deepcopy(clean)
    internal = {
        "raw_rows": [["private-row-marker", "001"]],
        "storage_path": "/private/storage-marker/source.csv",
        "secret": "private-secret-marker",
        "traceback": "Traceback private-traceback-marker",
    }
    pending.update(internal)
    if status == RunStatus.WAITING_CLARIFICATION:
        pending["questions"][0].update(internal)
    elif status == RunStatus.WAITING_DESIGN_APPROVAL:
        design = pending["design"]
        design.update(internal)
        design["facts"][0].update(internal)
        design["keys"][0].update(internal)
        design["metrics"][0].update(internal)
        design["update_policy"].update(internal)
        design["dashboard"].update(internal)
        design["dashboard"]["cards"][0].update(internal)
    await polling.set_state(status, pending=pending)
    before = await polling.persisted()
    response = await polling.get()
    assert response.status_code == 200
    assert response.json()["pending"] == clean
    for marker in (
        "private-row-marker",
        "private-secret-marker",
        "storage-marker",
        "private-traceback-marker",
        "raw_rows",
        "storage_path",
    ):
        assert marker not in response.text
    assert await polling.persisted() == before


@pytest.mark.parametrize(
    "internal_error",
    [
        None,
        "",
        "Traceback (most recent call last): private-traceback-marker",
        "Connection failed: postgresql://user:private-password-marker@localhost/private_db",
        "Could not open /private/storage-marker/customers.csv",
        "Authorization: Bearer private-token-marker",
    ],
)
async def test_failed_run_exposes_only_the_public_error_message(
    polling: RunPollingScenario, internal_error: str | None
) -> None:
    await polling.set_state(RunStatus.FAILED, error=internal_error)
    before = await polling.persisted()
    response = await polling.get()
    assert response.status_code == 200
    assert response.json()["error"] == PUBLIC_FAILURE
    assert response.json()["pending"] is None
    if internal_error:
        assert internal_error not in response.text
    assert await polling.persisted() == before


@pytest.mark.parametrize("status", [status for status in RunStatus if status != RunStatus.FAILED])
async def test_nonfailed_run_does_not_expose_a_stale_internal_error(
    polling: RunPollingScenario, status: RunStatus
) -> None:
    await polling.set_state(
        status, pending=polling.pending(status), error="private-stale-error-marker"
    )
    response = await polling.get()
    assert response.status_code == 200
    assert response.json()["error"] is None
    assert "private-stale-error-marker" not in response.text


@pytest.mark.parametrize("status", [RunStatus.RUNNING, RunStatus.PUBLISHED, RunStatus.FAILED])
async def test_polling_hides_stale_pending_outside_an_active_interrupt(
    polling: RunPollingScenario, status: RunStatus
) -> None:
    await polling.set_state(status, pending={"raw_rows": [["private-stale-row-marker"]]})
    before = await polling.persisted()
    response = await polling.get()
    assert response.status_code == 200
    assert response.json()["pending"] is None
    assert "private-stale-row-marker" not in response.text
    assert await polling.persisted() == before


@pytest.mark.parametrize("step", [None, "/private/step-marker/profile.py", "private-unknown-step"])
async def test_polling_does_not_expose_unknown_internal_step_names(
    polling: RunPollingScenario, step: str | None
) -> None:
    await polling.set_state(RunStatus.RUNNING, step=step)
    response = await polling.get()
    assert response.status_code == 200
    assert response.json()["current_step"] is None
    if step is not None:
        assert step not in response.text


@pytest.mark.parametrize("status", list(RunStatus))
async def test_repeated_polling_preserves_database_rows_and_only_executes_selects(
    polling: RunPollingScenario,
    database_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    status: RunStatus,
) -> None:
    await polling.set_state(status, pending=polling.pending(status))
    before = await polling.persisted()
    statements: list[str] = []

    def record_statement(
        connection: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    commit = AsyncMock(side_effect=AssertionError("Polling must not commit"))
    event.listen(database_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(AsyncSession, "commit", commit)
            responses = [await polling.get() for _ in range(5)]
    finally:
        event.remove(database_engine.sync_engine, "before_cursor_execute", record_statement)
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json() == responses[0].json() for response in responses)
    assert datetime.fromisoformat(responses[0].json()["updated_at"]) == FIXED_UPDATED_AT
    assert statements
    assert set(statements) == {"SELECT"}
    commit.assert_not_called()
    assert await polling.persisted() == before


async def test_polling_observes_changes_committed_by_another_session(
    polling: RunPollingScenario,
) -> None:
    first = await polling.get()
    assert first.status_code == 200
    assert first.json()["status"] == "running"
    next_updated_at = datetime(2020, 1, 2, 3, 5, 6, tzinfo=UTC)
    pending = polling.pending(RunStatus.WAITING_JOB)
    async with polling.factory.begin() as writer:
        run = await writer.get(PipelineRun, polling.run_ids[0])
        assert run is not None
        run.status = RunStatus.WAITING_JOB
        run.pending = pending
        run.updated_at = next_updated_at
    response = await polling.get()
    assert response.status_code == 200
    assert response.json()["status"] == "waiting_job"
    assert response.json()["pending"] == pending
    assert datetime.fromisoformat(response.json()["updated_at"]) == next_updated_at


async def test_a_fresh_api_instance_reads_the_same_persisted_pending(
    polling: RunPollingScenario,
) -> None:
    await polling.set_state(
        RunStatus.WAITING_DESIGN_APPROVAL,
        pending=polling.pending(RunStatus.WAITING_DESIGN_APPROVAL),
        step="design_gate",
    )
    first = await polling.get()
    assert first.status_code == 200
    fresh_app = FastAPI()
    fresh_app.state.sessionmaker = polling.factory
    fresh_app.include_router(runs.router, prefix="/api")
    async with AsyncClient(
        transport=ASGITransport(app=fresh_app),
        base_url="http://fresh-polling.test",
    ) as client:
        response = await client.get(
            f"/api/projects/{polling.project_ids[0]}/runs/{polling.run_ids[0]}",
            headers=polling.headers["reviewer"],
        )
    assert response.status_code == 200
    assert response.json() == first.json()


async def test_concurrent_polling_reads_the_same_snapshot_without_writes(
    polling: RunPollingScenario,
) -> None:
    await polling.set_state(RunStatus.WAITING_JOB, pending=polling.pending(RunStatus.WAITING_JOB))
    before = await polling.persisted()
    responses = await asyncio.gather(
        *[polling.get(actor="engineer" if index % 2 == 0 else "reviewer") for index in range(6)]
    )
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json() == responses[0].json() for response in responses)
    assert await polling.persisted() == before


async def get_builds(
    polling: RunPollingScenario, *, actor: str = "engineer", project_index: int = 0
) -> Response:
    project, run = polling.project_ids[project_index], polling.run_ids[0]
    return await polling.client.get(
        f"/api/projects/{project}/runs/{run}/builds", headers=polling.headers[actor]
    )


@pytest.mark.parametrize("actor", ["engineer", "reviewer"])
async def test_members_read_builds_of_a_run_without_code(
    polling: RunPollingScenario, actor: str
) -> None:
    response = await get_builds(polling, actor=actor)
    assert response.status_code == 200, response.text
    assert response.json() == {"attempts": []}


@pytest.mark.parametrize(("actor", "status"), [("anonymous", 401), ("outsider", 403)])
async def test_builds_require_authentication_and_project_membership(
    polling: RunPollingScenario, actor: str, status: int
) -> None:
    assert (await get_builds(polling, actor=actor)).status_code == status


async def test_builds_reject_a_run_under_the_wrong_project(polling: RunPollingScenario) -> None:
    response = await get_builds(polling, project_index=1)
    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found in this project"}
