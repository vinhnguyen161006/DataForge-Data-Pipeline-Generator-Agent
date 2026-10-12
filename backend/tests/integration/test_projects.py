import asyncio
import secrets
import string
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.dml import Insert

from app.api.deps import get_session
from app.api.routes import auth, projects
from app.core.config import get_api_settings
from app.db.models import (
    Approval,
    ApprovalDecision,
    Batch,
    Gate,
    PipelineRun,
    Project,
    ProjectMember,
    ProjectRole,
    ReviewMode,
    User,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def project_password() -> str:
    return "learning-password-only"


@pytest.fixture
async def projects_client(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("DATAFORGE_JWT_SECRET", secrets.token_urlsafe(64))
    get_api_settings.cache_clear()

    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        get_api_settings.cache_clear()


async def _register_account(
    client: AsyncClient,
    session: AsyncSession,
    password: str,
) -> tuple[User, dict[str, str]]:
    email = f"project-user-{uuid4().hex}@example.test"
    registered = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert registered.status_code == 200
    user = await session.scalar(select(User).where(User.email == email))
    assert user is not None
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    return user, headers


@pytest.fixture
async def creator(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    project_password: str,
) -> tuple[User, dict[str, str]]:
    return await _register_account(projects_client, db_session, project_password)


@pytest.fixture
async def other_account(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    project_password: str,
) -> tuple[User, dict[str, str]]:
    return await _register_account(projects_client, db_session, project_password)


async def _create(
    client: AsyncClient,
    headers: dict[str, str],
    slug: str,
    mode: str = "team",
    name: str = "Learning Project",
) -> Response:
    return await client.post(
        "/api/projects",
        headers=headers,
        json={"name": name, "slug": slug, "review_mode": mode},
    )


@pytest.mark.parametrize(
    ("mode", "expected_roles"),
    [
        ("team", ["engineer"]),
        ("solo", ["engineer", "reviewer"]),
    ],
)
async def test_create_project_assigns_creator_roles_and_lists_once(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    mode: str,
    expected_roles: list[str],
) -> None:
    user, headers = creator
    slug = f"project-{uuid4().hex}"
    created = await _create(projects_client, headers, slug, mode)
    assert created.status_code == 200

    payload = created.json()
    assert set(payload) == {"id", "name", "slug", "review_mode", "roles"}
    assert payload["name"] == "Learning Project"
    assert payload["slug"] == slug
    assert payload["review_mode"] == mode
    assert payload["roles"] == expected_roles

    project = await db_session.get(Project, UUID(payload["id"]))
    assert project is not None
    assert project.created_by == user.id

    memberships = list(
        await db_session.scalars(
            select(ProjectMember).where(ProjectMember.project_id == project.id)
        )
    )
    assert len(memberships) == len(expected_roles)
    assert {member.role.value for member in memberships} == set(expected_roles)
    assert all(member.user_id == user.id for member in memberships)

    listed = await projects_client.get("/api/projects", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == [payload]


async def test_omitted_review_mode_defaults_to_team(
    projects_client: AsyncClient,
    creator: tuple[User, dict[str, str]],
) -> None:
    _, headers = creator
    created = await projects_client.post(
        "/api/projects",
        headers=headers,
        json={"name": "Default Team", "slug": f"default-{uuid4().hex}"},
    )

    assert created.status_code == 200
    assert created.json()["review_mode"] == "team"
    assert created.json()["roles"] == ["engineer"]


async def test_user_without_memberships_sees_no_other_users_projects(
    projects_client: AsyncClient,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
) -> None:
    _, headers = creator
    _, other_headers = other_account
    created = await _create(projects_client, other_headers, f"other-{uuid4().hex}")
    assert created.status_code == 200

    listed = await projects_client.get("/api/projects", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == []


async def test_each_user_lists_only_their_member_projects(
    projects_client: AsyncClient,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
) -> None:
    _, headers_a = creator
    _, headers_b = other_account
    project_a = await _create(projects_client, headers_a, f"user-a-{uuid4().hex}")
    project_b = await _create(projects_client, headers_b, f"user-b-{uuid4().hex}", "solo")
    assert project_a.status_code == 200
    assert project_b.status_code == 200

    listed_a = await projects_client.get("/api/projects", headers=headers_a)
    listed_b = await projects_client.get("/api/projects", headers=headers_b)
    assert listed_a.status_code == 200
    assert listed_b.status_code == 200
    assert listed_a.json() == [project_a.json()]
    assert listed_b.json() == [project_b.json()]


@pytest.mark.parametrize("owner_mode", ["team", "solo"])
async def test_list_reports_current_users_roles_instead_of_other_members_roles(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
    owner_mode: str,
) -> None:
    _, owner_headers = creator
    reviewer, reviewer_headers = other_account
    created = await _create(projects_client, owner_headers, f"shared-{uuid4().hex}", owner_mode)
    assert created.status_code == 200
    payload = created.json()
    db_session.add(
        ProjectMember(
            project_id=UUID(payload["id"]),
            user_id=reviewer.id,
            role=ProjectRole.REVIEWER,
        )
    )
    await db_session.flush()

    owner_list = await projects_client.get("/api/projects", headers=owner_headers)
    reviewer_list = await projects_client.get("/api/projects", headers=reviewer_headers)
    assert owner_list.status_code == 200
    assert reviewer_list.status_code == 200
    assert owner_list.json() == [payload]
    assert reviewer_list.json() == [{**payload, "roles": ["reviewer"]}]


async def test_list_aggregates_each_projects_roles_independently(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
) -> None:
    user, headers = creator
    _, other_headers = other_account
    team = await _create(projects_client, headers, f"team-{uuid4().hex}")
    solo = await _create(projects_client, headers, f"solo-{uuid4().hex}", "solo")
    shared = await _create(projects_client, other_headers, f"shared-{uuid4().hex}")
    assert team.status_code == solo.status_code == shared.status_code == 200
    db_session.add(
        ProjectMember(
            project_id=UUID(shared.json()["id"]),
            user_id=user.id,
            role=ProjectRole.REVIEWER,
        )
    )
    await db_session.flush()

    listed = await projects_client.get("/api/projects", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 3
    by_id = {row["id"]: row for row in rows}
    assert by_id[team.json()["id"]] == team.json()
    assert by_id[solo.json()["id"]] == solo.json()
    assert by_id[shared.json()["id"]] == {**shared.json(), "roles": ["reviewer"]}


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("authorization", [None, "Bearer not-a-token"], ids=["missing", "invalid"])
async def test_project_endpoints_require_authentication(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    method: str,
    authorization: str | None,
) -> None:
    slug = f"unauthorized-{uuid4().hex}"
    headers = {} if authorization is None else {"Authorization": authorization}
    if method == "GET":
        response = await projects_client.get("/api/projects", headers=headers)
    else:
        response = await projects_client.post(
            "/api/projects",
            headers=headers,
            json={"name": "Unauthorized Project", "slug": slug},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    count = await db_session.scalar(
        select(func.count()).select_from(Project).where(Project.slug == slug)
    )
    assert count == 0


@pytest.mark.parametrize("duplicate_case", ["same-user", "different-user", "trimmed-slug"])
async def test_duplicate_slug_is_global_and_does_not_create_extra_memberships(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
    duplicate_case: str,
) -> None:
    user, headers = creator
    creator_id = user.id
    _, other_headers = other_account
    slug = f"duplicate-{uuid4().hex}"
    first = await _create(projects_client, headers, slug)
    assert first.status_code == 200
    project_id = UUID(first.json()["id"])

    submitted_slug = f"  {slug}  " if duplicate_case == "trimmed-slug" else slug
    duplicate_headers = other_headers if duplicate_case == "different-user" else headers
    duplicate = await _create(
        projects_client, duplicate_headers, submitted_slug, "solo", "Conflicting Project"
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Project slug already exists"}

    count = await db_session.scalar(
        select(func.count()).select_from(Project).where(Project.slug == slug)
    )
    assert count == 1
    project = await db_session.get(Project, project_id)
    assert project is not None
    assert project.created_by == creator_id
    assert project.name == "Learning Project"
    assert project.review_mode == ReviewMode.TEAM
    memberships = list(
        await db_session.scalars(
            select(ProjectMember).where(ProjectMember.project_id == project_id)
        )
    )
    assert [(member.user_id, member.role) for member in memberships] == [
        (creator_id, ProjectRole.ENGINEER)
    ]

    if duplicate_case == "different-user":
        outsider_list = await projects_client.get("/api/projects", headers=other_headers)
        assert outsider_list.status_code == 200
        assert outsider_list.json() == []


async def test_duplicate_slug_rolls_back_and_allows_next_creation(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
) -> None:
    _, headers = creator
    slug = f"conflict-{uuid4().hex}"
    first = await _create(projects_client, headers, slug)
    duplicate = await _create(projects_client, headers, slug)
    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert db_session.is_active

    recovered = await _create(projects_client, headers, f"recovered-{uuid4().hex}", "solo")
    assert recovered.status_code == 200

    listed = await projects_client.get("/api/projects", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 2
    assert {row["id"] for row in listed.json()} == {first.json()["id"], recovered.json()["id"]}


@pytest.mark.parametrize("mode", ["team", "solo"])
async def test_membership_insert_failure_rolls_back_the_project(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    creator: tuple[User, dict[str, str]],
    mode: str,
) -> None:
    """Raise a real foreign-key violation after the Project INSERT has completed."""
    _, headers = creator
    slug = f"failed-membership-{uuid4().hex}"
    missing_user_id = uuid4()
    flushed_project_ids: list[UUID] = []

    def invalid_member(*, project_id: UUID, user_id: UUID, role: ProjectRole) -> ProjectMember:
        flushed_project_ids.append(project_id)
        return ProjectMember(
            project_id=project_id,
            user_id=missing_user_id,
            role=role,
        )

    with monkeypatch.context() as patcher:
        patcher.setattr(projects, "ProjectMember", invalid_member)
        with pytest.raises(IntegrityError) as failure:
            await _create(projects_client, headers, slug, mode)

    assert getattr(failure.value.orig, "sqlstate", None) == "23503"
    assert len(flushed_project_ids) == (2 if mode == "solo" else 1)
    assert db_session.is_active
    project_count = await db_session.scalar(
        select(func.count()).select_from(Project).where(Project.slug == slug)
    )
    membership_count = await db_session.scalar(
        select(func.count())
        .select_from(ProjectMember)
        .where(ProjectMember.project_id.in_(flushed_project_ids))
    )
    assert project_count == 0
    assert membership_count == 0

    recovered = await _create(projects_client, headers, slug, mode)
    assert recovered.status_code == 200
    listed = await projects_client.get("/api/projects", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == [recovered.json()]


async def test_other_unique_violation_is_not_reported_as_duplicate_slug(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    creator: tuple[User, dict[str, str]],
) -> None:
    _, headers = creator
    first = await _create(projects_client, headers, f"original-{uuid4().hex}")
    assert first.status_code == 200
    existing_id = UUID(first.json()["id"])
    new_slug = f"pk-conflict-{uuid4().hex}"

    def conflicting_project(
        *, name: str, slug: str, review_mode: ReviewMode, created_by: UUID
    ) -> Project:
        return Project(
            id=existing_id,
            name=name,
            slug=slug,
            review_mode=review_mode,
            created_by=created_by,
        )

    with monkeypatch.context() as patcher:
        patcher.setattr(projects, "Project", conflicting_project)
        with pytest.raises(IntegrityError) as failure:
            await _create(projects_client, headers, new_slug)

    assert getattr(failure.value.orig, "sqlstate", None) == "23505"
    assert db_session.is_active
    count = await db_session.scalar(
        select(func.count()).select_from(Project).where(Project.slug == new_slug)
    )
    assert count == 0

    recovered = await _create(projects_client, headers, new_slug)
    assert recovered.status_code == 200


@pytest.mark.parametrize("removed_role", [ProjectRole.ENGINEER, ProjectRole.REVIEWER])
async def test_list_updates_roles_after_one_membership_is_revoked(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    removed_role: ProjectRole,
) -> None:
    user, headers = creator
    created = await _create(projects_client, headers, f"partial-{uuid4().hex}", "solo")
    assert created.status_code == 200
    project_id = UUID(created.json()["id"])
    membership = await db_session.get(ProjectMember, (project_id, user.id, removed_role))
    assert membership is not None
    await db_session.delete(membership)
    await db_session.flush()

    remaining = (
        ProjectRole.REVIEWER if removed_role == ProjectRole.ENGINEER else ProjectRole.ENGINEER
    )
    listed = await projects_client.get("/api/projects", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == [{**created.json(), "roles": [remaining.value]}]


async def test_creator_without_membership_no_longer_sees_project(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
) -> None:
    user, headers = creator
    removed = await _create(projects_client, headers, f"removed-{uuid4().hex}")
    retained = await _create(projects_client, headers, f"retained-{uuid4().hex}")
    assert removed.status_code == retained.status_code == 200
    project_id = UUID(removed.json()["id"])
    membership = await db_session.get(ProjectMember, (project_id, user.id, ProjectRole.ENGINEER))
    assert membership is not None
    await db_session.delete(membership)
    await db_session.flush()

    listed = await projects_client.get("/api/projects", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == [retained.json()]

    project = await db_session.get(Project, project_id)
    assert project is not None
    assert project.created_by == user.id


async def test_create_trims_name_and_slug_before_storing(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
) -> None:
    _, headers = creator
    slug = f"trimmed-{uuid4().hex}"
    created = await _create(projects_client, headers, f"  {slug}  ", name="  Learning Project  ")
    assert created.status_code == 200
    assert created.json()["name"] == "Learning Project"
    assert created.json()["slug"] == slug

    stored = await db_session.get(Project, UUID(created.json()["id"]))
    assert stored is not None
    assert stored.name == "Learning Project"
    assert stored.slug == slug


@pytest.mark.parametrize(
    "invalid_slug",
    [
        "",
        "   ",
        "UPPERCASE",
        "contains space",
        "under_score",
        "-leading",
        "trailing-",
        "two--hyphens",
        "x" * 64,
        None,
        123,
    ],
    ids=[
        "empty",
        "whitespace",
        "uppercase",
        "space",
        "underscore",
        "leading-hyphen",
        "trailing-hyphen",
        "double-hyphen",
        "too-long",
        "null",
        "number",
    ],
)
async def test_create_rejects_invalid_slug(
    projects_client: AsyncClient,
    creator: tuple[User, dict[str, str]],
    invalid_slug: object,
) -> None:
    _, headers = creator
    response = await projects_client.post(
        "/api/projects",
        headers=headers,
        json={"name": "Invalid Slug", "slug": invalid_slug},
    )
    assert response.status_code == 422

    listed = await projects_client.get("/api/projects", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == []


@pytest.mark.parametrize(
    "invalid_name",
    ["", "   ", "x" * 256, None, 123],
    ids=["empty", "whitespace", "too-long", "null", "number"],
)
async def test_create_rejects_invalid_name(
    projects_client: AsyncClient,
    creator: tuple[User, dict[str, str]],
    invalid_name: object,
) -> None:
    _, headers = creator
    response = await projects_client.post(
        "/api/projects",
        headers=headers,
        json={"name": invalid_name, "slug": f"invalid-name-{uuid4().hex}"},
    )
    assert response.status_code == 422

    listed = await projects_client.get("/api/projects", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == []


@pytest.mark.parametrize("invalid_mode", ["unknown", None, 123], ids=["unknown", "null", "number"])
async def test_create_rejects_invalid_review_mode(
    projects_client: AsyncClient,
    creator: tuple[User, dict[str, str]],
    invalid_mode: object,
) -> None:
    _, headers = creator
    response = await projects_client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "Invalid Mode",
            "slug": f"invalid-mode-{uuid4().hex}",
            "review_mode": invalid_mode,
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("missing_field", ["name", "slug"])
async def test_create_requires_name_and_slug(
    projects_client: AsyncClient,
    creator: tuple[User, dict[str, str]],
    missing_field: str,
) -> None:
    _, headers = creator
    payload = {"name": "Missing Field", "slug": f"missing-{uuid4().hex}"}
    payload.pop(missing_field)
    response = await projects_client.post("/api/projects", headers=headers, json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("name_length", "slug_length"),
    [(1, 40), (255, 40), (20, 1), (20, 63)],
    ids=["minimum-name", "maximum-name", "minimum-slug", "maximum-slug"],
)
async def test_create_accepts_name_and_slug_length_boundaries(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    name_length: int,
    slug_length: int,
) -> None:
    _, headers = creator
    name = "n" * name_length
    slug = (uuid4().hex * 2)[:slug_length]
    if slug_length == 1:
        existing = set(
            await db_session.scalars(select(Project.slug).where(func.length(Project.slug) == 1))
        )
        available = next(
            (value for value in string.ascii_lowercase + string.digits if value not in existing),
            None,
        )
        if available is None:
            pytest.skip("The test database has no unused single-character slug")
        slug = available
    response = await _create(projects_client, headers, slug, name=name)

    assert response.status_code == 200
    assert response.json()["name"] == name
    assert response.json()["slug"] == slug


async def test_list_has_stable_creation_time_and_id_order(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
) -> None:
    user, headers = creator
    first_id, middle_id, last_id = sorted([uuid4(), uuid4(), uuid4()])
    timestamp = datetime(2020, 1, 1, tzinfo=UTC)
    later = Project(
        id=first_id,
        name="Later",
        slug=f"later-{uuid4().hex}",
        created_by=user.id,
        review_mode=ReviewMode.TEAM,
        created_at=timestamp + timedelta(days=1),
    )
    earlier_high = Project(
        id=last_id,
        name="Earlier High",
        slug=f"earlier-high-{uuid4().hex}",
        created_by=user.id,
        review_mode=ReviewMode.TEAM,
        created_at=timestamp,
    )
    earlier_low = Project(
        id=middle_id,
        name="Earlier Low",
        slug=f"earlier-low-{uuid4().hex}",
        created_by=user.id,
        review_mode=ReviewMode.TEAM,
        created_at=timestamp,
    )
    db_session.add_all([later, earlier_high, earlier_low])
    await db_session.flush()
    db_session.add_all(
        [
            ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.ENGINEER)
            for project in (later, earlier_high, earlier_low)
        ]
    )
    await db_session.flush()

    first = await projects_client.get("/api/projects", headers=headers)
    second = await projects_client.get("/api/projects", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert [row["id"] for row in first.json()] == [str(middle_id), str(last_id), str(first_id)]


async def test_reviewer_can_create_a_new_project_and_becomes_its_engineer(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
) -> None:
    _, owner_headers = creator
    reviewer, reviewer_headers = other_account
    shared = await _create(projects_client, owner_headers, f"reviewed-{uuid4().hex}")
    assert shared.status_code == 200
    db_session.add(
        ProjectMember(
            project_id=UUID(shared.json()["id"]),
            user_id=reviewer.id,
            role=ProjectRole.REVIEWER,
        )
    )
    await db_session.flush()

    created = await _create(projects_client, reviewer_headers, f"new-owner-{uuid4().hex}")
    assert created.status_code == 200
    assert created.json()["roles"] == ["engineer"]

    stored = await db_session.get(Project, UUID(created.json()["id"]))
    assert stored is not None
    assert stored.created_by == reviewer.id
    listed = await projects_client.get("/api/projects", headers=reviewer_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 2
    by_id = {row["id"]: row for row in listed.json()}
    assert by_id[shared.json()["id"]]["roles"] == ["reviewer"]
    assert by_id[created.json()["id"]]["roles"] == ["engineer"]


async def test_engineer_adds_reviewer_and_retry_returns_empty_204(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
) -> None:
    _, engineer_headers = creator
    target, target_headers = other_account
    target_id = target.id
    submitted_email = f"  {target.email.upper()}  "

    created = await _create(
        projects_client,
        engineer_headers,
        f"members-{uuid4().hex}",
    )
    assert created.status_code == 200
    project_id = UUID(created.json()["id"])

    for _ in range(2):
        added = await projects_client.post(
            f"/api/projects/{project_id}/members",
            headers=engineer_headers,
            json={
                "email": submitted_email,
                "role": "reviewer",
            },
        )
        assert added.status_code == 204
        assert added.content == b""

    count = await db_session.scalar(
        select(func.count())
        .select_from(ProjectMember)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == target_id,
            ProjectMember.role == ProjectRole.REVIEWER,
        )
    )
    assert count == 1

    history = await projects_client.get(
        f"/api/projects/{project_id}/approvals",
        headers=target_headers,
    )
    assert history.status_code == 200
    assert history.json() == []


@dataclass(frozen=True)
class MemberProject:
    project_id: UUID
    engineer_id: UUID
    reviewer_id: UUID
    reviewer_email: str
    engineer_headers: dict[str, str]
    reviewer_headers: dict[str, str]


async def _grant_member(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: UUID,
    email: str,
    role: ProjectRole,
) -> Response:
    return await client.post(
        f"/api/projects/{project_id}/members",
        headers=headers,
        json={"email": email, "role": role.value},
    )


@pytest.fixture
async def member_project(
    projects_client: AsyncClient,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
) -> MemberProject:
    engineer, engineer_headers = creator
    reviewer, reviewer_headers = other_account
    engineer_id = engineer.id
    reviewer_id = reviewer.id
    reviewer_email = reviewer.email
    created = await _create(projects_client, engineer_headers, f"access-{uuid4().hex}")
    assert created.status_code == 200
    project_id = UUID(created.json()["id"])
    added = await _grant_member(
        projects_client, engineer_headers, project_id, reviewer_email, ProjectRole.REVIEWER
    )
    assert added.status_code == 204
    return MemberProject(
        project_id=project_id,
        engineer_id=engineer_id,
        reviewer_id=reviewer_id,
        reviewer_email=reviewer_email,
        engineer_headers=engineer_headers,
        reviewer_headers=reviewer_headers,
    )


async def _seed_approval(
    session: AsyncSession,
    project_id: UUID,
    approver_id: UUID,
    *,
    independent_review: bool = True,
    gate: Gate = Gate.CODE,
    decision: ApprovalDecision = ApprovalDecision.APPROVED,
    comment: str | None = "Original review comment",
    created_at: datetime | None = None,
    approval_id: UUID | None = None,
) -> Approval:
    """Create FK-complete history fixtures without invoking the approval workflow."""
    batch = Batch(project_id=project_id)
    session.add(batch)
    await session.flush()
    run = PipelineRun(
        project_id=project_id,
        batch_id=batch.id,
        request_text="Approval history fixture",
    )
    session.add(run)
    await session.flush()
    approval = Approval(
        project_id=project_id,
        run_id=run.id,
        gate=gate,
        decision=decision,
        approver_id=approver_id,
        independent_review=independent_review,
        fingerprint="a" * 64,
        fingerprint_parts={"fixture": "approval-history"},
        comment=comment,
    )
    if created_at is not None:
        approval.created_at = created_at
    if approval_id is not None:
        approval.id = approval_id
    session.add(approval)
    await session.flush()
    return approval


@pytest.mark.parametrize("role", [ProjectRole.ENGINEER, ProjectRole.REVIEWER])
async def test_engineer_can_grant_either_role_to_a_new_member(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
    role: ProjectRole,
) -> None:
    _, headers = creator
    target, target_headers = other_account
    target_id, target_email = target.id, target.email
    created = await _create(projects_client, headers, f"grant-{uuid4().hex}")
    assert created.status_code == 200
    project_id = UUID(created.json()["id"])

    added = await _grant_member(projects_client, headers, project_id, target_email, role)
    assert added.status_code == 204
    assert added.content == b""
    membership = await db_session.get(ProjectMember, (project_id, target_id, role))
    assert membership is not None

    listed = await projects_client.get("/api/projects", headers=target_headers)
    assert listed.status_code == 200
    assert listed.json() == [{**created.json(), "roles": [role.value]}]


@pytest.mark.parametrize("caller", ["reviewer", "outsider"])
async def test_only_project_engineers_can_add_members(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    member_project: MemberProject,
    project_password: str,
    caller: str,
) -> None:
    headers = member_project.reviewer_headers
    if caller == "outsider":
        _, headers = await _register_account(projects_client, db_session, project_password)

    rejected = await _grant_member(
        projects_client,
        headers,
        member_project.project_id,
        member_project.reviewer_email,
        ProjectRole.REVIEWER,
    )

    assert rejected.status_code == 403
    assert rejected.json() == {"detail": "Insufficient project permissions"}
    count = await db_session.scalar(
        select(func.count())
        .select_from(ProjectMember)
        .where(ProjectMember.project_id == member_project.project_id)
    )
    assert count == 2


async def test_engineer_of_another_project_cannot_add_members_here(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
) -> None:
    engineer, engineer_headers = creator
    other, other_headers = other_account
    engineer_id, other_email = engineer.id, other.email
    owned = await _create(projects_client, engineer_headers, f"owned-{uuid4().hex}")
    reviewed = await _create(projects_client, other_headers, f"reviewed-{uuid4().hex}")
    assert owned.status_code == reviewed.status_code == 200
    reviewed_id = UUID(reviewed.json()["id"])
    db_session.add(
        ProjectMember(project_id=reviewed_id, user_id=engineer_id, role=ProjectRole.REVIEWER)
    )
    await db_session.flush()

    rejected = await _grant_member(
        projects_client, engineer_headers, reviewed_id, other_email, ProjectRole.REVIEWER
    )
    assert rejected.status_code == 403


@pytest.mark.parametrize("endpoint", ["members", "approvals"])
@pytest.mark.parametrize("authorization", [None, "Bearer not-a-token"], ids=["missing", "invalid"])
async def test_member_and_approval_endpoints_require_authentication(
    projects_client: AsyncClient,
    member_project: MemberProject,
    endpoint: str,
    authorization: str | None,
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}
    path = f"/api/projects/{member_project.project_id}/{endpoint}"
    if endpoint == "members":
        response = await projects_client.post(
            path,
            headers=headers,
            json={"email": member_project.reviewer_email, "role": "reviewer"},
        )
    else:
        response = await projects_client.get(path, headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_unknown_member_returns_404_and_next_grant_succeeds(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    member_project: MemberProject,
    project_password: str,
) -> None:
    target, _ = await _register_account(projects_client, db_session, project_password)
    target_id, target_email = target.id, target.email
    missing = await _grant_member(
        projects_client,
        member_project.engineer_headers,
        member_project.project_id,
        f"missing-{uuid4().hex}@example.test",
        ProjectRole.ENGINEER,
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "User not found"}
    assert db_session.is_active

    recovered = await _grant_member(
        projects_client,
        member_project.engineer_headers,
        member_project.project_id,
        target_email,
        ProjectRole.ENGINEER,
    )
    assert recovered.status_code == 204
    assert (
        await db_session.get(
            ProjectMember, (member_project.project_id, target_id, ProjectRole.ENGINEER)
        )
        is not None
    )


@pytest.mark.parametrize("first_role", [ProjectRole.ENGINEER, ProjectRole.REVIEWER])
async def test_team_rejects_opposite_role_without_changing_existing_membership(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
    first_role: ProjectRole,
) -> None:
    _, headers = creator
    target, _ = other_account
    target_id, target_email = target.id, target.email
    created = await _create(projects_client, headers, f"separated-{uuid4().hex}")
    assert created.status_code == 200
    project_id = UUID(created.json()["id"])
    first = await _grant_member(projects_client, headers, project_id, target_email, first_role)
    assert first.status_code == 204

    opposite = ProjectRole.REVIEWER if first_role == ProjectRole.ENGINEER else ProjectRole.ENGINEER
    rejected = await _grant_member(projects_client, headers, project_id, target_email, opposite)
    assert rejected.status_code == 409
    assert rejected.json() == {"detail": "Team members cannot hold both project roles"}
    assert db_session.is_active
    stored = list(
        await db_session.scalars(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == target_id
            )
        )
    )
    assert stored == [first_role]

    retry = await _grant_member(projects_client, headers, project_id, target_email, first_role)
    assert retry.status_code == 204


async def test_team_engineer_cannot_grant_self_reviewer(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
) -> None:
    user, headers = creator
    user_id, email = user.id, user.email
    created = await _create(projects_client, headers, f"self-review-{uuid4().hex}")
    assert created.status_code == 200
    project_id = UUID(created.json()["id"])
    response = await _grant_member(
        projects_client, headers, project_id, email, ProjectRole.REVIEWER
    )
    assert response.status_code == 409

    roles = list(
        await db_session.scalars(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
            )
        )
    )
    assert roles == [ProjectRole.ENGINEER]


async def test_target_role_in_another_project_does_not_block_grant(
    projects_client: AsyncClient,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
) -> None:
    _, headers = creator
    target, target_headers = other_account
    email = target.email
    first = await _create(projects_client, headers, f"role-p-{uuid4().hex}")
    second = await _create(projects_client, headers, f"role-q-{uuid4().hex}")
    assert first.status_code == second.status_code == 200

    reviewer = await _grant_member(
        projects_client, headers, UUID(first.json()["id"]), email, ProjectRole.REVIEWER
    )
    engineer = await _grant_member(
        projects_client, headers, UUID(second.json()["id"]), email, ProjectRole.ENGINEER
    )
    assert reviewer.status_code == engineer.status_code == 204
    listed = await projects_client.get("/api/projects", headers=target_headers)
    assert listed.status_code == 200
    by_id = {row["id"]: row["roles"] for row in listed.json()}
    assert by_id == {first.json()["id"]: ["reviewer"], second.json()["id"]: ["engineer"]}


@pytest.mark.parametrize("first_role", [ProjectRole.ENGINEER, ProjectRole.REVIEWER])
async def test_solo_can_grant_both_roles_to_the_same_user(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    other_account: tuple[User, dict[str, str]],
    first_role: ProjectRole,
) -> None:
    _, headers = creator
    target, target_headers = other_account
    target_id, email = target.id, target.email
    created = await _create(projects_client, headers, f"solo-member-{uuid4().hex}", "solo")
    assert created.status_code == 200
    project_id = UUID(created.json()["id"])
    opposite = ProjectRole.REVIEWER if first_role == ProjectRole.ENGINEER else ProjectRole.ENGINEER

    for role in (first_role, opposite, first_role, opposite):
        added = await _grant_member(projects_client, headers, project_id, email, role)
        assert added.status_code == 204
        assert added.content == b""

    count = await db_session.scalar(
        select(func.count())
        .select_from(ProjectMember)
        .where(ProjectMember.project_id == project_id, ProjectMember.user_id == target_id)
    )
    assert count == 2
    listed = await projects_client.get("/api/projects", headers=target_headers)
    assert listed.status_code == 200
    assert listed.json() == [{**created.json(), "roles": ["engineer", "reviewer"]}]
    history = await projects_client.get(
        f"/api/projects/{project_id}/approvals", headers=target_headers
    )
    assert history.status_code == 200
    assert history.json() == []


@pytest.mark.parametrize(
    ("mode", "role", "expected_count"),
    [
        ("team", ProjectRole.ENGINEER, 1),
        ("solo", ProjectRole.ENGINEER, 2),
        ("solo", ProjectRole.REVIEWER, 2),
    ],
)
async def test_readding_creators_existing_role_is_an_empty_204(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    mode: str,
    role: ProjectRole,
    expected_count: int,
) -> None:
    user, headers = creator
    user_id, email = user.id, user.email
    created = await _create(projects_client, headers, f"retry-owner-{uuid4().hex}", mode)
    assert created.status_code == 200
    project_id = UUID(created.json()["id"])
    response = await _grant_member(projects_client, headers, project_id, email, role)
    assert response.status_code == 204
    assert response.content == b""
    count = await db_session.scalar(
        select(func.count())
        .select_from(ProjectMember)
        .where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
    )
    assert count == expected_count


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("email", "not-an-email"),
        ("email", None),
        ("email", 123),
        ("role", "admin"),
        ("role", None),
        ("role", 123),
    ],
    ids=["email-format", "email-null", "email-number", "role-unknown", "role-null", "role-number"],
)
async def test_member_add_rejects_invalid_input(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    member_project: MemberProject,
    field: str,
    invalid_value: object,
) -> None:
    payload: dict[str, object] = {"email": member_project.reviewer_email, "role": "reviewer"}
    payload[field] = invalid_value
    response = await projects_client.post(
        f"/api/projects/{member_project.project_id}/members",
        headers=member_project.engineer_headers,
        json=payload,
    )
    assert response.status_code == 422
    count = await db_session.scalar(
        select(func.count())
        .select_from(ProjectMember)
        .where(ProjectMember.project_id == member_project.project_id)
    )
    assert count == 2


@pytest.mark.parametrize("field", ["email", "role"])
async def test_member_add_requires_email_and_role(
    projects_client: AsyncClient,
    member_project: MemberProject,
    field: str,
) -> None:
    payload = {"email": member_project.reviewer_email, "role": "reviewer"}
    payload.pop(field)
    response = await projects_client.post(
        f"/api/projects/{member_project.project_id}/members",
        headers=member_project.engineer_headers,
        json=payload,
    )
    assert response.status_code == 422


async def test_member_insert_is_rolled_back_if_processing_fails_after_insert(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    member_project: MemberProject,
    project_password: str,
) -> None:
    """Execute a real membership INSERT, then fail before commit."""
    target, _ = await _register_account(projects_client, db_session, project_password)
    target_id, email = target.id, target.email
    original_execute = AsyncSession.execute

    async def fail_after_insert(
        session: AsyncSession, statement: Any, *args: Any, **kwargs: Any
    ) -> Any:
        result = await original_execute(session, statement, *args, **kwargs)
        if isinstance(statement, Insert) and statement.table.name == "project_members":
            raise RuntimeError("Expected failure after membership insert")
        return result

    with monkeypatch.context() as patcher:
        patcher.setattr(AsyncSession, "execute", fail_after_insert)
        with pytest.raises(RuntimeError, match="Expected failure after membership insert"):
            await _grant_member(
                projects_client,
                member_project.engineer_headers,
                member_project.project_id,
                email,
                ProjectRole.ENGINEER,
            )

    assert db_session.is_active
    count = await db_session.scalar(
        select(func.count())
        .select_from(ProjectMember)
        .where(
            ProjectMember.project_id == member_project.project_id,
            ProjectMember.user_id == target_id,
        )
    )
    assert count == 0
    recovered = await _grant_member(
        projects_client,
        member_project.engineer_headers,
        member_project.project_id,
        email,
        ProjectRole.ENGINEER,
    )
    assert recovered.status_code == 204


@pytest.mark.parametrize("endpoint", ["members", "approvals"])
@pytest.mark.parametrize("project_case", ["unknown", "invalid-uuid"])
async def test_member_and_history_endpoints_handle_unavailable_project_ids(
    projects_client: AsyncClient,
    member_project: MemberProject,
    endpoint: str,
    project_case: str,
) -> None:
    project_id = str(uuid4()) if project_case == "unknown" else "not-a-uuid"
    path = f"/api/projects/{project_id}/{endpoint}"
    if endpoint == "members":
        response = await projects_client.post(
            path,
            headers=member_project.engineer_headers,
            json={"email": member_project.reviewer_email, "role": "reviewer"},
        )
    else:
        response = await projects_client.get(path, headers=member_project.engineer_headers)
    assert response.status_code == (403 if project_case == "unknown" else 422)


@pytest.mark.parametrize("caller", ["engineer", "reviewer"])
async def test_project_members_can_read_complete_approval_history(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    member_project: MemberProject,
    caller: str,
) -> None:
    approval = await _seed_approval(
        db_session, member_project.project_id, member_project.reviewer_id
    )
    headers = (
        member_project.engineer_headers if caller == "engineer" else member_project.reviewer_headers
    )
    response = await projects_client.get(
        f"/api/projects/{member_project.project_id}/approvals", headers=headers
    )
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(approval.id),
            "project_id": str(member_project.project_id),
            "run_id": str(approval.run_id),
            "gate": "code",
            "decision": "approved",
            "approver_id": str(member_project.reviewer_id),
            "independent_review": True,
            "fingerprint": "a" * 64,
            "comment": "Original review comment",
            "created_at": response.json()[0]["created_at"],
            "review_note": None,
        }
    ]
    assert datetime.fromisoformat(response.json()[0]["created_at"]) == approval.created_at


async def test_outsider_cannot_read_existing_approval_history(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    member_project: MemberProject,
    project_password: str,
) -> None:
    await _seed_approval(db_session, member_project.project_id, member_project.reviewer_id)
    _, headers = await _register_account(projects_client, db_session, project_password)
    response = await projects_client.get(
        f"/api/projects/{member_project.project_id}/approvals", headers=headers
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Project membership required"}


async def test_history_does_not_accept_membership_in_another_project(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    member_project: MemberProject,
) -> None:
    other = await _create(
        projects_client, member_project.reviewer_headers, f"private-history-{uuid4().hex}", "solo"
    )
    assert other.status_code == 200
    other_id = UUID(other.json()["id"])
    await _seed_approval(db_session, other_id, member_project.reviewer_id, independent_review=False)

    response = await projects_client.get(
        f"/api/projects/{other_id}/approvals", headers=member_project.engineer_headers
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Project membership required"}


async def test_history_filters_rows_to_the_requested_project(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    member_project: MemberProject,
) -> None:
    other = await _create(
        projects_client, member_project.engineer_headers, f"other-history-{uuid4().hex}"
    )
    assert other.status_code == 200
    own = await _seed_approval(db_session, member_project.project_id, member_project.reviewer_id)
    foreign = await _seed_approval(db_session, UUID(other.json()["id"]), member_project.engineer_id)
    response = await projects_client.get(
        f"/api/projects/{member_project.project_id}/approvals",
        headers=member_project.engineer_headers,
    )
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [str(own.id)]
    assert str(foreign.id) not in response.text


@pytest.mark.parametrize(
    ("gate", "decision", "comment"),
    [
        (Gate.DESIGN, ApprovalDecision.RETURNED, None),
        (Gate.CODE, ApprovalDecision.APPROVED, "Preserve this comment"),
    ],
)
async def test_history_preserves_gate_decision_and_comment(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    member_project: MemberProject,
    gate: Gate,
    decision: ApprovalDecision,
    comment: str | None,
) -> None:
    await _seed_approval(
        db_session,
        member_project.project_id,
        member_project.reviewer_id,
        gate=gate,
        decision=decision,
        comment=comment,
    )
    response = await projects_client.get(
        f"/api/projects/{member_project.project_id}/approvals",
        headers=member_project.reviewer_headers,
    )
    assert response.status_code == 200
    row = response.json()[0]
    assert row["gate"] == gate.value
    assert row["decision"] == decision.value
    assert row["comment"] == comment


async def test_history_orders_newest_first_with_a_stable_id_tiebreaker(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    member_project: MemberProject,
) -> None:
    low, middle, high = sorted([uuid4(), uuid4(), uuid4()])
    timestamp = datetime(2020, 1, 1, tzinfo=UTC)
    for approval_id, created_at in (
        (middle, timestamp),
        (high, timestamp),
        (low, timestamp + timedelta(days=1)),
    ):
        await _seed_approval(
            db_session,
            member_project.project_id,
            member_project.reviewer_id,
            created_at=created_at,
            approval_id=approval_id,
        )

    first = await projects_client.get(
        f"/api/projects/{member_project.project_id}/approvals",
        headers=member_project.engineer_headers,
    )
    second = await projects_client.get(
        f"/api/projects/{member_project.project_id}/approvals",
        headers=member_project.engineer_headers,
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert [row["id"] for row in first.json()] == [str(low), str(high), str(middle)]


async def test_solo_history_explicitly_reports_no_independent_review(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
) -> None:
    user, headers = creator
    user_id = user.id
    created = await _create(projects_client, headers, f"solo-history-{uuid4().hex}", "solo")
    assert created.status_code == 200
    project_id = UUID(created.json()["id"])
    await _seed_approval(
        db_session,
        project_id,
        user_id,
        independent_review=False,
        comment="Solo review original comment",
    )

    response = await projects_client.get(f"/api/projects/{project_id}/approvals", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 1
    row = response.json()[0]
    assert row["independent_review"] is False
    assert row["review_note"] == "No independent review"
    assert row["comment"] == "Solo review original comment"


@pytest.mark.parametrize("original_mode", [ReviewMode.TEAM, ReviewMode.SOLO])
async def test_history_uses_recorded_independence_after_project_mode_changes(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    creator: tuple[User, dict[str, str]],
    original_mode: ReviewMode,
) -> None:
    user, headers = creator
    user_id = user.id
    created = await _create(
        projects_client, headers, f"historical-mode-{uuid4().hex}", original_mode.value
    )
    assert created.status_code == 200
    project_id = UUID(created.json()["id"])
    independent = original_mode == ReviewMode.TEAM
    await _seed_approval(db_session, project_id, user_id, independent_review=independent)

    project = await db_session.get(Project, project_id)
    assert project is not None
    project.review_mode = ReviewMode.SOLO if independent else ReviewMode.TEAM
    if not independent:
        await db_session.execute(
            delete(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.role == ProjectRole.REVIEWER,
            )
        )
    await db_session.flush()

    response = await projects_client.get(f"/api/projects/{project_id}/approvals", headers=headers)
    assert response.status_code == 200
    row = response.json()[0]
    assert row["independent_review"] is independent
    assert row["review_note"] == (None if independent else "No independent review")


async def test_history_access_is_revoked_when_last_membership_is_removed(
    projects_client: AsyncClient,
    db_session: AsyncSession,
    member_project: MemberProject,
) -> None:
    await _seed_approval(db_session, member_project.project_id, member_project.reviewer_id)
    path = f"/api/projects/{member_project.project_id}/approvals"
    before = await projects_client.get(path, headers=member_project.reviewer_headers)
    assert before.status_code == 200
    membership = await db_session.get(
        ProjectMember,
        (member_project.project_id, member_project.reviewer_id, ProjectRole.REVIEWER),
    )
    assert membership is not None
    await db_session.delete(membership)
    await db_session.flush()

    after = await projects_client.get(path, headers=member_project.reviewer_headers)
    assert after.status_code == 403


@pytest.fixture
async def committing_projects_client(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    """Use actual request sessions for concurrent membership writes."""
    monkeypatch.setenv("DATAFORGE_JWT_SECRET", secrets.token_urlsafe(64))
    get_api_settings.cache_clear()
    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.state.sessionmaker = session_factory
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        get_api_settings.cache_clear()


@pytest.mark.parametrize(
    ("mode", "opposite_roles", "expected_statuses", "expected_count"),
    [("team", False, [204, 204], 1), ("team", True, [204, 409], 1), ("solo", True, [204, 204], 2)],
    ids=["duplicate-role", "team-opposite-roles", "solo-opposite-roles"],
)
async def test_concurrent_member_grants_preserve_project_role_policy(
    committing_projects_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    project_password: str,
    mode: str,
    opposite_roles: bool,
    expected_statuses: list[int],
    expected_count: int,
) -> None:
    """Hold the parent row until both requests wait, then verify committed results."""
    engineer_email = f"concurrent-engineer-{uuid4().hex}@example.test"
    target_email = f"concurrent-member-{uuid4().hex}@example.test"
    project_id: UUID | None = None
    try:
        registered = await committing_projects_client.post(
            "/api/auth/register",
            json={"email": engineer_email, "password": project_password},
        )
        target = await committing_projects_client.post(
            "/api/auth/register",
            json={"email": target_email, "password": project_password},
        )
        assert registered.status_code == target.status_code == 200
        headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
        created = await _create(
            committing_projects_client, headers, f"concurrent-grants-{uuid4().hex}", mode
        )
        assert created.status_code == 200
        project_id = UUID(created.json()["id"])
        second_role = ProjectRole.ENGINEER if opposite_roles else ProjectRole.REVIEWER

        async with session_factory() as blocker:
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(blocker_pid, int)
            await blocker.execute(select(Project).where(Project.id == project_id).with_for_update())
            first_task = asyncio.create_task(
                _grant_member(
                    committing_projects_client,
                    headers,
                    project_id,
                    target_email,
                    ProjectRole.REVIEWER,
                )
            )
            second_task = asyncio.create_task(
                _grant_member(
                    committing_projects_client,
                    headers,
                    project_id,
                    target_email,
                    second_role,
                )
            )

            async def wait_for_both_requests() -> None:
                while True:
                    async with session_factory() as observer:
                        count = await observer.scalar(
                            text(
                                "WITH RECURSIVE waiting(pid) AS ("
                                "SELECT pid FROM pg_stat_activity "
                                "WHERE datname = current_database() "
                                "AND :blocker_pid = ANY(pg_blocking_pids(pid)) "
                                "UNION "
                                "SELECT activity.pid FROM pg_stat_activity AS activity "
                                "JOIN waiting ON waiting.pid = ANY(pg_blocking_pids(activity.pid)) "
                                "WHERE activity.datname = current_database()"
                                ") SELECT count(*) FROM waiting"
                            ),
                            {"blocker_pid": blocker_pid},
                        )
                    if count == 2:
                        return
                    await asyncio.sleep(0.01)

            try:
                await asyncio.wait_for(wait_for_both_requests(), timeout=10)
            finally:
                await blocker.rollback()
                first, second = await asyncio.gather(
                    first_task, second_task, return_exceptions=True
                )

        assert isinstance(first, Response)
        assert isinstance(second, Response)
        assert sorted([first.status_code, second.status_code]) == expected_statuses
        for response in (first, second):
            if response.status_code == 204:
                assert response.content == b""
            else:
                assert response.json() == {"detail": "Team members cannot hold both project roles"}

        async with session_factory() as observer:
            user = await observer.scalar(select(User).where(User.email == target_email))
            assert user is not None
            roles = list(
                await observer.scalars(
                    select(ProjectMember.role).where(
                        ProjectMember.project_id == project_id, ProjectMember.user_id == user.id
                    )
                )
            )
            assert len(roles) == expected_count
            if expected_count == 2:
                assert set(roles) == {ProjectRole.ENGINEER, ProjectRole.REVIEWER}
            elif not opposite_roles:
                assert roles == [ProjectRole.REVIEWER]
    finally:
        async with session_factory() as cleanup:
            if project_id is not None:
                await cleanup.execute(
                    delete(ProjectMember).where(ProjectMember.project_id == project_id)
                )
                await cleanup.execute(delete(Project).where(Project.id == project_id))
            await cleanup.execute(
                delete(User).where(User.email.in_([engineer_email, target_email]))
            )
            await cleanup.commit()
