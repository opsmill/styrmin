"""Unit tests for the argon2id password module."""

from __future__ import annotations

import pytest
from argon2 import PasswordHasher

from styrmin_backend.services.auth.password import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    hash_password,
    needs_rehash,
    verify_password,
)
from styrmin_backend.services.exceptions import PasswordPolicyError


def test_hash_then_verify_returns_true() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password(hashed, "correct horse battery staple") is True


def test_verify_returns_false_on_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password(hashed, "wrong password 12345") is False


def test_verify_returns_false_on_malformed_hash() -> None:
    assert verify_password("not-a-real-hash", "anything goes here") is False


def test_two_hashes_of_the_same_password_differ() -> None:
    a = hash_password("correct horse battery staple")
    b = hash_password("correct horse battery staple")
    assert a != b


def test_needs_rehash_true_for_weaker_parameters() -> None:
    weaker = PasswordHasher(memory_cost=8, time_cost=1, parallelism=1)
    weaker_hash = weaker.hash("correct horse battery staple")
    assert needs_rehash(weaker_hash) is True


def test_needs_rehash_false_for_current_parameters() -> None:
    hashed = hash_password("correct horse battery staple")
    assert needs_rehash(hashed) is False


def test_password_too_short_raises() -> None:
    with pytest.raises(PasswordPolicyError):
        hash_password("a" * (MIN_PASSWORD_LENGTH - 1))


def test_password_too_long_raises() -> None:
    with pytest.raises(PasswordPolicyError):
        hash_password("a" * (MAX_PASSWORD_LENGTH + 1))
