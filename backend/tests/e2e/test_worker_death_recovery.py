"""E2E coverage for recovering flow runs orphaned by a dead worker (#312).

Root cause: a Prefect ``ProcessWorker`` whose parent process dies while it
holds a claimed flow run never gets that run reassigned. Confirmed by direct
reproduction: killing only the flow run's subprocess self-heals via
Prefect's own crash-reporting in ~2s (the surviving parent worker observes
the non-zero exit); killing the whole worker process (OOM kill, a
``kubectl rollout restart``, a node eviction) leaves the run permanently
stuck in RUNNING/PENDING with no other recovery path.

The fix (``PrefectManager.setup_zombie_flow_run_automation``) registers
Prefect's own documented zombie-flow-run Automation
(https://docs.prefect.io/v3/advanced/detect-zombie-flows) on every server
startup: it reacts to a flow run's heartbeats going silent and marks it
Crashed.

This test forces the exact failure mode directly against the real
``task-worker`` Kubernetes Deployment installed by the ``styrmin_deployment``
session fixture (the same Helm chart / resource limits used in production),
rather than re-deriving the mechanism at a lower level. It deploys a small
throwaway Prefect flow (not ``apply_state``) to keep the blast radius of
force-deleting the shared ``task-worker`` pod as small as possible for
other tests sharing this session's stack.
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid

import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Pod as AsyncPod, Service as AsyncService
from prefect.client.orchestration import PrefectClient

from tests.e2e.conftest import _portforward, _wait_for_http

pytestmark = [
    pytest.mark.ci,
    pytest.mark.shard_general,
    pytest.mark.api_only(
        reason="Exercises the Prefect API and Kubernetes pod lifecycle directly; "
        "no UI-specific behavior to cover."
    ),
]

_AUTOMATION_NAME = "Crash zombie flow runs"

_PROBE_FLOW_SOURCE = """\
import time
from prefect import flow


@flow(name="e2e-worker-death-probe")
def e2e_worker_death_probe(seconds: int = 45) -> str:
    time.sleep(seconds)
    return "done"
