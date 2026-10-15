"""Replica patches in ``ApplicationHelmReleaseBuilder.build()`` (023 T013).

Pins contracts/post-render-patch.md: the component replica patches take the stop patch's place in
``postRenderers[0].kustomize.patches``, after the component label patches and before the backup,
scheduling and component container patches. A deployment with no replica override and no driver
``replicas`` or ``singleton`` renders the same patch list as before the change (SC-006).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    SpecPatch,
    Target,
    TargetPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
    ApplicationHelmReleaseBuilder,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    ComponentsContext,
    Identifier,
    LabelIdentifier,
    ResolvedComponentEnvVars,
    ResolvedComponentScheduling,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
    ResourceRequirements,
    ResourceSpec,
    SchedulingConfig,
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
    build_component_container_patches,
)
from styrmin_backend.services.replicas.patch_builder import (
    build_component_replica_patches,
)


def _component(  # noqa: PLR0913
    name: str,
    label: str,
    *,
    enabled: bool = True,
    replicas: int | None = None,
    singleton: bool = False,
    override: int | None = None,
    backup: dict[str, Any] | None = None,
) -> ComponentContext:
    # Every component also carries env vars and a resources request, so each patch group shows.
    extra = {"backup": backup} if backup is not None else {}
    return ComponentContext(
        name=name,
        enabled=enabled,
        config=ArbitrarySectionModel(
            identifier=Identifier(
                label=LabelIdentifier(root={"app.kubernetes.io/name": label})
            ),
            container=label,
            replicas=replicas,
            singleton=singleton,
            **extra,
        ),
        scheduling=ResolvedComponentScheduling(
            config=SchedulingConfig(
                resources=ResourceRequirements(requests=ResourceSpec(cpu="100m"))
            )
        ),
        env_vars=ResolvedComponentEnvVars(config={"LOG_LEVEL": "debug"}),
        replica_override=override,
    )


def _context(*components: ComponentContext) -> GlobalContext:
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
                    values_template="replicaCount: 1\n",
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
        labels={"deployment_id": str(deployment_id)},
        deployed_services=[],
        components=ComponentsContext(root={c.name: c for c in components}),
    )


def _rendered_patches(context: GlobalContext) -> list[dict[str, Any]]:
    rendered = (
        ApplicationHelmReleaseBuilder(context=context).build(utilities=[]).render()
    )
    return rendered["spec"]["postRenderers"][0]["kustomize"]["patches"]


def _render(patches: list[TargetPatch]) -> list[dict[str, Any]]:
    return [tp.render_value() for tp in patches]


def _groups(
    context: GlobalContext, replica_patches: list[TargetPatch]
) -> dict[str, list[dict[str, Any]]]:
    """Each patch group of ``build()``, rendered, in the order the contract fixes."""
    builder = ApplicationHelmReleaseBuilder(context=context)
    return {
        "labels": _render(
            builder.build_target_for_label_patches(labels=context.labels)
        ),
        "component_labels": _render(builder.build_target_for_component_labels()),
        "replicas": _render(replica_patches),
        "backup": _render(builder.build_backup_annotation_patches()),
        "scheduling": _render(builder.build_scheduling_post_rendering_patches()),
        "component_container": _render(build_component_container_patches(context)),
    }


def _pre_change_stop_patches(context: GlobalContext) -> list[TargetPatch]:
    """The removed ``build_components_state_post_rendering_patches``, kept as the SC-006 reference."""
    assert context.components is not None
    return [
        TargetPatch(
            target=Target(
                label_selector=component.config.identifier.label.label_selectable(),
                kind=kind,
            ),
            patch=SpecPatch(specs={"replicas": 0}),
        )
        for component in context.components.root.values()
        if component.enabled is False
        for kind in ("Deployment", "StatefulSet")
    ]


def _is_replica_patch(entry: dict[str, Any]) -> bool:
    doc = yaml.safe_load(entry["patch"])
    return isinstance(doc, list) and any(
        op.get("path") == "/spec/replicas" for op in doc
    )


class TestReplicaPatchOrdering:
    def test_replica_patches_sit_between_component_labels_and_backup(self) -> None:
        context = _context(
            _component(
                "server",
                "simple-app",
                replicas=1,
                override=2,
                backup={"enabled": True, "kind": "disk", "volume": "data"},
            ),
            _component(
                "database",
                "postgresql",
                singleton=True,
                backup={"enabled": True, "kind": "postgres"},
            ),
            _component("worker", "worker", replicas=2, enabled=False),
        )
        groups = _groups(context, build_component_replica_patches(context))

        patches = _rendered_patches(context)

        assert all(groups.values()), "fixture must produce every patch group"
        assert patches == [entry for group in groups.values() for entry in group]
        replica_idx = [i for i, p in enumerate(patches) if _is_replica_patch(p)]
        assert replica_idx == list(
            range(
                len(groups["labels"]) + len(groups["component_labels"]),
                len(groups["labels"])
                + len(groups["component_labels"])
                + len(groups["replicas"]),
            )
        )
        assert [
            yaml.safe_load(patches[i]["patch"])[0]["value"] for i in replica_idx
        ] == [
            2,
            2,
            1,
            1,
            0,
            0,
        ]


class TestNoReplicaDeclaration:
    @pytest.mark.parametrize(
        "stopped",
        [
            pytest.param((), id="all-running"),
            pytest.param(("database",), id="one-stopped"),
            pytest.param(("server", "database"), id="all-stopped"),
        ],
    )
    def test_renders_the_same_patch_list_as_before_the_change(
        self, stopped: tuple[str, ...]
    ) -> None:
        context = _context(
            _component(
                "server",
                "simple-app",
                enabled="server" not in stopped,
                backup={"enabled": True, "kind": "disk", "volume": "data"},
            ),
            _component("database", "postgresql", enabled="database" not in stopped),
        )
        before = _groups(context, _pre_change_stop_patches(context))

        patches = _rendered_patches(context)

        assert patches == [entry for group in before.values() for entry in group]
        assert len([p for p in patches if _is_replica_patch(p)]) == 2 * len(stopped)
