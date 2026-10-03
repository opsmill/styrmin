"""Tests for the client-side ``{{ app.version }}`` token helpers (018, FR-008)."""

from __future__ import annotations

import re

import pytest
from styrmin_sdk.models import has_app_version_token, pinned_image_components
from styrmin_sdk.models.image_reference import APP_VERSION_TOKEN_RE


def test_token_regex_mirrors_the_backend_pattern() -> None:
    assert APP_VERSION_TOKEN_RE.pattern == r"\{\{\s*app\.version\s*\}\}"
    assert APP_VERSION_TOKEN_RE.flags & re.ASCII


@pytest.mark.parametrize(
    "reference",
    [
        "app:{{ app.version }}",
        "app:{{app.version}}",
        "app:{{   app.version   }}",
        "app:{{\tapp.version\n}}",
        "app:v{{ app.version }}-patched",
        "registry.example/acme/app-{{ app.version }}:stable",
    ],
)
def test_has_app_version_token_accepts_token(reference: str) -> None:
    assert has_app_version_token(reference) is True


@pytest.mark.parametrize(
    "reference",
    [
        "app:1.0.0",
        "registry.example/acme/app-patched:1.0.0",
        "app:{{ app.Version }}",
        "app:{{ app.name }}",
        "app:{{ app.version }",
        "app:{{\xa0app.version }}",
        "",
    ],
)
def test_has_app_version_token_rejects_non_token(reference: str) -> None:
    assert has_app_version_token(reference) is False


def test_pinned_image_components_lists_token_free_overrides_sorted() -> None:
    overrides = {
        "worker": "registry.example/acme/app:{{ app.version }}",
        "server": "registry.example/acme/app-patched:1.0.0",
        "api": None,
        "web": "",
        "alpha": "registry.example/acme/alpha@sha256:" + "a" * 64,
    }

    assert pinned_image_components(overrides) == ["alpha", "server"]


def test_pinned_image_components_empty_when_every_override_has_the_token() -> None:
    assert pinned_image_components({"server": "app:{{ app.version }}", "worker": None}) == []
    assert pinned_image_components({}) == []