"""


@pytest.mark.e2e
async def test_worker_death_recovers_orphaned_flow_run(
    vcluster: dict,
    styrmin_deployment: str,  # noqa: ARG001 -- ensures the stack is up
) -> None:
    """A flow run claimed by a task-worker whose pod is force-deleted mid-run
    is recovered (transitioned to Crashed) by the zombie-flow-run Automation,
    without any manual intervention or worker restart on the test's part."""
    kubeconfig_path = vcluster["kubeconfig_path"]
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)

    prefect_service = await AsyncService.get(
        "prefect-server", namespace="styrmin", api=kr8s_api
    )
    async with _portforward(prefect_service, remote_port=4200) as prefect_port:
        prefect_url = f"http://localhost:{prefect_port}/api"
        await _wait_for_http(f"{prefect_url}/health", timeout=60.0)

        async with PrefectClient(api=prefect_url) as client:
            # The Automation is registered once by PrefectManager.initialize()
            # on server startup (session-scoped styrmin_deployment fixture
            # already brought the stack up) -- assert it's actually present
            # rather than assuming the registration ran.
            automations = await client.read_automations_by_name(name=_AUTOMATION_NAME)
            assert automations, (
                "Expected PrefectManager.initialize() to have registered the "
                f"{_AUTOMATION_NAME!r} Automation on server startup"
            )

            # Find the target task-worker pod up front (Kubernetes, not
            # Prefect) -- the pod we'll force-delete once our probe run
            # claims it.
            pods = [
                pod
                async for pod in AsyncPod.list(namespace="styrmin", api=kr8s_api)
                if isinstance(pod, AsyncPod)
                and pod.metadata.get("labels", {}).get("app.kubernetes.io/component")
                == "task-worker"
            ]
            assert pods, (
                "Expected at least one task-worker pod in the styrmin namespace"
            )
            target_pod = pods[0]

            # task-worker's image filesystem is read-only for its non-root
            # user in production -- there's no bind-mounted backend/ to drop
            # a fixture into (unlike the docker-compose dev stack). Write the
            # probe flow directly into the pod's writable /tmp instead.
            #
            # The source is embedded as a base64 argument rather than piped
            # via exec's `stdin` -- some clusters negotiate the older
            # v4.channel.k8s.io exec subprotocol, which kr8s's stdin support
            # doesn't work with (only v5.channel.k8s.io does).
            probe_name = f"e2e-worker-death-probe-{uuid.uuid4().hex[:8]}"
            probe_path = f"/tmp/{probe_name}.py"
            encoded_source = base64.b64encode(_PROBE_FLOW_SOURCE.encode()).decode()
            await target_pod.exec(
                ["sh", "-c", f"echo {encoded_source} | base64 -d > {probe_path}"],
                check=True,
            )

            # Deploy the probe flow to styrmin-work-pool (the pool
            # task-worker polls) rather than reusing apply_state /
            # create_instance_crd -- keeps this test independent of
            # driver/deployment machinery unrelated to the failure mode
            # under test.
            flow_id = await client.create_flow_from_name("e2e-worker-death-probe")
            deployment_id = await client.create_deployment(
                flow_id=flow_id,
                name=probe_name,
                entrypoint=f"{probe_name}.py:e2e_worker_death_probe",
                work_pool_name="styrmin-work-pool",
                # Without an explicit storage/pull step, the runner tries to
                # download flow code from a storage block ("Downloading flow
                # code from storage at None") instead of loading it straight
                # off disk -- reproduced directly. set_working_directory
                # matches how every catalogue.py-registered internal flow in
                # this repo is deployed (see WorkflowDefinition.to_deployment).
                pull_steps=[
                    {
                        "prefect.deployments.steps.set_working_directory": {
                            "directory": "/tmp",
                        }
                    }
                ],
            )
            flow_run = await client.create_flow_run_from_deployment(
                deployment_id=deployment_id,
                parameters={"seconds": 45},
            )

            # Wait for the run to actually start (a worker claimed it), then
            # force-delete its pod -- the real analogue of an OOM kill, a
            # `kubectl rollout restart`, or a node eviction. This is the
            # exact failure mode: killing the *parent* worker process, not
            # just the flow run's own subprocess (which already self-heals
            # via Prefect's built-in crash-reporting and needs no fix).
            deadline = time.monotonic() + 30
            state_type = None
            while time.monotonic() < deadline:
                run = await client.read_flow_run(flow_run.id)
                state_type = run.state_type.value if run.state_type else None
                if state_type == "RUNNING":
                    break
                await asyncio.sleep(1)
            assert state_type == "RUNNING", (
                f"Probe flow run never reached RUNNING (last state: {state_type})"
            )

            await target_pod.delete(force=True, grace_period=0)

            # Recovery: the zombie-flow-run Automation reacts to the missed
            # heartbeat and marks the run Crashed. The detection window is
            # 3x the configured heartbeat frequency (180s default here ->
            # 540s), matching setup_zombie_flow_run_automation's own
            # calculation -- a shorter window flags every healthy in-flight
            # flow run as a false positive (see
            # test_detection_window_is_a_multiple_of_configured_heartbeat_frequency).
            # Padded generously for CI scheduling variance.
            recovery_timeout = 600
            deadline = time.monotonic() + recovery_timeout
            state_type = None
            run = None
            while time.monotonic() < deadline:
                run = await client.read_flow_run(flow_run.id)
                state_type = run.state_type.value if run.state_type else None
                if state_type == "CRASHED":
                    break
                await asyncio.sleep(5)

            assert state_type == "CRASHED", (
                "Orphaned flow run was never recovered by the zombie-flow-run "
                f"Automation within {recovery_timeout}s (last state: "
                f"{state_type}). Without the fix, this run stays stuck in "
                "RUNNING forever."
            )
            assert run is not None and run.state is not None
            assert "heartbeat" in (run.state.message or "").lower()

            await client.delete_deployment(deployment_id)
