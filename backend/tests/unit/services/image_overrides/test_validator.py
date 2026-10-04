"""Unit tests for write-time image override validation (018, T059).

Both helpers read the raw config dict, ahead of ``DeploymentConfig`` construction, so the typed
errors name the component (research D-008).
"""

from __future__ import annotations

from typing import Any

import pytest

from styrmin_backend.services.image_overrides.exceptions import (
    InvalidImageReferenceError,
    UnknownComponentImageOverrideError,
)
from styrmin_backend.services.image_overrides.validator import (
    prevalidate_image_overrides,
    validate_image_override_targets,
)

PATCHED = "registry.example/acme/simple-app-patched"
TOKEN_REFERENCE = f"{PATCHED}:{{{{ app.version }}}}"


@pytest.mark.parametrize(
    "config",
    [
        None,
        {},
        {"components": None},
        {"components": {"ghost": None}},
        {"components": {"ghost": {"image": None}}},
        {"components": {"ghost": {"env_vars": {"A": "1"}, "args": ["--x"]}}},
        {"components": {"server": {"image": f"{PATCHED}:1"}}},
    ],
    ids=[
        "no-config",
        "no-components",
        "components-null",
        "block-null",
        "image-null",
        "block-without-image",
        "known-component",
    ],
)
def test_validate_image_override_targets_accepts(config: dict[str, Any] | None) -> None:
    validate_image_override_targets(config, ["server", "worker"])


def test_validate_image_override_targets_rejects_unknown_component() -> None:
    config = {
        "components": {"server": {"image": f"{PATCHED}:1"}, "ghost": {"image": "App"}}
    }

    with pytest.raises(UnknownComponentImageOverrideError) as exc_info:
        validate_image_override_targets(config, ["worker", "server"])

    assert exc_info.value.error_metadata == {
        "component_name": "ghost",
        "known_components": ["server", "worker"],
    }


def test_prevalidate_image_overrides_accepts_valid_and_null_references() -> None:
    config = {
        "components": {
            "server": {"image": TOKEN_REFERENCE},
            "worker": {"image": None},
            "db": {"args": ["--x"]},
        }
    }

    prevalidate_image_overrides(config, version="1.0.0")
    prevalidate_image_overrides(None, version="1.0.0")


@pytest.mark.parametrize(
    ("reference", "version", "reason", "application_version"),
    [
        ("App:1", "1.0.0", "grammar", None),
        ("", "1.0.0", "grammar", None),
        (PATCHED, "1.0.0", "missing_tag_or_digest", None),
        (f"{PATCHED}:{{{{ app.name }}}}", "1.0.0", "template_expression", None),
        (TOKEN_REFERENCE, "1.1.0+build", "after_substitution", "1.1.0+build"),
    ],
    ids=[
        "grammar",
        "empty-string",
        "missing-tag-or-digest",
        "template-expression",
        "after-substitution",
    ],
)
def test_prevalidate_image_overrides_names_the_component(
    reference: str, version: str, reason: str, application_version: str | None
) -> None:
    config = {
        "components": {
            "server": {"image": f"{PATCHED}:1"},
            "worker": {"image": reference},
        }
    }

    with pytest.raises(InvalidImageReferenceError) as exc_info:
        prevalidate_image_overrides(config, version=version)

    assert exc_info.value.error_metadata == {
        "component_name": "worker",
        "reference": reference,
        "reason": reason,
        "application_version": application_version,
    }
    assert "'worker'" in str(exc_info.value)


def test_prevalidate_image_overrides_rejects_non_string_reference() -> None:
    with pytest.raises(InvalidImageReferenceError) as exc_info:
        prevalidate_image_overrides(
            {"components": {"server": {"image": 7}}}, version="1.0.0"
        )

    assert exc_info.value.reason == "grammar"
    assert exc_info.value.component_name == "server"
