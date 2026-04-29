"""E2E coverage for pod-component attribution (spec 005-match-pod-component).

Verifies that:
1. For a multi-component driver, every pod produced by a declared component
   is reported with ``componentName`` matching that component's name.
2. A pod added to the deployment's namespace WITHOUT the
   ``styrmin/component`` label is reported with ``componentName == None``
   (no drop, no fabrication, no rejection).

The db-test driver declares three components — ``server``, ``mariadb``,
``mongodb`` — which is enough to exercise multi-component attribution.
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

# db-test declares these three components (driver/examples/db-test/driver.styrmin.yml).
_EXPECTED_COMPONENTS = {"server", "mariadb", "mongodb"}


async def _poll_pod_statuses_until(
    client: StyrminClient,
    deployment_id: UUID,
    *,
    predicate,
    timeout: float = 120.0,
    interval: float = 5.0,
):
    """Poll ``get_deployment_pod_statuses`` until ``predicate(pods)`` returns
    a truthy value. Returns the truthy value (typically the pod list itself).

    ``deployment_id`` is the SDK type — passed straight through.
    """
    deadline = time.time() + timeout
    last_pods: list = []
    while time.time() < deadline:
        result = await client.get_deployment_pod_statuses(deployment_id=deployment_id)
        pods = result.deployment.pod_statuses if result.deployment else []
        outcome = predicate(pods)
        if outcome:
            return outcome
        last_pods = pods
        await asyncio.sleep(interval)
    raise AssertionError(
        f"Predicate never became truthy within {timeout}s. "
        f"Last observed pods: {[(p.pod_name, p.component_name) for p in last_pods]}"
    )


@pytest.mark.ci
async def test_pod_component_attribution(
    deployed_db_test: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> None:
    _, client = session_scenario_driver
    deployment_id = UUID(str(deployed_db_test["deployment_id"]))
    namespace = deployed_db_test["namespace"]
    kubeconfig_path = deployed_db_test["kubeconfig_path"]

    # 1) Wait until at least one pod from each declared component has been
    #    reported by the agent. The agent polls every ~5s by default; we
    #    give it a generous window because db-test pulls real DB images.
    def all_components_reported(pods) -> bool:
        observed = {p.component_name for p in pods if p.component_name is not None}
        return _EXPECTED_COMPONENTS.issubset(observed)

    pods = await _poll_pod_statuses_until(
        client, deployment_id, predicate=all_components_reported, timeout=180.0
    )

    # Cross-check each reported component name against the actual pod's
    # styrmin/component label fetched directly from the cluster — the
    # agent's report and the live label must agree.
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    for pod_status in pods:
        if pod_status.component_name is None:
            continue
        live_pod = await AsyncPod.get(
            pod_status.pod_name, namespace=namespace, api=kr8s_api
        )
        live_label = (live_pod.metadata.get("labels") or {}).get(_COMPONENT_LABEL_KEY)
        assert live_label == pod_status.component_name, (
            f"Reported component_name={pod_status.component_name!r} for pod "
            f"{pod_status.pod_name!r} does not match the live "
            f"styrmin/component label {live_label!r}"
        )

    # 2) Inject an unlabelled pod into the deployment's namespace and verify
    #    the agent reports it with component_name=None.
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
        api=kr8s_api,
    )
    await debug_pod.create()
    try:

        def unlabelled_pod_visible(pods) -> bool:
            return any(
                p.pod_name == debug_pod_name and p.component_name is None for p in pods
            )

        await _poll_pod_statuses_until(
            client, deployment_id, predicate=unlabelled_pod_visible, timeout=60.0
        )
    finally:
        await debug_pod.delete()
