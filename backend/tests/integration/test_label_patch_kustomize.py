"""Styrmin's label patches through real ``kubectl kustomize`` (025 contract C-004a, #435).

With Helm v4 defaults, Helm hooks reach the post-renderers too, and a chart hook often has no
``metadata.labels``. The patches from ``build_target_for_label_patches`` must add Styrmin's labels
to such a resource, keep the labels a resource already has, and leave its annotations alone.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    TargetPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
    ApplicationHelmReleaseBuilder,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
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

pytestmark = pytest.mark.skipif(
    shutil.which("kubectl") is None,
    reason="kubectl is required to run kustomize build",
)

STYRMIN_LABEL = "styrmin/deployment-id"
CHART_LABELS = {"app.kubernetes.io/name": "server", "app.kubernetes.io/instance": "rel"}
HOOK_ANNOTATIONS = {
    "helm.sh/hook": "pre-upgrade",
    "helm.sh/hook-delete-policy": "before-hook-creation",
}


def _context() -> GlobalContext:
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
            version="0.1.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(), name="chart", version="0.1.0", values_template=""
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
        deployed_services=[],
    )


def _resources() -> list[dict[str, Any]]:
    pod_template = {
        "metadata": {"labels": dict(CHART_LABELS)},
        "spec": {"containers": [{"name": "main", "image": "chart/main:1.0"}]},
    }
    return [
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "server", "labels": dict(CHART_LABELS)},
            "spec": {
                "selector": {"matchLabels": dict(CHART_LABELS)},
                "template": pod_template,
            },
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "settings"},
            "data": {"key": "value"},
        },
        {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": "migrate", "annotations": dict(HOOK_ANNOTATIONS)},
            "spec": {
                "template": {
                    "spec": {
                        "restartPolicy": "Never",
                        "containers": [{"name": "hook", "image": "chart/main:1.0"}],
                    }
                }
            },
        },
    ]


def _kustomize(
    resources: list[dict[str, Any]], patches: list[TargetPatch]
) -> subprocess.CompletedProcess[str]:
    """Run ``kubectl kustomize`` with the patches as Flux passes them (inline, with targets)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "base.yaml").write_text(yaml.safe_dump_all(resources, sort_keys=False))
        kustomization = {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "resources": ["base.yaml"],
            "patches": [tp.render_value() for tp in patches],
        }
        (root / "kustomization.yaml").write_text(yaml.safe_dump(kustomization))
        return subprocess.run(
            ["kubectl", "kustomize", str(root)],
            check=False,
            capture_output=True,
            text=True,
        )


def test_labels_reach_resources_with_and_without_labels() -> None:
    patches = ApplicationHelmReleaseBuilder(
        context=_context()
    ).build_target_for_label_patches(
        labels={"deployment-id": "abc"}, label_prefix="styrmin"
    )

    result = _kustomize(_resources(), patches)

    assert result.returncode == 0, result.stderr
    rendered = {doc["kind"]: doc for doc in yaml.safe_load_all(result.stdout)}
    assert set(rendered) == {"Deployment", "ConfigMap", "Job"}
    for doc in rendered.values():
        assert doc["metadata"]["labels"][STYRMIN_LABEL] == "abc"
    assert rendered["Deployment"]["metadata"]["labels"] == {
        **CHART_LABELS,
        STYRMIN_LABEL: "abc",
    }
    assert rendered["Deployment"]["spec"]["template"]["metadata"]["labels"] == {
        **CHART_LABELS,
        STYRMIN_LABEL: "abc",
    }
    assert rendered["ConfigMap"]["metadata"]["labels"] == {STYRMIN_LABEL: "abc"}
    assert rendered["ConfigMap"]["data"] == {"key": "value"}
    assert rendered["Job"]["metadata"]["labels"] == {STYRMIN_LABEL: "abc"}
    assert rendered["Job"]["metadata"]["annotations"] == HOOK_ANNOTATIONS
