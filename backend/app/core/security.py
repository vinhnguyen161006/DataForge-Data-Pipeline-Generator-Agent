from uuid import UUID


def hash_password(password: str) -> str:
    """TODO: hash the password with argon2 (argon2-cffi PasswordHasher)."""
    raise NotImplementedError


def verify_password(password_hash: str, password: str) -> bool:
    """TODO: verify an argon2 hash; return False on mismatch instead of raising."""
    raise NotImplementedError


def create_access_token(user_id: UUID, secret: str, ttl_minutes: int) -> str:
    """TODO: issue an HS256 JWT with sub=user_id, iat and exp claims."""
    raise NotImplementedError


def decode_access_token(token: str, secret: str) -> UUID:
    """TODO: decode and validate the JWT and return the user id from `sub`."""
    raise NotImplementedError
