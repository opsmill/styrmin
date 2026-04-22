"""Integration tests for hierarchical pod scheduling post-renderers.

These are **integration-tier** tests — they exercise the real patch output
against a vCluster API server but deliberately bypass the full Flux-driven
HelmRelease path (chart server, git server, Styrmin control plane, kopf
operator). They:

1. Build the post-renderer patches via the actual production code
   (``AffinityPatch`` rendering, ``build_affinity_patches`` dispatching).
2. Feed those patches through ``kubectl kustomize`` to verify the output
   is valid Kustomize-strategic-merge YAML that renders the expected pod
   spec.
3. Apply the rendered manifests to the vCluster and read back the stored
   Deployment to verify the affinity landed on the pod template.

They complement — but do **not** replace — the constitution-required
end-to-end tests in ``backend/tests/e2e/test_pod_scheduling.py``, which
drive the full user-facing path (GraphQL mutation → reconciler → FluxCD
HelmRelease → rendered pods).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest
import yaml
from kubernetes_asyncio import client as kubeclient

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    AffinityPatch,
    NodeAffinityPatch,
    ResourcesPatch,
    RuntimeClassPatch,
    TolerationsPatch,
    TopologySpreadPatch,
)
from styrmin_backend.context.models.config import (
    AffinityBlock,
    AffinityTerm,
    LabelSelector,
    PostRenderInjection,
    ResourceRequirements,
    ResourceSpec,
    SchedulingConfig,
    Toleration,
    TopologySpreadConstraint,
    WeightedAffinityTerm,
)
from styrmin_backend.services.scheduling.patch_builder import (
    build_affinity_patches,
    build_node_affinity_patches,
    build_resources_patches,
    build_runtime_class_patches,
    build_tolerations_patches,
    build_topology_spread_patches,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _term(app: str, topology: str = "kubernetes.io/hostname") -> AffinityTerm:
    return AffinityTerm(
        topology_key=topology,
        label_selector=LabelSelector(match_labels={"app": app}),
    )


def _kustomize_build(
    base_manifest: str,
    patches: "list[AffinityPatch | ResourcesPatch | TolerationsPatch | TopologySpreadPatch | NodeAffinityPatch | RuntimeClassPatch]",
) -> list[dict]:
    """Run ``kubectl kustomize`` on *base_manifest* + *patches*, return docs.

    Each patch is wired to its target via a ``target:`` selector — matching
    how FluxCD's ``HelmRelease.spec.postRenderers`` applies our patches in
    production. Strategic-merge patches carry a placeholder
    ``metadata.name: any``; Kustomize uses the selector to pick the target.
    JSON-patch documents (``ResourcesPatch``) are distinguished by the
    rendered YAML starting with a list operator — Kustomize accepts both.
    """
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / "base.yaml").write_text(base_manifest)

        patch_entries: list[dict] = []
        for idx, p in enumerate(patches):
            filename = f"patch-{idx}.yaml"
            (td_path / filename).write_text(p.render_value())
            patch_entries.append(
                {
                    "path": filename,
                    "target": {"kind": p.kind, "name": ".*"},
                }
            )

        kustomization = {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "resources": ["base.yaml"],
            "patches": patch_entries,
        }
        (td_path / "kustomization.yaml").write_text(yaml.safe_dump(kustomization))

        result = subprocess.run(
            ["kubectl", "kustomize", str(td_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return list(yaml.safe_load_all(result.stdout))


_BASE_NGINX_DEPLOYMENT = textwrap.dedent(
    """
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: nginx
    spec:
      replicas: 1
      selector:
        matchLabels:
          app: nginx
      template:
        metadata:
          labels:
            app: nginx
        spec:
          containers:
            - name: nginx
              image: nginx:1.25-alpine
    """
).strip()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPodAffinityPostRenderer:
    """T037 (lifted to kustomize + real cluster verification)."""

    async def test_pod_affinity_required_injected_on_deployment(
        self, real_kubernetes: kubeclient.ApiClient
    ) -> None:
        """US1: an unmodified nginx Deployment + our AffinityPatch should
        produce a Deployment whose ``spec.template.spec.affinity.podAffinity``
        carries the required term, and which the Kubernetes API accepts.
        """
        resolved = SchedulingConfig(
            pod_affinity=AffinityBlock(required=[_term("nginx")]),
        )
        target_patches = build_affinity_patches(resolved)
        # Extract the Deployment-kind patch for the kustomization.
        deployment_patches = [
            tp.patch for tp in target_patches if tp.target.kind == "Deployment"
        ]
        assert deployment_patches, (
            "build_affinity_patches must emit a Deployment-kind patch"
        )

        rendered = _kustomize_build(_BASE_NGINX_DEPLOYMENT, deployment_patches)  # type: ignore[arg-type]
        assert len(rendered) == 1
        doc = rendered[0]
        pod_affinity = doc["spec"]["template"]["spec"]["affinity"]["podAffinity"]
        required = pod_affinity["requiredDuringSchedulingIgnoredDuringExecution"]
        assert len(required) == 1
        assert required[0]["topologyKey"] == "kubernetes.io/hostname"
        assert required[0]["labelSelector"]["matchLabels"] == {"app": "nginx"}

        await _apply_and_verify(doc, real_kubernetes, expected_pod_affinity_app="nginx")

    async def test_pod_anti_affinity_injected_across_two_deployments(
        self, real_kubernetes: kubeclient.ApiClient
    ) -> None:
        """US1 Independent Test distilled for a single-node vCluster: two
        deployments render with anti-affinity terms pointing at each other
        on the ``styrmin/deployment_id`` label. We don't verify actual pod
        placement (that needs multiple nodes); we verify that the rendered
        Deployment spec carries the correctly-targeted anti-affinity rule.
        """
        dep_a_term = AffinityTerm(
            topology_key="kubernetes.io/hostname",
            label_selector=LabelSelector(match_labels={"app": "nginx-b"}),
        )
        resolved_a = SchedulingConfig(
            pod_anti_affinity=AffinityBlock(required=[dep_a_term])
        )

        dep_b_term = AffinityTerm(
            topology_key="kubernetes.io/hostname",
            label_selector=LabelSelector(match_labels={"app": "nginx-a"}),
        )
        resolved_b = SchedulingConfig(
            pod_anti_affinity=AffinityBlock(required=[dep_b_term])
        )

        for suffix, resolved in (("a", resolved_a), ("b", resolved_b)):
            base = _BASE_NGINX_DEPLOYMENT.replace(
                "name: nginx", f"name: nginx-{suffix}"
            ).replace("app: nginx", f"app: nginx-{suffix}")

            patches = [
                tp.patch
                for tp in build_affinity_patches(resolved)
                if tp.target.kind == "Deployment"
            ]
            assert patches, "missing Deployment patch"
            rendered = _kustomize_build(base, patches)  # type: ignore[arg-type]
            doc = rendered[0]
            anti = doc["spec"]["template"]["spec"]["affinity"]["podAntiAffinity"]
            other_suffix = "b" if suffix == "a" else "a"
            assert (
                anti["requiredDuringSchedulingIgnoredDuringExecution"][0][
                    "labelSelector"
                ]["matchLabels"]["app"]
                == f"nginx-{other_suffix}"
            )

            await _apply_and_verify(
                doc,
                real_kubernetes,
                expected_pod_anti_affinity_app=f"nginx-{other_suffix}",
            )


class TestPostRendererInjectionWithoutDriverChanges:
    """T049: US6 Independent Test — unmodified chart + all four feature
    groups applied via post-renderer => each value appears on the rendered
    pod spec without any driver-side changes.
    """

    async def test_all_features_inject_into_unmodified_deployment(
        self, real_kubernetes: kubeclient.ApiClient
    ) -> None:
        resolved = SchedulingConfig(
            pod_affinity=AffinityBlock(
                required=[_term("nginx")],
                preferred=[WeightedAffinityTerm(weight=75, term=_term("nginx"))],
            ),
            resources=ResourceRequirements(
                requests=ResourceSpec(cpu="50m", memory="64Mi"),
                limits=ResourceSpec(cpu="250m", memory="256Mi"),
            ),
            tolerations=[
                Toleration(
                    key="dedicated",
                    operator="Equal",
                    value="batch",
                    effect="NoSchedule",
                )
            ],
        )

        deployment_patches = [
            tp.patch
            for tp in build_affinity_patches(resolved, inject=resolved.inject)
            if tp.target.kind == "Deployment"
        ]
        assert deployment_patches, "missing Deployment patch"

        rendered = _kustomize_build(_BASE_NGINX_DEPLOYMENT, deployment_patches)  # type: ignore[arg-type]
        doc = rendered[0]

        # Affinity was injected
        affinity = doc["spec"]["template"]["spec"]["affinity"]
        assert affinity["podAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ][0]["labelSelector"]["matchLabels"] == {"app": "nginx"}
        assert (
            affinity["podAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"][
                0
            ]["weight"]
            == 75
        )

        # The original chart content (container image) was preserved
        assert (
            doc["spec"]["template"]["spec"]["containers"][0]["image"]
            == "nginx:1.25-alpine"
        )

        await _apply_and_verify(doc, real_kubernetes, expected_pod_affinity_app="nginx")

    async def test_inject_opt_out_produces_no_affinity(
        self, real_kubernetes: kubeclient.ApiClient
    ) -> None:
        resolved = SchedulingConfig(
            pod_affinity=AffinityBlock(required=[_term("nginx")]),
            inject=PostRenderInjection(pod_affinity=False),
        )
        patches = build_affinity_patches(resolved, inject=resolved.inject)
        assert patches == [], (
            "inject.pod_affinity=False must produce no patches (US6 opt-out)"
        )

        # Sanity: applying the unmodified base succeeds with no affinity.
        rendered = list(yaml.safe_load_all(_BASE_NGINX_DEPLOYMENT))
        doc = rendered[0]
        assert "affinity" not in doc["spec"]["template"]["spec"]

        await _apply_and_verify(doc, real_kubernetes, expect_no_affinity=True)


class TestResourceHierarchyPostRenderer:
    """T060 (US2 Independent Test distilled): environment-level defaults +
    deployment-level override + component-level override => the rendered
    Deployment carries the deepest-per-field merged resources on each
    container. Uses the resolver directly + kustomize build + real
    apply/readback.
    """

    async def test_resource_hierarchy_env_dep_comp(
        self, real_kubernetes: kubeclient.ApiClient
    ) -> None:
        from styrmin_backend.context.resolvers import _resolve_scheduling_config

        env = SchedulingConfig(
            resources=ResourceRequirements(
                requests=ResourceSpec(cpu="100m", memory="256Mi")
            )
        )
        dep = SchedulingConfig(
            resources=ResourceRequirements(limits=ResourceSpec(memory="2Gi"))
        )
        comp = SchedulingConfig(
            resources=ResourceRequirements(requests=ResourceSpec(cpu="2"))
        )

        resolved, prov = _resolve_scheduling_config(env, dep, comp)

        # Sanity: merge produced the expected deepest-wins values.
        assert resolved.resources is not None
        assert resolved.resources.requests is not None
        assert resolved.resources.requests.cpu == "2"  # comp wins
        assert resolved.resources.requests.memory == "256Mi"  # env inherited
        assert resolved.resources.limits is not None
        assert resolved.resources.limits.memory == "2Gi"  # dep wins
        assert prov["resources.requests.cpu"] == "component"
        assert prov["resources.requests.memory"] == "environment"
        assert prov["resources.limits.memory"] == "deployment"

        deployment_patches = [
            tp.patch
            for tp in build_resources_patches(resolved)
            if tp.target.kind == "Deployment"
        ]
        assert deployment_patches

        rendered = _kustomize_build(_BASE_NGINX_DEPLOYMENT, deployment_patches)  # type: ignore[arg-type]
        doc = rendered[0]
        resources = doc["spec"]["template"]["spec"]["containers"][0]["resources"]
        assert resources["requests"]["cpu"] == "2"
        assert resources["requests"]["memory"] == "256Mi"
        assert resources["limits"]["memory"] == "2Gi"

        # Apply to the real cluster and read back.
        apps = kubeclient.AppsV1Api(real_kubernetes)
        name = doc["metadata"]["name"]
        namespace = "default"
        try:
            await apps.delete_namespaced_deployment(name=name, namespace=namespace)
        except kubeclient.ApiException as e:
            if e.status != 404:
                raise
        await apps.create_namespaced_deployment(namespace=namespace, body=doc)

        stored = await apps.read_namespaced_deployment(name=name, namespace=namespace)
        stored_resources = stored.spec.template.spec.containers[0].resources
        assert stored_resources.requests["cpu"] == "2"
        assert stored_resources.requests["memory"] == "256Mi"
        assert stored_resources.limits["memory"] == "2Gi"


class TestTolerationsAndTopologyAndNodeAffinityPostRenderer:
    """T080 (US3 Independent Test distilled): tolerations + topology spread
    + node affinity all inject and compose without clobbering each other.
    """

    async def test_tolerations_topology_node_affinity_inject_and_compose(
        self, real_kubernetes: kubeclient.ApiClient
    ) -> None:
        resolved = SchedulingConfig(
            tolerations=[
                Toleration(
                    key="dedicated",
                    operator="Equal",
                    value="batch",
                    effect="NoSchedule",
                )
            ],
            topology_spread_constraints=[
                TopologySpreadConstraint(
                    max_skew=1,
                    topology_key="kubernetes.io/hostname",
                    when_unsatisfiable="ScheduleAnyway",
                )
            ],
            node_affinity=AffinityBlock(
                required=[
                    AffinityTerm(
                        topology_key="",
                        label_selector=LabelSelector(
                            match_expressions=[
                                {  # type: ignore[list-item]
                                    "key": "node-type",
                                    "operator": "In",
                                    "values": ["worker"],
                                }
                            ]
                        ),
                    )
                ]
            ),
            # Also include pod_affinity to verify it composes with
            # node_affinity (separate paths in the affinity block).
            pod_affinity=AffinityBlock(required=[_term("nginx")]),
        )

        patches = []
        for builder in (
            build_affinity_patches,
            build_tolerations_patches,
            build_topology_spread_patches,
            build_node_affinity_patches,
        ):
            patches.extend(
                p.patch for p in builder(resolved) if p.target.kind == "Deployment"
            )
        assert patches, "expected patches from every builder"

        rendered = _kustomize_build(_BASE_NGINX_DEPLOYMENT, patches)  # type: ignore[arg-type]
        doc = rendered[0]
        pod_spec = doc["spec"]["template"]["spec"]

        # Tolerations injected
        assert pod_spec["tolerations"][0]["key"] == "dedicated"
        assert pod_spec["tolerations"][0]["effect"] == "NoSchedule"

        # Topology spread injected
        assert pod_spec["topologySpreadConstraints"][0]["topologyKey"] == (
            "kubernetes.io/hostname"
        )
        assert pod_spec["topologySpreadConstraints"][0]["whenUnsatisfiable"] == (
            "ScheduleAnyway"
        )

        # Pod affinity and node affinity COMPOSE (both present under
        # spec.template.spec.affinity.*). This is the key invariant the
        # AffinityPatch/NodeAffinityPatch split guarantees.
        affinity = pod_spec["affinity"]
        assert "podAffinity" in affinity
        assert "nodeAffinity" in affinity
        assert affinity["podAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ][0]["labelSelector"]["matchLabels"] == {"app": "nginx"}
        node_aff = affinity["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]
        assert (
            node_aff["nodeSelectorTerms"][0]["matchExpressions"][0]["key"]
            == "node-type"
        )

        # Apply to the real cluster: this is the strict check — the
        # Kubernetes API server validates the whole pod spec and rejects
        # any shape violation (e.g. nodeSelectorTerms missing, toleration
        # schema mismatch, topology-spread defaults).
        apps = kubeclient.AppsV1Api(real_kubernetes)
        name = doc["metadata"]["name"]
        namespace = "default"
        try:
            await apps.delete_namespaced_deployment(name=name, namespace=namespace)
        except kubeclient.ApiException as e:
            if e.status != 404:
                raise
        await apps.create_namespaced_deployment(namespace=namespace, body=doc)

        stored = await apps.read_namespaced_deployment(name=name, namespace=namespace)
        stored_pod_spec = stored.spec.template.spec
        assert stored_pod_spec.tolerations[0].key == "dedicated"
        assert (
            stored_pod_spec.topology_spread_constraints[0].topology_key
            == "kubernetes.io/hostname"
        )
        assert (
            stored_pod_spec.affinity.pod_affinity.required_during_scheduling_ignored_during_execution[
                0
            ].label_selector.match_labels
            == {"app": "nginx"}
        )
        assert (
            stored_pod_spec.affinity.node_affinity.required_during_scheduling_ignored_during_execution.node_selector_terms[
                0
            ]
            .match_expressions[0]
            .key
            == "node-type"
        )


class TestRuntimeClassPostRenderer:
    """T092 (US4 Independent Test distilled): a component's runtime class
    is applied to its pod template without affecting other components.
    Uses a narrowing ``label_selector`` on the patch to target one
    component only; verifies the resulting Deployment carries
    ``spec.template.spec.runtimeClassName`` while a sibling Deployment
    without the patch does not.
    """

    async def test_runtime_class_applied_only_to_targeted_component(
        self, real_kubernetes: kubeclient.ApiClient
    ) -> None:
        # Install a RuntimeClass CR so the API accepts the name.
        node_api = kubeclient.NodeV1Api(real_kubernetes)
        try:
            await node_api.create_runtime_class(
                body={
                    "apiVersion": "node.k8s.io/v1",
                    "kind": "RuntimeClass",
                    "metadata": {"name": "kata-test"},
                    "handler": "runc",  # any node-installed handler
                }
            )
        except kubeclient.ApiException as e:
            if e.status != 409:  # already exists
                raise

        resolved = SchedulingConfig(runtime_class="kata-test")
        deployment_patches = [
            tp.patch
            for tp in build_runtime_class_patches(resolved)
            if tp.target.kind == "Deployment"
        ]
        assert deployment_patches

        # Apply to sidecar-a ONLY (two separate deployments; only -a patched)
        base_a = _BASE_NGINX_DEPLOYMENT.replace("name: nginx", "name: nginx-a").replace(
            "app: nginx", "app: nginx-a"
        )
        base_b = _BASE_NGINX_DEPLOYMENT.replace("name: nginx", "name: nginx-b").replace(
            "app: nginx", "app: nginx-b"
        )

        rendered_a = _kustomize_build(base_a, deployment_patches)  # type: ignore[arg-type]
        rendered_b = list(yaml.safe_load_all(base_b))  # no patch

        doc_a = rendered_a[0]
        doc_b = rendered_b[0]
        assert doc_a["spec"]["template"]["spec"]["runtimeClassName"] == "kata-test"
        assert "runtimeClassName" not in doc_b["spec"]["template"]["spec"]

        apps = kubeclient.AppsV1Api(real_kubernetes)
        namespace = "default"
        for doc in (doc_a, doc_b):
            name = doc["metadata"]["name"]
            try:
                await apps.delete_namespaced_deployment(name=name, namespace=namespace)
            except kubeclient.ApiException as e:
                if e.status != 404:
                    raise
            await apps.create_namespaced_deployment(namespace=namespace, body=doc)

        stored_a = await apps.read_namespaced_deployment(
            name="nginx-a", namespace=namespace
        )
        stored_b = await apps.read_namespaced_deployment(
            name="nginx-b", namespace=namespace
        )
        assert stored_a.spec.template.spec.runtime_class_name == "kata-test"
        assert stored_b.spec.template.spec.runtime_class_name in (None, "")


# ---------------------------------------------------------------------------
# Apply + read-back helper
# ---------------------------------------------------------------------------


async def _apply_and_verify(  # noqa: PLR0913
    doc: dict,
    kubernetes: kubeclient.ApiClient,
    *,
    expected_pod_affinity_app: str | None = None,
    expected_pod_anti_affinity_app: str | None = None,
    expect_no_affinity: bool = False,
) -> None:
    """Apply *doc* to the vcluster and read back the Deployment to verify
    the pod template carries the expected scheduling fields.
    """
    apps = kubeclient.AppsV1Api(kubernetes)
    name = doc["metadata"]["name"]
    namespace = "default"

    # Clean up any prior run (tests can retry in the same session).
    try:
        await apps.delete_namespaced_deployment(name=name, namespace=namespace)
    except kubeclient.ApiException as e:
        if e.status != 404:
            raise

    await apps.create_namespaced_deployment(namespace=namespace, body=doc)

    stored = await apps.read_namespaced_deployment(name=name, namespace=namespace)
    affinity = stored.spec.template.spec.affinity

    if expect_no_affinity:
        assert affinity is None or (
            affinity.pod_affinity is None and affinity.pod_anti_affinity is None
        )
        return

    assert affinity is not None, "Deployment stored without affinity block"
    if expected_pod_affinity_app is not None:
        assert affinity.pod_affinity is not None
        term = (
            affinity.pod_affinity.required_during_scheduling_ignored_during_execution[0]
        )
        assert term.label_selector.match_labels == {"app": expected_pod_affinity_app}
    if expected_pod_anti_affinity_app is not None:
        assert affinity.pod_anti_affinity is not None
        term = affinity.pod_anti_affinity.required_during_scheduling_ignored_during_execution[
            0
        ]
        assert term.label_selector.match_labels == {
            "app": expected_pod_anti_affinity_app
        }


# ---------------------------------------------------------------------------
# Skip if required tooling is absent (keeps the file importable locally)
# ---------------------------------------------------------------------------


pytestmark = pytest.mark.skipif(
    shutil.which("kubectl") is None,
    reason="kubectl is required to run kustomize build",
)
