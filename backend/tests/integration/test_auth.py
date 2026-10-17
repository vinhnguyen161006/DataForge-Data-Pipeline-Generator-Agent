import asyncio
import secrets
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import CurrentUserDep, get_session
from app.api.routes import auth
from app.core.config import get_api_settings
from app.core.security import decode_access_token, verify_password
from app.db.models import User

pytestmark = pytest.mark.integration


def _make_auth_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth.router, prefix="/api")

    @app.get("/api/me")
    async def current_user_probe(user: CurrentUserDep) -> dict[str, str]:
        return {"user_id": str(user.id)}

    return app


@pytest.fixture
def auth_signing_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    secret = secrets.token_urlsafe(64)
    monkeypatch.setenv("DATAFORGE_JWT_SECRET", secret)
    get_api_settings.cache_clear()
    try:
        yield secret
    finally:
        get_api_settings.cache_clear()


@pytest.fixture
def account_email() -> str:
    return f"auth-{uuid4().hex}@example.test"


@pytest.fixture
def account_password() -> str:
    return "learning-password-only"


@pytest.fixture
def incorrect_password() -> str:
    return "incorrect-password-only"


@pytest.fixture
async def auth_client(
    db_session: AsyncSession,
    auth_signing_secret: str,
) -> AsyncIterator[AsyncClient]:
    """Use the outer transaction fixture while exercising real auth dependencies."""
    app = _make_auth_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def committing_auth_client(
    session_factory: async_sessionmaker[AsyncSession],
    auth_signing_secret: str,
) -> AsyncIterator[AsyncClient]:
    """Provide separate request sessions for tests that commit to the test database."""
    app = _make_auth_app()
    app.state.sessionmaker = session_factory

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def _register(client: AsyncClient, email: str, password: str) -> Response:
    return await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )


async def _login(client: AsyncClient, email: str, password: str) -> Response:
    return await client.post(
        "/api/auth/token",
        data={"username": email, "password": password, "grant_type": "password"},
    )


def _bearer_headers(response: Response) -> dict[str, str]:
    token = response.json()["access_token"]
    assert isinstance(token, str)
    return {"Authorization": f"Bearer {token}"}


async def test_register_login_and_access_authenticated_route(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    auth_signing_secret: str,
    account_email: str,
    account_password: str,
) -> None:
    registered = await _register(auth_client, account_email, account_password)
    assert registered.status_code == 200

    user = await db_session.scalar(select(User).where(User.email == account_email))
    assert user is not None
    assert user.password_hash != account_password
    assert verify_password(user.password_hash, account_password)

    logged_in = await _login(auth_client, account_email, account_password)
    assert logged_in.status_code == 200

    expected_scheme = "bearer"
    for issued in (registered, logged_in):
        payload = issued.json()
        assert set(payload) == {"access_token", "token_type"}
        assert payload["token_type"] == expected_scheme
        assert decode_access_token(payload["access_token"], auth_signing_secret) == user.id

        protected = await auth_client.get("/api/me", headers=_bearer_headers(issued))
        assert protected.status_code == 200
        assert protected.json() == {"user_id": str(user.id)}


@pytest.mark.parametrize("email_variant", ["uppercase", "surrounding-whitespace"])
async def test_register_normalizes_email(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    account_email: str,
    account_password: str,
    email_variant: str,
) -> None:
    submitted = account_email.upper()
    if email_variant == "surrounding-whitespace":
        submitted = f"  {submitted}  "

    registered = await _register(auth_client, submitted, account_password)
    assert registered.status_code == 200

    user = await db_session.scalar(select(User).where(User.email == account_email))
    assert user is not None
    assert user.email == account_email

    logged_in = await _login(auth_client, account_email, account_password)
    assert logged_in.status_code == 200


@pytest.mark.parametrize("email_variant", ["same", "uppercase", "surrounding-whitespace"])
async def test_register_rejects_duplicate_email_without_changing_password(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    account_email: str,
    account_password: str,
    incorrect_password: str,
    email_variant: str,
) -> None:
    registered = await _register(auth_client, account_email, account_password)
    assert registered.status_code == 200

    duplicate_email = account_email
    if email_variant == "uppercase":
        duplicate_email = account_email.upper()
    elif email_variant == "surrounding-whitespace":
        duplicate_email = f"  {account_email.upper()}  "

    duplicate = await _register(auth_client, duplicate_email, incorrect_password)
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Email already registered"}

    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == account_email)
    )
    assert count == 1

    original_login = await _login(auth_client, account_email, account_password)
    replacement_login = await _login(auth_client, account_email, incorrect_password)
    assert original_login.status_code == 200
    assert replacement_login.status_code == 401


async def test_duplicate_registration_rolls_back_and_session_remains_usable(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    account_email: str,
    account_password: str,
) -> None:
    first = await _register(auth_client, account_email, account_password)
    assert first.status_code == 200

    duplicate = await _register(auth_client, account_email, account_password)
    assert duplicate.status_code == 409
    assert db_session.is_active

    new_email = f"after-conflict-{uuid4().hex}@example.test"
    recovered = await _register(auth_client, new_email, account_password)
    assert recovered.status_code == 200

    existing_login = await _login(auth_client, account_email, account_password)
    new_login = await _login(auth_client, new_email, account_password)
    assert existing_login.status_code == 200
    assert new_login.status_code == 200


