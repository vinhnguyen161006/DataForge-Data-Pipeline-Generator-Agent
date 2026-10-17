import secrets
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

import jwt
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session, require_project_member, require_role
from app.core.config import get_api_settings
from app.core.security import create_access_token, hash_password
from app.db.models import Project, ProjectMember, ProjectRole, User

pytestmark = pytest.mark.integration

EngineerDep = Annotated[User, Depends(require_role(ProjectRole.ENGINEER))]
ReviewerDep = Annotated[User, Depends(require_role(ProjectRole.REVIEWER))]
MemberDep = Annotated[User, Depends(require_project_member)]
UserDep = Annotated[User, Depends(get_current_user)]


@pytest.fixture
def signing_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    secret = secrets.token_urlsafe(64)
    monkeypatch.setenv("DATAFORGE_JWT_SECRET", secret)
    get_api_settings.cache_clear()
    try:
        yield secret
    finally:
        get_api_settings.cache_clear()


@pytest.fixture
async def deps_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"deps-user-{uuid4()}@example.test",
        password_hash=hash_password("test-deps-only"),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def deps_projects(
    db_session: AsyncSession,
    deps_user: User,
) -> tuple[Project, Project]:
    project_p = Project(
        name="Project P",
        slug=f"deps-p-{uuid4().hex}",
        created_by=deps_user.id,
    )
    project_q = Project(
        name="Project Q",
        slug=f"deps-q-{uuid4().hex}",
        created_by=deps_user.id,
    )
    db_session.add_all([project_p, project_q])
    await db_session.flush()
    db_session.add_all(
        [
            ProjectMember(
                project_id=project_p.id,
                user_id=deps_user.id,
                role=ProjectRole.ENGINEER,
            ),
            ProjectMember(
                project_id=project_q.id,
                user_id=deps_user.id,
                role=ProjectRole.REVIEWER,
            ),
        ]
    )
    await db_session.flush()
    return project_p, project_q


@pytest.fixture
async def deps_client(
    db_session: AsyncSession,
    signing_secret: str,
) -> AsyncIterator[AsyncClient]:
    app = FastAPI()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    @app.get("/me")
    async def current_user_probe(user: UserDep) -> dict[str, str]:
        return {"user_id": str(user.id)}

    @app.get("/projects/{project_id}/engineer")
    async def engineer_probe(user: EngineerDep) -> dict[str, str]:
        return {"user_id": str(user.id)}

    @app.get("/projects/{project_id}/reviewer")
    async def reviewer_probe(user: ReviewerDep) -> dict[str, str]:
        return {"user_id": str(user.id)}

    @app.get("/projects/{project_id}/member")
    async def member_probe(user: MemberDep) -> dict[str, str]:
        return {"user_id": str(user.id)}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
def auth_headers(deps_user: User, signing_secret: str) -> dict[str, str]:
    token = create_access_token(deps_user.id, signing_secret, 5)
    return {"Authorization": f"Bearer {token}"}


async def test_engineer_role_is_scoped_to_project(
    deps_client: AsyncClient,
    deps_user: User,
    deps_projects: tuple[Project, Project],
    auth_headers: dict[str, str],
) -> None:
    project_p, project_q = deps_projects
    allowed = await deps_client.get(f"/projects/{project_p.id}/engineer", headers=auth_headers)
    forbidden = await deps_client.get(f"/projects/{project_q.id}/engineer", headers=auth_headers)
    unauthenticated = await deps_client.get(f"/projects/{project_p.id}/engineer")

    assert allowed.status_code == 200
    assert allowed.json() == {"user_id": str(deps_user.id)}
    assert forbidden.status_code == 403
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"] == "Bearer"


async def test_current_user_accepts_valid_token(
    deps_client: AsyncClient,
    deps_user: User,
    auth_headers: dict[str, str],
) -> None:
    response = await deps_client.get("/me", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"user_id": str(deps_user.id)}


@pytest.mark.parametrize(
    "authorization",
    [None, "Basic dXNlcjpwYXNz", "Bearer", "Bearer not-a-token"],
    ids=["missing", "wrong-scheme", "empty-bearer", "malformed-token"],
)
async def test_current_user_rejects_invalid_authorization(
    deps_client: AsyncClient,
    authorization: str | None,
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}
    response = await deps_client.get("/me", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Could not validate credentials"}


@pytest.mark.parametrize(
    "failure_case",
    ["wrong-secret", "expired", "invalid-subject", "missing-subject", "wrong-algorithm"],
)
async def test_current_user_rejects_invalid_jwt(
    deps_client: AsyncClient,
    deps_user: User,
    signing_secret: str,
    failure_case: str,
) -> None:
    now = int(datetime.now(UTC).timestamp())
    claims: dict[str, str | int] = {
        "sub": str(deps_user.id),
        "iat": now,
        "exp": now + 300,
    }
    secret = signing_secret
    algorithm = "HS256"

    if failure_case == "wrong-secret":
        secret = secrets.token_urlsafe(64)
    elif failure_case == "expired":
        claims["iat"] = now - 300
        claims["exp"] = now - 60
    elif failure_case == "invalid-subject":
        claims["sub"] = "not-a-uuid"
    elif failure_case == "missing-subject":
        claims.pop("sub")
    elif failure_case == "wrong-algorithm":
        algorithm = "HS512"

    token = jwt.encode(claims, secret, algorithm=algorithm)
    response = await deps_client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Could not validate credentials"}


async def test_current_user_rejects_unknown_user(
    deps_client: AsyncClient,
    signing_secret: str,
) -> None:
    token = create_access_token(uuid4(), signing_secret, 5)
    response = await deps_client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_current_user_rejects_token_after_user_deletion(
    db_session: AsyncSession,
    deps_client: AsyncClient,
    deps_user: User,
    auth_headers: dict[str, str],
) -> None:
    before = await deps_client.get("/me", headers=auth_headers)
    assert before.status_code == 200

    await db_session.delete(deps_user)
    await db_session.flush()

    after = await deps_client.get("/me", headers=auth_headers)
    assert after.status_code == 401
    assert after.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("project_index", "expected_status"),
    [(0, 403), (1, 200)],
    ids=["engineer-only-project", "reviewer-project"],
)
async def test_reviewer_role_is_scoped_to_project(
    deps_client: AsyncClient,
    deps_user: User,
    deps_projects: tuple[Project, Project],
    auth_headers: dict[str, str],
    project_index: int,
    expected_status: int,
) -> None:
    project = deps_projects[project_index]
    response = await deps_client.get(f"/projects/{project.id}/reviewer", headers=auth_headers)

    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json() == {"user_id": str(deps_user.id)}


