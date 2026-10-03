"""Every in-repo example driver declares its component containers (017 / FR-008, SC-002).

Styrmin injects env vars by post-render patch into each component's declared
container, so an example driver that omits one, or still wires env vars through
the retired ``component_env_vars`` filter, would silently drop user env vars.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from styrmin_backend.services.driver.loaders import get_local_driver_loader
from styrmin_backend.services.driver.models.resources.driver import DriverSpec

_EXAMPLES_DIR = Path(__file__).resolve().parents[5] / "driver" / "examples"
_DRIVER_DIRS = sorted(p for p in _EXAMPLES_DIR.iterdir() if p.is_dir())

# Mirrors specs/017-post-render-env-vars/driver-containers.md, verified by
# `helm template` of each pinned chart with the driver's own values.
_EXPECTED_CONTAINERS: dict[str, dict[str, str]] = {
    "simple-app": {"server": "simple-app", "database": "postgresql"},
    "db-test": {"server": "db-test", "mariadb": "mariadb", "mongodb": "mongodb"},
    "infrahub": {
        "server": "infrahub-server",
        "task-worker": "infrahub-task-worker",
        "database": "neo4j",
        "cache": "redis",
        "message-queue": "rabbitmq",
        "task-manager": "prefect-server",
        "task-manager-db": "postgresql",
    },
    "infrahub-enterprise": {
        "server": "infrahub-server",
        "task-worker": "infrahub-task-worker",
        "database": "neo4j",
        "cache": "redis",
        "message-queue": "rabbitmq",
        "task-manager": "prefect-server",
        "task-manager-db": "postgresql",
    },
    "infrahub-mcp": {"server": "infrahub-mcp"},
    "semaphore": {"server": "semaphore", "database": "postgresql"},
    "slurpit": {
        "portal": "slurpit-portal",
        "warehouse": "styrmin-slurpit-warehouse",
        "scanner": "slurpit-scanner",
        "scraper": "slurpit-scraper",
        "mariadb": "slurpit-mariadb",
        "mongodb": "styrmin-slurpit-mongodb",
    },
}


def _declared_containers(driver_dir: Path) -> dict[str, str | None]:
    driver = get_local_driver_loader(path=str(driver_dir)).load_driver()
    assert isinstance(driver.driver_spec, DriverSpec)
    components = driver.driver_spec.spec.components
    assert components is not None, f"{driver_dir.name} declares no components"
    return {name: component.container for name, component in components.root.items()}


def test_expected_mapping_covers_existing_drivers() -> None:
    assert set(_EXPECTED_CONTAINERS) == {p.name for p in _DRIVER_DIRS}


@pytest.mark.parametrize("driver_dir", _DRIVER_DIRS, ids=lambda p: p.name)
def test_every_component_declares_container(driver_dir: Path) -> None:
    containers = _declared_containers(driver_dir)

    missing = sorted(name for name, container in containers.items() if not container)
    assert not missing, f"{driver_dir.name}: components without a container: {missing}"
    assert containers == _EXPECTED_CONTAINERS[driver_dir.name]


@pytest.mark.parametrize("driver_dir", _DRIVER_DIRS, ids=lambda p: p.name)
def test_values_template_does_not_use_component_env_vars(driver_dir: Path) -> None:
    template = (driver_dir / "values.j2.yml").read_text()

    assert "component_env_vars" not in template
