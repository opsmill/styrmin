"""The ``infrahub`` and ``infrahub-enterprise`` drivers publish ``task-manager`` through Styrmin (#598, T024).

Written before the driver change (T031, T032). Source: ``specs/033-service-ingress-override/``,
FR-013 and research D-003 and D-005.

After the change, each driver declares ``task-manager`` as ``scope: external``, so Styrmin builds its
Ingress and the driver does not enable the chart's Prefect Ingress. ``infrahub`` stays ``scope: internal`` with the chart's
own Ingress, which keeps the application address as its host. The Prefect UI calls its API at the
host of the Ingress that Styrmin builds, which is the override host when the service has an override
(``services['task-manager'].human_readable_fqdn``, which the context builder fills with the override
suffix).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
    SilentUndefined,
    get_jinja_environment,
)

_EXAMPLES_DIR = Path(__file__).resolve().parents[4] / "driver" / "examples"
_DRIVERS = ["infrahub", "infrahub-enterprise"]
# ``spec.version`` of each driver before #598. The new version must be higher.
_VERSION_BEFORE = {"infrahub": 5, "infrahub-enterprise": 4}

_INFRAHUB_PRIMARY = "driver-1234.example.test"
_INFRAHUB_READABLE = "infrahub-prod.example.test"
_TASK_MANAGER_RESOLVED_READABLE = "task-manager-prod.example.test"
_TASK_MANAGER_OVERRIDE_READABLE = "task-manager-prod.tailnet.example.ts.net"


def _driver_spec(driver: str) -> dict[str, Any]:
    manifest = yaml.safe_load(
        (_EXAMPLES_DIR / driver / "driver.styrmin.yml").read_text()
    )
    return manifest["spec"]


def _services(driver: str) -> dict[str, dict[str, Any]]:
    return {service["name"]: service for service in _driver_spec(driver)["services"]}


def _context(
    *,
    task_manager_host: str = _TASK_MANAGER_RESOLVED_READABLE,
    overridden: bool = False,
    external_url_port: int | None = 443,
) -> dict[str, Any]:
    return {
        "app": {"version": "1.5.0"},
        "parameters": {"database_storage_size": 100, "enable_analytics": True},
        "services": {
            "infrahub": {
                "primary_fqdn": _INFRAHUB_PRIMARY,
                "human_readable_fqdn": _INFRAHUB_READABLE,
                "overridden": False,
            },
            "task-manager": {
                "primary_fqdn": _INFRAHUB_PRIMARY,
                "human_readable_fqdn": task_manager_host,
                "overridden": overridden,
            },
        },
        "instance": {
            "config": {
                "ingress_class": "nginx",
                "standard_storage": {"storage_class": "standard"},
                "fast_storage": {"storage_class": "standard"},
                "external_url_scheme": "https",
                "external_url_port": external_url_port,
            }
        },
        "components": {},
    }


def _render(driver: str, **context: Any) -> dict[str, Any]:
    template = (_EXAMPLES_DIR / driver / "values.j2.yml").read_text()
    environment = get_jinja_environment(undefined=SilentUndefined)
    values = yaml.safe_load(
        environment.from_string(template).render(_context(**context))
    )
    # infrahub-enterprise nests the community chart under `infrahub:`.
    return values["infrahub"] if driver == "infrahub-enterprise" else values


@pytest.mark.parametrize("driver", _DRIVERS)
def test_the_driver_version_is_higher_than_before(driver: str) -> None:
    """FR-013: ``scope: external`` is a change of behaviour, so it ships as a new driver version."""
    assert int(_driver_spec(driver)["version"]) > _VERSION_BEFORE[driver]


@pytest.mark.parametrize("driver", _DRIVERS)
def test_task_manager_is_declared_external(driver: str) -> None:
    task_manager = _services(driver)["task-manager"]

    assert task_manager == {
        "name": "task-manager",
        "kind": "http",
        "scope": "external",
        "port": 4200,
        "component": "task-manager",
    }


@pytest.mark.parametrize("driver", _DRIVERS)
def test_infrahub_stays_internal(driver: str) -> None:
    """FR-013: the ``infrahub`` service keeps its chart Ingress, so Styrmin builds none for it."""
    infrahub = _services(driver)["infrahub"]

    assert infrahub == {
        "name": "infrahub",
        "kind": "http",
        "scope": "internal",
        "port": 8000,
        "component": "server",
    }


@pytest.mark.parametrize("driver", _DRIVERS)
def test_infrahub_is_still_the_first_declared_service(driver: str) -> None:
    """research D-003: the application address goes to the first declared service when it is external,
    and ``infrahub`` is internal, so the chart Ingress keeps it. Declaring ``task-manager`` first
    would move the address to the Ingress that Styrmin builds."""
    names = [service["name"] for service in _driver_spec(driver)["services"]]

    assert names[0] == "infrahub"


@pytest.mark.parametrize("driver", _DRIVERS)
def test_the_driver_does_not_enable_the_chart_prefect_ingress(driver: str) -> None:
    """FR-013, FR-014: a driver that declares a service ``external`` must not render an Ingress for it.

    The driver leaves ``prefect-server.ingress`` out, so the chart default applies. Read on 2026-11-13:
    the ``prefect-server`` subchart of ``infrahub`` 4.33.2 and of ``infrahub-enterprise`` 4.19.2 sets
    ``ingress.enabled: false`` and neither Infrahub chart overrides it. A chart version that changes the
    default is not checked here: the end-to-end test of the override counts the chart Ingresses.
    """
    prefect = _render(driver)["prefect-server"]

    assert prefect.get("ingress", {}).get("enabled", False) is False


@pytest.mark.parametrize("driver", _DRIVERS)
def test_the_chart_ingress_of_infrahub_is_kept_with_the_application_address(
    driver: str,
) -> None:
    ingress = _render(driver)["infrahubServer"]["ingress"]

    assert ingress["enabled"] is True
    assert ingress["hostname"] == _INFRAHUB_PRIMARY
    assert ingress["extraHosts"] == [{"hostname": _INFRAHUB_READABLE, "path": "/"}]


@pytest.mark.parametrize("driver", _DRIVERS)
@pytest.mark.parametrize(
    ("host", "overridden"),
    [
        (_TASK_MANAGER_RESOLVED_READABLE, False),
        (_TASK_MANAGER_OVERRIDE_READABLE, True),
    ],
    ids=["resolved-host", "override-host"],
)
def test_the_prefect_ui_calls_the_api_at_the_host_of_the_service(
    driver: str, host: str, overridden: bool
) -> None:
    """The browser-side Prefect UI must call the host that the Styrmin-built Ingress serves."""
    prefect = _render(driver, task_manager_host=host, overridden=overridden)[
        "prefect-server"
    ]

    assert prefect["server"]["uiConfig"]["prefectUiApiUrl"] == f"https://{host}/api"


@pytest.mark.parametrize("driver", _DRIVERS)
def test_the_prefect_ui_api_url_keeps_a_non_default_port(driver: str) -> None:
    prefect = _render(
        driver,
        task_manager_host=_TASK_MANAGER_OVERRIDE_READABLE,
        overridden=True,
        external_url_port=8443,
    )["prefect-server"]

    assert (
        prefect["server"]["uiConfig"]["prefectUiApiUrl"]
        == f"https://{_TASK_MANAGER_OVERRIDE_READABLE}:8443/api"
    )