async def test_register_rolls_back_if_token_creation_fails(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    account_email: str,
    account_password: str,
) -> None:
    def fail_token(user_id: UUID, secret: str, ttl_minutes: int) -> str:
        raise RuntimeError("Expected token creation failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(auth, "create_access_token", fail_token)
        with pytest.raises(RuntimeError, match="Expected token creation failure"):
            await _register(auth_client, account_email, account_password)

    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == account_email)
    )
    assert count == 0
    assert db_session.is_active

    recovered = await _register(auth_client, account_email, account_password)
    assert recovered.status_code == 200


async def test_register_does_not_disguise_other_integrity_errors_as_duplicate_email(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    account_email: str,
    account_password: str,
) -> None:
    """Cause a real primary-key conflict rather than an email unique violation."""
    first = await _register(auth_client, account_email, account_password)
    assert first.status_code == 200

    existing = await db_session.scalar(select(User).where(User.email == account_email))
    assert existing is not None
    existing_id = existing.id
    db_session.expunge(existing)
    new_email = f"pk-conflict-{uuid4().hex}@example.test"

    def conflicting_user(*, email: str, password_hash: str) -> User:
        return User(id=existing_id, email=email, password_hash=password_hash)

    with monkeypatch.context() as patcher:
        patcher.setattr(auth, "User", conflicting_user)
        with pytest.raises(IntegrityError):
            await _register(auth_client, new_email, account_password)

    assert db_session.is_active
    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == new_email)
    )
    assert count == 0

    recovered = await _register(auth_client, new_email, account_password)
    assert recovered.status_code == 200


