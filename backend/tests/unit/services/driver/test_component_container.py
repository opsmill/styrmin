"""Unit tests for the driver-side component container field (017 / FR-001).

``spec.components.<name>.container`` is optional; a malformed Kubernetes
container name fails driver registration with an error naming the component.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from styrmin_backend.services.driver.exceptions import DriverLoadingError
from styrmin_backend.services.driver.loaders import get_local_driver_loader
from styrmin_backend.services.driver.models.resources.driver import DriverSpec


def _driver_spec(server: dict[str, Any]) -> dict[str, Any]:
    return {
        "apiVersion": "styrmin.io/v1",
        "kind": "ApplicationDriver",
        "metadata": {"name": "simple-app"},
        "spec": {
            "version": "0.1.0",
            "supported_versions": ">=0.1,<1.0",
            "info": {"description": "Container field fixture"},
            "helm": {"main": {"location": "./src/helm", "version": "0.1.0"}},
            "components": {
                "server": server,
                "database": {
                    "identifier": {"label": {"app.kubernetes.io/name": "postgresql"}},
                },
            },
        },
    }


def _server(**extra: Any) -> dict[str, Any]:
    return {"identifier": {"label": {"app.kubernetes.io/name": "simple-app"}}, **extra}


def _load(tmp_path: Path, spec: dict[str, Any]) -> DriverSpec:
    """Register-path load: parse + deserialize + cross-field validation."""
    (tmp_path / "driver.styrmin.yml").write_text(yaml.safe_dump(spec))
    (tmp_path / "values.j2.yml").write_text("{}\n")
    driver = get_local_driver_loader(path=str(tmp_path)).load_driver()
    assert isinstance(driver.driver_spec, DriverSpec)
    return driver.driver_spec


def test_declared_container_loads_and_is_exposed(tmp_path: Path) -> None:
    spec = _load(tmp_path, _driver_spec(_server(container="simple-app")))

    assert spec.spec.components is not None
    assert spec.spec.components.root["server"].container == "simple-app"


def test_declared_container_is_persisted_in_component_definition(
    tmp_path: Path,
) -> None:
    # ``applications.py`` stores ``components.model_dump()`` as the
    # driver-version component definitions; the container must ride along.
    spec = _load(tmp_path, _driver_spec(_server(container="simple-app")))

    assert spec.spec.components is not None
    dumped = spec.spec.components.model_dump()
    assert dumped["server"]["container"] == "simple-app"
    assert dumped["database"]["container"] is None


def test_omitted_container_loads_as_none(tmp_path: Path) -> None:
    spec = _load(tmp_path, _driver_spec(_server()))

    assert spec.spec.components is not None
    assert spec.spec.components.root["server"].container is None
    assert spec.spec.components.root["database"].container is None


@pytest.mark.parametrize(
    "name",
    ["a", "simple-app", "a1-b2", "0db", "a" * 63],
    ids=["single-char", "simple-app", "alnum-dash", "leading-digit", "63-chars"],
)
def test_valid_container_names_accepted(tmp_path: Path, name: str) -> None:
    spec = _load(tmp_path, _driver_spec(_server(container=name)))

    assert spec.spec.components is not None
    assert spec.spec.components.root["server"].container == name


@pytest.mark.parametrize(
    "name",
    ["Simple_App", "-bad", "", "a" * 64],
    ids=["uppercase-underscore", "leading-dash", "empty", "64-chars"],
)
def test_malformed_container_fails_registration(tmp_path: Path, name: str) -> None:
    with pytest.raises(DriverLoadingError) as exc_info:
        _load(tmp_path, _driver_spec(_server(container=name)))

    message = str(exc_info.value)
    assert "components.server.container" in message
    assert "container name" in message
