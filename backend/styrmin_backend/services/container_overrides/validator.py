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
* Values pass through verbatim — no templating/expansion (FR-014).
"""

from __future__ import annotations

from typing import Literal

from styrmin_backend.services.container_overrides.exceptions import (
    InvalidContainerArgsError,
    InvalidContainerCommandError,
)

ContainerOverrideField = Literal["command", "args"]


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
    value: list[str] | None,
    component_name: str | None = None,
) -> list[str] | None:
    """Validate a single ``command``/``args`` override list.

    Returns the value unchanged on success (``None`` passes straight through as
    "unset"). Raises :class:`InvalidContainerCommandError` or
    :class:`InvalidContainerArgsError` — chosen by ``field`` — on any shape
    violation, so the offending field is unambiguous in the error
    (US4 Scenario 3). ``component_name`` is threaded into the error metadata
    when the caller knows it (the mutation boundary does; the Pydantic field
    validator does not).
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
    return value
