"""E2E tests for the deployment deletion feature.

Covers:

- RETAIN disposition tears down cluster resources and leaves the
  deployment tombstoned with its timeline intact.
- REMOVE disposition additionally drops all backups belonging to the
  deployment's instances before teardown.
- Concurrency guard rejects deletion while another workflow is in
  flight for the same deployment.
- Re-issuing deletion against a tombstoned deployment is idempotent
  (returns ALREADY_DELETED).

These tests run against the Kind / vcluster fixture produced by the
existing e2e harness and exercise the full path: GraphQL mutation →
service → Prefect DELETE_INSTANCE flow → operator on.delete handler →
backend tombstoning callback.
"""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

import pytest
from kubernetes_asyncio import client as kubeclient
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import OperationFailedError, StyrminError
from styrmin_sdk.graphql._generated.enums import BackupDisposition

from tests.e2e.conftest import _wait_for_deployment_running


async def _wait_for_deployment_deleted(
    client: StyrminClient,
    deployment_id: str,
    timeout: float = 600.0,
    interval: float = 10.0,
) -> None:
    """Poll until a deployment reaches the DELETED terminal state.

    Raises TimeoutError on failure to converge.
    """
    deadline = time.time() + timeout
    last_status = "unknown"
    while time.time() < deadline:
        try:
            deployment = await client.deployments.get(deployment_id)
            last_status = deployment.status
            if last_status == "deleted":
                return
        except StyrminError:
            pass
        await asyncio.sleep(interval)
    raise TimeoutError(
        f"Deployment {deployment_id} did not reach 'deleted' after {timeout}s "
        f"(last status: {last_status})"
    )


async def _namespace_exists(api: kubeclient.ApiClient, namespace: str) -> bool:
    core_api = kubeclient.CoreV1Api(api)
    try:
        await core_api.read_namespace(name=namespace)
        return True
    except kubeclient.api_client.ApiException as exc:
        if exc.status == 404:
            return False
        raise


async def _list_helm_releases(api: kubeclient.ApiClient, namespace: str) -> list[dict]:
    custom_api = kubeclient.CustomObjectsApi(api)
    try:
        result = await custom_api.list_namespaced_custom_object(
            group="helm.toolkit.fluxcd.io",
            version="v2",
            namespace=namespace,
            plural="helmreleases",
        )
        return result.get("items", [])
    except kubeclient.api_client.ApiException as exc:
        if exc.status == 404:
            return []
        raise


