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


def _format_known_components(known: list[str]) -> str:
    """Render a known-components list for an error message.

    Joins the names for readability and special-cases the empty list so the
    operator gets an actionable hint ("the driver declares no components")
    instead of a bare ``[]`` that reads like a bug.
    """
    return ", ".join(known) if known else "(none — the driver declares no components)"


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


class UnknownComponentContainerOverrideError(ServiceError):
    """A ``command``/``args`` block targets a component the driver does not declare.

    Raised at the GraphQL mutation boundary (FR-004), before any reconcile is
    planned. The error metadata includes the sorted list of component names
    declared by the checked driver version so the operator can fix the
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
        checked_against: str = "",
    ) -> None:
        self.component_name = component_name
        self.known_components = known_components or []
        super().__init__(
            message
            or (
                f"Container override targets component {component_name!r} "
                f"which is not declared by {checked_against or 'the driver version'}. "
                f"Declared components: {_format_known_components(self.known_components)}."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "known_components": self.known_components,
        }


class ContainerOverrideSizeLimitExceededError(ServiceError):
    """A ``command``/``args`` override exceeded a size cap.

    Mirrors
    :class:`~styrmin_backend.services.env_vars.exceptions.EnvVarSizeLimitExceededError`
    for the container-override slots. Container overrides are component-scope
    only (no layering/merge), so the input list IS the resolved value — a
    single per-list cap suffices and there is no separate post-merge cap. The
    tripped cap is described by the keyword arguments:

    * ``elements`` + ``cap``: per-list element-count cap.
    * ``bytes`` + ``cap``: per-list serialised UTF-8 byte cap.

    ``field`` names the offending slot (``command``/``args``); ``component_name``
    is threaded in when the caller knows it (the mutation boundary does, the
    Pydantic field validator does not).
    """

    error_code = "CONTAINER_OVERRIDE_SIZE_LIMIT_EXCEEDED"
    default_message = "The container override exceeds the allowed size"

    def __init__(
        self,
        message: str = "",
        field: str = "",
        component_name: str | None = None,
        elements: int | None = None,
        bytes: int | None = None,
        cap: int | None = None,
    ) -> None:
        self.field = field
        self.component_name = component_name
        self.elements = elements
        self.bytes = bytes
        self.cap = cap
        super().__init__(message or self._build_default_message())

    def _component_suffix(self) -> str:
        return f" for component {self.component_name!r}" if self.component_name else ""

    def _build_default_message(self) -> str:
        slot = self.field or "override"
        if self.elements is not None:
            return (
                f"Container {slot} override{self._component_suffix()} has "
                f"{self.elements} elements (cap: {self.cap})."
            )
        if self.bytes is not None:
            return (
                f"Container {slot} override{self._component_suffix()} is "
                f"{self.bytes} bytes (cap: {self.cap})."
            )
        return self.default_message

    @property
    def error_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        if self.field:
            meta["field"] = self.field
        if self.component_name is not None:
            meta["component_name"] = self.component_name
        if self.elements is not None:
            meta["elements"] = self.elements
        if self.bytes is not None:
            meta["bytes"] = self.bytes
        if self.cap is not None:
            meta["cap"] = self.cap
        return meta
