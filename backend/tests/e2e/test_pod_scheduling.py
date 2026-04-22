"""End-to-end tests for hierarchical pod scheduling and resource configuration.

Drives the full user-facing path: GraphQL mutation via ``StyrminClient`` →
server reconciler → FluxCD HelmRelease post-renderers → rendered pod spec
on the vcluster. Asserts by reading the resulting ``apps/v1`` resource back
from the vcluster API server.

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
from typing import Any, AsyncGenerator, Callable

import pytest
from kubernetes_asyncio import client as kubeclient
from styrmin_sdk import StyrminClient
from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.get_deployment_resolved_scheduling import (
    GetDeploymentResolvedScheduling,
)

from tests.e2e.conftest import _wait_for_deployment_running

# Single-node vcluster: we cannot verify actual node placement, only that
# the rendered pod template carries the intended scheduling fields.
#
# 480s is chosen to exceed the observed worst-case end-to-end reconcile path
# (GraphQL mutation → Styrmin workflow → HelmRelease update → FluxCD
# re-render → Kustomize post-render → Deployment patch) under test load on
# a single-node vcluster, where multiple reconciliations serialize.
RECONCILE_TIMEOUT_SECONDS = 480.0
RECONCILE_POLL_INTERVAL = 3.0

# SLO for FR-019. The spec says "platform's normal reconciliation SLO" without
# defining a number; we use the same budget as the other reconciliation waits
# so the test validates propagation (not micro-latency).
UPDATE_SLO_SECONDS = RECONCILE_TIMEOUT_SECONDS


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
    client: StyrminClient,
    deployment_id: str,
    *,
    scheduling: dict,
    vcluster: dict,
    namespace: str,
    label_selector: str,
    predicate: Callable[[Any], bool],
    description: str,
) -> Any:
    """Submit an ``updateDeployment`` with *scheduling* and wait for the
    rendered pod template to satisfy *predicate*.
    """
    await client.deployments.update(deployment_id, config={"scheduling": scheduling})
    await _wait_for_deployment_running(client, deployment_id, timeout=300.0)
    return await _wait_for_pod_template(
        vcluster,
        namespace=namespace,
        label_selector=label_selector,
        predicate=predicate,
        description=description,
    )


async def _clear_scheduling(client: StyrminClient, deployment_id: str) -> None:
    """Reset deployment config so subsequent tests start clean.

    We preserve non-scheduling config by reading the deployment first.
    """
    deployment = await client.deployments.get(deployment_id)
    current = deployment.config if isinstance(deployment.config, dict) else {}
    cleaned = {k: v for k, v in current.items() if k != "scheduling"}
    await client.deployments.update(deployment_id, config=cleaned)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def scheduling_environment(
    styrmin_resources: dict,
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
    """
    client: StyrminClient = styrmin_resources["client"]
    cluster_id = styrmin_resources["cluster_id"]

    env = await client.environments.create(
        name="scheduling-e2e",
        cluster_id=cluster_id,
        config={
            "ip_whitelist": ["127.0.0.1"],
        },
    )
    yield {
        "environment_id": str(env.id),
        "client": client,
    }


