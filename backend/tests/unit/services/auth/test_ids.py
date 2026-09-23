"""Unit tests for :func:`parse_uuid_list` (issue #351)."""

from __future__ import annotations

from uuid import UUID

import pytest

from styrmin_backend.services.auth.ids import parse_uuid_list
from styrmin_backend.services.exceptions import ValidationError

_VALID = "11111111-1111-1111-1111-111111111111"


def test_none_passes_through() -> None:
    assert parse_uuid_list(None, field="groupIds") is None


def test_empty_list_passes_through() -> None:
    assert parse_uuid_list([], field="groupIds") == []


def test_valid_ids_are_parsed() -> None:
    assert parse_uuid_list([_VALID], field="groupIds") == [UUID(_VALID)]


def test_uppercase_uuid_is_accepted() -> None:
    assert parse_uuid_list([_VALID.upper()], field="groupIds") == [UUID(_VALID)]


def test_duplicate_ids_are_preserved() -> None:
    assert parse_uuid_list([_VALID, _VALID], field="groupIds") == [
        UUID(_VALID),
        UUID(_VALID),
    ]


def test_empty_string_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_uuid_list([""], field="groupIds")


def test_malformed_id_raises_validation_error() -> None:
    with pytest.raises(ValidationError) as excinfo:
        parse_uuid_list(["not-a-uuid"], field="groupIds")

    assert excinfo.value.error_code == "VALIDATION_ERROR"
    message = str(excinfo.value)
    assert "groupIds" in message
    assert "not-a-uuid" in message


def test_every_malformed_entry_is_reported() -> None:
    with pytest.raises(ValidationError) as excinfo:
        parse_uuid_list(["bad-one", _VALID, "bad-two"], field="memberIds")

    message = str(excinfo.value)
    assert "memberIds" in message
    assert "bad-one" in message
    assert "bad-two" in message
