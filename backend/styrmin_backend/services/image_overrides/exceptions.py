"""Exception types for per-component image overrides (018, contracts/errors.md).

Every exception subclasses :class:`ServiceError` (Constitution §IV) and carries a stable
``error_code`` that the GraphQL ``StructuredErrorExtension`` projects onto ``extensions.code``.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from styrmin_backend.services.exceptions import ServiceError

ImageReferenceReason = Literal[
    "grammar", "missing_tag_or_digest", "template_expression", "after_substitution"
]


def _format_known_components(known: list[str]) -> str:
    return ", ".join(known) if known else "(none — the driver declares no components)"


class InvalidImageReferenceError(ServiceError):
    """An image override is not a usable image reference.

    Raised on write, on ``updateDeploymentVersion`` and at render. ``reference`` is the stored
    string; ``resolved_reference`` (message only) is the string after ``{{ app.version }}``
    substitution, and ``application_version`` the version substituted, when one was.
    """

    error_code = "INVALID_IMAGE_REFERENCE"
    default_message = "The image override is not a valid image reference"

    def __init__(  # noqa: PLR0913
        self,
        message: str = "",
        *,
        reason: ImageReferenceReason = "grammar",
        reference: str = "",
        component_name: str | None = None,
        application_version: str | None = None,
        resolved_reference: str | None = None,
        detail: str = "",
    ) -> None:
        self.reason: ImageReferenceReason = reason
        self.reference = reference
        self.component_name = component_name
        self.application_version = application_version
        self.resolved_reference = resolved_reference
        self.detail = detail
        super().__init__(message or self._build_default_message())

    def _build_default_message(self) -> str:
        subject = (
            f"for component {self.component_name!r} " if self.component_name else ""
        )
        # JSON quoting keeps control characters visible in the message.
        quoted = json.dumps(self.reference, ensure_ascii=False)
        if self.detail:
            problem = self.detail
        elif self.reason == "missing_tag_or_digest":
            problem = f'{quoted} has no tag or digest (add ":<tag>", "@sha256:<digest>", or ":{{{{ app.version }}}}")'
        elif self.reason == "template_expression":
            problem = f"{quoted} contains a template expression; only {{{{ app.version }}}} is substituted"
        elif self.reason == "after_substitution":
            problem = (
                f"{quoted} resolves to {json.dumps(self.resolved_reference, ensure_ascii=False)} "
                f"for application version {json.dumps(self.application_version, ensure_ascii=False)}, "
                "which is not a valid image reference"
            )
        else:
            problem = (
                f"{quoted} is not a valid image reference (expected "
                "[registry[:port]/]name[:tag][@digest] with a lowercase name)"
            )
        return f"Image override {subject}is invalid: {problem}."

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "reference": self.reference,
            "reason": self.reason,
            "application_version": self.application_version,
        }


class UnknownComponentImageOverrideError(ServiceError):
    """A block with a non-null ``image`` names a component the driver version does not declare.

    Mirrors ``UNKNOWN_COMPONENT_CONTAINER_OVERRIDE``; ``known_components`` is sorted.
    """

    error_code = "UNKNOWN_COMPONENT_IMAGE_OVERRIDE"
    default_message = "Image override targets an unknown component"

    def __init__(
        self,
        message: str = "",
        component_name: str = "",
        known_components: list[str] | None = None,
        checked_against: str = "",
    ) -> None:
        self.component_name = component_name
        self.known_components = sorted(known_components or [])
        super().__init__(
            message
            or (
                f"Image override targets component {component_name!r} "
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
