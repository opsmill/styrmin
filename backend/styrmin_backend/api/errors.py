"""Structured error handling extension for the GraphQL API.

GraphQL errors fall into three categories, each handled differently by
``StructuredErrorExtension``:

1. ``ServiceError`` raised from a resolver — message + ``error_code`` +
   ``error_metadata`` are surfaced verbatim via ``extensions``.
2. Request-validation errors from graphql-core (parse / validate /
   variable coercion). These are spec-defined as client-safe; their
   message is preserved and ``extensions.code`` defaults to
   ``VALIDATION_ERROR``.
3. Any other Python exception bubbling out of a resolver — masked as
   ``"An internal error occurred"`` with ``INTERNAL_ERROR`` so internal
   details never reach the client.

Error codes for ServiceError-driven responses are declared on each
subclass via the ``error_code`` attribute (see services/exceptions.py).
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any, Iterator

from graphql import ExecutionResult, GraphQLError
from strawberry.extensions import SchemaExtension

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
    # Env vars (008-deployment-env-vars, data-model.md §7)
    INVALID_ENV_VAR_NAME = "INVALID_ENV_VAR_NAME"
    DUPLICATE_ENV_VAR_NAME = "DUPLICATE_ENV_VAR_NAME"
    ENV_VAR_SIZE_LIMIT_EXCEEDED = "ENV_VAR_SIZE_LIMIT_EXCEEDED"
    UNKNOWN_COMPONENT_ENV_VAR = "UNKNOWN_COMPONENT_ENV_VAR"
    DRIVER_ENV_VAR_DOC_COMPONENT_MISMATCH = "DRIVER_ENV_VAR_DOC_COMPONENT_MISMATCH"
    DRIVER_ENV_VAR_DOC_LEVEL_MISMATCH = "DRIVER_ENV_VAR_DOC_LEVEL_MISMATCH"


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

        if original is None or isinstance(original, GraphQLError):
            # Request-validation / parse / variable-coercion error from
            # graphql-core — the message is spec-defined as client-safe.
            self._log_validation_error(error)
            existing = dict(error.extensions or {})
            existing.setdefault("code", ErrorCode.VALIDATION_ERROR)
            error.extensions = existing
            return error

        # Unexpected resolver exception — mask internal details
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

    def _log_validation_error(self, error: GraphQLError) -> None:
        logger.info("GraphQL validation error: %s", error.message)

    def _log_unexpected_error(self, error: GraphQLError) -> None:
        logger.error(
            "Unexpected GraphQL error: %s",
            error.message,
            exc_info=error.original_error,
        )
