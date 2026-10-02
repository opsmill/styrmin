"""The component container reaches ``ComponentContext.config.container`` (017).

The patch builder reads it from the rendering context; stored instance
contexts written before the field existed must keep validating.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.context.models.input import ComponentInput, ContextInput
from styrmin_backend.context.resolvers import resolve_global_context


def _component(**extra: Any) -> dict[str, Any]:
    return {
        "name": "server",
        "enabled": True,
        "config": {"identifier": {"label": {"app": "simple-app"}}, **extra},
    }


def _context_input(*components: dict[str, Any]) -> ContextInput:
    deployment_id = uuid4()
    return ContextInput.model_validate(
        {
            "config": {"cluster": {}, "environment": {}, "deployment": {}},
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
    )


def test_component_config_container_reaches_component_context() -> None:
    context = resolve_global_context(
        context_input=_context_input(_component(container="simple-app"))
    )

    assert context.components is not None
    assert context.components["server"].config.container == "simple-app"


def test_component_config_without_container_yields_none() -> None:
    context = resolve_global_context(context_input=_context_input(_component()))

    assert context.components is not None
    assert context.components["server"].config.container is None


def test_container_survives_stored_context_round_trip() -> None:
    context = resolve_global_context(
        context_input=_context_input(_component(container="simple-app"))
    )

    restored = GlobalContext.model_validate(context.model_dump(mode="json"))

    assert restored.components is not None
    assert restored.components["server"].config.container == "simple-app"


def test_stored_context_without_container_key_still_validates() -> None:
    context = resolve_global_context(context_input=_context_input(_component()))
    stored = context.model_dump(mode="json")
    # Simulate an instance context persisted before the field existed.
    stored["components"]["server"]["config"].pop("container", None)
    assert "container" not in stored["components"]["server"]["config"]

    restored = GlobalContext.model_validate(stored)

    assert restored.components is not None
    assert restored.components["server"].config.container is None
