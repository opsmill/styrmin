"""Tests for shared CLI validators and type aliases."""

from __future__ import annotations

from pathlib import Path

import pytest
from styrminctl.cli import app
from styrminctl.types import validate_directory_exists, validate_positive, validate_uuid


def test_validate_uuid_valid_v4() -> None:
    validate_uuid(str, "550e8400-e29b-41d4-a716-446655440000")


def test_validate_uuid_valid_no_hyphens() -> None:
    validate_uuid(str, "550e8400e29b41d4a716446655440000")


def test_validate_uuid_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid UUID"):
        validate_uuid(str, "not-a-uuid")


def test_validate_uuid_empty_string() -> None:
    with pytest.raises(ValueError, match="Invalid UUID"):
        validate_uuid(str, "")


def test_validate_uuid_none_passes() -> None:
    validate_uuid(str, None)


def test_validate_positive_none_passes() -> None:
    validate_positive(float, None)


def test_validate_positive_valid() -> None:
    validate_positive(float, 5.0)


def test_validate_positive_zero_raises() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        validate_positive(float, 0)


def test_validate_positive_negative_raises() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        validate_positive(float, -1)


def test_validate_directory_exists_none_passes() -> None:
    validate_directory_exists(str, None)


def test_validate_directory_exists_valid(tmp_path: Path) -> None:
    validate_directory_exists(str, str(tmp_path))


def test_validate_directory_exists_nonexistent() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        validate_directory_exists(str, "/nonexistent/path/abc123")


def test_validate_directory_exists_file(tmp_path: Path) -> None:
    f = tmp_path / "somefile.txt"
    f.write_text("hello")
    with pytest.raises(ValueError, match="not a directory"):
        validate_directory_exists(str, str(f))


def test_invalid_uuid_cli_error(capsys: pytest.CaptureFixture[str]) -> None:
    """Integration test: invalid UUID on CLI produces error exit."""
    with pytest.raises(SystemExit) as exc:
        app(["clusters", "get", "not-a-uuid"])
    assert exc.value.code != 0
