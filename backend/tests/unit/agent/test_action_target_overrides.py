"""Action primitives use the overrides of the instance they run for (#431).

An apply that sets an image override or env vars and changes the version runs the driver's
upgrade action with the target instance's context, before the override reaches the workload.
``get_component_images`` and ``execute_commands(env_from_component=...)`` therefore take the
overrides from the context instead of the workload.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes_asyncio.client import (
    V1Container,
    V1EnvVar,
    V1PodSpec,
    V1PodTemplateSpec,
)

from styrmin_backend.actions.primitives import execute_commands, get_component_images
from styrmin_backend.agent.service.kubernetes.primitives import get_component_env
from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    ComponentsContext,
    Identifier,
    LabelIdentifier,
    ResolvedComponentEnvVars,
    ResolvedComponentImageOverride,
)

LIVE_IMAGES = ["registry.example/acme/app:0.1.0", "exporter:2"]
TOKEN = "registry.example/acme/app-patched:{{ app.version }}"
PINNED = "registry.example/acme/app-patched:0.1.0"


def _context(
    *,
    container: str | None = "main",
    image: str | None = None,
    env: dict[str, str] | None = None,
    orphaned: bool = False,
) -> MagicMock:
    component = ComponentContext(
        name="server",
        enabled=True,
        config=ArbitrarySectionModel(
            identifier=Identifier(label=LabelIdentifier(root={"app": "server"})),
            container=container,
        ),
        image_override=(
            ResolvedComponentImageOverride(reference=image, is_orphaned=orphaned)
            if image is not None
            else None
        ),
        env_vars=(
            ResolvedComponentEnvVars(config=env, is_orphaned=orphaned)
            if env is not None
            else None
        ),
    )
    context = MagicMock()
    context.components = ComponentsContext(root={"server": component})
    context.app.version = "0.2.0"
    context.instance.namespace = "ns"
    context.instance.release_reference = "app-release"
    return context


async def _images(context: MagicMock) -> list[str]:
    with patch(
        "styrmin_backend.actions.primitives._k8s_get_component_images",
        new=AsyncMock(return_value=list(LIVE_IMAGES)),
    ):
        return await get_component_images.fn(component="server", context=context)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("image", "expected"),
    [
        (TOKEN, "registry.example/acme/app-patched:0.2.0"),
        (PINNED, PINNED),
    ],
    ids=["token", "pinned"],
)
async def test_applicable_override_is_first_image(image: str, expected: str) -> None:
    assert await _images(_context(image=image)) == [expected, "exporter:2"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"container": None, "image": TOKEN},
        {"image": TOKEN, "orphaned": True},
    ],
    ids=["no-override", "containerless", "orphaned"],
)
async def test_workload_images_without_applicable_override(
    kwargs: dict[str, Any],
) -> None:
    assert await _images(_context(**kwargs)) == LIVE_IMAGES


async def _job_env(
    context: MagicMock, workload_env: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]] | None, AsyncMock]:
    run_job = AsyncMock()
    env_reader = AsyncMock(return_value=(workload_env, []))
    with (
        patch("styrmin_backend.actions.primitives.get_component_env", new=env_reader),
        patch("styrmin_backend.actions.primitives.run_job", new=run_job),
    ):
        await execute_commands.fn(
            ["migrate"], image="app:0.2.0", context=context, env_from_component="server"
        )
    container = run_job.await_args.kwargs["body"]["spec"]["template"]["spec"][
        "containers"
    ][0]
    return container.get("env"), env_reader


@pytest.mark.asyncio
async def test_job_env_carries_the_context_env_vars() -> None:
    workload_env = [
        {"name": "CHART", "value": "kept"},
        {
            "name": "LOG_LEVEL",
            "valueFrom": {"configMapKeyRef": {"name": "c", "key": "k"}},
        },
        {"name": "REMOVED", "value": "still-there"},
    ]
    context = _context(env={"LOG_LEVEL": "debug", "NEW": "added"})

    env, env_reader = await _job_env(context, workload_env)

    assert env == [
        {"name": "CHART", "value": "kept"},
        {"name": "LOG_LEVEL", "value": "debug"},
        {"name": "REMOVED", "value": "still-there"},
        {"name": "NEW", "value": "added"},
    ]
    env_reader.assert_awaited_once_with(
        namespace="ns", label_selector="app=server", container="main"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [{"container": None}, {"orphaned": True}],
    ids=["containerless", "orphaned"],
)
async def test_job_env_without_applicable_env_vars(kwargs: dict[str, Any]) -> None:
    workload_env = [{"name": "CHART", "value": "kept"}]
    env, _ = await _job_env(_context(env={"NEW": "x"}, **kwargs), workload_env)
    assert env == workload_env


_TEMPLATE = V1PodTemplateSpec(
    spec=V1PodSpec(
        containers=[
            V1Container(
                name="sidecar", image="envoy", env=[V1EnvVar(name="S", value="1")]
            ),
            V1Container(name="main", image="app", env=[V1EnvVar(name="M", value="2")]),
        ],
    )
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("container", "expected"),
    [("main", "M"), (None, "S"), ("missing", "S")],
    ids=["named", "unset", "absent"],
)
async def test_workload_env_is_read_from_the_component_container(
    container: str | None, expected: str
) -> None:
    client = MagicMock()
    client.sanitize_for_serialization = lambda env: [
        {"name": e.name, "value": e.value} for e in env
    ]
    with patch(
        "styrmin_backend.agent.service.kubernetes.primitives._find_workload_pod_template",
        new=AsyncMock(return_value=_TEMPLATE),
    ):
        env, env_from = await get_component_env.__wrapped__(
            namespace="ns", label_selector="app=x", client=client, container=container
        )
    assert [e["name"] for e in env] == [expected]
    assert env_from == []
