"""Replica values reach ``ComponentContext`` (023, research D-002, data-model.md "Context").

``replica_override`` comes from ``DeploymentConfig.components[<name>].replicas``; the driver's
``replicas`` and ``singleton`` ride on ``ComponentContext.config``. A stored declaration with an
invalid ``replicas`` still resolves, without the key.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from loguru import logger

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.context.models.input import ComponentInput, ContextInput
from styrmin_backend.context.resolvers import resolve_global_context


def _component(name: str = "server", **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "enabled": True,
        "config": {"identifier": {"label": {"app": name}}, **extra},
    }


def _context_input(
    *components: dict[str, Any],
    deployment_config: dict[str, Any] | None = None,
    driver_version: str | None = None,
) -> ContextInput:
    deployment_id = uuid4()
    payload: dict[str, Any] = {
        "config": {
            "cluster": {},
            "environment": {},
            "deployment": deployment_config or {},
        },
        "instance": {
            "deployment_id": deployment_id,
            "namespace": f"styrmin-{deployment_id}",
            "release_reference": f"styrmin-{deployment_id}",
        },
        "application": {
            "name": "simple-app",
            "version": "0.1.0",
            "chart": {
                "id": uuid4(),
                "name": "simple-app",
                "version": "0.1.0",
                "values_template": "{}",
            },
            "repository": {"id": uuid4(), "url": "https://charts.example.test"},
        },
        "components": [ComponentInput.model_validate(c) for c in components],
        "environment_name": "dev",
    }
    if driver_version is not None:
        payload["driver_version"] = driver_version
    return ContextInput.model_validate(payload)


@pytest.fixture
def warnings() -> Any:
    messages: list[str] = []
    sink = logger.add(messages.append, level="WARNING", format="{message}")
    yield messages
    logger.remove(sink)


def test_override_reaches_component_context() -> None:
    context = resolve_global_context(
        context_input=_context_input(
            _component("server"),
            _component("database"),
            deployment_config={"components": {"server": {"replicas": 3}}},
        )
    )

    assert context.components is not None
    assert context.components["server"].replica_override == 3
    assert context.components["database"].replica_override is None


def test_component_without_a_block_has_no_override() -> None:
    context = resolve_global_context(context_input=_context_input(_component()))

    assert context.components is not None
    assert context.components["server"].replica_override is None


def test_override_on_undeclared_component_creates_no_component_context() -> None:
    context = resolve_global_context(
        context_input=_context_input(
            _component("server"),
            deployment_config={"components": {"ghost": {"replicas": 2}}},
        )
    )

    assert context.components is not None
    assert list(context.components.root) == ["server"]
    assert context.components["server"].replica_override is None


def test_driver_declaration_reaches_component_config() -> None:
    context = resolve_global_context(
        context_input=_context_input(
            _component("server", replicas=2),
            _component("database", singleton=True),
        )
    )

    assert context.components is not None
    assert context.components["server"].config.replicas == 2
    assert context.components["server"].config.singleton is False
    assert context.components["database"].config.replicas is None
    assert context.components["database"].config.singleton is True


def test_declaration_without_the_keys_dumps_as_before() -> None:
    context = resolve_global_context(
        context_input=_context_input(_component("server", container="simple-app"))
    )

    dumped = context.model_dump(mode="json")["components"]["server"]["config"]
    assert dumped == {
        "identifier": {"label": {"app": "server"}},
        "container": "simple-app",
    }


def test_replica_values_survive_stored_context_round_trip() -> None:
    context = resolve_global_context(
        context_input=_context_input(
            _component("server", replicas=2),
            _component("database", singleton=True),
            deployment_config={"components": {"server": {"replicas": 4}}},
        )
    )

    restored = GlobalContext.model_validate(context.model_dump(mode="json"))

    assert restored.components is not None
    assert restored.components["server"].replica_override == 4
    assert restored.components["server"].config.replicas == 2
    assert restored.components["database"].config.singleton is True


def test_stored_context_without_replica_override_key_still_validates() -> None:
    context = resolve_global_context(context_input=_context_input(_component()))
    stored = context.model_dump(mode="json")
    # Simulate an instance context persisted before the field existed.
    stored["components"]["server"].pop("replica_override")

    restored = GlobalContext.model_validate(stored)

    assert restored.components is not None
    assert restored.components["server"].replica_override is None


def test_invalid_stored_replicas_still_resolves(warnings: list[str]) -> None:
    context = resolve_global_context(
        context_input=_context_input(
            _component("server", replicas="3", port=8000),
            driver_version="3",
        )
    )

    assert context.components is not None
    server = context.components["server"]
    assert server.config.replicas is None
    assert server.config.singleton is False
    assert server.config["port"] == 8000
    assert len(warnings) == 1
    assert "driver simple-app version 3" in warnings[0]
    assert "server" in warnings[0]


def test_invalid_stored_singleton_still_resolves(warnings: list[str]) -> None:
    context = resolve_global_context(
        context_input=_context_input(
            _component("database", singleton="yes", replicas=3)
        )
    )

    assert context.components is not None
    database = context.components["database"]
    assert database.config.singleton is False
    assert database.config.replicas is None
    assert len(warnings) == 1
    assert "driver simple-app" in warnings[0]
    assert "database" in warnings[0]
