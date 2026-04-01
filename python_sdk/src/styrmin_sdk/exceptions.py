"""Styrmin SDK exception hierarchy."""

from __future__ import annotations

from typing import Any


class StyrminError(Exception):
    """Base exception for all Styrmin SDK errors."""


class StyrminTransportError(StyrminError):
    """HTTP-level transport error (connection refused, timeout, non-2xx status)."""


class StyrminGraphQLError(StyrminError):
    """GraphQL-level error (the response contained an 'errors' key)."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors
        messages = "; ".join(e.get("message", str(e)) for e in errors)
        super().__init__(f"GraphQL errors: {messages}")


class StyrminAPIError(StyrminError):
    """Server returned an error union type via __typename."""

    def __init__(self, message: str, typename: str) -> None:
        self.typename = typename
        super().__init__(message)


class ResourceNotFoundError(StyrminAPIError):
    """The requested resource was not found."""


class ResourceAlreadyExistsError(StyrminAPIError):
    """A resource with the given identifier already exists."""


class OperationFailedError(StyrminAPIError):
    """A mutation operation failed."""
