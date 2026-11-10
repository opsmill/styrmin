"""``parse_service_overrides`` reads the stored ``config["services"]`` in one way (#598, review M1)."""

from __future__ import annotations

from typing import Any

import pytest

from styrmin_backend.context.models.config import (
    ServiceConfigBlock,
    parse_service_overrides,
)


@pytest.mark.parametrize(
    "config",
    [None, {}, {"services": None}, {"services": {}}, {"components": {"server": {}}}],
    ids=["no-config", "empty-config", "null-services", "empty-services", "no-key"],
)
def test_a_config_without_a_service_block_holds_no_override(
    config: dict[str, Any] | None,
) -> None:
    assert parse_service_overrides(config) == {}


def test_the_stored_blocks_are_returned_by_driver_service_name() -> None:
    config = {
        "services": {
            "task-manager": {"ingress_class": "tailscale", "fqdn_suffix": "a.example"},
            "api": {"fqdn_suffix": "b.example"},
        }
    }

    assert parse_service_overrides(config) == {
        "task-manager": ServiceConfigBlock(
            ingress_class="tailscale", fqdn_suffix="a.example"
        ),
        "api": ServiceConfigBlock(fqdn_suffix="b.example"),
    }
