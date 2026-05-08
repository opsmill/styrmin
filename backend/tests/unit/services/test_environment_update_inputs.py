"""Unit tests for ``UpdateEnvironmentInput`` conversion helpers (009 / US2).

Phase-1 placeholder so the file is wired into pytest collection. Real
input-conversion tests land in T040.
"""

from __future__ import annotations

from styrmin_backend.api.definitions.environment.inputs import (
    UpdateEnvironmentInput,
)


def test_update_environment_input_class_is_importable() -> None:
    """The placeholder class exists and can be referenced."""
    assert UpdateEnvironmentInput is not None
