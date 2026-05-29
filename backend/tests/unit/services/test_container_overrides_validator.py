"""Unit tests for :func:`validate_container_override` (014, US1 happy paths).

US4 negative paths (empty list, non-string element) are added by the US4 phase
(see ``contracts/errors.md`` / data-model.md §6). This module covers the
accept-side: ``None`` passes through, valid lists are returned verbatim, and
empty-string elements are accepted (FR-006).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from styrmin_backend.context.models.components import (
    ResolvedComponentContainerOverride,
)
from styrmin_backend.context.models.config import (
    ComponentConfigBlock,
    DeploymentConfig,
)
from styrmin_backend.services.container_overrides.exceptions import (
    ContainerOverrideSizeLimitExceededError,
    InvalidContainerArgsError,
    InvalidContainerCommandError,
)
from styrmin_backend.services.container_overrides.validator import (
    CONTAINER_OVERRIDE_BYTE_CAP,
    CONTAINER_OVERRIDE_MAX_ELEMENTS,
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


# ---------------------------------------------------------------------------
# Size caps (mirrors env-vars FR-008 — keeps the deployment CRD under the
# Kubernetes resource size limit)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["command", "args"])
def test_list_at_element_cap_accepted(field: str) -> None:
    """A list exactly at the element-count cap is accepted (boundary)."""
    value = ["x"] * CONTAINER_OVERRIDE_MAX_ELEMENTS
    assert validate_container_override(field, value) == value


@pytest.mark.parametrize("field", ["command", "args"])
def test_list_over_element_cap_rejected(field: str) -> None:
    """One element past the cap raises the size error with element metadata."""
    value = ["x"] * (CONTAINER_OVERRIDE_MAX_ELEMENTS + 1)
    with pytest.raises(ContainerOverrideSizeLimitExceededError) as exc:
        validate_container_override(field, value, component_name="server")
    meta = exc.value.error_metadata
    assert meta["field"] == field
    assert meta["component_name"] == "server"
    assert meta["elements"] == CONTAINER_OVERRIDE_MAX_ELEMENTS + 1
    assert meta["cap"] == CONTAINER_OVERRIDE_MAX_ELEMENTS
    assert exc.value.error_code == "CONTAINER_OVERRIDE_SIZE_LIMIT_EXCEEDED"


@pytest.mark.parametrize("field", ["command", "args"])
def test_list_over_byte_cap_rejected(field: str) -> None:
    """A single element whose UTF-8 size exceeds the byte cap is rejected with
    byte metadata (element count alone is under the element cap)."""
    value = ["a" * (CONTAINER_OVERRIDE_BYTE_CAP + 1)]
    with pytest.raises(ContainerOverrideSizeLimitExceededError) as exc:
        validate_container_override(field, value, component_name="server")
    meta = exc.value.error_metadata
    assert meta["field"] == field
    assert meta["bytes"] == CONTAINER_OVERRIDE_BYTE_CAP + 1
    assert meta["cap"] == CONTAINER_OVERRIDE_BYTE_CAP
    # The element-count branch did not fire (single element well under 1024).
    assert "elements" not in meta


@pytest.mark.parametrize("field", ["command", "args"])
def test_multibyte_chars_counted_as_utf8_bytes(field: str) -> None:
    """The byte cap counts UTF-8 bytes, not characters: a list of multi-byte
    characters whose byte length exceeds the cap is rejected even though its
    character count and element count are small."""
    # "€" is 3 UTF-8 bytes; build a value whose byte size trips the cap.
    char_count = CONTAINER_OVERRIDE_BYTE_CAP // 3 + 1
    value = ["€" * char_count]
    with pytest.raises(ContainerOverrideSizeLimitExceededError) as exc:
        validate_container_override(field, value)
    assert exc.value.error_metadata["bytes"] > CONTAINER_OVERRIDE_BYTE_CAP


# ---------------------------------------------------------------------------
# Model-level enforcement (read/CRD path). The ``ComponentConfigBlock`` field
# validators run ``mode="before"`` so a non-list / non-string element raises
# the typed error directly (a ``ServiceError``, propagated un-wrapped by
# Pydantic v2) instead of Pydantic's ``list[str]`` coercion failing first into
# a generic ``ValidationError`` — symmetry with the write-boundary
# pre-validator on every path that builds the model (errors HIGH-1).
# ---------------------------------------------------------------------------


class TestModelLevelEnforcement:
    @pytest.mark.parametrize("field", ["command", "args"])
    @pytest.mark.parametrize("bad", [[], [123], "notalist", [None], [True]])
    def test_component_config_block_surfaces_typed_error(
        self, field: str, bad: object
    ) -> None:
        with pytest.raises(_EXPECTED_ERROR[field]):
            ComponentConfigBlock.model_validate({field: bad})

    @pytest.mark.parametrize("field", ["command", "args"])
    @pytest.mark.parametrize("bad", [[], [123], "notalist"])
    def test_deployment_config_read_path_surfaces_typed_error(
        self, field: str, bad: object
    ) -> None:
        """``DeploymentConfig.model_validate`` is the read/CRD entry point used
        by ``_validate_env_section``; the typed code must survive here too."""
        with pytest.raises(_EXPECTED_ERROR[field]):
            DeploymentConfig.model_validate({"components": {"server": {field: bad}}})

    @pytest.mark.parametrize("field", ["command", "args"])
    def test_valid_block_round_trips(self, field: str) -> None:
        block = ComponentConfigBlock.model_validate({field: ["sh", "-c", ""]})
        assert getattr(block, field) == ["sh", "-c", ""]


class TestResolvedOverrideRejectsEmptyList:
    """``ResolvedComponentContainerOverride`` makes the "no empty list"
    invariant local to the type so a direct-construction caller cannot smuggle
    an ``[]`` to the renderer (types-review item 1)."""

    @pytest.mark.parametrize("field", ["command", "args"])
    def test_empty_list_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError, match="non-empty list or None"):
            ResolvedComponentContainerOverride(**{field: []})

    def test_none_and_nonempty_accepted(self) -> None:
        assert ResolvedComponentContainerOverride().command is None
        assert ResolvedComponentContainerOverride(command=["serve"]).command == [
            "serve"
        ]
        # Empty-string elements remain valid (non-empty list).
        assert ResolvedComponentContainerOverride(args=[""]).args == [""]
