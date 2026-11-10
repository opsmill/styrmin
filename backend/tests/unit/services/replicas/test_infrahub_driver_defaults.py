"""The new infrahub driver versions keep every pod count (023 T042, SC-004).

``infrahub`` 5 and ``infrahub-enterprise`` 4 declare ``server.replicas`` and
``task-worker.replicas`` instead of the ``replicas_server`` and ``replicas_task_worker``
parameters of ``infrahub`` 4 and ``infrahub-enterprise`` 3 (kept in the functional test
fixtures). Each driver default must equal the old parameter default, and the values template
must no longer send a count to the chart, so the replica patch is the only source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
    SilentUndefined,
    get_jinja_environment,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
_EXAMPLES_DIR = _REPO_ROOT / "driver" / "examples"
_LEGACY_DIR = (
    _REPO_ROOT / "backend" / "tests" / "functional" / "fixtures" / "legacy_drivers"
)
_RETIRED = {"replicas_server": "server", "replicas_task_worker": "task-worker"}
_SINGLETONS = {"database", "task-manager-db", "cache"}


class _Driver(NamedTuple):
    name: str
    legacy_dir: str
    old_version: str
    new_version: str
    # Where the community chart's values sit in the rendered values.
    chart_root: tuple[str, ...]


_DRIVERS = [
    _Driver("infrahub", "infrahub-v4", "4", "6", ()),
    _Driver("infrahub-enterprise", "infrahub-enterprise-v3", "3", "5", ("infrahub",)),
]


def _spec(directory: Path) -> dict[str, Any]:
    return yaml.safe_load((directory / "driver.styrmin.yml").read_text())["spec"]


def _rendered_values(directory: Path) -> dict[str, Any]:
    template = (directory / "values.j2.yml").read_text()
    environment = get_jinja_environment(undefined=SilentUndefined)
    services = {
        name: {"primary_fqdn": "a.test", "human_readable_fqdn": "b.test"}
        for name in ("infrahub", "task-manager")
    }
    return yaml.safe_load(
        environment.from_string(template).render({"services": services})
    )


@pytest.mark.parametrize("driver", _DRIVERS, ids=lambda d: d.name)
def test_driver_defaults_equal_the_retired_parameter_defaults(driver: _Driver) -> None:
    old = _spec(_LEGACY_DIR / driver.legacy_dir)
    new = _spec(_EXAMPLES_DIR / driver.name)
    assert (old["version"], new["version"]) == (driver.old_version, driver.new_version)

    old_defaults = {p["name"]: p["default"] for p in old["parameters"]}
    new_defaults = {p["name"]: p["default"] for p in new["parameters"]}
    for parameter, component in _RETIRED.items():
        assert new["components"][component]["replicas"] == old_defaults[parameter]
    # Only the two replica parameters are retired; the others keep their defaults.
    assert new_defaults == {
        name: value for name, value in old_defaults.items() if name not in _RETIRED
    }
    assert {
        name for name, c in new["components"].items() if c.get("singleton") is True
    } == _SINGLETONS


@pytest.mark.parametrize("driver", _DRIVERS, ids=lambda d: d.name)
def test_values_template_no_longer_sets_the_counts(driver: _Driver) -> None:
    old_template = (_LEGACY_DIR / driver.legacy_dir / "values.j2.yml").read_text()
    new_template = (_EXAMPLES_DIR / driver.name / "values.j2.yml").read_text()
    for parameter in _RETIRED:
        assert parameter in old_template
        assert parameter not in new_template

    values = _rendered_values(_EXAMPLES_DIR / driver.name)
    for key in driver.chart_root:
        values = values[key]
    # Without a value the chart renders its own default; the replica patch sets the count.
    assert "replicas" not in values["infrahubServer"]
    assert "replicas" not in values["infrahubTaskWorker"]
