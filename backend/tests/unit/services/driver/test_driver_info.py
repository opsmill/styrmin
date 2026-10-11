"""Unit tests for ``spec.info.icon`` and ``spec.info.links`` validation (020 / US3).

``icon`` must be an absolute ``https`` URL and each ``links[].url`` an absolute
``http``/``https`` URL, neither with a username or password; each ``links``
entry has exactly ``link`` and ``url``. An invalid value does not fail the
load: it is left out and named in ``Info.warnings``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

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


def test_valid_icon_builds_driver_spec_without_warnings() -> None:
    icon = "https://example.com/logo.svg"
    info = DriverSpec.model_validate(_driver_spec({"icon": icon})).spec.info

    assert str(info.icon) == icon
    assert info.warnings == []


@pytest.mark.parametrize(
    "icon",
    [
        "xxxx",
        "logo.svg",
        "javascript:alert(1)",
        "data:image/png;base64,AAAA",
        "ftp://host/logo.png",
        "http://example.com/logo.png",
        42,
    ],
    ids=[
        "placeholder",
        "relative-path",
        "javascript",
        "data-uri",
        "ftp",
        "http",
        "number",
    ],
)
def test_invalid_icon_is_dropped_with_a_warning(icon: object) -> None:
    info = DriverSpec.model_validate(_driver_spec({"icon": icon})).spec.info

    assert info.icon is None
    assert info.warnings == [
        "spec.info.icon must be an absolute https URL, such as "
        f"https://example.com/logo.svg (found {icon!r}). The icon was not stored."
    ]


def test_icon_with_credentials_is_dropped_without_repeating_them() -> None:
    info = DriverSpec.model_validate(
        _driver_spec({"icon": "https://user:secret@example.com/logo.svg"})
    ).spec.info

    assert info.icon is None
    assert info.warnings == [
        "spec.info.icon must not contain a username or password. The icon was not stored."
    ]


@pytest.mark.parametrize(
    ("link", "problem"),
    [
        ({"link": "Docs"}, "spec.info.links[1] is missing the `url` key"),
        ({}, "spec.info.links[1] is missing the `link` and `url` keys"),
        (
            {"link": "Docs", "url": "https://example.com", "name": "x"},
            "spec.info.links[1] has keys other than `link` and `url`: name",
        ),
        ("Docs", "spec.info.links[1] must be a mapping with `link` and `url` keys"),
        (
            {"link": 3, "url": "https://example.com"},
            "spec.info.links[1].link must be text (found 3)",
        ),
        (
            {"link": "Docs", "url": "javascript:x"},
            "spec.info.links[1].url must be an absolute http or https URL, such as "
            "https://example.com/docs (found 'javascript:x')",
        ),
        (
            {"link": "Docs", "url": "https://user:secret@example.com"},
            "spec.info.links[1].url must not contain a username or password",
        ),
    ],
    ids=[
        "missing-url",
        "missing-both",
        "extra-key",
        "not-a-mapping",
        "label-not-text",
        "javascript-url",
        "credentials",
    ],
)
def test_invalid_link_is_dropped_and_the_others_kept(
    link: object, problem: str
) -> None:
    valid = {"link": "Homepage", "url": "http://example.com/home"}
    info = DriverSpec.model_validate(_driver_spec({"links": [valid, link]})).spec.info

    assert [entry.model_dump(mode="json") for entry in info.links or []] == [valid]
    assert info.warnings == [f"{problem}. The link was not stored."]


def test_links_that_are_not_a_list_are_dropped_with_a_warning() -> None:
    info = DriverSpec.model_validate(_driver_spec({"links": "https://x"})).spec.info

    assert info.links is None
    assert info.warnings == [
        "spec.info.links must be a list of entries with `link` and `url` keys "
        "(found str). The links were not stored."
    ]


def _write_driver(directory: Path, info: dict[str, Any]) -> None:
    (directory / "driver.styrmin.yml").write_text(yaml.safe_dump(_driver_spec(info)))
    (directory / "values.j2.yml").write_text("{}\n")


def test_loader_loads_placeholder_icon_and_reports_it(tmp_path: Path) -> None:
    _write_driver(tmp_path, {"icon": "xxxx"})

    driver = get_local_driver_loader(path=str(tmp_path)).load_driver()

    info = driver.driver_spec.spec.info
    assert info.icon is None
    assert len(info.warnings) == 1
    assert info.warnings[0].startswith("spec.info.icon must be an absolute https URL")


def test_loader_error_lists_one_line_per_invalid_field(tmp_path: Path) -> None:
    _write_driver(tmp_path, {"license": 1, "authors": "fatih"})

    with pytest.raises(DriverLoadingError) as exc_info:
        get_local_driver_loader(path=str(tmp_path)).load_driver()

    message = str(exc_info.value)
    assert message.endswith(
        "The driver specification is invalid:\n"
        "- spec.info.authors: Input should be a valid list (found 'fatih')\n"
        "- spec.info.license: Input should be a valid string (found 1)"
    )
    assert "errors.pydantic.dev" not in message
