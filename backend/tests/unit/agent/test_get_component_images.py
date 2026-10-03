"""Unit tests for ``get_component_images`` ordering (018-component-image-overrides T038, D-010).

When the component declares a component container present in the pod template, its image is
element 0 so upgrade actions can take ``images[0]``; the list always keeps every image.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from kubernetes_asyncio.client import V1Container, V1PodSpec, V1PodTemplateSpec

from styrmin_backend.actions.primitives import (
    get_component_images as action_get_component_images,
)
from styrmin_backend.agent.service.kubernetes.primitives import get_component_images
from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    ComponentsContext,
    Identifier,
    LabelIdentifier,
)

# Undecorated function: inject a dummy client without fast_depends' type validation.
_get_images = get_component_images.__wrapped__

_TEMPLATE = V1PodTemplateSpec(
    spec=V1PodSpec(
        init_containers=[V1Container(name="init", image="busybox:1")],
        containers=[
            V1Container(name="sidecar", image="envoy:1.30"),
            V1Container(name="main", image="registry.example/acme/app:1.0.0"),
            V1Container(name="metrics", image="exporter:2"),
        ],
    )
)
_TEMPLATE_ORDER = ["envoy:1.30", "registry.example/acme/app:1.0.0", "exporter:2"]


async def _images(**kwargs: Any) -> list[str]:
    with patch(
        "styrmin_backend.agent.service.kubernetes.primitives._find_workload_pod_template",
        new=AsyncMock(return_value=_TEMPLATE),
    ) as finder:
        images = await _get_images(
            namespace="ns", label_selector="app=x", client=MagicMock(), **kwargs
        )
    finder.assert_awaited_once()
    return images


@pytest.mark.asyncio
async def test_component_container_image_is_first_and_list_keeps_every_image() -> None:
    assert await _images(container="main") == [
        "registry.example/acme/app:1.0.0",
        "envoy:1.30",
        "exporter:2",
    ]


@pytest.mark.asyncio
async def test_already_first_component_container_keeps_order() -> None:
    assert await _images(container="sidecar") == _TEMPLATE_ORDER


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [{}, {"container": None}, {"container": "missing"}, {"container": "init"}],
    ids=["unset", "none", "absent", "init-container-only"],
)
async def test_unset_or_absent_container_keeps_pod_template_order(
    kwargs: dict[str, Any],
) -> None:
    assert await _images(**kwargs) == _TEMPLATE_ORDER


def _context(container: str | None) -> MagicMock:
    component = ComponentContext(
        name="server",
        enabled=True,
        config=ArbitrarySectionModel(
            identifier=Identifier(
                label=LabelIdentifier(root={"app.kubernetes.io/name": "server-app"})
            ),
            container=container,
        ),
    )
    context = MagicMock()
    context.components = ComponentsContext(root={"server": component})
    context.instance.namespace = f"ns-{uuid4().hex[:6]}"
    return context


@pytest.mark.asyncio
@pytest.mark.parametrize("container", ["main", None])
async def test_action_passes_component_container(container: str | None) -> None:
    context = _context(container)
    k8s = AsyncMock(return_value=["registry.example/acme/app:1.0.0"])
    with patch("styrmin_backend.actions.primitives._k8s_get_component_images", new=k8s):
        images = await action_get_component_images.fn(
            component="server", context=context
        )

    assert images == ["registry.example/acme/app:1.0.0"]
    k8s.assert_awaited_once_with(
        namespace=context.instance.namespace,
        label_selector="app.kubernetes.io/name=server-app",
        container=container,
    )
