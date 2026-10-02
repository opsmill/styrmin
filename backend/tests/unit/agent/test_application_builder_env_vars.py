"""Unit tests for env var patches in ``ApplicationHelmReleaseBuilder.build()``
(017-post-render-env-vars, T008).

Pins research D-002: env patches come after every scheduling patch, so the
scheduling ``ResourcesPatch`` (JSON patch on ``containers/0``) still hits the
chart's original first container. Also pins critique E3: the rendered
HelmRelease always sets both metadata maps the replace-spec update relies on.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import yaml

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


def _component(
    name: str,
    container: str,
    *,
    env_vars: dict[str, str] | None,
    with_resources: bool = True,
) -> ComponentContext:
    scheduling = (
        ResolvedComponentScheduling(
            config=SchedulingConfig(
                resources=ResourceRequirements(requests=ResourceSpec(cpu="100m"))
            )
        )
        if with_resources
        else None
    )
    return ComponentContext(
        name=name,
        enabled=True,
        config=ArbitrarySectionModel(
            identifier=Identifier(
                label=LabelIdentifier(root={"app.kubernetes.io/name": container})
            ),
            container=container,
        ),
        scheduling=scheduling,
        env_vars=(
            ResolvedComponentEnvVars(config=env_vars) if env_vars is not None else None
        ),
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


def _rendered(context: GlobalContext) -> dict[str, Any]:
    return ApplicationHelmReleaseBuilder(context=context).build(utilities=[]).render()


def _patches(rendered: dict[str, Any]) -> list[dict[str, Any]]:
    return rendered["spec"]["postRenderers"][0]["kustomize"]["patches"]


def _is_env_patch(entry: dict[str, Any]) -> bool:
    doc = yaml.safe_load(entry["patch"])
    if not isinstance(doc, dict):
        return False
    containers = doc.get("spec", {}).get("template", {}).get("spec", {})
    return any("env" in c for c in containers.get("containers", []))


def _is_resources_patch(entry: dict[str, Any]) -> bool:
    doc = yaml.safe_load(entry["patch"])
    return isinstance(doc, list) and any(
        op.get("path", "").endswith("/resources") for op in doc
    )


class TestEnvPatchOrdering:
    def test_env_patches_come_after_every_scheduling_patch(self) -> None:
        context = _context(
            _component("server", "simple-app", env_vars={"LOG_LEVEL": "debug"}),
            _component("database", "postgresql", env_vars={"PGTZ": "UTC"}),
        )

        patches = _patches(_rendered(context))
        env_idx = [i for i, p in enumerate(patches) if _is_env_patch(p)]
        resources_idx = [i for i, p in enumerate(patches) if _is_resources_patch(p)]

        assert len(env_idx) == 4, "two kinds per component with env vars"
        assert resources_idx, "fixture must produce scheduling resources patches"
        assert max(resources_idx) < min(env_idx)
        assert env_idx == list(range(len(patches) - 4, len(patches))), (
            "env patches must be the last entries in the post-render list"
        )

    def test_env_patch_targets_component_by_identifier_label(self) -> None:
        context = _context(
            _component("server", "simple-app", env_vars={"LOG_LEVEL": "debug"})
        )

        env_patches = [p for p in _patches(_rendered(context)) if _is_env_patch(p)]

        assert [p["target"] for p in env_patches] == [
            {
                "kind": "Deployment",
                "labelSelector": "app.kubernetes.io/name=simple-app",
            },
            {
                "kind": "StatefulSet",
                "labelSelector": "app.kubernetes.io/name=simple-app",
            },
        ]

    def test_no_env_patch_without_component_env_vars(self) -> None:
        context = _context(
            _component("server", "simple-app", env_vars=None),
            _component("database", "postgresql", env_vars={}),
        )

        patches = _patches(_rendered(context))

        assert patches, "label and scheduling patches are still emitted"
        assert not any(_is_env_patch(p) for p in patches)


class TestMetadataMaps:
    def test_build_always_sets_labels_and_annotations(self) -> None:
        # The replace-spec update adds metadata keys one by one, which needs
        # both maps to exist on the live object (critique E3).
        context = _context(_component("server", "simple-app", env_vars=None))

        metadata = _rendered(context)["metadata"]

        assert metadata["labels"]
        assert metadata["annotations"]
