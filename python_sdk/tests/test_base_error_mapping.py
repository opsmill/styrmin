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
    StyrminAPIError,
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


@pytest.mark.parametrize(
    ("code", "exception_class"),
    [
        ("NOT_FOUND", ResourceNotFoundError),
        ("ALREADY_EXISTS", ResourceAlreadyExistsError),
        ("DEPLOYMENT_RESTORING", DeploymentRestoringError),
        ("UNAUTHENTICATED", StyrminAuthenticationError),
        ("FORBIDDEN", StyrminAuthorizationError),
        ("VALIDATION_ERROR", OperationFailedError),
    ],
)
def test_exception_carries_all_extensions(code: str, exception_class: type[StyrminAPIError]) -> None:
    """Every mapped exception gives the caller all the extensions of the error (#522)."""
    extensions = {
        "code": code,
        "path": "deployment.config.scheduling.pod_affinity.required[0]",
        "deployment_id": "00000000-0000-0000-0000-000000000100",
        "deployment_name": "primary",
        "deleted": True,
    }
    result = {"errors": [{"message": "boom", "extensions": extensions}]}

    with pytest.raises(exception_class) as exc_info:
        BaseResource._check_graphql_errors(result)

    assert exc_info.value.extensions == extensions
    assert exc_info.value.typename == code


def test_exception_carries_extensions_of_first_error_only() -> None:
    """The exception is built from the first error, so it carries that error's extensions."""
    result = {
        "errors": [
            {"message": "first", "extensions": {"code": "VALIDATION_ERROR", "path": "a"}},
            {"message": "second", "extensions": {"code": "NOT_FOUND", "path": "b"}},
        ]
    }

    with pytest.raises(OperationFailedError) as exc_info:
        BaseResource._check_graphql_errors(result)

    assert exc_info.value.extensions == {"code": "VALIDATION_ERROR", "path": "a"}


def test_exception_extensions_are_a_copy() -> None:
    """Changing the exception's extensions does not change the response the caller holds."""
    extensions = {"code": "VALIDATION_ERROR", "path": "a"}
    result = {"errors": [{"message": "boom", "extensions": extensions}]}

    with pytest.raises(OperationFailedError) as exc_info:
        BaseResource._check_graphql_errors(result)
    exc_info.value.extensions["path"] = "changed"

    assert extensions == {"code": "VALIDATION_ERROR", "path": "a"}


@pytest.mark.parametrize("error", [{"message": "boom"}, {"message": "boom", "extensions": None}])
def test_error_without_extensions_gives_empty_extensions(error: dict) -> None:
    """An error with no ``extensions``, or ``extensions: null``, gives an empty dict."""
    with pytest.raises(OperationFailedError) as exc_info:
        BaseResource._check_graphql_errors({"errors": [error]})
    assert exc_info.value.extensions == {}
    assert not exc_info.value.typename


def test_exception_built_without_extensions_has_empty_extensions() -> None:
    """Code that builds an SDK exception with only a message and a code still works."""
    error = OperationFailedError("boom", "VALIDATION_ERROR")
    assert error.extensions == {}
    assert error.typename == "VALIDATION_ERROR"
