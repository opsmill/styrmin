"""The infrahub drivers leave the prefect-server chart's ``server.env`` untouched (017 / SC-003).

Overriding ``prefect-server.server.env`` replaces the chart's list and drops its
defaults (``PREFECT_UI_SERVE_BASE``, ``PROMETHEUS_MULTIPROC_DIR``), so the
analytics flag rides on ``global.prefect.env`` instead (research D-010).
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
_COMPONENTS = (
    "server",
    "task-worker",
    "database",
    "cache",
    "message-queue",
    "task-manager",
    "task-manager-db",
)
_SENTINEL = "STYRMIN_UNIT_SENTINEL"


def _context(*, enable_analytics: bool) -> dict[str, Any]:
    return {
        "app": {"version": "1.5.0"},
        "parameters": {
            "database_storage_size": 100,
            "enable_analytics": enable_analytics,
        },
        "services": {
            name: {
                "primary_fqdn": f"{name}.example.test",
                "human_readable_fqdn": f"{name}-hr.example.test",
            }
            for name in ("infrahub", "task-manager")
        },
        "instance": {
            "config": {
                "ingress_class": "nginx",
                "standard_storage": {"storage_class": "standard"},
                "fast_storage": {"storage_class": "standard"},
                "external_url_scheme": "https",
                "external_url_port": 443,
            }
        },
        # User env vars set on every component must not reach the values.
        "components": {
            name: {"env_vars": {"config": {_SENTINEL: "x"}}} for name in _COMPONENTS
        },
    }


def _render(driver: str, *, enable_analytics: bool = True) -> dict[str, Any]:
    template = (_EXAMPLES_DIR / driver / "values.j2.yml").read_text()
    environment = get_jinja_environment(undefined=SilentUndefined)
    rendered = environment.from_string(template).render(
        _context(enable_analytics=enable_analytics)
    )
    assert _SENTINEL not in rendered
    values = yaml.safe_load(rendered)
    # infrahub-enterprise nests the community chart under `infrahub:`.
    return values["infrahub"] if driver == "infrahub-enterprise" else values


@pytest.mark.parametrize("driver", ["infrahub", "infrahub-enterprise"])
def test_prefect_server_env_is_not_overridden(driver: str) -> None:
    prefect = _render(driver)["prefect-server"]

    assert "env" not in prefect["server"]


@pytest.mark.parametrize("driver", ["infrahub", "infrahub-enterprise"])
@pytest.mark.parametrize("enable_analytics", [True, False])
def test_analytics_flag_set_under_global_prefect_env(
    driver: str, enable_analytics: bool
) -> None:
    prefect = _render(driver, enable_analytics=enable_analytics)["prefect-server"]

    assert prefect["global"]["prefect"]["env"] == [
        {"name": "PREFECT_SERVER_ANALYTICS_ENABLED", "value": str(enable_analytics)}
    ]
    # The image tag set alongside it must survive the move.
    assert prefect["global"]["prefect"]["image"] == {"prefectTag": "1.5.0"}


@pytest.mark.parametrize("driver", ["infrahub", "infrahub-enterprise"])
def test_ingress_extra_hosts_use_hostname_key(driver: str) -> None:
    ingress = _render(driver)["infrahubServer"]["ingress"]

    # The chart's ingress template reads `.hostname` from each extraHosts entry.
    assert ingress["extraHosts"] == [
        {"hostname": "infrahub-hr.example.test", "path": "/"}
    ]
