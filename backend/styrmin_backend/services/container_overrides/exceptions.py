"""Exception types for component-scope container `command`/`args` overrides.

Every exception subclasses :class:`ServiceError` (Constitution §IV) and carries
a stable ``error_code`` that the GraphQL ``StructuredErrorExtension`` projects
onto ``extensions.code``. Codes match ``contracts/errors.md``.

These are deliberately distinct from the env-vars error classes
(``InvalidEnvVarValueError`` / ``UnknownComponentEnvVarError``) so the offending
field (``command`` vs ``args``) is unambiguous and env-vars behaviour stays
byte-identical (research.md D5, SC-004).
"""

from __future__ import annotations

from typing import Any

from styrmin_backend.services.exceptions import ServiceError


class InvalidContainerCommandError(ServiceError):
    """The component ``command`` override is malformed.

    Raised when ``command`` is an empty list ``[]``, is not a list, or carries
    a non-string element. Empty-string elements are accepted (FR-006). The
    value-side counterpart for the entrypoint slot.
    """

    error_code = "INVALID_CONTAINER_COMMAND"
    default_message = "The container command override is invalid"

    def __init__(
        self,
        message: str = "",
        component_name: str | None = None,
        detail: str = "",
    ) -> None:
        self.component_name = component_name
        self.detail = detail
        super().__init__(
            message
            or (
                f"Container command override{self._component_suffix()} is "
                f"invalid: {detail or 'must be a non-empty list of strings'}."
            )
        )

    def _component_suffix(self) -> str:
        return f" for component {self.component_name!r}" if self.component_name else ""

    @property
    def error_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {"field": "command"}
        if self.component_name is not None:
            meta["component_name"] = self.component_name
        if self.detail:
            meta["detail"] = self.detail
        return meta


class InvalidContainerArgsError(ServiceError):
    """The component ``args`` override is malformed.

    Same shape and rules as :class:`InvalidContainerCommandError` for the
    ``args`` slot.
    """

    error_code = "INVALID_CONTAINER_ARGS"
    default_message = "The container args override is invalid"

    def __init__(
        self,
        message: str = "",
        component_name: str | None = None,
        detail: str = "",
    ) -> None:
        self.component_name = component_name
        self.detail = detail
        super().__init__(
            message
            or (
                f"Container args override{self._component_suffix()} is "
                f"invalid: {detail or 'must be a non-empty list of strings'}."
            )
        )

    def _component_suffix(self) -> str:
        return f" for component {self.component_name!r}" if self.component_name else ""

    @property
    def error_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {"field": "args"}
        if self.component_name is not None:
            meta["component_name"] = self.component_name
        if self.detail:
            meta["detail"] = self.detail
        return meta


class DriverContainerOverrideDocComponentMismatchError(ServiceError):
    """A driver's ``spec.container_overrides`` doc references an undeclared component.

    Raised at driver load time (US6) — registration aborts so the driver
    author fixes the typo before the bad declaration reaches consumers.
    ``known_components`` lists the driver's declared component names so the
    error message is actionable. Mirrors
    :class:`~styrmin_backend.services.env_vars.exceptions.DriverEnvVarDocComponentMismatchError`.
    """

    error_code = "DRIVER_CONTAINER_OVERRIDE_DOC_COMPONENT_MISMATCH"
    default_message = (
        "Driver container_overrides doc references a component the driver "
        "does not declare"
    )

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
                f"container_overrides doc references component "
                f"{component_name!r} which is not declared by the driver. "
                f"Known components: {self.known_components}"
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "known_components": self.known_components,
        }


class UnknownComponentContainerOverrideError(ServiceError):
    """A ``command``/``args`` block targets a component the driver does not declare.

    Raised at the GraphQL mutation boundary (FR-004), before any reconcile is
    planned. The error metadata includes the sorted list of component names
    declared by the deployment's current driver so the operator can fix the
    typo without a round-trip. Independent of the env-vars
    :class:`UnknownComponentEnvVarError` — a block carrying only
    ``command``/``args`` (no ``env_vars``) is rejected here.
    """

    error_code = "UNKNOWN_COMPONENT_CONTAINER_OVERRIDE"
    default_message = "Container override block targets an unknown component"

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
                f"Container override targets component {component_name!r} "
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
