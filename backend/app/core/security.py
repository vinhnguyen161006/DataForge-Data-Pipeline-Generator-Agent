from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

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
    """TODO: issue an HS256 JWT with sub=user_id, iat and exp claims."""
    raise NotImplementedError


def decode_access_token(token: str, secret: str) -> UUID:
    """TODO: decode and validate the JWT and return the user id from `sub`."""
    raise NotImplementedError