@pytest.mark.parametrize(
    "invalid_email",
    [
        "",
        "not-an-email",
        "name@localhost",
        "@example.test",
        "name @example.test",
        "name@example .test",
        "x" * 310 + "@example.test",
        123,
        None,
        ["name@example.test"],
    ],
    ids=[
        "empty",
        "missing-at",
        "missing-domain-dot",
        "missing-local-part",
        "local-whitespace",
        "domain-whitespace",
        "too-long",
        "number",
        "null",
        "list",
    ],
)
async def test_register_rejects_invalid_email(
    auth_client: AsyncClient,
    account_password: str,
    invalid_email: object,
) -> None:
    response = await auth_client.post(
        "/api/auth/register",
        json={"email": invalid_email, "password": account_password},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("length", [0, 14, 1025], ids=["empty", "too-short", "too-long"])
async def test_register_rejects_password_outside_length_limits(
    auth_client: AsyncClient,
    account_email: str,
    length: int,
) -> None:
    response = await _register(auth_client, account_email, "x" * length)

    assert response.status_code == 422


@pytest.mark.parametrize("invalid_value", [None, 123], ids=["null", "number"])
async def test_register_rejects_non_string_password(
    auth_client: AsyncClient,
    account_email: str,
    invalid_value: object,
) -> None:
    response = await auth_client.post(
        "/api/auth/register",
        json={"email": account_email, "password": invalid_value},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("missing_field", ["email", "password"])
async def test_register_requires_both_fields(
    auth_client: AsyncClient,
    account_email: str,
    account_password: str,
    missing_field: str,
) -> None:
    payload = {"email": account_email, "password": account_password}
    payload.pop(missing_field)
    response = await auth_client.post("/api/auth/register", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize("length", [15, 1024], ids=["minimum", "maximum"])
async def test_register_accepts_password_length_boundaries(
    auth_client: AsyncClient,
    account_email: str,
    length: int,
) -> None:
    candidate = "x" * length
    registered = await _register(auth_client, account_email, candidate)
    logged_in = await _login(auth_client, account_email, candidate)

    assert registered.status_code == 200
    assert logged_in.status_code == 200


async def test_register_requires_json(
    auth_client: AsyncClient,
    account_email: str,
    account_password: str,
) -> None:
    response = await auth_client.post(
        "/api/auth/register",
        data={"email": account_email, "password": account_password},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("email_variant", ["uppercase", "surrounding-whitespace"])
async def test_login_normalizes_username_email(
    auth_client: AsyncClient,
    account_email: str,
    account_password: str,
    email_variant: str,
) -> None:
    registered = await _register(auth_client, account_email, account_password)
    assert registered.status_code == 200

    submitted = account_email.upper()
    if email_variant == "surrounding-whitespace":
        submitted = f"  {submitted}  "

    logged_in = await _login(auth_client, submitted, account_password)
    assert logged_in.status_code == 200


async def test_login_wrong_password_and_unknown_email_have_the_same_error(
    auth_client: AsyncClient,
    account_email: str,
    account_password: str,
    incorrect_password: str,
) -> None:
    registered = await _register(auth_client, account_email, account_password)
    assert registered.status_code == 200

    wrong = await _login(auth_client, account_email, incorrect_password)
    unknown = await _login(auth_client, f"missing-{uuid4().hex}@example.test", account_password)

    for response in (wrong, unknown):
        assert response.status_code == 401
        assert response.json() == {"detail": "Incorrect email or password"}
        assert response.headers["www-authenticate"] == "Bearer"


async def test_password_surrounding_whitespace_is_preserved(
    auth_client: AsyncClient,
    account_email: str,
    account_password: str,
) -> None:
    spaced = f"  {account_password}  "
    registered = await _register(auth_client, account_email, spaced)
    exact = await _login(auth_client, account_email, spaced)
    stripped = await _login(auth_client, account_email, account_password)

    assert registered.status_code == 200
    assert exact.status_code == 200
    assert stripped.status_code == 401


@pytest.mark.parametrize(
    "request_case",
    ["json", "missing-username", "missing-password", "email-field"],
)
async def test_login_requires_username_and_password_as_form_fields(
    auth_client: AsyncClient,
    account_email: str,
    account_password: str,
    request_case: str,
) -> None:
    payload = {"username": account_email, "password": account_password}
    if request_case == "json":
        response = await auth_client.post("/api/auth/token", json=payload)
    else:
        if request_case == "missing-username":
            payload.pop("username")
        elif request_case == "missing-password":
            payload.pop("password")
        elif request_case == "email-field":
            payload["email"] = payload.pop("username")
        response = await auth_client.post("/api/auth/token", data=payload)

    assert response.status_code == 422


async def test_expired_token_cannot_access_authenticated_route(
    auth_client: AsyncClient,
    auth_signing_secret: str,
    account_email: str,
    account_password: str,
) -> None:
    registered = await _register(auth_client, account_email, account_password)
    assert registered.status_code == 200

    claims = jwt.decode(
        registered.json()["access_token"], auth_signing_secret, algorithms=["HS256"]
    )
    now = int(datetime.now(UTC).timestamp())
    claims["iat"] = now - 300
    claims["exp"] = now - 60
    expired = jwt.encode(claims, auth_signing_secret, algorithm="HS256")

    response = await auth_client.get("/api/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_registered_user_token_stops_working_after_user_deletion(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    account_email: str,
    account_password: str,
) -> None:
    registered = await _register(auth_client, account_email, account_password)
    assert registered.status_code == 200
    headers = _bearer_headers(registered)

    before = await auth_client.get("/api/me", headers=headers)
    assert before.status_code == 200

    user = await db_session.scalar(select(User).where(User.email == account_email))
    assert user is not None
    await db_session.delete(user)
    await db_session.flush()

    after = await auth_client.get("/api/me", headers=headers)
    assert after.status_code == 401
    assert after.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("email_variant", ["same", "normalized"])
async def test_concurrent_registration_creates_exactly_one_committed_user(
    committing_auth_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    account_email: str,
    account_password: str,
    incorrect_password: str,
    email_variant: str,
) -> None:
    """Synchronize two independent sessions before INSERT and clean up committed test data."""
    competing_sessions: list[AsyncSession] = []
    both_ready = asyncio.Event()
    original_flush = AsyncSession.flush

    async def synchronized_flush(
        session: AsyncSession,
        objects: Sequence[Any] | None = None,
    ) -> None:
        if any(isinstance(item, User) and item.email == account_email for item in session.new):
            competing_sessions.append(session)
            if len(competing_sessions) == 2:
                both_ready.set()
            await asyncio.wait_for(both_ready.wait(), timeout=10)
        await original_flush(session, objects=objects)

    second_email = account_email
    if email_variant == "normalized":
        second_email = f"  {account_email.upper()}  "

    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(AsyncSession, "flush", synchronized_flush)
            first, second = await asyncio.gather(
                _register(committing_auth_client, account_email, account_password),
                _register(committing_auth_client, second_email, incorrect_password),
                return_exceptions=True,
            )

        assert isinstance(first, Response)
        assert isinstance(second, Response)
        assert len(competing_sessions) == 2
        assert competing_sessions[0] is not competing_sessions[1]
        assert sorted([first.status_code, second.status_code]) == [200, 409]

        winner = first if first.status_code == 200 else second
        loser = second if first.status_code == 200 else first
        winner_password = account_password if first.status_code == 200 else incorrect_password
        loser_password = incorrect_password if first.status_code == 200 else account_password
        assert loser.json() == {"detail": "Email already registered"}

        async with session_factory() as observer:
            users = list(await observer.scalars(select(User).where(User.email == account_email)))
            assert len(users) == 1
            assert verify_password(users[0].password_hash, winner_password)
            assert not verify_password(users[0].password_hash, loser_password)

        protected = await committing_auth_client.get("/api/me", headers=_bearer_headers(winner))
        logged_in = await _login(committing_auth_client, account_email, winner_password)
        assert protected.status_code == 200
        assert logged_in.status_code == 200
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(delete(User).where(User.email == account_email))
            await cleanup.commit()
