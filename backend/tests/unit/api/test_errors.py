"""Unit tests for ``StructuredErrorExtension``.

Verifies the three error categories the extension handles:

1. ``ServiceError`` — preserved with structured ``extensions.code`` + metadata.
2. GraphQL request-validation errors (parse / validate / variable coercion)
   — preserved with ``extensions.code = VALIDATION_ERROR``.
3. Unexpected resolver exceptions — masked as ``An internal error occurred``
   with ``extensions.code = INTERNAL_ERROR``.

Tests drive the extension through ``Schema.execute`` rather than calling
private helpers, so they exercise the full ``on_operation`` lifecycle.
"""

from __future__ import annotations

import enum
from typing import Any

import pytest
import strawberry
from strawberry.schema.config import StrawberryConfig

from styrmin_backend.api.errors import ErrorCode, StructuredErrorExtension
from styrmin_backend.services.exceptions import ServiceError


class _DemoServiceError(ServiceError):
    error_code = "DEMO_FAILURE"
    default_message = "Demo failure occurred"

    def __init__(self, *, resource_id: str) -> None:
        self.resource_id = resource_id
        super().__init__(f"Demo failure for {resource_id}")

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"resource_id": self.resource_id}


@strawberry.enum
class _Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


def _build_schema() -> strawberry.Schema:
    @strawberry.type
    class Query:
        @strawberry.field
        def pick(self, color: _Color) -> str:
            return color.value

        @strawberry.field
        def explode_service(self) -> str:
            raise _DemoServiceError(resource_id="abc-123")

        @strawberry.field
        def explode_runtime(self) -> str:
            raise RuntimeError("secret database password leaked")

    return strawberry.Schema(
        query=Query,
        extensions=[StructuredErrorExtension],
        config=StrawberryConfig(auto_camel_case=False),
    )


def _error_extensions(error: Any) -> dict[str, Any]:
    return dict(error.extensions or {})


@pytest.mark.asyncio
async def test_graphql_validation_error_message_is_preserved() -> None:
    """An invalid enum variable surfaces the graphql-core message verbatim and
    is tagged with ``VALIDATION_ERROR`` rather than masked as internal.
    """
    schema = _build_schema()

    result = await schema.execute(
        "query ($c: _Color!) { pick(color: $c) }",
        variable_values={"c": "NOT_A_REAL_COLOR"},
    )

    assert result.data is None
    assert result.errors is not None and len(result.errors) == 1
    error = result.errors[0]

    assert "NOT_A_REAL_COLOR" in error.message
    assert "_Color" in error.message
    assert error.message != "An internal error occurred"

    assert _error_extensions(error).get("code") == ErrorCode.VALIDATION_ERROR


@pytest.mark.asyncio
async def test_service_error_message_and_metadata_are_surfaced() -> None:
    """A ``ServiceError`` raised by a resolver is reported with its own
    message, ``error_code``, and ``error_metadata`` attached to extensions.
    """
    schema = _build_schema()

    result = await schema.execute("{ explode_service }")

    assert result.data is None
    assert result.errors is not None and len(result.errors) == 1
    error = result.errors[0]

    assert error.message == "Demo failure for abc-123"
    extensions = _error_extensions(error)
    assert extensions.get("code") == "DEMO_FAILURE"
    assert extensions.get("resource_id") == "abc-123"


@pytest.mark.asyncio
async def test_unexpected_resolver_exception_is_masked() -> None:
    """A non-``ServiceError`` Python exception bubbling out of a resolver is
    masked so internal details never reach the client.
    """
    schema = _build_schema()

    result = await schema.execute("{ explode_runtime }")

    assert result.errors is not None and len(result.errors) == 1
    error = result.errors[0]

    assert error.message == "An internal error occurred"
    assert "secret database password" not in error.message
    assert _error_extensions(error).get("code") == ErrorCode.INTERNAL_ERROR
