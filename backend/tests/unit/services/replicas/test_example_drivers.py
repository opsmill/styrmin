"""Replica patches and override checks on every example driver (023 T034).

SC-006: a component that declares neither ``replicas`` nor ``singleton`` gets no replica patch
when the deployment has no override, so its chart's count is unchanged. A declared one gets its
count. SC-001: every component that is not a singleton accepts a replica override of 2.
Expectations are read from each driver file, so the test holds whatever the examples declare.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import SpecPatch
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.components import (
    ComponentContext,
    ComponentsContext,
    ReplicaDeclaration,
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
from styrmin_backend.services.driver.deserializers import DriverSpecDeserializer
from styrmin_backend.services.replicas.exceptions import SingletonReplicaOverrideError
from styrmin_backend.services.replicas.patch_builder import (
    REPLICA_PATCH_KINDS,
    build_component_replica_patches,
)
from styrmin_backend.services.replicas.validator import validate_replica_overrides

_EXAMPLES_DIR = Path(__file__).resolve().parents[5] / "driver" / "examples"
_DRIVER_FILES = sorted(_EXAMPLES_DIR.glob("*/driver.styrmin.yml"))


def _raw_components(driver_file: Path) -> dict[str, dict[str, Any]]:
    """The component declarations as written in the file, before any model parses them."""
    return yaml.safe_load(driver_file.read_text())["spec"]["components"]


def _declarations(driver_file: Path) -> dict[str, ReplicaDeclaration]:
    driver = DriverSpecDeserializer().deserialize(
        data=yaml.safe_load(driver_file.read_text())
    )
    assert driver.spec.components is not None
    return dict(driver.spec.components.root)


def _context(declarations: dict[str, ReplicaDeclaration]) -> GlobalContext:
    """A running deployment of the driver with no replica override."""
    deployment_id = uuid4()
    namespace = get_kubernetes_reference(deployment_id)
    return GlobalContext(
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
        # The driver version stores each declaration's dump; a component's config is one entry.
        components=ComponentsContext(
            root={
                name: ComponentContext.model_validate(
                    {"name": name, "enabled": True, "config": declaration.model_dump()}
                )
                for name, declaration in declarations.items()
            }
        ),
    )


def _selector(raw: dict[str, Any]) -> str:
    # ``identifier.label.label_selectable()``: the first label (contracts/post-render-patch.md).
    key, value = next(iter(raw["identifier"]["label"].items()))
    return f"{key}={value}"


def _expected_count(raw: dict[str, Any]) -> int | None:
    if raw.get("replicas") is not None:
        return raw["replicas"]
    return 1 if raw.get("singleton") is True else None


def test_the_example_drivers_are_found() -> None:
    assert {"simple-app", "infrahub", "infrahub-enterprise"} <= {
        path.parent.name for path in _DRIVER_FILES
    }


@pytest.mark.parametrize("driver_file", _DRIVER_FILES, ids=lambda p: p.parent.name)
def test_only_declared_components_get_a_replica_patch(driver_file: Path) -> None:
    raw = _raw_components(driver_file)
    # Patches are matched to components by label selector, so the selectors must differ.
    assert len({_selector(c) for c in raw.values()}) == len(raw)

    patches = build_component_replica_patches(_context(_declarations(driver_file)))

    actual = []
    for tp in patches:
        assert isinstance(tp.patch, SpecPatch)
        actual.append(
            (tp.target.kind, tp.target.label_selector, tp.patch.specs["replicas"])
        )
    expected = [
        (kind, _selector(component), count)
        for component in raw.values()
        if (count := _expected_count(component)) is not None
        for kind in REPLICA_PATCH_KINDS
    ]
    assert sorted(actual) == sorted(expected)


@pytest.mark.parametrize("driver_file", _DRIVER_FILES, ids=lambda p: p.parent.name)
def test_every_component_that_is_not_a_singleton_accepts_two_replicas(
    driver_file: Path,
) -> None:
    raw = _raw_components(driver_file)
    declarations = _declarations(driver_file)

    for name, component in raw.items():
        config = {"components": {name: {"replicas": 2}}}
        check = {
            "components": declarations,
            "stored_config": None,
            "checked_against": f"example driver {driver_file.parent.name}",
        }
        if component.get("singleton") is True:
            with pytest.raises(SingletonReplicaOverrideError):
                validate_replica_overrides(config, **check)
        else:
            validate_replica_overrides(config, **check)
