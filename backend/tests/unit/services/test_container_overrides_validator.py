"""Unit tests for :func:`validate_container_override` (014, US1 happy paths).

US4 negative paths (empty list, non-string element) are added by the US4 phase
(see ``contracts/errors.md`` / data-model.md §6). This module covers the
accept-side: ``None`` passes through, valid lists are returned verbatim, and
empty-string elements are accepted (FR-006).
"""

from __future__ import annotations

import pytest

from styrmin_backend.services.container_overrides.exceptions import (
    InvalidContainerArgsError,
    InvalidContainerCommandError,
)
from styrmin_backend.services.container_overrides.validator import (
    validate_container_override,
)


@pytest.mark.parametrize("field", ["command", "args"])
def test_none_passes_through(field: str) -> None:
    """``None`` means "unset"/"clear" and is always accepted (FR-007)."""
    assert validate_container_override(field, None) is None


@pytest.mark.parametrize("field", ["command", "args"])
def test_valid_list_returned_verbatim(field: str) -> None:
    """A non-empty list of strings is returned unchanged (FR-014 verbatim)."""
    value = ["uvicorn", "simple_app.main:app", "--port", "8000"]
    assert validate_container_override(field, value) == value


@pytest.mark.parametrize("field", ["command", "args"])
def test_single_element_accepted(field: str) -> None:
    assert validate_container_override(field, ["serve"]) == ["serve"]


@pytest.mark.parametrize("field", ["command", "args"])
def test_empty_string_element_accepted(field: str) -> None:
    """``["sh", "-c", ""]`` is valid — empty-string elements are allowed,
    mirroring Kubernetes (FR-006, US4 Sc.4).
    """
    value = ["sh", "-c", ""]
    assert validate_container_override(field, value) == value


# ---------------------------------------------------------------------------
# US4 negative paths (data-model.md §6 table)
# ---------------------------------------------------------------------------

_EXPECTED_ERROR = {
    "command": InvalidContainerCommandError,
    "args": InvalidContainerArgsError,
}


@pytest.mark.parametrize("field", ["command", "args"])
def test_empty_list_rejected(field: str) -> None:
    """``[]`` is rejected with the per-field typed error (FR-006, US4 Sc.2)."""
    with pytest.raises(_EXPECTED_ERROR[field]) as exc:
        validate_container_override(field, [], component_name="server")
    assert exc.value.error_metadata["field"] == field
    assert exc.value.error_metadata["component_name"] == "server"


@pytest.mark.parametrize("field", ["command", "args"])
@pytest.mark.parametrize("value", [[123], ["ok", 5], [None], [True]])
def test_non_string_element_rejected(field: str, value: list) -> None:
    """A non-string element raises the per-field typed error (US4 Sc.3)."""
    with pytest.raises(_EXPECTED_ERROR[field]):
        validate_container_override(field, value, component_name="server")


@pytest.mark.parametrize("field", ["command", "args"])
def test_non_list_rejected(field: str) -> None:
    """A bare string (not a list) is rejected — guards against character
    iteration."""
    with pytest.raises(_EXPECTED_ERROR[field]):
        validate_container_override(field, "uvicorn")  # type: ignore[arg-type]


def test_field_selects_error_class() -> None:
    """``field`` chooses the error class so the offending slot is unambiguous
    (US4 Sc.3)."""
    with pytest.raises(InvalidContainerCommandError):
        validate_container_override("command", [])
    with pytest.raises(InvalidContainerArgsError):
        validate_container_override("args", [])
