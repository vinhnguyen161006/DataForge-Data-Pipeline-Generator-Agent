import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_api_settings
from app.core.security import decode_access_token
from app.db.models import ProjectMember, ProjectRole, User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="api/auth/token",
    auto_error=False,
)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide a request session and close it after dependency use."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker

    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    """Authenticate a bearer token against the current user record."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        raise credentials_error

    secret = get_api_settings().jwt_secret.get_secret_value()

    try:
        user_id = decode_access_token(token, secret)
    except InvalidTokenError as exc:
        raise credentials_error from exc

    user = await session.get(User, user_id)

    if user is None:
        raise credentials_error

    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_project_id(project_id: uuid.UUID) -> uuid.UUID:
    return project_id


ProjectIdDep = Annotated[uuid.UUID, Depends(get_project_id)]


def require_role(
    role: ProjectRole,
) -> Callable[..., Coroutine[Any, Any, User]]:
    """Require a specific role in the requested project."""

    async def check_role(
        project_id: ProjectIdDep,
        user: CurrentUserDep,
        session: SessionDep,
    ) -> User:
        membership = await session.scalar(
            select(ProjectMember).where(
                ProjectMember.user_id == user.id,
                ProjectMember.project_id == project_id,
                ProjectMember.role == role,
            )
        )

        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient project permissions",
            )

        return user

    return check_role


async def require_project_member(
    project_id: ProjectIdDep,
    user: CurrentUserDep,
    session: SessionDep,
) -> User:
    """Require that the current user is a member of the requested project."""
    membership = await session.scalar(
        select(ProjectMember)
        .where(
            ProjectMember.user_id == user.id,
            ProjectMember.project_id == project_id,
        )
        .limit(1)
    )

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Project membership required",
        )

    return user
