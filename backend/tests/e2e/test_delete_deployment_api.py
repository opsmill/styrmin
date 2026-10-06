"""E2E test for the deployment-deletion lifecycle (spec 008).

Drives the full path through the SDK and asserts on cluster + DB state.
The test is ``api_only`` because every action goes through the SDK (or
``kubernetes_asyncio`` for namespace introspection); no UI flow is
exercised. Per ``AGENTS.md`` § Dual-entrypoint scope, the
``[ui-chromium]`` variant would simply re-run the same SDK call paths
without adding coverage.

What it covers:

* ``client.deployments.delete(id)`` returns immediately with a born-
  complete ``DELETE_DEPLOYMENT`` task (US20, US21, FR-019).
* ``Deployment.status`` projects through ``DELETING -> DELETED`` via the
  status-reporter (US24, FR-004, FR-005).
* The terminal transition is gated on the namespace being actually gone
  (US14, FR-003).
* ``Deployment.deletedAt`` is non-null after ``DELETED`` (FR-005,
  FR-023).
* Backups attached to the tombstoned deployment remain queryable (US8,
  FR-012).
* The deletion event appears on the deployment timeline (US11,
  FR-011).
* A new deployment can reclaim the tombstoned deployment's service name
  in the same environment (regression: tombstones' ``DeployedService``
  rows used to hold the name, failing the redeploy with
  ``ServiceNameConflictError``).

Out of scope for this test:

* The ``includeDeleted`` listing filter (US25) — the SDK's
  ``client.environments.get`` does not currently fetch deployments;
  the propagation suite (``test_deployments_include_deleted.py``)
  covers that contract.
* The cluster-side CR retention TTL (US17, US18) — would require
  fast-forwarding ``DELETED_CR_TTL_HOURS``; covered by the operator
  unit tests in ``test_deployment_deletion_operator.py``.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio import config as k8s_config
from kubernetes_asyncio.client.api_client import ApiException
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import ResourceNotFoundError

from tests.e2e.conftest import create_deployment_after_ingress_teardown
from tests.e2e.drivers import ScenarioDriver

pytestmark = [
    pytest.mark.shard_general,
]


async def _namespace_exists(kubeconfig_path: str, namespace: str) -> bool:
    """Return True iff the namespace is present on the cluster."""
    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    core_api = kubeclient.CoreV1Api(api_client)
    try:
        await core_api.read_namespace(name=namespace)
        return True
    except ApiException as exc:
        if exc.status == 404:
            return False
        raise
    finally:
        await api_client.close()


async def _wait_for_namespace_gone(
    kubeconfig_path: str, namespace: str, timeout: float = 300.0
) -> None:
    """Block until the namespace returns 404 or the timeout elapses.

    Namespace finalisers can take minutes; we deliberately do not assert
    a tight upper bound here. The 5-minute default matches the project's
    other deletion E2E budgets.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not await _namespace_exists(kubeconfig_path, namespace):
            return
        await asyncio.sleep(5)
    raise AssertionError(
        f"Namespace {namespace!r} still present after {timeout}s — "
        "the operator did not advance the StyrminDeployment to phase: Deleted."
    )


