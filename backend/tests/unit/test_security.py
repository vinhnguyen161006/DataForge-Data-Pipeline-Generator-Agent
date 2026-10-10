import pytest
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from app.core.security import hash_password, verify_password


@pytest.fixture
def password() -> str:
    return " learning-password-only "


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
