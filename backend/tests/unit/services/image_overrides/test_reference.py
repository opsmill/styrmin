"""Unit tests for image-reference validation and ``{{ app.version }}`` substitution (018, T003).

The grammar cases come from the vector file the frontend validator also reads, so the
two implementations cannot drift (research D-007).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from styrmin_backend.services.image_overrides.exceptions import (
    InvalidImageReferenceError,
    UnknownComponentImageOverrideError,
)
from styrmin_backend.services.image_overrides.reference import (
    APP_VERSION_TOKEN_RE,
    has_app_version_token,
    substitute_app_version,
    validate_reference,
    validate_stored_reference,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
VECTORS_PATH = REPO_ROOT / "frontend" / "src" / "lib" / "image-reference.vectors.json"
VECTORS: list[dict[str, Any]] = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
PLACEHOLDER_VERSION = "0"


def _vector_id(case: dict[str, Any]) -> str:
    return json.dumps(case["reference"])[:48]


VALID_VECTORS = [case for case in VECTORS if case["valid"]]
INVALID_VECTORS = [case for case in VECTORS if not case["valid"]]


def test_vectors_cover_every_grammar_reason() -> None:
    reasons = {case["reason"] for case in INVALID_VECTORS}
    assert reasons == {"grammar", "missing_tag_or_digest", "template_expression"}
    assert all("after_substitution" != case.get("reason") for case in VECTORS)


@pytest.mark.parametrize("case", VALID_VECTORS, ids=_vector_id)
def test_validate_reference_accepts_valid_vector(case: dict[str, Any]) -> None:
    resolved = validate_reference(case["reference"], version=PLACEHOLDER_VERSION)
    assert resolved == substitute_app_version(case["reference"], PLACEHOLDER_VERSION)


@pytest.mark.parametrize("case", INVALID_VECTORS, ids=_vector_id)
def test_validate_reference_rejects_invalid_vector(case: dict[str, Any]) -> None:
    with pytest.raises(InvalidImageReferenceError) as exc_info:
        validate_reference(case["reference"], version=PLACEHOLDER_VERSION)
    assert exc_info.value.reason == case["reason"]
    assert exc_info.value.error_metadata["reason"] == case["reason"]
    assert exc_info.value.error_metadata["reference"] == case["reference"]


@pytest.mark.parametrize("case", VALID_VECTORS, ids=_vector_id)
def test_validate_stored_reference_returns_stored_string(case: dict[str, Any]) -> None:
    assert validate_stored_reference(case["reference"]) == case["reference"]


@pytest.mark.parametrize("case", INVALID_VECTORS, ids=_vector_id)
def test_validate_stored_reference_rejects_invalid_vector(case: dict[str, Any]) -> None:
    with pytest.raises(InvalidImageReferenceError) as exc_info:
        validate_stored_reference(case["reference"])
    assert exc_info.value.reason == case["reason"]
    assert exc_info.value.error_metadata["application_version"] is None


def test_validate_stored_reference_resolves_token_with_placeholder() -> None:
    # "app:{{ app.version }}" is valid only because the placeholder "0" makes it "app:0".
    assert validate_stored_reference("app:{{ app.version }}") == "app:{{ app.version }}"
    with pytest.raises(InvalidImageReferenceError) as exc_info:
        validate_stored_reference("app@sha256:{{ app.version }}")
    assert exc_info.value.reason == "grammar"


def test_validate_stored_reference_passes_none_through() -> None:
    assert validate_stored_reference(None) is None


@pytest.mark.parametrize("value", [123, True, ["app:1"], {"image": "app:1"}])
def test_non_string_reference_is_rejected_as_grammar(value: object) -> None:
    with pytest.raises(InvalidImageReferenceError) as exc_info:
        validate_stored_reference(value)
    assert exc_info.value.reason == "grammar"
    assert type(value).__name__ in str(exc_info.value)

    with pytest.raises(InvalidImageReferenceError) as exc_info:
        validate_reference(value, version="1.0.0", component_name="server")
    assert exc_info.value.reason == "grammar"
    assert exc_info.value.error_metadata["component_name"] == "server"


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("app:{{ app.version }}", "app:1.2.3"),
        ("app:{{app.version}}", "app:1.2.3"),
        ("app:{{   app.version   }}", "app:1.2.3"),
        ("app:{{\tapp.version\n}}", "app:1.2.3"),
        (
            "r.example/{{ app.version }}/app:v{{app.version}}-x",
            "r.example/1.2.3/app:v1.2.3-x",
        ),
        ("app:1.0.0", "app:1.0.0"),
        ("app:{{ app.Version }}", "app:{{ app.Version }}"),
        ("app:{{ app.version }", "app:{{ app.version }"),
        ("app:{{ app.version }}", "app:{{ app.version }}"),
    ],
)
def test_substitute_app_version_replaces_every_token(
    reference: str, expected: str
) -> None:
    assert substitute_app_version(reference, "1.2.3") == expected


def test_substitute_app_version_inserts_version_literally() -> None:
    # A version is a replacement value, never a regex template (no group references).
    assert substitute_app_version("app:{{ app.version }}", r"\1\g<0>") == r"app:\1\g<0>"


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("app:{{ app.version }}", True),
        ("app:{{app.version}}", True),
        ("app:{{   app.version   }}", True),
        ("registry.example/acme/app-{{ app.version }}:stable", True),
        ("app:1.0.0", False),
        ("app:{{ app.name }}", False),
        ("app:{{ app.Version }}", False),
        ("app:{{ app.version }", False),
        ("app:{{ app.version }}", False),
    ],
)
def test_has_app_version_token(reference: str, expected: bool) -> None:  # noqa: FBT001
    assert has_app_version_token(reference) is expected
    assert (APP_VERSION_TOKEN_RE.search(reference) is not None) is expected


def test_validate_reference_returns_reference_resolved_with_real_version() -> None:
    resolved = validate_reference(
        "registry.example/acme/app:{{ app.version }}", version="0.2.0"
    )
    assert resolved == "registry.example/acme/app:0.2.0"


def test_validate_reference_reports_after_substitution() -> None:
    with pytest.raises(InvalidImageReferenceError) as exc_info:
        validate_reference(
            "app:{{ app.version }}", version="1.0.0+build", component_name="server"
        )
    error = exc_info.value
    assert error.error_code == "INVALID_IMAGE_REFERENCE"
    assert error.error_metadata == {
        "component_name": "server",
        "reference": "app:{{ app.version }}",
        "reason": "after_substitution",
        "application_version": "1.0.0+build",
    }
    assert "'server'" in str(error)
    assert '"app:1.0.0+build"' in str(error)
    assert '"1.0.0+build"' in str(error)


def test_version_introducing_template_markers_is_after_substitution() -> None:
    with pytest.raises(InvalidImageReferenceError) as exc_info:
        validate_reference("app:{{ app.version }}", version="{{x}}")
    assert exc_info.value.reason == "after_substitution"


def test_reference_invalid_with_any_version_keeps_its_own_reason() -> None:
    with pytest.raises(InvalidImageReferenceError) as exc_info:
        validate_reference("App:{{ app.version }}", version="1.0.0+build")
    assert exc_info.value.reason == "grammar"
    assert exc_info.value.error_metadata["application_version"] == "1.0.0+build"


def test_pinned_reference_ignores_the_version() -> None:
    assert validate_reference("app:1", version="1.0.0+build") == "app:1"
    with pytest.raises(InvalidImageReferenceError) as exc_info:
        validate_reference("App:1", version="1.0.0+build")
    assert exc_info.value.reason == "grammar"
    assert exc_info.value.error_metadata["application_version"] is None


def test_missing_tag_message_matches_contract() -> None:
    with pytest.raises(InvalidImageReferenceError) as exc_info:
        validate_reference(
            "registry.example/acme/app", version="1.0.0", component_name="server"
        )
    assert str(exc_info.value) == (
        "Image override for component 'server' is invalid: \"registry.example/acme/app\" has no "
        'tag or digest (add ":<tag>", "@sha256:<digest>", or ":{{ app.version }}").'
    )


@pytest.mark.parametrize(
    ("reference", "fragment"),
    [
        ("App:1", "is not a valid image reference"),
        ("app:{{ app.name }}", "only {{ app.version }} is substituted"),
    ],
)
def test_message_without_component_name(reference: str, fragment: str) -> None:
    with pytest.raises(InvalidImageReferenceError) as exc_info:
        validate_stored_reference(reference)
    message = str(exc_info.value)
    assert message.startswith("Image override is invalid: ")
    assert fragment in message
    assert exc_info.value.error_metadata["component_name"] is None


def test_unknown_component_image_override_error() -> None:
    error = UnknownComponentImageOverrideError(
        component_name="ghost", known_components=["server", "database"]
    )
    assert error.error_code == "UNKNOWN_COMPONENT_IMAGE_OVERRIDE"
    assert error.error_metadata == {
        "component_name": "ghost",
        "known_components": ["database", "server"],
    }
    assert "'ghost'" in str(error)
    assert "database, server" in str(error)


def test_unknown_component_image_override_error_without_components() -> None:
    error = UnknownComponentImageOverrideError(component_name="ghost")
    assert error.error_metadata == {"component_name": "ghost", "known_components": []}
    assert "declares no components" in str(error)


def test_message_escapes_control_characters() -> None:
    with pytest.raises(InvalidImageReferenceError) as exc_info:
        validate_stored_reference("app:1\n")
    assert '"app:1\\n"' in str(exc_info.value)
    assert exc_info.value.error_metadata["reference"] == "app:1\n"