@pytest.fixture
async def fresh_simple_app(
    styrmin_resources: dict, simple_app_image: str, vcluster: dict
) -> dict:
    """Per-test deployment — deletion tests need their own instance so
    the session-scoped ``deployed_simple_app`` isn't consumed.

    The simple-app driver declares a service named ``simple-app``,
    which would collide with the session fixture's already-registered
    service in the same environment. Override the service name with a
    per-test suffix so both deployments can coexist.
    """
    client: StyrminClient = styrmin_resources["client"]
    environment_id = styrmin_resources["environment_id"]

    unique_suffix = uuid4().hex[:8]
    deployment_name = f"delete-e2e-{unique_suffix}"
    service_override = f"simple-app-delete-e2e-{unique_suffix}"

    task = await client.deployments.create(
        driver="simple-app",
        version="0.1.0",
        environment_id=environment_id,
        name=deployment_name,
        service_name_overrides=[
            {
                "driverServiceName": "simple-app",
                "overrideName": service_override,
            }
        ],
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None
    await _wait_for_deployment_running(client, deployment_id)

    return {
        "deployment_id": str(deployment_id),
        "namespace": f"styrmin-{deployment_id}",
    }


@pytest.mark.ci
@pytest.mark.api_only(
    reason="deletion lifecycle is exercised through the SDK and Prefect "
    "DELETE_INSTANCE flow; the UI delete dialog has its own ui_only "
    "scenario in test_deployment_deletion_ui.py"
)
async def test_delete_deployment_retain_tombstones_and_clears_cluster(
    styrmin_resources: dict,
    fresh_simple_app: dict,
    vcluster: dict,
) -> None:
    """RETAIN deletes the CRD, operator tears down owned resources,
    flow removes the namespace, backend tombstones the deployment
    with deleted_at set. Timeline still contains the DELETE_INSTANCE
    entry."""
    client: StyrminClient = styrmin_resources["client"]
    api: kubeclient.ApiClient = vcluster["api"]
    deployment_id = fresh_simple_app["deployment_id"]
    namespace = fresh_simple_app["namespace"]

    assert await _namespace_exists(api, namespace), (
        "Precondition: deployment namespace should exist"
    )

    task = await client.deployments.delete(
        deployment_id=deployment_id,
        backup_disposition=BackupDisposition.RETAIN,
    )
    assert task.type_ == "delete_instance"

    await _wait_for_deployment_deleted(client, deployment_id)

    tombstone = await client.deployments.get(deployment_id)
    assert tombstone.status == "deleted"
    assert tombstone.deleted_at is not None

    # Cluster state: no namespace, no HelmReleases belonging to the
    # release reference — the namespace delete from the flow cascades
    # through any leftover objects the operator didn't clean up.
    for _ in range(30):
        if not await _namespace_exists(api, namespace):
            break
        await asyncio.sleep(2)
    assert not await _namespace_exists(api, namespace), (
        "Namespace should be removed once deletion completes"
    )

    timeline = await client.deployments.get_timeline(deployment_id)
    delete_entries = [e for e in timeline if e.task.type_ == "delete_instance"]
    assert delete_entries, "Timeline must retain the DELETE_INSTANCE task"
    assert delete_entries[0].task.status == "success"


@pytest.mark.ci
@pytest.mark.api_only(
    reason="deletion lifecycle is exercised through the SDK and Prefect "
    "DELETE_INSTANCE flow; the UI delete dialog has its own ui_only "
    "scenario in test_deployment_deletion_ui.py"
)
async def test_delete_deployment_remove_drops_backups(
    styrmin_resources: dict,
    fresh_simple_app: dict,
    vcluster: dict,
) -> None:
    """REMOVE: existing backups disappear alongside cluster teardown."""
    client: StyrminClient = styrmin_resources["client"]
    deployment_id = fresh_simple_app["deployment_id"]

    deployment = await client.deployments.get(deployment_id)
    assert deployment.application_instance is not None
    instance_id = str(deployment.application_instance.id)

    # Create a backup so we have something concrete to verify got
    # removed. This may take time to complete depending on driver
    # strategies; the E2E harness tolerates slow starts.
    await client.backups.create(instance_id=instance_id)

    backups_before = await client.backups.list(instance_id=instance_id)
    assert backups_before, "Precondition: at least one backup present"

    await client.deployments.delete(
        deployment_id=deployment_id,
        backup_disposition=BackupDisposition.REMOVE,
    )
    await _wait_for_deployment_deleted(client, deployment_id)

    # Post-condition: backups for the original instance are gone.
    backups_after = await client.backups.list(instance_id=instance_id)
    assert backups_after == [], (
        f"REMOVE disposition should leave no backups, got {len(backups_after)}"
    )


@pytest.mark.ci
@pytest.mark.api_only(
    reason="deletion lifecycle is exercised through the SDK and Prefect "
    "DELETE_INSTANCE flow; the UI delete dialog has its own ui_only "
    "scenario in test_deployment_deletion_ui.py"
)
async def test_delete_deployment_rejects_concurrent_mutation(
    styrmin_resources: dict,
    fresh_simple_app: dict,
) -> None:
    """If another workflow is mid-flight for the same deployment, the
    delete mutation rejects with a typed ALREADY_IN_PROGRESS error
    rather than interleaving."""
    client: StyrminClient = styrmin_resources["client"]
    deployment_id = fresh_simple_app["deployment_id"]

    # Upgrade runs asynchronously; the task stays PENDING/RUNNING for
    # long enough that a follow-up delete lands while it's in flight.
    await client.deployments.update_version(deployment_id, "0.2.0")

    with pytest.raises(OperationFailedError) as exc:
        await client.deployments.delete(
            deployment_id=deployment_id,
            backup_disposition=BackupDisposition.RETAIN,
        )
    assert (
        "in flight" in str(exc.value).lower() or "in progress" in str(exc.value).lower()
    )


@pytest.mark.ci
@pytest.mark.api_only(
    reason="deletion lifecycle is exercised through the SDK and Prefect "
    "DELETE_INSTANCE flow; the UI delete dialog has its own ui_only "
    "scenario in test_deployment_deletion_ui.py"
)
async def test_delete_deployment_idempotent(
    styrmin_resources: dict,
    fresh_simple_app: dict,
) -> None:
    """Re-issuing delete against a deployment already tombstoned returns
    the typed ALREADY_DELETED error, not another cluster teardown."""
    client: StyrminClient = styrmin_resources["client"]
    deployment_id = fresh_simple_app["deployment_id"]

    await client.deployments.delete(
        deployment_id=deployment_id,
        backup_disposition=BackupDisposition.RETAIN,
    )
    await _wait_for_deployment_deleted(client, deployment_id)

    with pytest.raises(OperationFailedError) as exc:
        await client.deployments.delete(
            deployment_id=deployment_id,
            backup_disposition=BackupDisposition.RETAIN,
        )
    assert "delete" in str(exc.value).lower()
