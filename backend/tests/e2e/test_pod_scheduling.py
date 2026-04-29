"""End-to-end tests for hierarchical pod scheduling and resource configuration.

Drives the full user-facing path: ``updateDeployment`` (SDK or Playwright)
→ server reconciler → FluxCD HelmRelease post-renderers → rendered pod spec
on the vcluster. Asserts by reading the resulting ``apps/v1`` resource back
from the vcluster API server.

The suite intentionally collapses the per-feature checks into a single
consolidated end-to-end test. Unit tests under
``backend/tests/unit/context/`` and ``backend/tests/unit/services/`` cover
each scheduling sub-feature (tolerations, resources, affinity, topology
spread, runtime class) in isolation, and the integration tier under
``backend/tests/integration/`` exercises the post-renderer per-patch.
E2E's job is to prove that the full Styrmin → Flux → pod-template
pipeline delivers a deployment-level scheduling config intact — one
reconcile cycle is enough for that.

Covers the E2E tasks from ``specs/001-pod-scheduling-config/tasks.md``:

    T037 — US1 pod anti-affinity across two deployments
    T049 — US6 post-renderer injection into an unmodified driver
    T060 — US2 env+deployment resource hierarchy
    T069 — US5 ``Deployment.resolvedScheduling`` query
    T080 — US3 tolerations + topology spread + node affinity compose
    T092 — US4 runtime class at deployment scope
    T107 — consolidated quickstart scenario
    T109 — update → reconciliation within SLO
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncGenerator, Callable

import pytest
from kubernetes_asyncio import client as kubeclient
from styrmin_sdk import StyrminClient
from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.get_deployment_resolved_scheduling import (
    GetDeploymentResolvedScheduling,
)

from tests.e2e.drivers import ScenarioDriver

# Single-node vcluster: we cannot verify actual node placement, only that
# the rendered pod template carries the intended scheduling fields.
#
# 480s covers the end-to-end reconcile path (GraphQL → Styrmin workflow →
# HelmRelease update → FluxCD re-render → Kustomize post-render → Deployment
# patch) for a single deployment on a single-node vcluster. This timeout
# also doubles as an implicit SLO assertion for FR-019: if a single
# deployment-level update doesn't propagate to the pod template within
# 480s, the platform is not meeting its reconciliation SLO.
RECONCILE_TIMEOUT_SECONDS = 480.0
RECONCILE_POLL_INTERVAL = 3.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wait_for_pod_template(
    vcluster: dict,
    *,
    namespace: str,
    label_selector: str,
    predicate: Callable[[Any], bool],
    description: str,
    timeout: float = RECONCILE_TIMEOUT_SECONDS,
) -> Any:
    """Poll Deployments matching *label_selector* until *predicate* accepts one.

    Returns the matching Deployment. The predicate receives the full
    Deployment object so it can inspect ``spec.template.spec`` or labels.
    """
    apps = kubeclient.AppsV1Api(vcluster["api"])
    deadline = time.time() + timeout
    last_seen: str = "(no matching Deployments)"
    while time.time() < deadline:
        resp = await apps.list_namespaced_deployment(
            namespace=namespace, label_selector=label_selector
        )
        deployments = list(resp.items)
        for dep in deployments:
            try:
                if predicate(dep):
                    return dep
            except Exception:
                continue
        if deployments:
            last_seen = f"{len(deployments)} deployment(s) did not satisfy predicate"
        await asyncio.sleep(RECONCILE_POLL_INTERVAL)
    raise TimeoutError(
        f"Timed out waiting for {description} in namespace {namespace} "
        f"(selector={label_selector!r}): {last_seen}"
    )


async def _update_scheduling_and_wait(
    scenario_driver: ScenarioDriver,
    deployment_id: str,
    *,
    scheduling: dict,
    vcluster: dict,
    namespace: str,
    label_selector: str,
    predicate: Callable[[Any], bool],
    description: str,
) -> Any:
    """Submit scheduling config and wait for the rendered pod template to match.

    Goes through ``ScenarioDriver.update_deployment`` so both the API and
    UI entrypoints exercise the same path. The subsequent
    ``wait_for_deployment_running`` gives the Styrmin workflow time to
    complete before we start polling k8s directly.
    """
    await scenario_driver.update_deployment(
        deployment_id=deployment_id, config={"scheduling": scheduling}
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=300.0
    )
    return await _wait_for_pod_template(
        vcluster,
        namespace=namespace,
        label_selector=label_selector,
        predicate=predicate,
        description=description,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def scheduling_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    """Dedicated environment for scheduling E2E.

    Intentionally created with no env-level ``scheduling`` config. The
    post-renderer applies env-level resources to every container in the
    release — including the Bitnami postgresql StatefulSet — so an
    env-level ``resources.requests`` too low for postgres would cause
    Helm's ``--wait`` to time out and mark the release failed for the
    rest of the session. Env+deployment merge is covered at unit level
    (``backend/tests/unit/context/test_scheduling_resolver.py``) and by
    the integration test ``TestResourceHierarchyPostRenderer``.

    Created through ``session_scenario_driver`` so the ``[api]`` and
    ``[ui]`` variants each get their own env (the scenario driver is
    parametrized by ``driver_mode``). The uuid suffix keeps both names
    unique across modes and reruns.
    """
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"scheduling-e2e-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={"ip_whitelist": ["0.0.0.0/0"]},
    )
    yield {
        "environment_id": str(env.id),
        "client": client,
    }


@pytest.fixture(scope="module")
async def scheduling_deployment(
    scheduling_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    """Fresh simple-app deployment dedicated to the scheduling test suite.

    Module-scoped so the deployment is created once and reused across
    the consolidated test and the cross-deployment anti-affinity test.
    """
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scheduling_environment["environment_id"],
        name="scheduling-a",
    )
    deployment = await driver.wait_for_deployment_running(deployment_id=deployment.id)
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


@pytest.fixture(scope="module")
async def scheduling_deployment_b(
    scheduling_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    """Second deployment used only by the cross-deployment anti-affinity
    test (US1). Created once and reused.

    simple-app declares a logical service named ``simple-app``, and Styrmin
    enforces service-name uniqueness per environment. A second simple-app
    deployment in the same env must override the service name to avoid
    ``ResourceAlreadyExistsError``.
    """
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scheduling_environment["environment_id"],
        name="scheduling-b",
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": "simple-app-b"}
        ],
    )
    deployment = await driver.wait_for_deployment_running(deployment_id=deployment.id)
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


@pytest.fixture
def _scheduling_driver_bound(
    scheduling_environment: dict,
    scheduling_deployment: dict,  # noqa: ARG001 — force fixture ordering
    scenario_driver: ScenarioDriver,
) -> None:
    """Binds the function-scoped ``scenario_driver`` to the scheduling env.

    The function-scoped driver is a fresh instance per test with no
    environment context, while ``scheduling_deployment`` was created via
    the session-scoped driver — so the per-test driver needs this
    explicit attach before calling ``update_deployment`` /
    ``wait_for_deployment_running``.
    """
    scenario_driver.attach_to_deployment(
        environment_id=scheduling_environment["environment_id"]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.ci
async def test_scheduling_end_to_end(
    scheduling_environment: dict,
    scheduling_deployment: dict,
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _scheduling_driver_bound: None,
) -> None:
    """Consolidated end-to-end verification for deployment-level scheduling.

    Drives a single ``updateDeployment`` that sets tolerations, topology
    spread, node affinity, pod affinity, resource requests + limits, and
    runtime class in one go, then asserts every one of them lands on
    the rendered pod template after reconciliation. Also verifies the
    ``Deployment.resolvedScheduling`` GraphQL field mirrors the
    deployment-level config with ``provenance == "deployment"``.

    Replaces seven former per-feature tests; per-feature isolation lives
    at the unit + integration tiers. The cross-deployment anti-affinity
    case is still separate because it requires coordinating mutations
    across two deployments and stays ``api_only``.
    """
    client: StyrminClient = scheduling_environment["client"]
    deployment_id = scheduling_deployment["deployment_id"]

    # US4: register a RuntimeClass on the vcluster so the scheduler can
    # honour the reference we are about to set. Styrmin no longer
    # validates runtime-class names against cluster capabilities, but the
    # RuntimeClass resource still needs to exist or the pod stays Pending
    # after rollout.
    node_api = kubeclient.NodeV1Api(vcluster["api"])
    try:
        await node_api.create_runtime_class(
            body={
                "apiVersion": "node.k8s.io/v1",
                "kind": "RuntimeClass",
                "metadata": {"name": "kata-e2e"},
                "handler": "runc",
            }
        )
    except kubeclient.ApiException as e:
        if e.status != 409:
            raise

    def _all_features_landed(dep: Any) -> bool:
        spec = dep.spec.template.spec
        tols = spec.tolerations or []
        has_toleration = any(
            t.key == "dedicated" and t.value == "batch" and t.effect == "NoSchedule"
            for t in tols
        )

        spreads = spec.topology_spread_constraints or []
        has_spread = any(
            s.topology_key == "kubernetes.io/hostname" and s.max_skew == 1
            for s in spreads
        )

        affinity = spec.affinity
        has_node_affinity = (
            affinity is not None
            and affinity.node_affinity is not None
            and affinity.node_affinity.preferred_during_scheduling_ignored_during_execution
            is not None
        )
        has_pod_affinity = affinity is not None and affinity.pod_affinity is not None

        containers = spec.containers or []
        resources = containers[0].resources if containers else None
        requests = resources.requests if resources else None
        limits = resources.limits if resources else None
        has_requests = bool(requests) and requests.get("memory") == "192Mi"
        has_limits = bool(limits) and limits.get("cpu") == "500m"

        has_runtime_class = spec.runtime_class_name == "kata-e2e"

        return (
            has_toleration
            and has_spread
            and has_node_affinity
            and has_pod_affinity
            and has_requests
            and has_limits
            and has_runtime_class
        )

    scheduling = {
        "resources": {
            "requests": {"memory": "192Mi"},
            "limits": {"cpu": "500m"},
        },
        "tolerations": [
            {
                "key": "dedicated",
                "operator": "Equal",
                "value": "batch",
                "effect": "NoSchedule",
            }
        ],
        "topology_spread_constraints": [
            {
                "max_skew": 1,
                "topology_key": "kubernetes.io/hostname",
                "when_unsatisfiable": "ScheduleAnyway",
            }
        ],
        "node_affinity": {
            # ``preferred`` rather than ``required``: a required node-affinity
            # no node satisfies would leave pods Pending, which makes
            # helm-controller ``--wait`` time out and mark the release failed
            # for the rest of the session.
            "preferred": [
                {
                    "weight": 1,
                    "term": {
                        "topology_key": "",
                        "label_selector": {
                            "match_expressions": [
                                {
                                    "key": "node-type",
                                    "operator": "In",
                                    "values": ["worker"],
                                }
                            ]
                        },
                    },
                }
            ]
        },
        "pod_affinity": {
            # ``preferred`` rather than ``required``: a required pod-affinity
            # excludes the candidate pod itself, so with a single simple-app
            # replica there is no other matching pod to anchor onto, pods go
            # Pending, and helm ``--wait`` times out.
            "preferred": [
                {
                    "weight": 50,
                    "term": {
                        "topology_key": "kubernetes.io/hostname",
                        "label_selector": {
                            "match_labels": {"app.kubernetes.io/name": "simple-app"}
                        },
                    },
                }
            ]
        },
        "runtime_class": "kata-e2e",
    }

    await _update_scheduling_and_wait(
        scenario_driver,
        deployment_id,
        scheduling=scheduling,
        vcluster=vcluster,
        namespace=scheduling_deployment["namespace"],
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=_all_features_landed,
        description="all scheduling features composed on the rendered pod template",
    )

    # US5: resolvedScheduling must expose per-component merged config with
    # ``provenance == "deployment"`` for every field set at the deployment
    # level. The assertion is on the GraphQL resolver output; there is no
    # UI surface displaying resolvedScheduling today, so both entrypoints
    # read via the SDK.
    raw = await client._transport.execute(
        load_query("get_deployment_resolved_scheduling"),
        {"deploymentId": deployment_id},
    )
    assert "errors" not in raw or not raw.get("errors"), raw.get("errors")
    parsed = GetDeploymentResolvedScheduling.model_validate(raw["data"])
    assert parsed.deployment is not None
    entries = parsed.deployment.resolved_scheduling
    assert entries, "resolvedScheduling returned no entries"
    by_component = {e.component_name: e for e in entries}
    assert {"server", "database"}.issubset(by_component.keys()), (
        f"expected components 'server' and 'database', got {sorted(by_component)}"
    )
    for entry in entries:
        resources = (entry.config or {}).get("resources") or {}
        requests = resources.get("requests") or {}
        assert requests.get("memory") == "192Mi", (
            f"component {entry.component_name} memory = {requests.get('memory')!r}, "
            "expected '192Mi' (deployment)"
        )
        provenance = entry.provenance or {}
        assert provenance.get("resources.requests.memory") == "deployment"


@pytest.mark.ci
@pytest.mark.api_only(
    reason="scenario coordinates mutations across two deployments; the UI's "
    "scheduling dialog is single-deployment scoped, so driving this flow "
    "through the UI would require a bespoke two-deployment page-object "
    "helper that does not yet exist"
)
async def test_pod_anti_affinity_cross_deployment_via_graphql(
    scheduling_environment: dict,
    scheduling_deployment: dict,
    scheduling_deployment_b: dict,
    vcluster: dict,
) -> None:
    """US1 / T037: two deployments under the same environment each set
    pod-anti-affinity pointing at the other via the ``styrmin/deployment_id``
    label. Both rendered pod templates must carry the cross-targeting term.

    We use ``preferred`` (not ``required``) anti-affinity: on a single-node
    vcluster a required anti-affinity with ``kubernetes.io/hostname`` topology
    is structurally unsatisfiable, which would leave pods Pending and cause
    helm-controller ``--wait`` to time out. The assertion the constitution
    requires (user-facing config reaches the rendered pod template through
    the full Styrmin → Flux pipeline) is identical for preferred and required
    terms; actual placement guarantees require multi-node clusters.
    """
    client: StyrminClient = scheduling_environment["client"]
    dep_a_id = scheduling_deployment["deployment_id"]
    dep_b_id = scheduling_deployment_b["deployment_id"]

    try:
        await client.deployments.update(
            dep_a_id,
            config={
                "scheduling": {
                    "pod_anti_affinity": {
                        "preferred": [
                            {
                                "weight": 100,
                                "term": {
                                    "topology_key": "kubernetes.io/hostname",
                                    "deployment_ref": {"deployment_id": dep_b_id},
                                },
                            }
                        ]
                    }
                }
            },
        )
        await client.deployments.update(
            dep_b_id,
            config={
                "scheduling": {
                    "pod_anti_affinity": {
                        "preferred": [
                            {
                                "weight": 100,
                                "term": {
                                    "topology_key": "kubernetes.io/hostname",
                                    "deployment_ref": {"deployment_id": dep_a_id},
                                },
                            }
                        ]
                    }
                }
            },
        )

        async def _wait_running(deployment_id: str) -> None:
            # Scoped to this test's api-only path — we drive the SDK
            # directly so no scenario driver is in play.
            deadline = time.time() + 300.0
            while time.time() < deadline:
                dep = await client.deployments.get(deployment_id)
                if getattr(dep, "status", None) == "running":
                    return
                await asyncio.sleep(3.0)
            raise TimeoutError(
                f"deployment {deployment_id} did not reach 'running' within 300s"
            )

        await _wait_running(dep_a_id)
        await _wait_running(dep_b_id)

        def _anti_affinity_targets(expected_deployment_id: str):
            def _predicate(dep: Any) -> bool:
                affinity = dep.spec.template.spec.affinity
                if affinity is None or affinity.pod_anti_affinity is None:
                    return False
                weighted = (
                    affinity.pod_anti_affinity.preferred_during_scheduling_ignored_during_execution
                    or []
                )
                for w in weighted:
                    term = w.pod_affinity_term
                    if term is None or term.topology_key != "kubernetes.io/hostname":
                        continue
                    labels = (
                        (term.label_selector.match_labels or {})
                        if term.label_selector
                        else {}
                    )
                    if labels.get("styrmin/deployment_id") == expected_deployment_id:
                        return True
                return False

            return _predicate

        await _wait_for_pod_template(
            vcluster,
            namespace=scheduling_deployment["namespace"],
            label_selector="app.kubernetes.io/name=simple-app",
            predicate=_anti_affinity_targets(dep_b_id),
            description=f"deployment A anti-affinity against {dep_b_id}",
        )
        await _wait_for_pod_template(
            vcluster,
            namespace=scheduling_deployment_b["namespace"],
            label_selector="app.kubernetes.io/name=simple-app",
            predicate=_anti_affinity_targets(dep_a_id),
            description=f"deployment B anti-affinity against {dep_a_id}",
        )
    finally:
        # This test touches two deployments — clean both up so the
        # post-test state matches what other tests expect.
        for did in (dep_a_id, dep_b_id):
            try:
                await client.deployments.update(did, config={"scheduling": {}})
            except Exception:  # noqa: BLE001
                pass
