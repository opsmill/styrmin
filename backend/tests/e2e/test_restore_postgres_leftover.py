"""E2E: the restore of a PostgreSQL component when its database is not empty at the start of the restore hook.

A restore deletes the namespace and starts PostgreSQL on an empty volume. The application is
restored at the same time and migrates that empty database, so the restore hook can find tables
that the dump does not hold: the dump comes from a fully migrated database, and a migration that
has not finished leaves what a later migration would remove (Prefect's task manager does this with
a foreign key). ``pg_restore --clean`` drops only what the dump holds, so it used to fail on a
table that such a leftover depends on, and every retry failed the same way.

The test driver ``postgres-leftover`` creates the leftover the same way every time, in the
PostgreSQL init script, which runs on every start on an empty volume. That makes the scenario
exact where the real race has a window of a few seconds: the init script creates ``e2e_parent``
and ``e2e_child``, which refers to it. The test drops ``e2e_child`` before the backup, so the dump
holds ``e2e_parent`` only, and the restore finds ``e2e_child`` again. The restore must complete
and give back the rows.

The test has its own environment and deployment, because a restore deletes the deployment's
namespace.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Pod as AsyncPod
from styrmin_sdk import StyrminClient

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.test_backup_restore import (
    DEPLOYMENT_RUNNING_TIMEOUT_SECONDS,
    _wait_for_sdk_deployment_running,
    wait_for_pods_ready,
)

pytestmark = [
    pytest.mark.shard_backup,
]

POSTGRES_POD = "styrmin-postgresql-0"
PSQL = "PGPASSWORD=simple-app-password psql -U simple-app -d simple_app -tA -c"
MARKER_ROWS = "1,2,3"


@pytest.fixture(scope="module")
async def restore_test_drivers(
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    git_server: dict[str, str],
) -> None:
    """Load the test driver into Styrmin."""
    driver, _ = session_scenario_driver
    await driver.load_driver_version(
        git_url=git_server["postgres-leftover"], ref="master"
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


async def sql(deployment: dict, statement: str) -> str:
    """Run ``statement`` in the PostgreSQL pod of the deployment, as the application's role."""
    kr8s_api = await kr8s.asyncio.api(kubeconfig=deployment["kubeconfig_path"])
    pod = await AsyncPod.get(
        POSTGRES_POD, namespace=deployment["namespace"], api=kr8s_api
    )
    result = await pod.exec(
        ["sh", "-c", f'{PSQL} "{statement}"'], container="postgresql", check=True
    )
    return result.stdout.decode().strip()


async def back_up(client: StyrminClient, deployment: dict):
    created = await client.backups.create_backup(instance_id=deployment["instance_id"])
    backup = await client.backups.wait_for_backup(created.id, max_wait=300)
    assert backup.status == "completed", backup
    return backup


@pytest.mark.ci
@pytest.mark.api_only(
    reason="Every action is a raw SDK or Kubernetes call and no dual-entrypoint driver "
    "method is invoked. The scenario is in the data of the restore, which the UI shows "
    "the same way as in test_backup_and_restore_lifecycle[ui-chromium]: a [ui-chromium] "
    "variant would repeat the same GraphQL calls with one more deployment boot."
)
async def test_restore_loads_the_dump_over_a_table_that_the_application_created_first(
    styrmin_resources: dict,
    restore_test_drivers: None,  # noqa: ARG001 — loads the test driver
    simple_app_image: str,  # noqa: ARG001 — builds the image
    velero_ready: None,  # noqa: ARG001 — ensures Velero is up before backup/restore
    vcluster: dict,
) -> None:
    """The restore completes and gives back the rows, and drops what the dump does not hold."""
    client: StyrminClient = styrmin_resources["client"]
    async with deployed(client, styrmin_resources, vcluster, "postgres-leftover") as (
        deployment
    ):
        assert await sql(deployment, "INSERT INTO e2e_parent VALUES (1), (2), (3)") == (
            "INSERT 0 3"
        )
        # The dump must not hold the table that the init script creates again at the restore.
        await sql(deployment, "DROP TABLE e2e_child")
        backup = await back_up(client, deployment)

        created_restore = await client.backups.create_restore(backup_id=backup.id)
        restore = await client.backups.wait_for_restore(
            created_restore.id, max_wait=600
        )

        assert restore.status == "completed", (
            f"restore {restore.id}: {restore.status!r}, {restore.error_message!r}"
        )
        assert [(step.key, step.status.value) for step in restore.steps] == [
            ("restore:namespace", "SUCCEEDED"),
            ("restore:velero", "SUCCEEDED"),
            ("restore:recovery", "SUCCEEDED"),
        ], restore.steps
        await wait_for_pods_ready(
            deployment["kubeconfig_path"], deployment["namespace"]
        )
        assert (
            await sql(
                deployment,
                "SELECT string_agg(id::text, ',' ORDER BY id) FROM e2e_parent",
            )
            == MARKER_ROWS
        )
        assert (
            await sql(
                deployment,
                "SELECT count(*) FROM pg_tables WHERE tablename = 'e2e_child'",
            )
            == "0"
        ), "the table that the dump does not hold is gone after the restore"
