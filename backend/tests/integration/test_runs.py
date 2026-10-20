"""Access control for run routes, independent of graph execution and Gate 1 resumption."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.deps import get_session
from app.api.routes import runs
from app.core.config import get_api_settings
from app.core.security import create_access_token, hash_password
from app.db.models import (
    Approval,
    Batch,
    DesignVersion,
    Job,
    PipelineRun,
    Project,
    ProjectMember,
    ProjectRole,
    RunStatus,
    User,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from httpx import Response
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

Operation = Literal["create", "status", "clarifications", "design-decision"]
OPERATIONS: tuple[Operation, ...] = ("create", "status", "clarifications", "design-decision")
MUTATIONS: tuple[Operation, ...] = ("create", "clarifications", "design-decision")


@dataclass(frozen=True)
class RunAccessData:
    project_ids: tuple[UUID, UUID]
    batch_ids: tuple[UUID, UUID]
    run_ids: tuple[UUID, UUID]
    engineer_id: UUID
    reviewer_id: UUID
    outsider_id: UUID


@pytest.fixture
def run_signing_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    secret = secrets.token_urlsafe(64)
    monkeypatch.setenv("DATAFORGE_JWT_SECRET", secret)
    get_api_settings.cache_clear()
    try:
        yield secret
    finally:
        get_api_settings.cache_clear()


@pytest.fixture
async def run_access_data(db_session: AsyncSession) -> RunAccessData:
    password_hash = hash_password("test-run-access-only")
    engineer, reviewer, outsider = [
        User(email=f"run-access-{uuid4().hex}@example.test", password_hash=password_hash)
        for _ in range(3)
    ]
    db_session.add_all([engineer, reviewer, outsider])
    await db_session.flush()
    projects = [
        Project(
            name=f"Run access project {index}",
            slug=f"run-access-{uuid4().hex}",
            created_by=engineer.id,
        )
        for index in range(2)
    ]
    db_session.add_all(projects)
    await db_session.flush()
    db_session.add_all(
        [
            ProjectMember(project_id=project.id, user_id=engineer.id, role=ProjectRole.ENGINEER)
            for project in projects
        ]
        + [
            ProjectMember(
                project_id=projects[0].id, user_id=reviewer.id, role=ProjectRole.REVIEWER
            ),
            ProjectMember(
                project_id=projects[1].id, user_id=reviewer.id, role=ProjectRole.ENGINEER
            ),
        ]
    )
    batches = [
        Batch(project_id=project.id, required_files=["customers.csv"]) for project in projects
    ]
    db_session.add_all(batches)
    await db_session.flush()
    pipeline_runs = [
        PipelineRun(
            project_id=project.id,
            batch_id=batch.id,
            request_text=f"Private analytical requirement for project {index}",
            status=RunStatus.WAITING_DESIGN_APPROVAL,
            current_step="design_review",
            pending={"kind": "design_approval", "private_note": f"Project {index} design"},
        )
        for index, (project, batch) in enumerate(zip(projects, batches, strict=True))
    ]
    db_session.add_all(pipeline_runs)
    await db_session.commit()
    return RunAccessData(
        project_ids=(projects[0].id, projects[1].id),
        batch_ids=(batches[0].id, batches[1].id),
        run_ids=(pipeline_runs[0].id, pipeline_runs[1].id),
        engineer_id=engineer.id,
        reviewer_id=reviewer.id,
        outsider_id=outsider.id,
    )


@pytest.fixture
async def run_access_client(
    db_session: AsyncSession, run_signing_secret: str
) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(runs.router, prefix="/api")

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _headers(user_id: UUID, secret: str) -> dict[str, str]:
    token = create_access_token(user_id, secret, 5)
    return {"Authorization": f"Bearer {token}"}


async def _request(
    client: AsyncClient,
    data: RunAccessData,
    operation: Operation,
    headers: dict[str, str],
    *,
    project_id: UUID | str | None = None,
    batch_id: UUID | str | None = None,
    run_id: UUID | str | None = None,
    body: dict[str, Any] | None = None,
) -> Response:
    project = data.project_ids[0] if project_id is None else project_id
    batch = data.batch_ids[0] if batch_id is None else batch_id
    run = data.run_ids[0] if run_id is None else run_id
    base = f"/api/projects/{project}/runs"
    if operation == "create":
        payload: dict[str, Any] = {
            "batch_id": str(batch),
            "request_text": "Analyze the uploaded customers",
        }
        return await client.post(base, headers=headers, json=payload if body is None else body)
    if operation == "status":
        return await client.get(f"{base}/{run}", headers=headers)
    if operation == "clarifications":
        payload = {"answers": [{"question": "Which customers?", "answer": "All customers"}]}
    else:
        payload = {"decision": "approve"}
    return await client.post(
        f"{base}/{run}/{operation}", headers=headers, json=payload if body is None else body
    )


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("credentials", ["missing", "malformed", "expired", "unknown-user"])
async def test_run_routes_require_a_valid_current_user(
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
    operation: Operation,
    credentials: str,
) -> None:
    if credentials == "missing":
        headers = {}
    elif credentials == "malformed":
        headers = {"Authorization": "Bearer not-a-token"}
    elif credentials == "expired":
        now = int(datetime.now(UTC).timestamp())
        token = jwt.encode(
            {
                "sub": str(run_access_data.engineer_id),
                "iat": now - 600,
                "exp": now - 300,
            },
            run_signing_secret,
            algorithm="HS256",
        )
        headers = {"Authorization": f"Bearer {token}"}
    else:
        headers = _headers(uuid4(), run_signing_secret)
    response = await _request(run_access_client, run_access_data, operation, headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Could not validate credentials"}


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_run_routes_reject_project_outsiders(
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
    operation: Operation,
) -> None:
    response = await _request(
        run_access_client,
        run_access_data,
        operation,
        _headers(run_access_data.outsider_id, run_signing_secret),
    )
    assert response.status_code == 403
    detail = (
        "Project membership required"
        if operation == "status"
        else "Insufficient project permissions"
    )
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize("operation", MUTATIONS)
async def test_run_mutations_reject_reviewer_even_when_engineer_in_another_project(
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
    operation: Operation,
) -> None:
    response = await _request(
        run_access_client,
        run_access_data,
        operation,
        _headers(run_access_data.reviewer_id, run_signing_secret),
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient project permissions"}


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("project_index", [0, 1], ids=["first-project", "second-project"])
async def test_run_routes_reject_foreign_resources_despite_membership_in_both_projects(
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
    operation: Operation,
    project_index: int,
) -> None:
    foreign_index = 1 - project_index
    response = await _request(
        run_access_client,
        run_access_data,
        operation,
        _headers(run_access_data.engineer_id, run_signing_secret),
        project_id=run_access_data.project_ids[project_index],
        batch_id=run_access_data.batch_ids[foreign_index],
        run_id=run_access_data.run_ids[foreign_index],
    )
    assert response.status_code == 404
    resource = "Batch" if operation == "create" else "Run"
    assert response.json() == {"detail": f"{resource} not found in this project"}


async def test_reviewer_cannot_poll_a_foreign_run_under_their_project(
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
) -> None:
    response = await _request(
        run_access_client,
        run_access_data,
        "status",
        _headers(run_access_data.reviewer_id, run_signing_secret),
        run_id=run_access_data.run_ids[1],
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found in this project"}


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_run_routes_return_not_found_for_unknown_resources(
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
    operation: Operation,
) -> None:
    response = await _request(
        run_access_client,
        run_access_data,
        operation,
        _headers(run_access_data.engineer_id, run_signing_secret),
        batch_id=uuid4(),
        run_id=uuid4(),
    )
    assert response.status_code == 404
    resource = "Batch" if operation == "create" else "Run"
    assert response.json() == {"detail": f"{resource} not found in this project"}


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_run_routes_do_not_reveal_resources_under_an_unknown_project(
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
    operation: Operation,
) -> None:
    response = await _request(
        run_access_client,
        run_access_data,
        operation,
        _headers(run_access_data.engineer_id, run_signing_secret),
        project_id=uuid4(),
    )
    assert response.status_code == 403
    assert set(response.json()) == {"detail"}


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_run_routes_validate_project_uuid(
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
    operation: Operation,
) -> None:
    response = await _request(
        run_access_client,
        run_access_data,
        operation,
        _headers(run_access_data.engineer_id, run_signing_secret),
        project_id="invalid-project-id",
    )
    assert response.status_code == 422
    assert any(error["loc"] == ["path", "project_id"] for error in response.json()["detail"])


@pytest.mark.parametrize("operation", ["status", "clarifications", "design-decision"])
async def test_run_routes_validate_run_uuid(
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
    operation: Operation,
) -> None:
    response = await _request(
        run_access_client,
        run_access_data,
        operation,
        _headers(run_access_data.engineer_id, run_signing_secret),
        run_id="invalid-run-id",
    )
    assert response.status_code == 422
    assert any(error["loc"] == ["path", "run_id"] for error in response.json()["detail"])


@pytest.mark.parametrize(
    ("operation", "body", "field"),
    [
        ("create", {}, "batch_id"),
        (
            "create",
            {"batch_id": "invalid-batch-id", "request_text": "Analyze customers"},
            "batch_id",
        ),
        ("create", {"batch_id": str(UUID(int=1))}, "request_text"),
        ("clarifications", {}, "answers"),
        ("clarifications", {"answers": "invalid answers"}, "answers"),
        ("design-decision", {}, "decision"),
        ("design-decision", {"decision": "publish"}, "decision"),
    ],
    ids=[
        "missing-batch",
        "invalid-batch-uuid",
        "missing-request",
        "missing-answers",
        "invalid-answers",
        "missing-decision",
        "invalid-decision",
    ],
)
async def test_run_routes_reject_invalid_request_bodies(
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
    operation: Operation,
    body: dict[str, Any],
    field: str,
) -> None:
    response = await _request(
        run_access_client,
        run_access_data,
        operation,
        _headers(run_access_data.engineer_id, run_signing_secret),
        body=body,
    )
    assert response.status_code == 422
    assert any(error["loc"] == ["body", field] for error in response.json()["detail"])


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_run_access_is_revoked_for_an_existing_token(
    db_session: AsyncSession,
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
    operation: Operation,
) -> None:
    headers = _headers(run_access_data.engineer_id, run_signing_secret)
    membership = await db_session.get(
        ProjectMember,
        (run_access_data.project_ids[0], run_access_data.engineer_id, ProjectRole.ENGINEER),
    )
    assert membership is not None
    await db_session.delete(membership)
    await db_session.flush()
    response = await _request(run_access_client, run_access_data, operation, headers)
    assert response.status_code == 403
    detail = (
        "Project membership required"
        if operation == "status"
        else "Insufficient project permissions"
    )
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize("actor", ["engineer", "reviewer"])
async def test_project_members_can_reach_the_polling_resource_lookup(
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
    actor: str,
) -> None:
    """A scoped 404 proves membership passed without claiming that polling is implemented."""
    user_id = run_access_data.engineer_id if actor == "engineer" else run_access_data.reviewer_id
    response = await _request(
        run_access_client,
        run_access_data,
        "status",
        _headers(user_id, run_signing_secret),
        run_id=uuid4(),
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found in this project"}


@pytest.mark.parametrize("project_index", [0, 1], ids=["first-project", "second-project"])
async def test_scoped_batch_lookup_returns_the_requested_batch(
    db_session: AsyncSession, run_access_data: RunAccessData, project_index: int
) -> None:
    batch = await runs._get_project_batch(
        db_session,
        run_access_data.project_ids[project_index],
        run_access_data.batch_ids[project_index],
    )
    assert batch.id == run_access_data.batch_ids[project_index]
    assert batch.project_id == run_access_data.project_ids[project_index]


@pytest.mark.parametrize("project_index", [0, 1], ids=["first-project", "second-project"])
async def test_scoped_run_lookup_returns_the_requested_run(
    db_session: AsyncSession, run_access_data: RunAccessData, project_index: int
) -> None:
    run = await runs._get_project_run(
        db_session,
        run_access_data.project_ids[project_index],
        run_access_data.run_ids[project_index],
    )
    assert run.id == run_access_data.run_ids[project_index]
    assert run.project_id == run_access_data.project_ids[project_index]
    assert run.batch_id == run_access_data.batch_ids[project_index]


async def test_denied_requests_leave_runs_and_workflow_records_unchanged(
    db_session: AsyncSession,
    run_access_client: AsyncClient,
    run_access_data: RunAccessData,
    run_signing_secret: str,
) -> None:
    async def record_counts() -> tuple[int | None, ...]:
        return tuple(
            [
                await db_session.scalar(select(func.count()).select_from(model))
                for model in (PipelineRun, Batch, Job, Approval, DesignVersion)
            ]
        )

    state_query = (
        select(
            PipelineRun.id,
            PipelineRun.status,
            PipelineRun.current_step,
            PipelineRun.pending,
            PipelineRun.error,
            PipelineRun.updated_at,
        )
        .where(PipelineRun.id.in_(run_access_data.run_ids))
        .order_by(PipelineRun.id)
    )
    before_counts = await record_counts()
    before_states = (await db_session.execute(state_query)).all()
    for operation in OPERATIONS:
        foreign = await _request(
            run_access_client,
            run_access_data,
            operation,
            _headers(run_access_data.engineer_id, run_signing_secret),
            batch_id=run_access_data.batch_ids[1],
            run_id=run_access_data.run_ids[1],
        )
        outsider = await _request(
            run_access_client,
            run_access_data,
            operation,
            _headers(run_access_data.outsider_id, run_signing_secret),
        )
        assert foreign.status_code == 404
        assert outsider.status_code == 403
        for response in (foreign, outsider):
            assert "Private analytical requirement" not in response.text
            assert "private_note" not in response.text
            assert str(run_access_data.run_ids[1]) not in response.text
            assert str(run_access_data.batch_ids[1]) not in response.text

    await db_session.flush()
    assert await record_counts() == before_counts
    assert (await db_session.execute(state_query)).all() == before_states
