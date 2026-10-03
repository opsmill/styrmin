"""Component-container patches through real ``kubectl kustomize`` (018-component-image-overrides, T009).

Renders the builder's real patches, exactly as they land in ``HelmRelease.spec.postRenderers``,
into a kustomization over a chart-like fixture and checks the guarantees in
contracts/post-render-patch.md: the image lands on the named container only, a wrong name fails
the render with a guard key the operator parser understands, env-only output is byte-identical to
the env strategic merge alone (SC-002), and a kind matching nothing is a no-op.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    ContainerEnvPatch,
    TargetPatch,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    ComponentsContext,
    Identifier,
    LabelIdentifier,
    ResolvedComponentEnvVars,
    ResolvedComponentImageOverride,
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
from styrmin_backend.services.component_container.exceptions import (
    GUARD_KEY_PREFIX,
    parse_guard_failure,
)
from styrmin_backend.services.component_container.patch_builder import (
    build_component_container_patches,
)

pytestmark = pytest.mark.skipif(
    shutil.which("kubectl") is None,
    reason="kubectl is required to run kustomize build",
)

LABEL = "app.kubernetes.io/name"
PATCHED = "registry.example/acme/server-patched:0.1.0"

_POD_SPEC = textwrap.dedent(
    """
    initContainers:
      - name: init
        image: chart/init:1.0
    containers:
      - name: sidecar
        image: chart/sidecar:1.0
        env:
          - name: SIDECAR_MODE
            value: proxy
      - name: main
        image: chart/main:1.0
        imagePullPolicy: Always
        env:
          - name: CHART_VAR
            value: chart
          - name: LOG_LEVEL
            value: info
    """
).strip()


def _workload(kind: str, name: str, *, api_version: str = "apps/v1") -> dict[str, Any]:
    template = {
        "metadata": {"labels": {LABEL: "server"}},
        "spec": yaml.safe_load(_POD_SPEC),
    }
    spec: dict[str, Any] = {"template": template}
    if kind != "Job":
        spec["selector"] = {"matchLabels": {LABEL: "server"}}
    if kind == "Job":
        template["spec"]["restartPolicy"] = "Never"
    return {
        "apiVersion": api_version,
        "kind": kind,
        "metadata": {"name": name, "labels": {LABEL: "server"}},
        "spec": spec,
    }


def _resources(*, with_statefulset: bool = True) -> list[dict[str, Any]]:
    resources = [
        _workload("Deployment", "server"),
        _workload("Job", "server-migrate", api_version="batch/v1"),
    ]
    if with_statefulset:
        resources.append(_workload("StatefulSet", "server-store"))
    return resources


def _context(
    *,
    container: str = "main",
    env_vars: dict[str, str] | None = None,
    image: str | None = None,
    component: str = "server",
) -> GlobalContext:
    deployment_id = uuid4()
    namespace = get_kubernetes_reference(deployment_id)
    server = ComponentContext(
        name=component,
        enabled=True,
        config=ArbitrarySectionModel(
            identifier=Identifier(label=LabelIdentifier(root={LABEL: "server"})),
            container=container,
        ),
        env_vars=ResolvedComponentEnvVars(config=env_vars) if env_vars else None,
        image_override=(
            ResolvedComponentImageOverride(reference=image) if image else None
        ),
    )
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
        components=ComponentsContext(root={component: server}),
    )


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


def _render(
    resources: list[dict[str, Any]], patches: list[TargetPatch]
) -> dict[str, dict[str, Any]]:
    result = _kustomize(resources, patches)
    assert result.returncode == 0, result.stderr
    return {doc["kind"]: doc for doc in yaml.safe_load_all(result.stdout)}


def _containers(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in doc["spec"]["template"]["spec"]["containers"]}


def _base(kind: str) -> dict[str, Any]:
    return next(r for r in _resources() if r["kind"] == kind)


class TestImageOverride:
    def test_sets_the_image_on_the_named_container_only(self) -> None:
        patches = build_component_container_patches(_context(image=PATCHED))

        rendered = _render(_resources(), patches)

        for kind in ("Deployment", "StatefulSet"):
            doc = rendered[kind]
            pod_spec = doc["spec"]["template"]["spec"]
            base_containers = _containers(_base(kind))
            main = _containers(doc)["main"]
            assert main == {**base_containers["main"], "image": PATCHED}
            assert main["imagePullPolicy"] == "Always"
            assert _containers(doc)["sidecar"] == base_containers["sidecar"]
            assert len(pod_spec["containers"]) == 2
            assert (
                pod_spec["initContainers"]
                == _base(kind)["spec"]["template"]["spec"]["initContainers"]
            )
            assert not any(GUARD_KEY_PREFIX in key for key in pod_spec)
        assert rendered["Job"] == _base("Job")

    def test_env_and_image_together(self) -> None:
        patches = build_component_container_patches(
            _context(env_vars={"LOG_LEVEL": "debug"}, image=PATCHED)
        )

        main = _containers(_render(_resources(), patches)["Deployment"])["main"]

        assert main["image"] == PATCHED
        assert {e["name"]: e.get("value") for e in main["env"]} == {
            "CHART_VAR": "chart",
            "LOG_LEVEL": "debug",
        }

    def test_wrong_container_name_fails_with_guard_key_and_no_output(self) -> None:
        patches = build_component_container_patches(
            _context(container="wrong", image=PATCHED)
        )

        result = _kustomize(_resources(), patches)

        assert result.returncode != 0
        assert result.stdout == ""
        assert f"{GUARD_KEY_PREFIX}server~1wrong/image" in result.stderr
        assert parse_guard_failure(result.stderr) == ("server", "wrong")

    def test_escaped_component_name_round_trips_through_the_parser(self) -> None:
        patches = build_component_container_patches(
            _context(component="ser~v/er", container="wrong", image=PATCHED)
        )

        result = _kustomize(_resources(), patches)

        assert result.returncode != 0
        assert f"{GUARD_KEY_PREFIX}ser~0v~1er~1wrong/image" in result.stderr
        assert parse_guard_failure(result.stderr) == ("ser~v/er", "wrong")


class TestEnvOnly:
    def test_output_is_byte_identical_to_the_env_merge_alone(self) -> None:
        # SC-002: the env-only guard saves, removes and restores the image, changing nothing.
        patches = build_component_container_patches(
            _context(env_vars={"LOG_LEVEL": "debug", "NEW_VAR": "x"})
        )
        merges_only = [tp for tp in patches if isinstance(tp.patch, ContainerEnvPatch)]
        assert len(merges_only) < len(patches)

        with_guard = _kustomize(_resources(), patches)
        without_guard = _kustomize(_resources(), merges_only)

        assert with_guard.returncode == 0, with_guard.stderr
        assert without_guard.returncode == 0, without_guard.stderr
        assert with_guard.stdout == without_guard.stdout
        docs = {doc["kind"]: doc for doc in yaml.safe_load_all(with_guard.stdout)}
        for kind in ("Deployment", "StatefulSet"):
            main = _containers(docs[kind])["main"]
            assert main["image"] == "chart/main:1.0"
            assert {e["name"]: e.get("value") for e in main["env"]} == {
                "CHART_VAR": "chart",
                "LOG_LEVEL": "debug",
                "NEW_VAR": "x",
            }

    def test_wrong_container_name_fails_with_guard_key_and_no_output(self) -> None:
        patches = build_component_container_patches(
            _context(container="wrong", env_vars={"LOG_LEVEL": "debug"})
        )

        result = _kustomize(_resources(), patches)

        assert result.returncode != 0
        assert result.stdout == ""
        assert f"{GUARD_KEY_PREFIX}server~1wrong/image" in result.stderr
        assert parse_guard_failure(result.stderr) == ("server", "wrong")


class TestUnmatchedKind:
    def test_kind_matching_nothing_is_a_no_op(self) -> None:
        patches = build_component_container_patches(
            _context(env_vars={"LOG_LEVEL": "debug"}, image=PATCHED)
        )
        deployment_only = [tp for tp in patches if tp.target.kind == "Deployment"]
        assert len(deployment_only) < len(patches)

        all_kinds = _kustomize(_resources(with_statefulset=False), patches)
        matched_only = _kustomize(_resources(with_statefulset=False), deployment_only)

        assert all_kinds.returncode == 0, all_kinds.stderr
        assert all_kinds.stdout == matched_only.stdout
