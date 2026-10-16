"""``ComponentConfig.replicas`` and ``singleton`` read a stored declaration once (023)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from loguru import logger

from styrmin_backend.api.definitions.application_driver.model import ComponentConfig


@pytest.fixture
def warnings() -> Any:
    messages: list[str] = []
    sink = logger.add(messages.append, level="WARNING", format="{message}")
    yield messages
    logger.remove(sink)


def _component(config: dict[str, Any]) -> ComponentConfig:
    return ComponentConfig(
        id=uuid4(), name="server", config=config, driver_version="driver version adv-1"
    )


def test_invalid_stored_key_warns_once_for_both_fields(warnings: list[str]) -> None:
    component = _component(
        {"identifier": {"label": {"app": "server"}}, "replicas": "3", "singleton": True}
    )

    assert component.replicas() is None
    assert component.singleton() is True
    assert len(warnings) == 1
    assert "replicas='3'" in warnings[0]
    assert "driver version adv-1" in warnings[0]


def test_problems_outside_the_replica_keys_read_as_declared(
    warnings: list[str],
) -> None:
    # No identifier and a container name the driver load would reject.
    component = _component({"container": "Bad_Name", "replicas": 2})

    assert component.replicas() == 2
    assert component.singleton() is False
    assert warnings == []
