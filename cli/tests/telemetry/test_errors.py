"""Unit tests for ``categorize_error`` (T008).

Maps each exception type to its expected ``(outcome, error_category)`` per
research.md R7, plus the success and ``SystemExit`` rules.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from styrmin_sdk.exceptions import (
    DeploymentRestoringError,
    OperationFailedError,
    ResourceAlreadyExistsError,
    ResourceNotFoundError,
    StyrminAuthenticationError,
    StyrminAuthorizationError,
    StyrminError,
    StyrminGraphQLError,
    StyrminTransportError,
)
from styrminctl.errors import AsymmetricEnvCredentialsError, TokenStoreError
from styrminctl.telemetry.errors import categorize_error


def test_success_is_none_exception() -> None:
    assert categorize_error(None) == ("success", None)


@pytest.mark.parametrize(
    ("exc", "expected_category"),
    [
        (StyrminAuthenticationError("x", "Unauthenticated"), "auth"),
        (StyrminAuthorizationError("x", "Forbidden"), "auth"),
        (StyrminTransportError("x"), "network"),
        (ResourceNotFoundError("x", "NotFound"), "not_found"),
        (ResourceAlreadyExistsError("x", "Exists"), "validation"),
        (StyrminGraphQLError([{"message": "boom"}]), "validation"),
        (AsymmetricEnvCredentialsError("STYRMIN_PASSWORD"), "validation"),
        (OperationFailedError("x", "Failed"), "server"),
        (DeploymentRestoringError("x", "Restoring"), "server"),
        (TokenStoreError.__new__(TokenStoreError), "server"),
    ],
)
def test_typed_exceptions_map_to_failure(exc: Exception, expected_category: str) -> None:
    outcome, category = categorize_error(exc)
    assert outcome == "failure"
    assert category == expected_category


def test_token_store_error_instance(tmp_path: Path) -> None:
    exc = TokenStoreError(tmp_path / "token.json", "corrupt")
    assert categorize_error(exc) == ("failure", "server")


@pytest.mark.parametrize("code", [0, None])
def test_system_exit_zero_or_none_is_success(code: object) -> None:
    assert categorize_error(SystemExit(code)) == ("success", None)


@pytest.mark.parametrize("code", [1, 2, "some error message"])
def test_system_exit_nonzero_is_usage_failure(code: object) -> None:
    assert categorize_error(SystemExit(code)) == ("failure", "usage")


def test_unknown_exception_is_unknown() -> None:
    assert categorize_error(ValueError("nope")) == ("failure", "unknown")


def test_base_styrmin_error_without_specific_type_is_unknown() -> None:
    # A bare StyrminError (not one of the mapped subclasses) falls through to
    # the generic unknown bucket.
    assert categorize_error(StyrminError("generic")) == ("failure", "unknown")
