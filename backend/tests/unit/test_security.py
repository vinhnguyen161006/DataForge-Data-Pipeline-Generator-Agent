import base64
import json
import secrets
from datetime import UTC, datetime
from uuid import uuid4

import jwt
import pytest
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from jwt.exceptions import (
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAlgorithmError,
    InvalidSignatureError,
    InvalidTokenError,
    MissingRequiredClaimError,
)

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


@pytest.fixture
def password() -> str:
    return " learning-password-only"


def test_hash_password_return_encoded_hash(password: str) -> None:
    password_hash = hash_password(password)

    assert password_hash.startswith("$argon2id$")
    assert password not in password_hash


def test_verify_password_accepts_correct_password(password: str) -> None:
    password_hash = hash_password(password)

    assert verify_password(password_hash, password) is True


def test_verify_password_rejects_wrong_password(password: str) -> None:
    password_hash = hash_password(password)
    assert verify_password(password_hash, "wrong-password") is False


def test_same_password_produces_different_valid_hashes(password: str) -> None:
    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash != second_hash
    assert verify_password(first_hash, password) is True  #
    assert verify_password(second_hash, password) is True


@pytest.mark.parametrize("invalid_hash", ["", "not-an-argon2-hash"])
def test_verify_password_rejects_invalid_hashes(invalid_hash: str, password: str) -> None:
    assert verify_password(invalid_hash, password) is False


def test_verify_password_preserves_unexpected_verification_error(
    monkeypatch: pytest.MonkeyPatch,
    password: str,
) -> None:
    def fail_verification(
        self: PasswordHasher,
        encoded_hash: str,
        candidate: str,
    ) -> bool:
        raise VerificationError("Unexpected verification failure")

    monkeypatch.setattr(PasswordHasher, "verify", fail_verification)

    with pytest.raises(VerificationError, match="Unexpected verification failure"):
        verify_password("unused-hash", password)


@pytest.fixture
def jwt_secret() -> str:
    return secrets.token_urlsafe(64)


@pytest.fixture
def token_claims() -> dict[str, str | int]:
    now = int(datetime.now(UTC).timestamp())
    return {
        "sub": str(uuid4()),
        "iat": now,
        "exp": now + 300,
    }


def test_access_token_round_trip(jwt_secret: str) -> None:
    user_id = uuid4()
    before = int(datetime.now(UTC).timestamp())
    token = create_access_token(user_id, jwt_secret, 5)
    after = int(datetime.now(UTC).timestamp())

    assert decode_access_token(token, jwt_secret) == user_id

    claims = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    assert claims["sub"] == str(user_id)
    assert before <= claims["iat"] <= after
    assert claims["exp"] - claims["iat"] == 300


def test_access_token_rejects_expiration(
    jwt_secret: str,
    token_claims: dict[str, str | int],
) -> None:
    now = int(datetime.now(UTC).timestamp())
    token_claims["iat"] = now - 600
    token_claims["exp"] = now - 60
    token = jwt.encode(token_claims, jwt_secret, algorithm="HS256")

    with pytest.raises(ExpiredSignatureError):
        decode_access_token(token, jwt_secret)


def test_access_token_rejects_wrong_secret(jwt_secret: str) -> None:
    token = create_access_token(uuid4(), jwt_secret, 5)

    with pytest.raises(InvalidSignatureError):
        decode_access_token(token, secrets.token_urlsafe(64))


def test_access_token_rejects_modified_payload(
    jwt_secret: str,
    token_claims: dict[str, str | int],
) -> None:
    token = jwt.encode(token_claims, jwt_secret, algorithm="HS256")
    header, _, signature = token.split(".")
    changed_claims = {**token_claims, "sub": str(uuid4())}
    payload = (
        base64.urlsafe_b64encode(json.dumps(changed_claims).encode()).rstrip(b"=").decode("ascii")
    )
    modified_token = f"{header}.{payload}.{signature}"

    with pytest.raises(InvalidSignatureError):
        decode_access_token(modified_token, jwt_secret)


@pytest.mark.parametrize("claim", ["sub", "iat", "exp"])
def test_access_token_requires_claims(
    claim: str,
    jwt_secret: str,
    token_claims: dict[str, str | int],
) -> None:
    token_claims.pop(claim)
    token = jwt.encode(token_claims, jwt_secret, algorithm="HS256")

    with pytest.raises(MissingRequiredClaimError):
        decode_access_token(token, jwt_secret)


@pytest.mark.parametrize("subject", ["not-a-uuid", "", 123])
def test_access_token_rejects_invalid_subject(
    subject: str | int,
    jwt_secret: str,
    token_claims: dict[str, str | int],
) -> None:
    token_claims["sub"] = subject
    token = jwt.encode(token_claims, jwt_secret, algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, jwt_secret)


@pytest.mark.parametrize("claim", ["iat", "exp"])
def test_access_token_rejects_invalid_time_claim(
    claim: str,
    jwt_secret: str,
    token_claims: dict[str, str | int],
) -> None:
    token_claims[claim] = "not-a-timestamp"
    token = jwt.encode(token_claims, jwt_secret, algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, jwt_secret)


def test_access_token_rejects_future_issued_at(
    jwt_secret: str,
    token_claims: dict[str, str | int],
) -> None:
    now = int(datetime.now(UTC).timestamp())
    token_claims["iat"] = now + 3600
    token_claims["exp"] = now + 7200
    token = jwt.encode(token_claims, jwt_secret, algorithm="HS256")

    with pytest.raises(ImmatureSignatureError):
        decode_access_token(token, jwt_secret)


def test_access_token_rejects_other_algorithm(
    jwt_secret: str,
    token_claims: dict[str, str | int],
) -> None:
    token = jwt.encode(token_claims, jwt_secret, algorithm="HS512")

    with pytest.raises(InvalidAlgorithmError):
        decode_access_token(token, jwt_secret)


@pytest.mark.parametrize("token", ["", "not-a-token"])
def test_access_token_rejects_malformed_token(
    token: str,
    jwt_secret: str,
) -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, jwt_secret)


@pytest.mark.parametrize("ttl_minutes", [0, -1])
def test_access_token_requires_positive_lifetime(
    ttl_minutes: int,
    jwt_secret: str,
) -> None:
    with pytest.raises(ValueError, match="Token lifetime must be positive"):
        create_access_token(uuid4(), jwt_secret, ttl_minutes)