@pytest.fixture(scope="module")
async def scheduling_deployment(
    scheduling_environment: dict,
    simple_app_image: str,
    vcluster: dict,
) -> dict:
    """Fresh simple-app deployment dedicated to the scheduling test suite.

    Session-scoped so the deployment is created once and reused across
    tests in this file. Each test sets the full scheduling config it cares
    about, then (via teardown) clears it so the next test starts from a
    known state.
    """
    client: StyrminClient = scheduling_environment["client"]
    task = await client.deployments.create(
        driver="simple-app",
        version="0.1.0",
        environment_id=scheduling_environment["environment_id"],
        name="scheduling-a",
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None
    await _wait_for_deployment_running(client, deployment_id)
    return {
        "deployment_id": str(deployment_id),
        "namespace": f"styrmin-{deployment_id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


@pytest.fixture(scope="module")
async def scheduling_deployment_b(
    scheduling_environment: dict,
    simple_app_image: str,
    vcluster: dict,
) -> dict:
    """Second deployment used only by the cross-deployment anti-affinity
    test (US1). Created once and reused.

    simple-app declares a logical service named ``simple-app``, and Styrmin
    enforces service-name uniqueness per environment. A second simple-app
    deployment in the same env must override the service name to avoid
    ``ResourceAlreadyExistsError``.
    """
    client: StyrminClient = scheduling_environment["client"]
    task = await client.deployments.create(
        driver="simple-app",
        version="0.1.0",
        environment_id=scheduling_environment["environment_id"],
        name="scheduling-b",
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": "simple-app-b"}
        ],
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None
    await _wait_for_deployment_running(client, deployment_id)
    return {
        "deployment_id": str(deployment_id),
        "namespace": f"styrmin-{deployment_id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


@pytest.fixture
async def _reset_scheduling_after_test(
    scheduling_environment: dict,
    scheduling_deployment: dict,
) -> AsyncGenerator[None, None]:
    """Strip scheduling config after each test to avoid cross-test bleed."""
    yield
    try:
        await _clear_scheduling(
            scheduling_environment["client"], scheduling_deployment["deployment_id"]
        )
        await _wait_for_deployment_running(
            scheduling_environment["client"],
            scheduling_deployment["deployment_id"],
            timeout=300.0,
        )
    except Exception:  # noqa: BLE001
        # Teardown errors shouldn't mask the test's own failure.
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.ci
async def test_post_renderer_injects_into_unmodified_driver(
    scheduling_environment: dict,
    scheduling_deployment: dict,
    vcluster: dict,
    _reset_scheduling_after_test: None,
) -> None:
    """US6 / T049: the ``simple-app`` driver's ``values.j2.yml`` does not
    reference ``context.components[*].scheduling``. Setting deployment-level
    scheduling via ``updateDeployment`` therefore proves post-renderer
    injection: any scheduling on the rendered pod template can only have
    come from ``HelmRelease.spec.postRenderers``, not the chart template.
    """
    client = scheduling_environment["client"]

    def _has_tolerations(dep: Any) -> bool:
        tols = dep.spec.template.spec.tolerations or []
        return any(t.key == "dedicated" and t.value == "batch" for t in tols)

    await _update_scheduling_and_wait(
        client,
        scheduling_deployment["deployment_id"],
        scheduling={
            "tolerations": [
                {
                    "key": "dedicated",
                    "operator": "Equal",
                    "value": "batch",
                    "effect": "NoSchedule",
                }
            ]
        },
        vcluster=vcluster,
        namespace=scheduling_deployment["namespace"],
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=_has_tolerations,
        description="toleration injected by post-renderer",
    )


@pytest.mark.ci
async def test_resource_requests_via_graphql(
    scheduling_environment: dict,
    scheduling_deployment: dict,
    vcluster: dict,
    _reset_scheduling_after_test: None,
) -> None:
    """US2 / T060: deployment-level ``resources.requests`` lands on the
    rendered pod template.

    Env-level resources could break the shared postgresql dependency's
    scheduling (see ``scheduling_environment`` docstring), so this E2E
    exercises the deployment → pod pipeline only. Env + deployment merge
    (deepest-wins) is covered by the resolver unit tests and the
    integration test ``TestResourceHierarchyPostRenderer``.
    """
    client = scheduling_environment["client"]

    def _resources_match(dep: Any) -> bool:
        containers = dep.spec.template.spec.containers or []
        if not containers:
            return False
        requests = containers[0].resources.requests if containers[0].resources else None
        if not requests:
            return False
        return requests.get("cpu") == "250m" and requests.get("memory") == "256Mi"

    await _update_scheduling_and_wait(
        client,
        scheduling_deployment["deployment_id"],
        scheduling={
            "resources": {
                "requests": {"cpu": "250m", "memory": "256Mi"},
            }
        },
        vcluster=vcluster,
        namespace=scheduling_deployment["namespace"],
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=_resources_match,
        description="deployment-level resource requests on pod template",
    )


@pytest.mark.ci
async def test_tolerations_topology_node_affinity_compose_via_graphql(
    scheduling_environment: dict,
    scheduling_deployment: dict,
    vcluster: dict,
    _reset_scheduling_after_test: None,
) -> None:
    """US3 / T080: three independent scheduling features set together must
    each appear on the rendered pod spec without clobbering each other.
    """
    client = scheduling_environment["client"]

    def _all_three_present(dep: Any) -> bool:
        spec = dep.spec.template.spec
        tols = spec.tolerations or []
        spreads = spec.topology_spread_constraints or []
        has_toleration = any(
            t.key == "dedicated" and t.effect == "NoSchedule" for t in tols
        )
        has_spread = any(s.topology_key == "kubernetes.io/hostname" for s in spreads)
        node_aff = (
            spec.affinity.node_affinity
            if spec.affinity and spec.affinity.node_affinity
            else None
        )
        # We use ``preferred`` rather than ``required`` below — a required
        # node-affinity that no node satisfies would leave pods Pending,
        # which in turn makes helm-controller ``--wait`` time out and mark
        # the release failed for the rest of the session.
        has_node = (
            node_aff is not None
            and node_aff.preferred_during_scheduling_ignored_during_execution
            is not None
        )
        return has_toleration and has_spread and has_node

    await _update_scheduling_and_wait(
        client,
        scheduling_deployment["deployment_id"],
        scheduling={
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
        },
        vcluster=vcluster,
        namespace=scheduling_deployment["namespace"],
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=_all_three_present,
        description="tolerations + topology spread + node affinity composed",
    )


@pytest.mark.ci
async def test_runtime_class_via_graphql(
    scheduling_environment: dict,
    scheduling_deployment: dict,
    vcluster: dict,
    _reset_scheduling_after_test: None,
) -> None:
    """US4 / T092: register a RuntimeClass on the vcluster, set it through
    ``updateDeployment``, and assert the rendered pod template carries
    ``runtimeClassName``.

    Per-component selectivity is integration-tier only until the public
    API exposes per-component config mutation.
    """
    client = scheduling_environment["client"]
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

    def _has_runtime_class(dep: Any) -> bool:
        return dep.spec.template.spec.runtime_class_name == "kata-e2e"

    await _update_scheduling_and_wait(
        client,
        scheduling_deployment["deployment_id"],
        scheduling={"runtime_class": "kata-e2e"},
        vcluster=vcluster,
        namespace=scheduling_deployment["namespace"],
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=_has_runtime_class,
        description="runtimeClassName=kata-e2e on pod template",
    )


@pytest.mark.ci
async def test_resolved_scheduling_graphql_query(
    scheduling_environment: dict,
    scheduling_deployment: dict,
    vcluster: dict,
    _reset_scheduling_after_test: None,
) -> None:
    """US5 / T069: after configuring deployment-level scheduling, the
    ``Deployment.resolvedScheduling`` GraphQL field must return one entry
    per component, each carrying the fully-merged per-component
    ``SchedulingConfig`` plus provenance.

    This is the exact data that drivers receive under
    ``context.components[*].scheduling`` — so the resolver path is
    exercised end-to-end even without a custom driver template.
    """
    client = scheduling_environment["client"]

    await client.deployments.update(
        scheduling_deployment["deployment_id"],
        config={
            "scheduling": {
                "resources": {
                    "requests": {"memory": "128Mi"},
                }
            }
        },
    )
    await _wait_for_deployment_running(
        client, scheduling_deployment["deployment_id"], timeout=300.0
    )

    raw = await client._transport.execute(
        load_query("get_deployment_resolved_scheduling"),
        {"deploymentId": scheduling_deployment["deployment_id"]},
    )
    assert "errors" not in raw or not raw.get("errors"), raw.get("errors")
    parsed = GetDeploymentResolvedScheduling.model_validate(raw["data"])
    assert parsed.deployment is not None
    entries = parsed.deployment.resolved_scheduling
    assert entries, "resolvedScheduling returned no entries"

    by_component = {e.component_name: e for e in entries}
    # simple-app declares two components; both must appear.
    assert {"server", "database"}.issubset(by_component.keys()), (
        f"expected components 'server' and 'database', got {sorted(by_component)}"
    )

    for entry in entries:
        resources = (entry.config or {}).get("resources") or {}
        requests = resources.get("requests") or {}
        assert requests.get("memory") == "128Mi", (
            f"component {entry.component_name} memory = {requests.get('memory')!r}, expected '128Mi' (deployment)"
        )
        provenance = entry.provenance or {}
        assert provenance.get("resources.requests.memory") == "deployment"


@pytest.mark.ci
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
    client = scheduling_environment["client"]
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
        await _wait_for_deployment_running(client, dep_a_id, timeout=300.0)
        await _wait_for_deployment_running(client, dep_b_id, timeout=300.0)

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
                await _clear_scheduling(client, did)
                await _wait_for_deployment_running(client, did, timeout=300.0)
            except Exception:  # noqa: BLE001
                pass


@pytest.mark.ci
async def test_quickstart_consolidated_scenario(
    scheduling_environment: dict,
    scheduling_deployment: dict,
    vcluster: dict,
    _reset_scheduling_after_test: None,
) -> None:
    """T107: stack multiple feature groups onto one deployment and verify
    they all survive rendering through Flux.

    Mirrors the ``quickstart.md`` end-to-end walk-through at the scope the
    MVP public API supports (deployment-level, since per-component and
    per-environment update mutations are not yet exposed).
    """
    client = scheduling_environment["client"]

    def _everything_landed(dep: Any) -> bool:
        spec = dep.spec.template.spec
        tols = spec.tolerations or []
        spreads = spec.topology_spread_constraints or []
        containers = spec.containers or []
        resources = containers[0].resources if containers else None
        requests = resources.requests if resources else None
        limits = resources.limits if resources else None
        return (
            any(t.key == "dedicated" for t in tols)
            and any(s.topology_key == "kubernetes.io/hostname" for s in spreads)
            and bool(requests)
            and requests.get("memory") == "192Mi"
            and bool(limits)
            and limits.get("cpu") == "500m"
            and spec.affinity is not None
            and spec.affinity.pod_affinity is not None
        )

    await _update_scheduling_and_wait(
        client,
        scheduling_deployment["deployment_id"],
        scheduling={
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
            "pod_affinity": {
                # ``preferred`` rather than ``required``: a required
                # pod-affinity excludes the candidate pod itself, so with a
                # single simple-app replica there is no other matching pod
                # to anchor onto, pods go Pending, and helm ``--wait``
                # times out.
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
        },
        vcluster=vcluster,
        namespace=scheduling_deployment["namespace"],
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=_everything_landed,
        description="all four feature groups composed on the pod template",
    )


@pytest.mark.ci
async def test_update_triggers_reconciliation_within_slo(
    scheduling_environment: dict,
    scheduling_deployment: dict,
    vcluster: dict,
    _reset_scheduling_after_test: None,
) -> None:
    """T109 / FR-019: changing scheduling config must propagate to the
    pod template within the reconciliation SLO. We measure wall-clock
    time from the ``updateDeployment`` mutation returning to the rendered
    pod template reflecting the new value.
    """
    client = scheduling_environment["client"]

    marker_memory = "223Mi"

    start = time.monotonic()
    await client.deployments.update(
        scheduling_deployment["deployment_id"],
        config={
            "scheduling": {
                "resources": {"requests": {"memory": marker_memory}},
            }
        },
    )

    def _marker_landed(dep: Any) -> bool:
        containers = dep.spec.template.spec.containers or []
        if not containers or not containers[0].resources:
            return False
        requests = containers[0].resources.requests or {}
        return requests.get("memory") == marker_memory

    await _wait_for_pod_template(
        vcluster,
        namespace=scheduling_deployment["namespace"],
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=_marker_landed,
        description=f"memory={marker_memory} on pod template",
        timeout=UPDATE_SLO_SECONDS,
    )
    elapsed = time.monotonic() - start
    assert elapsed <= UPDATE_SLO_SECONDS, (
        f"Reconciliation took {elapsed:.1f}s, SLO is {UPDATE_SLO_SECONDS:.0f}s"
    )
