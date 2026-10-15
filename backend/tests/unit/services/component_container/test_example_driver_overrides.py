"""Every example driver takes ``command`` and ``args`` on each component container (022 T011).

SC-001: loads each ``driver/examples/*/driver.styrmin.yml``, stores ``command`` and ``args`` on
every component that declares a component container, resolves them through the context service
and checks that the patch builder writes both lists into a merge patch naming that container.
No values template is involved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    ComponentContainerPatch,
    ContainerMergePatch,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.components import (
    ComponentContext,
    ComponentsContext,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.services.component_container.patch_builder import (
    COMPONENT_CONTAINER_PATCH_KINDS,
    build_component_container_patches,
)
from styrmin_backend.services.context import _populate_component_container_overrides
from styrmin_backend.services.driver.deserializers import DriverSpecDeserializer

_EXAMPLES_DIR = Path(__file__).resolve().parents[5] / "driver" / "examples"
_DRIVER_FILES = sorted(_EXAMPLES_DIR.glob("*/driver.styrmin.yml"))
_COMMAND = ["/bin/sh", "-c"]
_ARGS = ["exec server --log-level debug"]


def _driver_components(driver_file: Path) -> dict[str, dict[str, Any]]:
    driver = DriverSpecDeserializer().deserialize(
        data=yaml.safe_load(driver_file.read_text())
    )
    assert driver.spec.components is not None
    # The driver version stores this dump; each deployment component's config is one entry.
    return driver.spec.components.model_dump()


def _context(
    components: dict[str, dict[str, Any]], overrides: dict[str, dict[str, list[str]]]
) -> GlobalContext:
    deployment_id = uuid4()
    namespace = get_kubernetes_reference(deployment_id)
    context = GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment_id,
            namespace=namespace,
            release_reference=namespace,
        ),
        app=ApplicationContext(
            name="example",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(), name="chart", version="1.0.0", values_template=""
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
        deployed_services=[],
        components=ComponentsContext(
            root={
                name: ComponentContext.model_validate(
                    {"name": name, "enabled": True, "config": config}
                )
                for name, config in components.items()
            }
        ),
    )
    _populate_component_container_overrides(
        context=context, deployment_config={"components": overrides}
    )
    return context


def _selector(config: dict[str, Any]) -> str:
    key, value = next(iter(config["identifier"]["label"].items()))
    return f"{key}={value}"


def test_the_example_drivers_are_found() -> None:
    assert {"simple-app", "infrahub", "infrahub-enterprise"} <= {
        path.parent.name for path in _DRIVER_FILES
    }


@pytest.mark.parametrize("driver_file", _DRIVER_FILES, ids=lambda p: p.parent.name)
def test_every_component_container_gets_command_and_args(driver_file: Path) -> None:
    components = _driver_components(driver_file)
    containers = {
        name: config["container"]
        for name, config in components.items()
        if config.get("container") is not None
    }
    assert containers, f"{driver_file} declares no component container"
    context = _context(
        components,
        {name: {"command": _COMMAND, "args": _ARGS} for name in containers},
    )

    patches = build_component_container_patches(context)

    merges = [tp for tp in patches if isinstance(tp.patch, ContainerMergePatch)]
    guards = [tp for tp in patches if isinstance(tp.patch, ComponentContainerPatch)]
    assert len(merges) == len(containers) * len(COMPONENT_CONTAINER_PATCH_KINDS)
    assert {(tp.patch.component, tp.patch.container) for tp in guards} == set(
        containers.items()
    )
    for name, container in containers.items():
        selector = _selector(components[name])
        component_merges = [tp for tp in merges if tp.target.label_selector == selector]
        assert sorted(tp.target.kind for tp in component_merges) == sorted(
            COMPONENT_CONTAINER_PATCH_KINDS
        ), name
        for tp in component_merges:
            assert tp.patch.container == container, name
            assert tp.patch.command == _COMMAND, name
            assert tp.patch.args == _ARGS, name
            assert tp.patch.env == {}, name


@pytest.mark.parametrize("driver", ["infrahub", "infrahub-enterprise"])
@pytest.mark.parametrize(
    ("component", "container"),
    [("server", "infrahub-server"), ("task-worker", "infrahub-task-worker")],
)
def test_infrahub_command_reaches_server_and_task_worker(
    driver: str, component: str, container: str
) -> None:
    # The pre-migration templates sent only args for these two components.
    components = _driver_components(_EXAMPLES_DIR / driver / "driver.styrmin.yml")
    context = _context(components, {component: {"command": _COMMAND}})

    merges = [
        tp.patch
        for tp in build_component_container_patches(context)
        if isinstance(tp.patch, ContainerMergePatch)
    ]

    assert [(m.kind, m.container, m.command, m.args) for m in merges] == [
        (kind, container, _COMMAND, None) for kind in COMPONENT_CONTAINER_PATCH_KINDS
    ]
