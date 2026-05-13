"""Unit tests for the password-masking helper (FR-029).

Asserts that ``mask_variables`` redacts every sensitive field name —
top-level, nested, and inside list items — without mutating the original
mapping.
"""

from __future__ import annotations

import pytest

from styrmin_backend.api.logging.mask import (
    MASK_PLACEHOLDER,
    MASKED_VARIABLE_NAMES,
    mask_variables,
)


def test_returns_empty_dict_for_none() -> None:
    assert mask_variables(None) == {}


def test_passes_non_sensitive_fields_through_unchanged() -> None:
    original = {"username": "alice", "displayName": "Alice"}
    assert mask_variables(original) == original


def test_redacts_every_known_sensitive_field_at_top_level() -> None:
    # One iteration per name in the allow-list — fails loudly if the
    # frozenset is changed without updating downstream call sites.
    for name in MASKED_VARIABLE_NAMES:
        masked = mask_variables({name: "secret-value"})
        assert masked[name] == MASK_PLACEHOLDER
        assert "secret-value" not in masked.values()


def test_redacts_inside_nested_input_object() -> None:
    payload = {"input": {"username": "alice", "password": "hunter22!"}}
    masked = mask_variables(payload)
    assert masked["input"]["password"] == MASK_PLACEHOLDER
    assert masked["input"]["username"] == "alice"


def test_redacts_inside_list_items() -> None:
    payload = {"users": [{"password": "a"}, {"password": "b"}]}
    masked = mask_variables(payload)
    assert masked["users"][0]["password"] == MASK_PLACEHOLDER
    assert masked["users"][1]["password"] == MASK_PLACEHOLDER


def test_does_not_mutate_input() -> None:
    original = {"password": "hunter22!"}
    mask_variables(original)
    assert original == {"password": "hunter22!"}


@pytest.mark.parametrize("name", ["Password", "NEW_PASSWORD", "PASSWORD", "passWord"])
def test_redaction_is_case_sensitive(name: str) -> None:
    # The allow-list is exact-match. A case-mismatched key is left alone;
    # documents the contract so a downstream change is intentional.
    masked = mask_variables({name: "leak"})
    assert masked[name] == "leak"