async def _wait_for_status(
    client: StyrminClient,
    deployment_id: str,
    expected: str,
    timeout: float = 300.0,
) -> None:
    """Poll ``Deployment.status`` until it equals *expected* or we time out."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        deployment = await client.deployments.get(deployment_id)
        last = deployment.status
        if last == expected:
            return
        await asyncio.sleep(2)
    raise AssertionError(
        f"Deployment {deployment_id} never reached status {expected!r} "
        f"within {timeout}s. Last observed: {last!r}."
    )


@pytest.mark.api_only(
    reason="Drives the deletion lifecycle entirely through the SDK and "
    "verifies cluster/DB state via kubernetes_asyncio + the SDK. The "
    "[ui-chromium] variant would re-run the same SDK call paths without "
    "adding coverage; the UI surface is exercised separately by "
    "test_delete_deployment_ui.py."
)
@pytest.mark.ci
async def test_delete_deployment_api(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
    vcluster: dict,
) -> None:
    """End-to-end deletion: deploy → backup → delete → tombstone → redeploy."""
    client: StyrminClient = styrmin_resources["client"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    # 1. Deploy a fresh simple-app into the shared scenario env. We need
    # a unique service-name override per the env's per-env service-name
    # uniqueness check (the `deployed_simple_app` session deployment is
    # already using the default name).
    override = f"delete-{uuid.uuid4().hex[:6]}"
    deployment = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": override}
        ],
    )
    deployment = await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment.id, timeout=300.0
    )
    deployment_id = deployment.id
    instance_id = deployment.instance_id
    namespace = f"styrmin-{deployment_id}"
    assert instance_id is not None, "Running deployment must have an instance_id"

    # Sanity: the namespace was actually created.
    assert await _namespace_exists(kubeconfig_path, namespace), (
        f"Namespace {namespace!r} was not created during deploy"
    )

    # 2. Create a backup so we can later assert it survives deletion.
    backup = await scenario_driver.create_backup(instance_id=instance_id)
    backup = await scenario_driver.wait_for_backup(backup_id=backup.id, max_wait=180)
    assert backup.status == "completed", (
        f"Setup precondition: backup must complete before delete; got {backup.status}"
    )
    backup_id = backup.id

    # 3. Trigger deletion through the SDK. The mutation must return
    # immediately with a born-complete DELETE_DEPLOYMENT task — it MUST
    # NOT block on the namespace finaliser (US21, FR-019).
    delete_started_at = time.monotonic()
    task = await client.deployments.delete(deployment_id)
    delete_elapsed = time.monotonic() - delete_started_at

    # SC-002: triggering deletion is acknowledged within ~2 seconds. We
    # use a generous 10s upper bound here to tolerate test-environment
    # variability while still catching the case where the resolver
    # accidentally blocks on cluster teardown.
    assert delete_elapsed < 10.0, (
        f"deleteDeployment took {delete_elapsed:.1f}s — must return "
        "immediately, not block on cluster teardown"
    )
    assert task.type_ == "delete_deployment", (
        f"Expected task.type=delete_deployment, got {task.type_!r}"
    )
    assert task.status == "success", (
        f"DELETE_DEPLOYMENT task must be born complete; got status={task.status!r}"
    )

    # 4. Status flips to DELETING via the status reporter once the
    # operator picks up the spec.deletionRequested flip.
    await _wait_for_status(client, deployment_id, "deleting", timeout=120.0)

    # 5. Wait for the namespace to be fully torn down. The terminal
    # DELETED transition is gated on this (US14).
    await _wait_for_namespace_gone(kubeconfig_path, namespace, timeout=300.0)

    # 6. Once the namespace is gone, the operator advances the CR to
    # phase: Deleted, the status reporter projects displayState=Deleted
    # to the DB, and atomically stamps deleted_at. Allow up to two
    # reconciliation ticks for the propagation.
    await _wait_for_status(client, deployment_id, "deleted", timeout=180.0)

    tombstoned = await client.deployments.get(deployment_id)
    assert tombstoned.status == "deleted", tombstoned.status
    assert tombstoned.deleted_at is not None, (
        "Deployment.deletedAt must be populated atomically with the "
        "DELETED transition (FR-005)"
    )

    # 7. Idempotency / not-found contract: a second delete on the
    # already-tombstoned deployment surfaces as ResourceNotFound (the
    # SDK's NOT_FOUND mapping; conflated with unknown id per spec
    # FR-009). Scripts treat this as the natural success outcome for a
    # repeated cleanup call.
    with pytest.raises(ResourceNotFoundError):
        await client.deployments.delete(deployment_id)

    # 8. Backups are retained against the tombstoned deployment (US8,
    # FR-012). The backup row must still resolve by id.
    surviving_backup = await client.backups.get_backup(backup_id)
    assert str(surviving_backup.id) == str(backup_id), (
        "Backup row must remain queryable after the parent deployment is tombstoned"
    )

    # 9. The deletion appears on the deployment timeline (US11,
    # FR-011). The timeline is task-derived, so a new entry of type
    # DELETE_DEPLOYMENT must be present.
    timeline = await client.deployments.get_timeline(deployment_id)
    delete_entries = [
        entry for entry in timeline if entry.task.type_ == "delete_deployment"
    ]
    assert len(delete_entries) >= 1, (
        "Timeline must contain at least one DELETE_DEPLOYMENT entry; "
        f"observed types: {[e.task.type_ for e in timeline]}"
    )

    # 10. The freed service name can be claimed again in the same env. The
    # deletion may have emptied the env, so wait out its ingress teardown.
    redeployed = await create_deployment_after_ingress_teardown(
        scenario_driver,
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": override}
        ],
    )
    redeployed = await scenario_driver.wait_for_deployment_running(
        deployment_id=redeployed.id, timeout=300.0
    )
    assert redeployed.id != deployment_id, "Redeploy must create a distinct deployment"