@pytest.mark.parametrize("project_index", [0, 1], ids=["engineer", "reviewer"])
async def test_project_member_accepts_either_role(
    deps_client: AsyncClient,
    deps_user: User,
    deps_projects: tuple[Project, Project],
    auth_headers: dict[str, str],
    project_index: int,
) -> None:
    project = deps_projects[project_index]
    response = await deps_client.get(f"/projects/{project.id}/member", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"user_id": str(deps_user.id)}


@pytest.mark.parametrize("endpoint", ["engineer", "reviewer", "member"])
async def test_project_dependencies_reject_non_member(
    db_session: AsyncSession,
    deps_client: AsyncClient,
    deps_projects: tuple[Project, Project],
    signing_secret: str,
    endpoint: str,
) -> None:
    outsider = User(
        email=f"outsider-{uuid4()}@example.test",
        password_hash=hash_password("test-outsider-only"),
    )
    db_session.add(outsider)
    await db_session.flush()
    token = create_access_token(outsider.id, signing_secret, 5)
    project_p, _ = deps_projects

    response = await deps_client.get(
        f"/projects/{project_p.id}/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert set(response.json()) == {"detail"}


@pytest.mark.parametrize("endpoint", ["engineer", "reviewer", "member"])
async def test_project_dependencies_accept_user_with_both_roles(
    db_session: AsyncSession,
    deps_client: AsyncClient,
    deps_user: User,
    deps_projects: tuple[Project, Project],
    auth_headers: dict[str, str],
    endpoint: str,
) -> None:
    project_p, _ = deps_projects
    db_session.add(
        ProjectMember(
            project_id=project_p.id,
            user_id=deps_user.id,
            role=ProjectRole.REVIEWER,
        )
    )
    await db_session.flush()

    response = await deps_client.get(f"/projects/{project_p.id}/{endpoint}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"user_id": str(deps_user.id)}


@pytest.mark.parametrize("removed_role", [ProjectRole.ENGINEER, ProjectRole.REVIEWER])
async def test_revoking_one_role_preserves_the_other_role(
    db_session: AsyncSession,
    deps_client: AsyncClient,
    deps_user: User,
    deps_projects: tuple[Project, Project],
    auth_headers: dict[str, str],
    removed_role: ProjectRole,
) -> None:
    project_p, _ = deps_projects
    db_session.add(
        ProjectMember(
            project_id=project_p.id,
            user_id=deps_user.id,
            role=ProjectRole.REVIEWER,
        )
    )
    await db_session.flush()

    before = await deps_client.get(
        f"/projects/{project_p.id}/{removed_role.value}", headers=auth_headers
    )
    assert before.status_code == 200

    membership = await db_session.get(ProjectMember, (project_p.id, deps_user.id, removed_role))
    assert membership is not None
    await db_session.delete(membership)
    await db_session.flush()

    remaining_role = (
        ProjectRole.REVIEWER if removed_role == ProjectRole.ENGINEER else ProjectRole.ENGINEER
    )
    revoked = await deps_client.get(
        f"/projects/{project_p.id}/{removed_role.value}", headers=auth_headers
    )
    retained = await deps_client.get(
        f"/projects/{project_p.id}/{remaining_role.value}", headers=auth_headers
    )
    member = await deps_client.get(f"/projects/{project_p.id}/member", headers=auth_headers)

    assert revoked.status_code == 403
    assert retained.status_code == 200
    assert member.status_code == 200


async def test_revoking_last_membership_rejects_existing_token(
    db_session: AsyncSession,
    deps_client: AsyncClient,
    deps_user: User,
    deps_projects: tuple[Project, Project],
    auth_headers: dict[str, str],
) -> None:
    project_p, project_q = deps_projects
    before = await deps_client.get(f"/projects/{project_p.id}/member", headers=auth_headers)
    assert before.status_code == 200

    membership = await db_session.get(
        ProjectMember, (project_p.id, deps_user.id, ProjectRole.ENGINEER)
    )
    assert membership is not None
    await db_session.delete(membership)
    await db_session.flush()

    for endpoint in ("engineer", "member"):
        response = await deps_client.get(
            f"/projects/{project_p.id}/{endpoint}", headers=auth_headers
        )
        assert response.status_code == 403

    unaffected = await deps_client.get(f"/projects/{project_q.id}/member", headers=auth_headers)
    assert unaffected.status_code == 200


@pytest.mark.parametrize("endpoint", ["engineer", "reviewer", "member"])
async def test_unknown_project_is_forbidden_without_exposing_project_data(
    deps_client: AsyncClient,
    auth_headers: dict[str, str],
    endpoint: str,
) -> None:
    response = await deps_client.get(f"/projects/{uuid4()}/{endpoint}", headers=auth_headers)

    assert response.status_code == 403
    assert set(response.json()) == {"detail"}
