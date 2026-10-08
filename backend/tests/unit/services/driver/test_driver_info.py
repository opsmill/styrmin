"""Unit tests for ``spec.info.icon`` and ``spec.info.links`` validation (020 / US3).

``icon`` and each ``links[].url`` must be absolute ``http``/``https`` URLs, and
each ``links`` entry has exactly ``link`` and ``url`` (FR-003, FR-004). The
Pydantic error names the field path, which the loader passes on unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from styrmin_backend.services.driver.exceptions import DriverLoadingError
from styrmin_backend.services.driver.loaders import get_local_driver_loader
from styrmin_backend.services.driver.models.resources.driver import DriverSpec


def _driver_spec(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "apiVersion": "styrmin.io/v1",
        "kind": "ApplicationDriver",
        "metadata": {"name": "info-validation"},
        "spec": {
            "version": "0.1.0",
            "supported_versions": ">=0.1,<1.0",
            "info": info,
            "helm": {"main": {"location": "./src/helm", "version": "0.1.0"}},
        },
    }


@pytest.mark.parametrize(
    "icon",
    ["https://example.com/logo.svg", "http://example.com/logo.png"],
    ids=["https-svg", "http-png"],
)
def test_valid_icon_builds_driver_spec(icon: str) -> None:
    spec = DriverSpec.model_validate(_driver_spec({"icon": icon}))

    assert str(spec.spec.info.icon) == icon


@pytest.mark.parametrize(
    ("icon", "reason"),
    [
        ("xxxx", "Input should be a valid URL"),
        ("logo.svg", "Input should be a valid URL"),
        ("javascript:alert(1)", "URL scheme should be 'http' or 'https'"),
        ("data:image/png;base64,AAAA", "URL scheme should be 'http' or 'https'"),
        ("ftp://host/logo.png", "URL scheme should be 'http' or 'https'"),
    ],
    ids=["placeholder", "relative-path", "javascript", "data-uri", "ftp"],
)
def test_invalid_icon_names_the_field(icon: str, reason: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        DriverSpec.model_validate(_driver_spec({"icon": icon}))

    message = str(exc_info.value)
    assert "spec.info.icon" in message
    assert reason in message


@pytest.mark.parametrize(
    ("link", "location", "reason"),
    [
        ({"link": "Docs"}, "spec.info.links.0.url", "Field required"),
        (
            {"link": "Docs", "url": "https://example.com", "name": "x"},
            "spec.info.links.0.name",
            "Extra inputs are not permitted",
        ),
        (
            {"link": "Docs", "url": "javascript:x"},
            "spec.info.links.0.url",
            "URL scheme should be 'http' or 'https'",
        ),
        (
            {"link": "Docs", "url": "not-a-url"},
            "spec.info.links.0.url",
            "Input should be a valid URL",
        ),
    ],
    ids=["missing-url", "extra-key", "javascript-url", "not-a-url"],
)
def test_invalid_link_names_the_entry(
    link: dict[str, str], location: str, reason: str
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        DriverSpec.model_validate(_driver_spec({"links": [link]}))

    message = str(exc_info.value)
    assert "spec.info.links.0" in message
    assert location in message
    assert reason in message


def test_loader_rejects_placeholder_icon_with_field_path(tmp_path: Path) -> None:
    (tmp_path / "driver.styrmin.yml").write_text(
        yaml.safe_dump(_driver_spec({"icon": "xxxx"}))
    )
    (tmp_path / "values.j2.yml").write_text("{}\n")

    with pytest.raises(DriverLoadingError) as exc_info:
        get_local_driver_loader(path=str(tmp_path)).load_driver()

    assert "spec.info.icon" in str(exc_info.value)
