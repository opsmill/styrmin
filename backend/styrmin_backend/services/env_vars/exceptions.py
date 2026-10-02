"""Exception types for deployment environment variable handling.

Every exception subclasses :class:`ServiceError` (Constitution §IV) and carries
a stable ``error_code`` that the GraphQL ``StructuredErrorExtension`` projects
onto ``extensions.code``. Codes match ``data-model.md`` §7.
"""

from __future__ import annotations

from typing import Any

from styrmin_backend.services.exceptions import (
    PostRenderPatchRenderingError,
    ServiceError,
)


class InvalidEnvVarNameError(ServiceError):
    """The env var name failed the POSIX-style name regex.

    Raised when an operator (or a driver-side documentation entry) submits a
    name that does not match ``^[A-Za-z_][A-Za-z0-9_]*$``.
    """

    error_code = "INVALID_ENV_VAR_NAME"
    default_message = "The environment variable name is invalid"

    def __init__(
        self,
        message: str = "",
        name: str = "",
        scope: str | None = None,
    ) -> None:
        self.name = name
        self.scope = scope
        super().__init__(
            message
            or (
                f"Environment variable name {name!r} must match "
                "^[A-Za-z_][A-Za-z0-9_]*$"
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {"name": self.name}
        if self.scope is not None:
            meta["scope"] = self.scope
        return meta


class DuplicateEnvVarNameError(ServiceError):
    """A single scope's input list contains the same name more than once.

    Detected before the dict is built (FR-009).
    """

    error_code = "DUPLICATE_ENV_VAR_NAME"
    default_message = "Duplicate environment variable name in input list"

    def __init__(
        self,
        message: str = "",
        name: str = "",
        scope: str = "",
    ) -> None:
        self.name = name
        self.scope = scope
        super().__init__(
            message
            or (
                f"Environment variable name {name!r} appears more than once in "
                f"scope {scope!r}; remove the duplicate before submitting."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"name": self.name, "scope": self.scope}


class DuplicateComponentNameError(ServiceError):
    """The ``components`` input list contains the same component name twice.

    Detected before the list is flattened to the persisted
    ``dict[str, dict]`` shape so the typed error code reaches the GraphQL
    boundary intact (FR-009).
    """

    error_code = "DUPLICATE_COMPONENT_NAME"
    default_message = "Duplicate component name in input list"

    def __init__(
        self,
        message: str = "",
        name: str = "",
    ) -> None:
        self.name = name
        super().__init__(
            message
            or (
                f"Component name {name!r} appears more than once in the input "
                "list; remove the duplicate before submitting."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"name": self.name}


class InvalidEnvVarValueError(ServiceError):
    """The env var value is not a string.

    Raised by :func:`validate_env_var_value` and :func:`validate_env_vars_dict`
    at the entry point — before any UTF-8 byte counting or size cap check —
    so that JSON config write paths surface a typed
    ``extensions.code = "INVALID_ENV_VAR_VALUE"`` instead of an
    ``AttributeError`` 500. The value-side counterpart to
    :class:`InvalidEnvVarNameError`.
    """

    error_code = "INVALID_ENV_VAR_VALUE"
    default_message = "Environment variable value must be a string"

    def __init__(
        self,
        message: str = "",
        name: str = "",
        value_type: str = "",
        scope: str | None = None,
    ) -> None:
        self.name = name
        self.value_type = value_type
        self.scope = scope
        super().__init__(
            message
            or (
                f"Environment variable {name!r} (scope={scope!r}): expected "
                f"str, got {value_type}"
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {"name": self.name, "value_type": self.value_type}
        if self.scope is not None:
            meta["scope"] = self.scope
        return meta


class EnvVarSizeLimitExceededError(ServiceError):
    """An env var payload exceeded one of the size caps.

    The ``scope`` parameter carries either an input layer name
    (``"environment"``, ``"deployment"``, ``"component"``) for FR-008 input
    caps, or ``"resolved"`` for FR-008a post-merge caps. The remaining keyword
    arguments describe which cap was tripped:

    * ``name`` + ``bytes`` + ``cap``: per-value 64 KiB cap.
    * ``entries`` + ``cap``: per-scope 100-entry cap.
    * ``bytes`` + ``cap``: per-scope 256 KiB serialised cap.
    * ``component`` + ``bytes`` + ``cap``: resolved per-component 256 KiB cap.
    """

    error_code = "ENV_VAR_SIZE_LIMIT_EXCEEDED"
    default_message = "Environment variable size limit exceeded"

    def __init__(
        self,
        message: str = "",
        scope: str = "",
        name: str | None = None,
        component: str | None = None,
        bytes: int | None = None,
        entries: int | None = None,
        cap: int | None = None,
    ) -> None:
        self.scope = scope
        self.name = name
        self.component = component
        self.bytes = bytes
        self.entries = entries
        self.cap = cap
        super().__init__(message or self._build_default_message())

    def _build_default_message(self) -> str:
        if self.entries is not None:
            return (
                f"Environment variable dict in scope {self.scope!r} has "
                f"{self.entries} entries (cap: {self.cap})."
            )
        if self.name is not None and self.bytes is not None:
            return (
                f"Environment variable {self.name!r} in scope {self.scope!r} "
                f"is {self.bytes} bytes (cap: {self.cap})."
            )
        if self.component is not None and self.bytes is not None:
            return (
                f"Resolved environment variable dict for component "
                f"{self.component!r} is {self.bytes} bytes (cap: {self.cap})."
            )
        if self.bytes is not None:
            return (
                f"Environment variable dict in scope {self.scope!r} is "
                f"{self.bytes} bytes (cap: {self.cap})."
            )
        return self.default_message

    @property
    def error_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {"scope": self.scope}
        if self.name is not None:
            meta["name"] = self.name
        if self.component is not None:
            meta["component"] = self.component
        if self.bytes is not None:
            meta["bytes"] = self.bytes
        if self.entries is not None:
            meta["entries"] = self.entries
        if self.cap is not None:
            meta["cap"] = self.cap
        return meta


class UnknownComponentEnvVarError(ServiceError):
    """A component-level env var block targets a component the driver does not declare.

    Raised at the GraphQL mutation boundary (FR-010). The error metadata
    includes the list of component names declared by the deployment's current
    driver so the operator can fix the typo without a round-trip.
    """

    error_code = "UNKNOWN_COMPONENT_ENV_VAR"
    default_message = "Environment variable block targets an unknown component"

    def __init__(
        self,
        message: str = "",
        component_name: str = "",
        known_components: list[str] | None = None,
    ) -> None:
        self.component_name = component_name
        self.known_components = known_components or []
        super().__init__(
            message
            or (
                f"Environment variables target component {component_name!r} "
                "which is not declared by the deployment's current driver. "
                f"Known components: {self.known_components}"
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "known_components": self.known_components,
        }


class DriverEnvVarDocComponentMismatchError(ServiceError):
    """A driver's ``spec.env_vars`` doc references a component the driver does not declare.

    Raised at driver load time (FR-013 / FR-014) — registration aborts so
    the driver author fixes the typo before the bad declaration reaches
    consumers. ``known_components`` lists the driver's declared component
    names so the error message is actionable.
    """

    error_code = "DRIVER_ENV_VAR_DOC_COMPONENT_MISMATCH"
    default_message = (
        "Driver env var doc references a component the driver does not declare"
    )

    def __init__(
        self,
        message: str = "",
        name: str = "",
        component_name: str = "",
        known_components: list[str] | None = None,
    ) -> None:
        self.name = name
        self.component_name = component_name
        self.known_components = known_components or []
        super().__init__(
            message
            or (
                f"env var doc {name!r} references component "
                f"{component_name!r} which is not declared by the driver. "
                f"Known components: {self.known_components}"
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "component_name": self.component_name,
            "known_components": self.known_components,
        }


class DriverEnvVarDocLevelMismatchError(ServiceError):
    """A driver env var doc's ``level`` does not match its ``components`` list.

    ``level=component`` requires a non-empty ``components`` list;
    ``level=deployment`` MUST NOT carry component references (FR-013).
    Raised at driver load time when a YAML payload bypasses the Pydantic
    model-level validator and a structured error is needed (e.g. when the
    loader catches the ``ValidationError`` and converts it to a typed
    failure for the operator).
    """

    error_code = "DRIVER_ENV_VAR_DOC_LEVEL_MISMATCH"
    default_message = "Driver env var doc level does not match its components list"

    def __init__(
        self,
        message: str = "",
        name: str = "",
        level: str = "",
    ) -> None:
        self.name = name
        self.level = level
        super().__init__(
            message
            or (
                f"env var doc {name!r}: level={level!r} is inconsistent "
                "with the components list (level='component' requires "
                "non-empty components; level='deployment' forbids them)."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"name": self.name, "level": self.level}


class EnvVarPatchRenderingError(PostRenderPatchRenderingError):
    """Failed to serialise an env var post-renderer patch into YAML."""

    default_message = "Failed to serialise env var post-renderer patch"
