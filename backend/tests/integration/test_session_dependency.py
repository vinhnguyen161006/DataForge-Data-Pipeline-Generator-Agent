from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.core.security import hash_password
from app.db.models import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.integration

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@pytest.mark.parametrize("fail_request", [False, True])
async def test_request_session_cleanup(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fail_request: bool,
) -> None:
    app = FastAPI()
    app.state.sessionmaker = session_factory

    used_sessions: list[AsyncSession] = []
    closed_sessions: list[AsyncSession] = []
    test_email = f"session-{uuid4()}@example.test"
    original_close = AsyncSession.close

    async def tracked_close(session: AsyncSession) -> None:
        await original_close(session)
        closed_sessions.append(session)

    monkeypatch.setattr(AsyncSession, "close", tracked_close)

    @app.post("/probe")
    async def probe(session: SessionDep) -> dict[str, str]:
        used_sessions.append(session)
        user = User(
            email=test_email,
            password_hash=hash_password("test-session-only"),
        )
        session.add(user)
        await session.flush()

        if fail_request:
            raise HTTPException(
                status_code=409,
                detail="Expected test failure",
            )

        return {"user_id": str(user.id)}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first_response = await client.post("/probe")
        second_response = await client.post("/probe")

    expected_status = 409 if fail_request else 200
    assert first_response.status_code == expected_status
    assert second_response.status_code == expected_status
    assert len(used_sessions) == 2
    assert used_sessions[0] is not used_sessions[1]
    assert closed_sessions == used_sessions

    async with session_factory() as observer:
        saved_id = await observer.scalar(select(User.id).where(User.email == test_email))

    assert saved_id is None
