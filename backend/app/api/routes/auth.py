from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.api.deps import SessionDep
from app.api.schemas import RegisterRequest, TokenResponse, normalize_email
from app.core.config import get_api_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
async def register(
    body: RegisterRequest,
    session: SessionDep,
) -> TokenResponse:
    """Create an account and return an access token after committing."""
    password_hash = await run_in_threadpool(hash_password, body.password)
    user = User(
        email=body.email,
        password_hash=password_hash,
    )

    try:
        session.add(user)
        await session.flush()
        response = _make_token_response(user.id)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()

        if _is_duplicate_email(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            ) from exc

        raise
    except Exception:
        await session.rollback()
        raise

    return response


@router.post("/token", response_model=TokenResponse)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
) -> TokenResponse:
    """Verify account credentials and return an access token."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

    email = normalize_email(form.username)
    user = await session.scalar(select(User).where(User.email == email))

    if user is None:
        raise credentials_error

    password_matches = await run_in_threadpool(
        verify_password,
        user.password_hash,
        form.password,
    )

    if not password_matches:
        raise credentials_error

    return _make_token_response(user.id)


def _make_token_response(user_id: UUID) -> TokenResponse:
    """Issue a token using the configured signing key and lifetime."""
    settings = get_api_settings()
    token = create_access_token(
        user_id,
        settings.jwt_secret.get_secret_value(),
        settings.jwt_ttl_minutes,
    )
    return TokenResponse(access_token=token)


def _is_duplicate_email(exc: IntegrityError) -> bool:
    """Identify the email unique violation from the asyncpg driver."""
    driver_error = getattr(exc.orig, "__cause__", None)
    return (
        getattr(driver_error, "sqlstate", None) == "23505"
        and getattr(driver_error, "constraint_name", None) == "uq_users_email"
    )
