import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProjectRole, User


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """TODO: yield a session from request.app.state.sessionmaker."""
    raise NotImplementedError


async def get_current_user(request: Request) -> User:
    """TODO: read the bearer token, decode it, load the User or raise 401."""
    raise NotImplementedError


def require_role(
    role: ProjectRole,
) -> Callable[..., Coroutine[Any, Any, User]]:
    """TODO: dependency factory: the current user must hold `role` on the path project_id, else
    403 (FR-20).
    """
    raise NotImplementedError


async def get_project_id(project_id: uuid.UUID) -> uuid.UUID:
    return project_id
