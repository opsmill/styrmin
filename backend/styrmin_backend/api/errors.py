"""Structured error handling extension for the GraphQL API.

This module defines:
- ErrorCode: A StrEnum of machine-readable error codes for GraphQL responses.
- StructuredErrorExtension: A Strawberry SchemaExtension that enriches GraphQL
  errors with structured extensions.code fields.

Error codes are defined on each ServiceError subclass via the `error_code`
class attribute (see services/exceptions.py).
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any, Iterator

from graphql import GraphQLError
from strawberry.extensions import SchemaExtension
from graphql import ExecutionResult

from styrmin_backend.services.exceptions import ServiceError

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    """Machine-readable error codes for GraphQL error extensions."""

    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    OPERATION_FAILED = "OPERATION_FAILED"
    ALREADY_IN_PROGRESS = "ALREADY_IN_PROGRESS"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"


class StructuredErrorExtension(SchemaExtension):
    """Enrich GraphQL errors with structured extensions.code fields."""

    def on_operation(self) -> Iterator[None]:
        yield
        result = self.execution_context.result
        if isinstance(result, ExecutionResult) and result.errors:
            result.errors = [self._enrich_error(e) for e in result.errors]

    def _enrich_error(self, error: GraphQLError) -> GraphQLError:
        original = error.original_error
        if isinstance(original, ServiceError):
            code = original.error_code
            metadata = original.error_metadata
            self._log_error(code, original, metadata)
            return GraphQLError(
                message=str(original),
                path=error.path,
                extensions={"code": code, **metadata},
            )

        # Unexpected error — mask internal details
        self._log_unexpected_error(error)
        return GraphQLError(
            message="An internal error occurred",
            path=error.path,
            extensions={"code": ErrorCode.INTERNAL_ERROR},
        )

    def _log_error(
        self, code: str, exc: ServiceError, metadata: dict[str, Any]
    ) -> None:
        logger.warning(
            "GraphQL error: code=%s exception=%s message=%s metadata=%s",
            code,
            type(exc).__name__,
            str(exc),
            metadata,
        )

    def _log_unexpected_error(self, error: GraphQLError) -> None:
        logger.error(
            "Unexpected GraphQL error: %s",
            error.message,
            exc_info=error.original_error,
        )
