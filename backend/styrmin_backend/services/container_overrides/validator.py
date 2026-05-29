"""Validator for component-scope container `command`/`args` overrides.

A single helper, :func:`validate_container_override`, enforces the shape rules
from FR-006 in one place so they stay consistent across:

* the Pydantic ``field_validator``s on ``ComponentConfigBlock`` (defence in
  depth);
* the pre-Pydantic dict check at the deployment mutation boundary
  (``services/deployment.py``) so the typed error survives to GraphQL.

Rules (data-model.md §6):

* ``None`` → accepted (unset / clear via null-or-omit, FR-007).
* A present value MUST be a list whose every element is a ``str``; a non-list
  or a non-string element raises the per-field typed error.
* The list MUST be non-empty; ``[]`` is rejected (it is a meaningful, invalid
  value — clearing is null/omit, never ``[]`` — FR-007).
* Empty-string elements (``["sh", "-c", ""]``) ARE accepted (FR-006, mirrors
  Kubernetes).
* A present list is bounded by a per-list element-count cap and a serialised
  UTF-8 byte cap (mirrors the env-vars caps) so a pathological override cannot
  bloat the deployment CRD past the Kubernetes resource size limit. There is
  no layering/merge for container overrides, so the input list IS the resolved
  value — this single input-time cap is sufficient (no separate post-merge
  cap, unlike env-vars).
* Values pass through verbatim — no templating/expansion (FR-014).
"""

from __future__ import annotations

from typing import Any, Literal

from styrmin_backend.services.container_overrides.exceptions import (
    ContainerOverrideSizeLimitExceededError,
    InvalidContainerArgsError,
    InvalidContainerCommandError,
)

ContainerOverrideField = Literal["command", "args"]

# Per-list size caps. The 256 KiB byte ceiling reuses the env-vars per-scope
# cap (``PER_SCOPE_BYTE_CAP``) so ``command`` + ``args`` together stay well
# under the Kubernetes 1.5 MiB resource size limit; the element cap guards
# against a pathological token list inflating the CRD.
CONTAINER_OVERRIDE_MAX_ELEMENTS: int = 1024
CONTAINER_OVERRIDE_BYTE_CAP: int = 256 * 1024  # 262144


def _raise(
    field: ContainerOverrideField,
    component_name: str | None,
    detail: str,
) -> None:
    if field == "command":
        raise InvalidContainerCommandError(component_name=component_name, detail=detail)
    raise InvalidContainerArgsError(component_name=component_name, detail=detail)


def validate_container_override(
    field: ContainerOverrideField,
    value: Any,
    component_name: str | None = None,
) -> list[str] | None:
    """Validate a single ``command``/``args`` override list.

    Returns the value unchanged on success (``None`` passes straight through as
    "unset"). Raises :class:`InvalidContainerCommandError` or
    :class:`InvalidContainerArgsError` — chosen by ``field`` — on any shape
    violation, and :class:`ContainerOverrideSizeLimitExceededError` when a cap
    is exceeded, so the offending field is unambiguous in the error
    (US4 Scenario 3). ``component_name`` is threaded into the error metadata
    when the caller knows it (the mutation boundary does; the Pydantic field
    validator does not).

    Accepts ``value: Any`` because it runs as a Pydantic ``mode="before"``
    field validator (so it sees the raw, un-coerced input and rejects a
    non-list / non-string element with the typed error rather than letting
    Pydantic's ``list[str]`` coercion fail first into a generic
    ``ValidationError``) as well as a pre-Pydantic dict check at the mutation
    boundary.
    """
    if value is None:
        return None
    # ``bool`` is a subclass of ``int`` (not ``str``) and ``str`` itself is an
    # iterable — guard the container type first so a bare string is rejected
    # as "not a list" rather than silently iterated into characters.
    if not isinstance(value, list):
        _raise(
            field,
            component_name,
            f"expected a list of strings, got {type(value).__name__}",
        )
    if len(value) == 0:
        _raise(
            field,
            component_name,
            "an empty list is not allowed; clear by omitting the field "
            "(null), never []",
        )
    for element in value:
        if not isinstance(element, str):
            _raise(
                field,
                component_name,
                f"every element must be a string; got {type(element).__name__}",
            )
    # Size caps — every element is now known to be a ``str`` so ``.encode`` is
    # safe. Element-count first (cheap), then the serialised-byte budget.
    if len(value) > CONTAINER_OVERRIDE_MAX_ELEMENTS:
        raise ContainerOverrideSizeLimitExceededError(
            field=field,
            component_name=component_name,
            elements=len(value),
            cap=CONTAINER_OVERRIDE_MAX_ELEMENTS,
        )
    total_bytes = sum(len(element.encode("utf-8")) for element in value)
    if total_bytes > CONTAINER_OVERRIDE_BYTE_CAP:
        raise ContainerOverrideSizeLimitExceededError(
            field=field,
            component_name=component_name,
            bytes=total_bytes,
            cap=CONTAINER_OVERRIDE_BYTE_CAP,
        )
    return value
