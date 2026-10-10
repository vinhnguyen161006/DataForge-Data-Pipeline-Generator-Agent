from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from jwt.exceptions import InvalidTokenError

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """TODO: hash the password with argon2 (argon2-cffi PasswordHasher)."""
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a password, rejecting mismatches and clearly invalid hashes."""
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: UUID, secret: str, ttl_minutes: int) -> str:
    """Issue an HS256 access token with a positive lifetime."""
    if ttl_minutes <= 0:
        raise ValueError("Token lifetime must be positive.")

    issued_at = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> UUID:
    """Validate an HS256 access token and return its user UUID."""
    payload = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        options={"require": ["sub", "iat", "exp"]},
    )

    try:
        return UUID(payload["sub"])
    except ValueError as exc:
        raise InvalidTokenError("Token subject must be a UUID.") from exc
