"""E2E: a restore that ends ``PartiallyFailed`` puts the Styrmin labels back on the namespace.

Velero creates the namespace without its labels, because the backup leaves cluster-scoped
resources out. The recovery that puts them back runs only after a Velero restore that ended
``Completed``. After any other phase the namespace kept only ``kubernetes.io/metadata.name``,
and a policy that selects the namespace by ``styrmin/environment_id`` (the cluster policy that
lets a shared ingress controller in is one) no longer matched it: the application's pods ran
and nothing reached them from outside.

The test driver ``postgres-blocker`` makes the Velero restore end ``PartiallyFailed`` whatever
the PostgreSQL restore hook does: its init script creates, as the ``postgres`` superuser, a table
that the application's role can read, so the backup works, but cannot drop, so the hook cannot
load the dump over it.

The test has its own environment and deployment, because a restore deletes the deployment's
namespace.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Namespace as AsyncNamespace
from styrmin_sdk import StyrminClient

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.test_backup_restore import (
    DEPLOYMENT_RUNNING_TIMEOUT_SECONDS,
    _wait_for_sdk_deployment_running,
)

pytestmark = [
    pytest.mark.shard_backup,
]


@pytest.fixture(scope="module")
async def blocker_driver(
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    git_server: dict[str, str],
) -> None:
    """Load the test driver into Styrmin."""
    driver, _ = session_scenario_driver
    await driver.load_driver_version(
        git_url=git_server["postgres-blocker"], ref="master"
    )


@asynccontextmanager
async def deployed(
    client: StyrminClient,
    styrmin_resources: dict,
    vcluster: dict,
    driver_name: str,
) -> AsyncIterator[dict]:
    """A running deployment of ``driver_name`` in its own environment, which has a backup location."""
    suffix = uuid4().hex[:8]
    environment = await client.environments.create(
        name=f"{driver_name}-{suffix}",
        cluster_id=styrmin_resources["cluster_id"],
        config={},
    )
    try:
        await client.backup_storage_locations.assign(
            environment_id=environment.id, bsl_id=styrmin_resources["bsl_id"]
        )
        task = await client.deployments.create(
            driver=driver_name,
            version="0.1.0",
            environment_id=environment.id,
            name=f"{driver_name}-{suffix}",
        )
        assert task.deployment_id is not None, task
        deployment_id = str(task.deployment_id)
        instance_id = await _wait_for_sdk_deployment_running(
            client, deployment_id, timeout=DEPLOYMENT_RUNNING_TIMEOUT_SECONDS
        )
        yield {
            "environment_id": str(environment.id),
            "deployment_id": deployment_id,
            "instance_id": instance_id,
            "namespace": f"styrmin-{deployment_id}",
            "kubeconfig_path": vcluster["kubeconfig_path"],
        }
    finally:
        # The restore deleted and recreated the namespace: deleting the environment removes what is left.
        with suppress(Exception):
            await client.environments.delete(environment_id=environment.id)


@pytest.mark.ci
@pytest.mark.api_only(
    reason="Every action is a raw SDK or Kubernetes call and no dual-entrypoint driver "
    "method is invoked. The labels of a namespace are not shown in the UI, and "
    "BackupRestoreSteps.test.tsx covers how a failed restore step appears on the Backups "
    "tab: a [ui-chromium] variant would repeat the same GraphQL calls with one more "
    "deployment boot."
)
async def test_a_restore_that_ends_partially_failed_puts_the_namespace_labels_back(
    styrmin_resources: dict,
    blocker_driver: None,  # noqa: ARG001 — loads the test driver
    simple_app_image: str,  # noqa: ARG001 — builds the image
    velero_ready: None,  # noqa: ARG001 — ensures Velero is up before backup/restore
    vcluster: dict,
) -> None:
    """The restored namespace has its ``styrmin/environment_id`` and ``styrmin/deployment_id`` labels."""
    client: StyrminClient = styrmin_resources["client"]
    async with deployed(client, styrmin_resources, vcluster, "postgres-blocker") as (
        deployment
    ):
        created_backup = await client.backups.create_backup(
            instance_id=deployment["instance_id"]
        )
        backup = await client.backups.wait_for_backup(created_backup.id, max_wait=300)
        assert backup.status == "completed", backup

        created_restore = await client.backups.create_restore(backup_id=backup.id)
        restore = await client.backups.wait_for_restore(
            created_restore.id, max_wait=600
        )

        # The hook cannot drop a table that the application's role does not own.
        assert restore.status == "failed", restore
        assert restore.error_message is not None
        assert "PartiallyFailed" in restore.error_message, restore.error_message
        # The recovery of a completed restore did not run: the labels come from the new step.
        assert [(step.key, step.status.value) for step in restore.steps] == [
            ("restore:namespace", "SUCCEEDED"),
            ("restore:velero", "FAILED"),
        ], restore.steps

        kr8s_api = await kr8s.asyncio.api(kubeconfig=deployment["kubeconfig_path"])
        namespace = await AsyncNamespace.get(deployment["namespace"], api=kr8s_api)
        labels = dict(namespace.labels)
        assert labels.get("styrmin/environment_id") == deployment["environment_id"], (
            labels
        )
        assert labels.get("styrmin/deployment_id") == deployment["deployment_id"], (
            labels
        )

        # A failed restore leaves the deployment failed, not restoring.
        failed = await client.deployments.get(deployment["deployment_id"])
        assert failed.status == "failed", failed.status
