"""Tests for ``BaseResource._check_graphql_errors`` error-code routing.

The mapping table lives at one site (``python_sdk/src/styrmin_sdk/resources/_base.py``)
and is exercised by every resource; we test it directly here so a new code
(or a regression) is caught without having to set up a full resource fixture.
"""

from __future__ import annotations

import pytest
from styrmin_sdk.exceptions import (
    DeploymentRestoringError,
    OperationFailedError,
    ResourceAlreadyExistsError,
    ResourceNotFoundError,
    StyrminAuthenticationError,
    StyrminAuthorizationError,
)
from styrmin_sdk.resources._base import BaseResource  # noqa: PLC2701 — intentionally testing a private helper


def _make_result(code: str, message: str = "boom") -> dict:
    return {
        "errors": [
            {
                "message": message,
                "extensions": {"code": code},
            }
        ],
    }


def test_no_errors_is_noop() -> None:
    """A result without an ``errors`` key returns silently."""
    BaseResource._check_graphql_errors({"data": {"foo": "bar"}})
    BaseResource._check_graphql_errors({"data": None, "errors": []})


@pytest.mark.parametrize(
    "code",
    ["NOT_FOUND", "USER_NOT_FOUND", "GROUP_NOT_FOUND"],
)
def test_not_found_codes_map_to_resource_not_found(code: str) -> None:
    """All not-found shapes route to :class:`ResourceNotFoundError`.

    The .typename attribute carries the original code so callers that
    care can still branch on the precise resource.
    """
    with pytest.raises(ResourceNotFoundError) as exc_info:
        BaseResource._check_graphql_errors(_make_result(code))
    assert exc_info.value.typename == code


@pytest.mark.parametrize(
    "code",
    ["ALREADY_EXISTS", "DUPLICATE_USERNAME", "DUPLICATE_GROUP_NAME"],
)
def test_duplicate_codes_map_to_already_exists(code: str) -> None:
    """All duplicate-resource codes route to :class:`ResourceAlreadyExistsError`."""
    with pytest.raises(ResourceAlreadyExistsError) as exc_info:
        BaseResource._check_graphql_errors(_make_result(code))
    assert exc_info.value.typename == code


def test_deployment_restoring_maps_to_dedicated_exception() -> None:
    with pytest.raises(DeploymentRestoringError):
        BaseResource._check_graphql_errors(_make_result("DEPLOYMENT_RESTORING"))


@pytest.mark.parametrize("code", ["UNAUTHENTICATED", "INVALID_CREDENTIALS"])
def test_authentication_codes(code: str) -> None:
    with pytest.raises(StyrminAuthenticationError):
        BaseResource._check_graphql_errors(_make_result(code))


def test_forbidden_maps_to_authorization() -> None:
    with pytest.raises(StyrminAuthorizationError):
        BaseResource._check_graphql_errors(_make_result("FORBIDDEN"))


@pytest.mark.parametrize(
    "code",
    ["VALIDATION_ERROR", "USER_HAS_REFERENCES", "LAST_ADMIN", "", "UNKNOWN_CODE"],
)
def test_unmapped_codes_fall_back_to_operation_failed(code: str) -> None:
    """Codes without a dedicated exception class surface as :class:`OperationFailedError`."""
    with pytest.raises(OperationFailedError) as exc_info:
        BaseResource._check_graphql_errors(_make_result(code))
    assert exc_info.value.typename == code


def test_error_without_extensions_falls_back() -> None:
    """A bare error with no ``extensions`` block defaults to OperationFailed."""
    with pytest.raises(OperationFailedError) as exc_info:
        BaseResource._check_graphql_errors({"errors": [{"message": "no extensions here"}]})
    # Code defaults to empty string when extensions is absent.
    assert not exc_info.value.typename
    assert "no extensions" in str(exc_info.value)
