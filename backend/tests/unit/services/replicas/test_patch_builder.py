"""Unit tests for ``build_component_replica_patches`` (023 T012).

Pins contracts/post-render-patch.md: per component and per kind in ``("Deployment",
"StatefulSet")``, at most one JSON6902 ``add`` on ``/spec/replicas``: 0 when the component is
stopped, the resolved count while it runs, and no patch when the chart's count applies. The
stopped cases also pin the output of the stop patch builder this replaces.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
import yaml
from loguru import logger

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    SpecPatch,
    TargetPatch,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    ComponentsContext,
    Identifier,
    LabelIdentifier,
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
from styrmin_backend.services.replicas.patch_builder import (
    REPLICA_PATCH_KINDS,
    build_component_replica_patches,
)

_SAME_AS_NAME = "<component name>"
_KINDS = ["Deployment", "StatefulSet"]


def _component(  # noqa: PLR0913
    name: str,
    *,
    label: str | None = None,
    container: str | None = _SAME_AS_NAME,
    enabled: bool = True,
    replicas: int | None = None,
    singleton: bool = False,
    override: int | None = None,
) -> ComponentContext:
    return ComponentContext(
        name=name,
        enabled=enabled,
        config=ArbitrarySectionModel(
            identifier=Identifier(
                label=LabelIdentifier(root={"app.kubernetes.io/name": label or name})
            ),
            container=name if container == _SAME_AS_NAME else container,
            replicas=replicas,
            singleton=singleton,
        ),
        replica_override=override,
    )


def _context(*components: ComponentContext, declare: bool = True) -> GlobalContext:
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
            name="test-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(),
                    name="test-chart",
                    version="1.0.0",
                    values_template="",
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
        deployed_services=[],
        components=(
            ComponentsContext(root={c.name: c for c in components}) if declare else None
        ),
    )


def _summary(patches: list[TargetPatch]) -> list[tuple[str | None, str | None, Any]]:
    """(kind, label selector, replicas) per patch, in order."""
    summary = []
    for tp in patches:
        assert isinstance(tp.patch, SpecPatch)
        assert list(tp.patch.specs) == ["replicas"]
        summary.append(
            (tp.target.kind, tp.target.label_selector, tp.patch.specs["replicas"])
        )
    return summary


def _per_kind(selector: str, count: int) -> list[tuple[str, str, int]]:
    return [(kind, selector, count) for kind in _KINDS]


@pytest.fixture
def loguru_records() -> Iterator[list[dict[str, Any]]]:
    captured: list[dict[str, Any]] = []
    sink_id = logger.add(lambda m: captured.append(m.record), level="DEBUG")
    try:
        yield captured
    finally:
        logger.remove(sink_id)


class TestStoppedComponent:
    @pytest.mark.parametrize("override", [None, 1, 3])
    @pytest.mark.parametrize(
        ("replicas", "singleton"),
        [
            pytest.param(None, False, id="no-declaration"),
            pytest.param(2, False, id="driver-default-2"),
            pytest.param(None, True, id="singleton"),
        ],
    )
    def test_one_zero_patch_per_kind_whatever_the_override(
        self, override: int | None, replicas: int | None, singleton: bool
    ) -> None:
        context = _context(
            _component(
                "server",
                enabled=False,
                replicas=replicas,
                singleton=singleton,
                override=override,
            )
        )

        patches = build_component_replica_patches(context)

        assert _summary(patches) == _per_kind("app.kubernetes.io/name=server", 0)

    def test_matches_the_stop_patch_it_replaces(self) -> None:
        # The pre-023 stop patch: a ``replicas: 0`` add per kind, targeted by kind and selector.
        context = _context(_component("server", label="simple-app", enabled=False))

        rendered = [
            tp.render_value() for tp in build_component_replica_patches(context)
        ]

        assert rendered == [
            {
                "target": {
                    "kind": kind,
                    "labelSelector": "app.kubernetes.io/name=simple-app",
                },
                "patch": "- op: add\n  path: /spec/replicas\n  value: 0\n",
            }
            for kind in _KINDS
        ]


class TestRunningComponent:
    def test_override_sets_the_count(self) -> None:
        context = _context(_component("server", override=3))

        patches = build_component_replica_patches(context)

        assert _summary(patches) == _per_kind("app.kubernetes.io/name=server", 3)

    def test_override_wins_over_the_driver_default(self) -> None:
        context = _context(_component("server", replicas=2, override=4))

        patches = build_component_replica_patches(context)

        assert _summary(patches) == _per_kind("app.kubernetes.io/name=server", 4)

    def test_driver_default_sets_the_count(self) -> None:
        context = _context(_component("server", replicas=2))

        patches = build_component_replica_patches(context)

        assert _summary(patches) == _per_kind("app.kubernetes.io/name=server", 2)

    def test_singleton_without_replicas_gets_one(self) -> None:
        context = _context(_component("database", singleton=True))

        patches = build_component_replica_patches(context)

        assert _summary(patches) == _per_kind("app.kubernetes.io/name=database", 1)

    def test_singleton_ignores_a_stored_override_above_one(self) -> None:
        # Cannot be written; a stored one is read defensively as the singleton's count.
        context = _context(_component("database", singleton=True, override=3))

        patches = build_component_replica_patches(context)

        assert _summary(patches) == _per_kind("app.kubernetes.io/name=database", 1)

    def test_no_override_and_no_declaration_gets_no_patch(self) -> None:
        context = _context(_component("server"), _component("worker"))

        assert build_component_replica_patches(context) == []

    def test_component_without_container_is_still_patched(self) -> None:
        context = _context(_component("server", container=None, override=2))

        patches = build_component_replica_patches(context)

        assert _summary(patches) == _per_kind("app.kubernetes.io/name=server", 2)


class TestTargets:
    def test_selector_is_the_component_identifier_label(self) -> None:
        component = _component("server", label="simple-app", override=2)
        context = _context(component)

        patches = build_component_replica_patches(context)

        expected = component.config.identifier.label.label_selectable()
        assert expected == "app.kubernetes.io/name=simple-app"
        assert [tp.target.label_selector for tp in patches] == [expected, expected]
        assert [tp.target.kind for tp in patches] == _KINDS
        assert all(tp.target.name is None for tp in patches)

    def test_only_deployment_and_statefulset_are_targeted(self) -> None:
        assert REPLICA_PATCH_KINDS == ("Deployment", "StatefulSet")

    @pytest.mark.parametrize("count", [0, 1, 3, 2147483647])
    def test_rendered_patch_value_is_an_integer(self, count: int) -> None:
        enabled = count != 0
        context = _context(_component("server", enabled=enabled, override=count or 2))

        for tp in build_component_replica_patches(context):
            ops = yaml.safe_load(tp.render_value()["patch"])
            assert ops == [{"op": "add", "path": "/spec/replicas", "value": count}]
            assert type(ops[0]["value"]) is int

    def test_at_most_one_patch_per_kind_per_component(self) -> None:
        context = _context(
            _component("server", replicas=2, override=3),
            _component("worker", replicas=2),
            _component("database", singleton=True, override=1),
            _component("cache", singleton=True, enabled=False),
            _component("stopped", replicas=2, override=5, enabled=False),
            _component("chart"),
        )

        patches = build_component_replica_patches(context)

        per_workload = Counter(
            (tp.target.label_selector, tp.target.kind) for tp in patches
        )
        assert set(per_workload.values()) == {1}
        assert len(per_workload) == 5 * len(_KINDS)

    def test_no_components_declared_gets_empty_list(self) -> None:
        assert build_component_replica_patches(_context(declare=False)) == []

    def test_empty_components_gets_empty_list(self) -> None:
        assert build_component_replica_patches(_context()) == []


class TestLogging:
    def test_logs_component_count_and_source_at_debug(
        self, loguru_records: list[dict[str, Any]]
    ) -> None:
        context = _context(
            _component("server", override=3),
            _component("worker", replicas=2),
            _component("database", singleton=True, enabled=False),
            _component("chart"),
        )

        build_component_replica_patches(context)

        lines = [
            r for r in loguru_records if "component_replica_patch_built" in r["message"]
        ]
        assert {line["level"].name for line in lines} == {"DEBUG"}
        # A stopped component logs the source of the count it returns to when started.
        assert [line["extra"] for line in lines] == [
            {
                "component": "server",
                "replicas": 3,
                "source": "override",
                "enabled": True,
            },
            {
                "component": "worker",
                "replicas": 2,
                "source": "driver_default",
                "enabled": True,
            },
            {
                "component": "database",
                "replicas": 0,
                "source": "driver_default",
                "enabled": False,
            },
        ]
