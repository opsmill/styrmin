"""Styrmin SDK exception hierarchy."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


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
    """The server answered with a GraphQL error; the subclass depends on its ``extensions.code``.

    ``typename`` is the ``extensions.code`` of the error. ``extensions`` holds a copy of
    all the extensions of the error, ``code`` included: for example the ``path`` of a
    refused affinity term, or the ``deployments`` of a refused
    ``environment_clones.create()`` request. When the SDK raises the exception itself,
    without a server error, ``extensions`` holds only ``code``, or nothing when
    ``typename`` is empty.
    """

    def __init__(self, message: str, typename: str, extensions: Mapping[str, Any] | None = None) -> None:
        self.typename = typename
        self.extensions: dict[str, Any] = copy.deepcopy(dict(extensions or {}))
        if typename and "code" not in self.extensions:
            self.extensions["code"] = typename
        super().__init__(message)

    def __reduce__(self) -> tuple[Any, ...]:
        # The default reduction calls ``cls(message)``, which lacks ``typename``.
        return (type(self), (str(self), self.typename, self.extensions))


class ResourceNotFoundError(StyrminAPIError):
    """The requested resource was not found."""


class ResourceAlreadyExistsError(StyrminAPIError):
    """A resource with the given identifier already exists."""


class OperationFailedError(StyrminAPIError):
    """A mutation operation failed."""


class IncompatibleServerError(OperationFailedError):
    """The Styrmin server does not accept an operation this SDK sends; upgrade the server."""


class StyrminAuthenticationError(StyrminAPIError):
    """Authentication failed (UNAUTHENTICATED or INVALID_CREDENTIALS)."""


class StyrminAuthorizationError(StyrminAPIError):
    """Authenticated but the caller's effective role is below the required role."""


class DeploymentRestoringError(StyrminAPIError):
    """The deployment is restoring; deletion was refused for data integrity."""


class ApplyError(StyrminError):
    """Base error for failures during ``DeploymentResource.apply``."""


class ManifestValidationError(ApplyError):
    """A YAML manifest failed schema validation."""


class MissingRequiredFieldError(ManifestValidationError):
    """A required manifest field was absent after override resolution."""


class EnvironmentAmbiguityError(ApplyError):
    """The environment resolves to multiple clusters and ``cluster`` was not specified."""


class EnvironmentNotFoundError(ApplyError):
    """No environment matches the resolved ``(environment, cluster)`` pair."""


class DriverMismatchError(ApplyError):
    """The manifest's driver does not match the existing deployment's driver."""


class BatchNameConflictError(ApplyError):
    """Two manifests in a batch resolve to the same (name, environment) pair."""
