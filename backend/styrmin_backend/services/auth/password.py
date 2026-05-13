"""Argon2id password hashing per ADR-019."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

from styrmin_backend.services.exceptions import PasswordPolicyError

MIN_PASSWORD_LENGTH = 5
MAX_PASSWORD_LENGTH = 256

_HASHER = PasswordHasher(memory_cost=19456, time_cost=2, parallelism=1)
_VERIFY_FAILURES: tuple[type[Exception], ...] = (
    VerifyMismatchError,
    VerificationError,
    InvalidHashError,
)


def _validate_policy(plaintext: str) -> None:
    if len(plaintext) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    if len(plaintext) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters"
        )


def hash_password(plaintext: str) -> str:
    _validate_policy(plaintext)
    return _HASHER.hash(plaintext)


def verify_password(hash_str: str, plaintext: str) -> bool:
    try:
        return _HASHER.verify(hash_str, plaintext)
    except _VERIFY_FAILURES:
        return False


def needs_rehash(hash_str: str) -> bool:
    return _HASHER.check_needs_rehash(hash_str)
