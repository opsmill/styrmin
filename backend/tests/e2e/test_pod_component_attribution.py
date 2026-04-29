"""E2E coverage for pod-component attribution (spec 005-match-pod-component).

Verifies that:

1. For a deployed driver, every pod produced by a declared component is
   reported with ``componentName`` matching the component the agent
   reads from the pod's ``styrmin/component`` label.
2. A pod added to the deployment's namespace WITHOUT the
   ``styrmin/component`` label is reported with ``componentName == None``
   (no drop, no fabrication, no rejection).

We use the already-running ``deployed_simple_app`` session fixture
(driver: ``simple-app``, single component ``server``) so this test
does not pay a full deploy in its own session. The single-component
case is sufficient to exercise the contract — the agent's label
extraction is the same code path regardless of how many components a
driver declares — and the unit tests in
``backend/tests/unit/agent/test_status_reporter.py`` cover the
multi-value / blank / unknown / missing label cases at the function
level.
"""

from __future__ import annotations

import asyncio
import time
from uuid import UUID

import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Pod as AsyncPod
from styrmin_sdk import StyrminClient

from tests.e2e.drivers import ScenarioDriver

_COMPONENT_LABEL_KEY = "styrmin/component"


async def _live_pod_labels(
    kubeconfig_path: str, namespace: str
) -> dict[str, dict[str, str]]:
    """Return ``{pod_name: labels_dict}`` for every pod in ``namespace``."""
    api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    out: dict[str, dict[str, str]] = {}
    async for pod in AsyncPod.list(namespace=namespace, api=api):
        if isinstance(pod, AsyncPod):
            out[pod.name] = dict(pod.metadata.get("labels") or {})
    return out


async def _poll_pod_statuses_until(
    client: StyrminClient,
    deployment_id: UUID,
    *,
    predicate,
    timeout: float,
    interval: float = 5.0,
    failure_context: str = "",
):
    deadline = time.time() + timeout
    last_pods: list = []
    while time.time() < deadline:
        last_pods = await client.deployments.get_pod_statuses(
            deployment_id=deployment_id
        )
        outcome = predicate(last_pods)
        if outcome:
            return outcome
        await asyncio.sleep(interval)
    raise AssertionError(
        f"Predicate never became truthy within {timeout}s. "
        f"Last observed pods: "
        f"{[(p.pod_name, p.component_name) for p in last_pods]}. "
        f"{failure_context}"
    )


@pytest.mark.ci
async def test_pod_component_attribution(
    deployed_simple_app: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> None:
    _, client = session_scenario_driver
    deployment_id = UUID(str(deployed_simple_app["deployment_id"]))
    namespace = deployed_simple_app["namespace"]
    kubeconfig_path = deployed_simple_app["kubeconfig_path"]

    # Diagnostic: snapshot the actual labels on pods in the namespace
    # before asserting anything. If the platform's component-label
    # injection is broken, this output explains the assertion failure
    # without needing a separate run.
    live_labels = await _live_pod_labels(kubeconfig_path, namespace)
    label_summary = ", ".join(
        f"{name}: styrmin/component={labels.get(_COMPONENT_LABEL_KEY, '<missing>')!r}"
        for name, labels in live_labels.items()
    )

    # 1) Wait until the agent reports at least one pod of the
    #    ``simple-app`` deployment with component_name == "server".
    def server_component_reported(pods) -> bool:
        return any(p.component_name == "server" for p in pods)

    await _poll_pod_statuses_until(
        client,
        deployment_id,
        predicate=server_component_reported,
        timeout=60.0,
        failure_context=f"Live pod labels: {label_summary}",
    )

    # Cross-check: every reported pod whose component_name is non-None
    # must match the live ``styrmin/component`` label on that pod.
    pods = await client.deployments.get_pod_statuses(deployment_id=deployment_id)
    live_labels = await _live_pod_labels(kubeconfig_path, namespace)
    for pod_status in pods:
        if pod_status.component_name is None:
            continue
        live = live_labels.get(pod_status.pod_name, {}).get(_COMPONENT_LABEL_KEY)
        assert live == pod_status.component_name, (
            f"Reported component_name={pod_status.component_name!r} for pod "
            f"{pod_status.pod_name!r} disagrees with the live "
            f"styrmin/component label {live!r}"
        )

    # 2) Inject an unlabelled busybox pod into the deployment's namespace
    #    and verify the agent reports it with component_name=None.
    api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    debug_pod_name = "pod-component-test-unlabelled"
    debug_pod = AsyncPod(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": debug_pod_name, "namespace": namespace},
            "spec": {
                "containers": [
                    {
                        "name": "main",
                        "image": "busybox:1.36",
                        "command": ["sh", "-c", "sleep 3600"],
                    }
                ],
                "restartPolicy": "Never",
            },
        },
        api=api,
    )
    await debug_pod.create()
    try:

        def unlabelled_pod_visible_with_none(pods) -> bool:
            return any(
                p.pod_name == debug_pod_name and p.component_name is None for p in pods
            )

        await _poll_pod_statuses_until(
            client,
            deployment_id,
            predicate=unlabelled_pod_visible_with_none,
            timeout=60.0,
            failure_context="busybox pod was created but never reported.",
        )
    finally:
        await debug_pod.delete()
