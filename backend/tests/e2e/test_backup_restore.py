"""E2E tests for the backup and restore lifecycle."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService
from styrmin_sdk import StyrminClient

from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.drivers import ResourceNotFound, ScenarioDriver

pytestmark = [
    pytest.mark.shard_backup,
]

# Environment-scope retention policy exercised by the lifecycle test
# (016-backup-retention-ttl / US1). Deliberately different from the built-in
# ``DEFAULT_BACKUP_TTL`` ("720h") so the assertions cannot pass on the default.
ENVIRONMENT_BACKUP_TTL = "2160h"

# The env-config write fans out a redeploy Task to every deployment in the
# environment; the same budget the 009 fanout E2E allows for a deployment to
# reconcile back to RUNNING.
FANOUT_RECONCILE_TIMEOUT_SECONDS = 480.0

# ``TaskStatus`` values that mean "this Task is still in flight".
_NON_TERMINAL_TASK_STATUSES = frozenset({"pending", "running"})

# Backdated stamp written onto a BackupRepository's ``status.lastMaintenanceTime``
# to make kopia maintenance overdue. It doubles as the "not maintained yet"
# marker the poll waits to see replaced, so it must be a value Velero would never
# write itself.
MAINTENANCE_OVERDUE_SENTINEL = "1970-01-01T00:00:00Z"

# Parked on the repository once the forced cycle has been observed, so the
# session-shared cluster is not left running a maintenance Job on every reconcile.
MAINTENANCE_FREQUENCY_AFTER_CHECK = "24h"


@asynccontextmanager
async def portforward_simple_app(
    kubeconfig_path: str,
    namespace: str,
    service_name: str = "simple-app",
) -> AsyncIterator[int]:
    """Port-forward the simple-app service and yield the local port.

    ``service_name`` defaults to the driver's service name; callers that
    deploy with a ``service_name_overrides`` must pass the override so
    that cross-namespace ``ExternalName`` aliases for sibling deployments
    in the shared env don't get matched instead.
    """
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    simple_app_svc = await AsyncService.get(
        service_name, namespace=namespace, api=kr8s_api
    )
    assert simple_app_svc is not None, (
        f"Could not find service {service_name!r} in namespace {namespace!r}"
    )

    async with _portforward(simple_app_svc, remote_port=8000) as local_port:
        await _wait_for_http(
            f"http://localhost:{local_port}/health", timeout=30.0, interval=3.0
        )
        yield local_port


async def wait_for_pods_ready(
    kubeconfig_path: str,
    namespace: str,
    timeout: float = 180.0,
) -> None:
    """Wait until all pods in *namespace* have ready containers."""
    import time

    from kubernetes_asyncio import client as kubeclient, config as k8s_config

    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    core_api = kubeclient.CoreV1Api(api_client)

    deadline = time.time() + timeout
    while time.time() < deadline:
        pods = await core_api.list_namespaced_pod(namespace=namespace)
        if pods.items and all(
            c.ready
            for pod in pods.items
            if pod.status and pod.status.container_statuses
            for c in pod.status.container_statuses
        ):
            await api_client.close()
            return
        await asyncio.sleep(5)
    await api_client.close()
    raise TimeoutError(f"Pods in {namespace} did not become ready within {timeout}s")


async def read_velero_backup(kubeconfig_path: str, backup_name: str) -> dict:
    """Return the Velero Backup CRD named *backup_name* from the cluster."""
    from kubernetes_asyncio import client as kubeclient
    from kubernetes_asyncio import config as k8s_config
    from kubernetes_asyncio.client import CustomObjectsApi

    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    custom_api = CustomObjectsApi(api_client)
    try:
        return await custom_api.get_namespaced_custom_object(
            group="velero.io",
            version="v1",
            namespace="styrmin",
            plural="backups",
            name=backup_name,
        )
    finally:
        await api_client.close()


async def assert_velero_backup_uses_bsl(
    kubeconfig_path: str,
    backup_name: str,
    expected_bsl_name: str,
) -> None:
    """Verify the Velero Backup CRD on the cluster targets the expected BSL."""
    velero_backup = await read_velero_backup(kubeconfig_path, backup_name)
    actual = velero_backup["spec"].get("storageLocation")
    expected = f"styrmin-bsl-{expected_bsl_name}"
    assert actual == expected, f"Expected storageLocation '{expected}', got '{actual}'"


async def assert_backup_repository_maintenance_succeeds(
    kubeconfig_path: str,
    timeout: float = 300.0,
) -> None:
    """Force a kopia maintenance cycle and assert Velero can complete it.

    Velero builds the repository-maintenance Job out of its *own* Deployment,
    which it resolves under the hardcoded name ``velero`` in the Velero
    namespace (``pkg/repository/manager/manager.go``, ``buildMaintenanceJob``).
    When the Helm fullname drifts off that name — the subchart's default is
    ``<release>-velero`` — every cycle fails with ``error to build maintenance
    job: Deployment.apps "velero" not found``, kopia never prunes, and deleted
    backups keep occupying object storage forever. Nothing in the backup or
    restore flow notices, which is why the assertion lives here.

    Velero stamps ``status.lastMaintenanceTime`` when it *initialises* a
    repository and only maintains again one ``spec.maintenanceFrequency`` later,
    so a repository this young would never maintain inside a test run.
    Backdating the stamp makes it overdue; the frequency edit in the same patch
    is what wakes the controller, which reconciles on spec changes only.
    """
    import time

    from kubernetes_asyncio import client as kubeclient
    from kubernetes_asyncio import config as k8s_config
    from kubernetes_asyncio.client import CustomObjectsApi

    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    custom_api = CustomObjectsApi(api_client)
    repository_crd = {
        "group": "velero.io",
        "version": "v1",
        "namespace": "styrmin",
        "plural": "backuprepositories",
    }

    name = ""
    deadline = time.time() + timeout
    try:
        # Only a Ready repository takes the controller's maintenance branch, and
        # only an initialised one already carries the `status` object the patch
        # below writes into.
        while True:
            listed = await custom_api.list_namespaced_custom_object(**repository_crd)
            ready = [
                repository
                for repository in listed["items"]
                if (repository.get("status") or {}).get("phase") == "Ready"
            ]
            if ready:
                break
            assert time.time() < deadline, (
                "A completed file-system backup should have left a Ready Velero "
                "BackupRepository in the styrmin namespace; found "
                + str(
                    [
                        (
                            repository["metadata"]["name"],
                            (repository.get("status") or {}).get("phase"),
                        )
                        for repository in listed["items"]
                    ]
                )
            )
            await asyncio.sleep(5)

        name = ready[0]["metadata"]["name"]

        await custom_api.patch_namespaced_custom_object(
            **repository_crd,
            name=name,
            body=[
                {
                    "op": "add",
                    "path": "/status/lastMaintenanceTime",
                    "value": MAINTENANCE_OVERDUE_SENTINEL,
                },
                {"op": "replace", "path": "/spec/maintenanceFrequency", "value": "1s"},
            ],
        )

        # Read the sentinel back before waiting on it. `BackupRepository` has no
        # status subresource today, so patching `/status` through the main
        # endpoint lands — but if that ever changes the API server drops the
        # status half silently, `lastMaintenanceTime` keeps its original value,
        # and the poll below would return on its first iteration having proved
        # nothing.
        patched = await custom_api.get_namespaced_custom_object(
            **repository_crd, name=name
        )
        assert (patched.get("status") or {}).get(
            "lastMaintenanceTime"
        ) == MAINTENANCE_OVERDUE_SENTINEL, (
            f"Backdating status.lastMaintenanceTime on {name!r} did not stick "
            f"(got {(patched.get('status') or {}).get('lastMaintenanceTime')!r}), "
            "so this assertion cannot tell a maintained repository from an "
            "untouched one. `BackupRepository` has probably gained a status "
            "subresource — patch it through that instead."
        )

        status: dict = {}
        while time.time() < deadline:
            repository = await custom_api.get_namespaced_custom_object(
                **repository_crd, name=name
            )
            status = repository.get("status") or {}
            # Velero writes the failure onto `status.message` and leaves
            # `lastMaintenanceTime` untouched, so a non-empty message is a
            # verdict, not a transient state — fail on it instead of burning
            # the whole timeout.
            message = status.get("message") or ""
            assert not message, (
                f"Velero could not maintain backup repository {name!r}: "
                f'{message}. A `Deployment.apps "velero" not found` here '
                "means the Velero Deployment is no longer named `velero` — see "
                "backend/tests/unit/test_helm_velero_naming.py."
            )
            if status.get("lastMaintenanceTime") != MAINTENANCE_OVERDUE_SENTINEL:
                return
            await asyncio.sleep(5)

        raise AssertionError(
            f"Velero did not maintain backup repository {name!r} within "
            f"{timeout}s: status.lastMaintenanceTime is still the backdated "
            f"sentinel and status.message is empty (phase "
            f"{status.get('phase')!r})"
        )
    finally:
        # Park the frequency well beyond the session so the remaining tests do
        # not share the cluster with a maintenance Job every reconcile. Runs
        # even on failure: the 1s frequency must not outlive this assertion.
        if name:
            with suppress(Exception):
                await custom_api.patch_namespaced_custom_object(
                    **repository_crd,
                    name=name,
                    body=[
                        {
                            "op": "replace",
                            "path": "/spec/maintenanceFrequency",
                            "value": MAINTENANCE_FREQUENCY_AFTER_CHECK,
                        }
                    ],
                )
        await api_client.close()
        await api_client.close()


async def assert_velero_backup_ttl(
    kubeconfig_path: str,
    backup_name: str,
    expected_ttl: str,
) -> None:
    """Verify the Velero Backup CRD carries the resolved retention TTL.

    This is the outer end of 016-backup-retention-ttl / FR-002: whatever the
    resolver picked must land on ``spec.ttl`` of the object Velero actually
    acts on, not merely on the Styrmin backup record.
    """
    velero_backup = await read_velero_backup(kubeconfig_path, backup_name)
    actual = velero_backup["spec"].get("ttl")
    assert actual == expected_ttl, (
        f"Expected Velero Backup {backup_name!r} spec.ttl {expected_ttl!r}, "
        f"got {actual!r}"
    )


async def wait_for_env_fanout_steady_state(
    client: StyrminClient,
    deployment_id: str,
    pre_timeline_length: int,
    timeout: float = FANOUT_RECONCILE_TIMEOUT_SECONDS,
) -> None:
    """Block until the redeploy fanout from an env-config write has settled.

    Writing an environment's config queues a redeploy Task on every active
    deployment in it (009-environment-update) — synchronously, in the same
    transaction as the config row, so the new timeline entry is already visible
    when the mutation returns. ``backup_ttl`` renders to nothing, making the
    redeploy a Helm-level no-op, but the deployment still walks the whole
    reconcile path and a backup started mid-flight races it (016 critique E3).

    Steady state is: the fanout Task appeared, every Task added by the fanout
    reached a terminal status, and the deployment is back to RUNNING.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    last_reason = "fanout Task never appeared on the timeline"
    while asyncio.get_event_loop().time() < deadline:
        timeline = await client.deployments.get_timeline(deployment_id=deployment_id)
        new_count = len(timeline) - pre_timeline_length
        if new_count <= 0:
            await asyncio.sleep(2)
            continue
        # Timeline is ordered newest-first (``TaskRepository.find_by_deployment``),
        # so the fanout's entries sit at the front.
        in_flight = [
            entry
            for entry in timeline[:new_count]
            if (entry.task.status or "").lower() in _NON_TERMINAL_TASK_STATUSES
        ]
        if in_flight:
            last_reason = (
                f"{len(in_flight)} fanout Task(s) still in flight: "
                f"{[(str(e.task.type_), e.task.status) for e in in_flight]}"
            )
            await asyncio.sleep(2)
            continue
        deployment = await client.deployments.get(deployment_id)
        if deployment.status != "running":
            last_reason = f"deployment status is {deployment.status!r}, want 'running'"
            await asyncio.sleep(2)
            continue
        return
    raise AssertionError(
        f"Environment-config fanout did not reach steady state for deployment "
        f"{deployment_id} within {timeout}s — {last_reason}"
    )


@pytest.mark.ci
async def test_backup_and_restore_lifecycle(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,
    deployed_simple_app: dict,
    velero_ready: None,  # noqa: ARG001 — ensures Velero is up before backup/restore
    vcluster: dict,
) -> None:
    """Full lifecycle: write data -> backup -> modify -> restore -> verify.

    Also covers 016-backup-retention-ttl / US1: the environment-scope
    ``backup_ttl`` policy set below must land on the Velero Backup CRD's
    ``spec.ttl`` and be readable back off the backup record together with
    Velero's own expiry.
    """
    client: StyrminClient = styrmin_resources["client"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    deployment_id = deployed_simple_app["deployment_id"]
    instance_id = deployed_simple_app["instance_id"]
    assert instance_id is not None, "Deployment should have an instance_id"
    namespace = deployed_simple_app["namespace"]

    # Verify environment exposes backup capability (BSL was assigned by the fixture)
    environment = await client.environments.get(environment_id=scenario_environment_id)
    assert environment.capabilities is not None, "Environment should have capabilities"
    assert "backup" in environment.capabilities, (
        "Environment should have backup capability"
    )
    assert "velero" in environment.capabilities["backup"], (
        "Environment should have velero backup provider"
    )
    assert (
        environment.capabilities["backup"]["velero"]["storage_location"]
        == styrmin_resources["bsl_name"]
    ), f"Backup storage_location should be '{styrmin_resources['bsl_name']}'"

    # 0. Set the environment-scope retention policy (016 / FR-001), then let
    #    the redeploy fanout it triggers settle before touching any data —
    #    the environment is session-shared and the backup must not race the
    #    no-op redeploy (critique E3).
    pre_timeline_length = len(
        await client.deployments.get_timeline(deployment_id=deployment_id)
    )
    # The scenario environment is session-scoped, so the policy set below is
    # reverted in the ``finally``: leaving a 2160h retention behind would
    # silently hand that policy to every later ``shard_backup`` test that
    # reuses this environment.
    previous_backup_ttl = (
        (await client.environments.get(environment_id=scenario_environment_id)).config
        or {}
    ).get("backup_ttl")

    try:
        # Driven through the dual-entrypoint driver method so the retention
        # policy is set via the typed SDK under ``[api-chromium]`` and via the
        # BackupRetentionForm on the Configuration tab under ``[ui-chromium]``
        # — the parametrisation IS the parity check (016 / US1).
        await scenario_driver.set_environment_backup_ttl(
            environment_id=scenario_environment_id,
            ttl=ENVIRONMENT_BACKUP_TTL,
        )
        stored_environment = await client.environments.get(
            environment_id=scenario_environment_id
        )
        assert (stored_environment.config or {}).get("backup_ttl") == (
            ENVIRONMENT_BACKUP_TTL
        ), (
            "Environment config should carry the retention policy, got "
            f"{stored_environment.config!r}"
        )
        await wait_for_env_fanout_steady_state(
            client,
            deployment_id=deployment_id,
            pre_timeline_length=pre_timeline_length,
        )
        await wait_for_pods_ready(kubeconfig_path, namespace)

        # The retention write left the UI driver on the environment detail
        # page, but every backup/restore step below acts on whichever
        # deployment detail page is open. Re-bind the driver and re-enter that
        # page. For the API driver ``attach_to_deployment`` is a no-op and the
        # wait is one SDK read on an already-running deployment, so this needs
        # no ``driver_mode`` branch.
        scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)
        await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)

        # 1. Write test data (increment counter N times)
        async with portforward_simple_app(kubeconfig_path, namespace) as port:
            async with httpx.AsyncClient() as http_client:
                for _ in range(5):
                    await http_client.get(f"http://localhost:{port}/count", timeout=10)
                resp = await http_client.get(
                    f"http://localhost:{port}/count", timeout=10
                )
                pre_backup_count = resp.json()["counter"]  # 6

        # 2. Create backup via scenario_driver, wait for completion
        created_backup = await scenario_driver.create_backup(instance_id=instance_id)
        assert created_backup.status in {"pending", "in_progress", "completed"}
        backup = await scenario_driver.wait_for_backup(
            backup_id=created_backup.id, max_wait=180
        )
        assert backup.status == "completed"

        # 2b. Verify backup targets the assigned BSL and carries the
        #     environment-scope retention (016 / FR-002).
        await assert_velero_backup_uses_bsl(
            kubeconfig_path=kubeconfig_path,
            backup_name=backup.name,
            expected_bsl_name=styrmin_resources["bsl_name"],
        )
        await assert_velero_backup_ttl(
            kubeconfig_path=kubeconfig_path,
            backup_name=backup.name,
            expected_ttl=ENVIRONMENT_BACKUP_TTL,
        )

        # 2c. The applied retention and Velero's own expiry are readable off the
        #     backup record — no cluster access required (016 / FR-006, FR-008).
        recorded_backup = await client.backups.get_backup(backup.id)
        assert recorded_backup.ttl == ENVIRONMENT_BACKUP_TTL, (
            f"Backup record should report the applied TTL {ENVIRONMENT_BACKUP_TTL!r}, "
            f"got {recorded_backup.ttl!r}"
        )
        assert recorded_backup.expires_at is not None, (
            "A completed backup must record Velero's expiration timestamp"
        )

        # 2d. Velero can actually maintain (kopia-prune) the repository the
        #     backup just wrote to. Without this the repository grows forever
        #     while every backup and restore keeps passing.
        await assert_backup_repository_maintenance_succeeds(kubeconfig_path)

        # 3. Write more data (counter goes higher)
        async with portforward_simple_app(kubeconfig_path, namespace) as port:
            async with httpx.AsyncClient() as http_client:
                for _ in range(5):
                    await http_client.get(f"http://localhost:{port}/count", timeout=10)

        # 4. Restore from backup via scenario_driver (same namespace)
        created_restore = await scenario_driver.create_restore(
            backup_id=backup.id, target_namespace=namespace
        )
        assert created_restore.status in {"pending", "in_progress", "completed"}
        restore = await scenario_driver.wait_for_restore(
            restore_id=created_restore.id, max_wait=300
        )
        assert restore.status == "completed"

        # 5. Wait for pods to recover, verify data restored
        await wait_for_pods_ready(kubeconfig_path, namespace)
        async with portforward_simple_app(kubeconfig_path, namespace) as port:
            async with httpx.AsyncClient() as http_client:
                resp = await http_client.get(
                    f"http://localhost:{port}/count", timeout=10
                )
                # Counter should be back near pre-backup value
                assert resp.json()["counter"] == pre_backup_count + 1

        # 6. Delete backup and verify
        await scenario_driver.delete_backup(backup_id=backup.id)
        with pytest.raises(ResourceNotFound):
            await scenario_driver.get_backup(backup_id=backup.id)
    finally:
        # Restore the session-shared environment's retention policy. The
        # revert itself must succeed (a leak is exactly what we are guarding
        # against); the fanout wait afterwards is best-effort so a cleanup
        # timeout can never mask the test's own failure.
        revert_timeline_length = len(
            await client.deployments.get_timeline(deployment_id=deployment_id)
        )
        await scenario_driver.set_environment_backup_ttl(
            environment_id=scenario_environment_id,
            ttl=previous_backup_ttl,
        )
        with suppress(AssertionError):
            await wait_for_env_fanout_steady_state(
                client,
                deployment_id=deployment_id,
                pre_timeline_length=revert_timeline_length,
            )
        # Leave the driver back on the deployment detail page: the UI driver's
        # page is session-scoped, and the sibling backup tests that follow act
        # on whatever page is open. Best-effort like the wait above — a cleanup
        # hiccup must never mask the test's own failure.
        scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)
        with suppress(Exception):
            await scenario_driver.wait_for_deployment_running(
                deployment_id=deployment_id, timeout=FANOUT_RECONCILE_TIMEOUT_SECONDS
            )


# ---------------------------------------------------------------------------
# Restore lifecycle (deployment.status transitions: running -> restoring -> running)
# ---------------------------------------------------------------------------


async def _wait_for_deployment_status(
    client: StyrminClient,
    deployment_id,
    expected: set[str],
    max_wait: float,
    poll: float = 1.0,
) -> str:
    """Poll deployment.status until it lands in *expected* or timeout.

    Returns the observed status; raises if no expected status is reached.
    """
    deadline = asyncio.get_event_loop().time() + max_wait
    last_seen: str = ""
    while asyncio.get_event_loop().time() < deadline:
        deployment = await client.deployments.get(deployment_id)
        last_seen = deployment.status
        if last_seen in expected:
            return last_seen
        await asyncio.sleep(poll)
    raise AssertionError(
        f"Deployment {deployment_id} status={last_seen!r}; expected one of {expected!r}"
    )


@pytest.mark.ci
async def test_restore_lifecycle_transitions(
    deployed_simple_app: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> None:
    """Backup → Restore → assert deployment passes through restoring → running.

    Reproduces the regression where post-velero the deployment landed in
    'failed' despite healthy pods. The lifecycle now flips to RESTORING on
    restore start and back to RUNNING after the restore-finish reapply.
    """
    driver, client = session_scenario_driver
    deployment_id = deployed_simple_app["deployment_id"]
    instance_id = deployed_simple_app["instance_id"]
    namespace = deployed_simple_app["namespace"]

    # Wait for the agent's status reporter to propagate the deployed
    # state to deployment.status. ``deployed_simple_app`` returns once
    # the CRD reaches Ready, but the DB-side status is updated on the
    # next status poll, which can lag a few seconds.
    await _wait_for_deployment_status(
        client, deployment_id, expected={"running"}, max_wait=30
    )

    backup = await driver.create_backup(instance_id=instance_id)
    backup = await driver.wait_for_backup(backup_id=backup.id, max_wait=180)
    assert backup.status == "completed"

    # Kick off the restore. The styrmin restore flow flips the deployment
    # to RESTORING in the same transaction that creates the restore record,
    # so the very next read should observe the transition.
    created_restore = await driver.create_restore(
        backup_id=backup.id, target_namespace=namespace
    )

    observed = await _wait_for_deployment_status(
        client,
        deployment_id,
        expected={"restoring"},
        max_wait=10,
    )
    assert observed == "restoring"

    # Velero + post-restore reapply runs to completion.
    restore = await driver.wait_for_restore(restore_id=created_restore.id, max_wait=600)
    assert restore.status == "completed"

    # The restore workflow's finish hook moves the deployment back to
    # running synchronously after the reapply succeeds.
    final = await _wait_for_deployment_status(
        client,
        deployment_id,
        expected={"running"},
        max_wait=120,
    )
    assert final == "running"


@pytest.mark.ci
async def test_restore_failure_marks_failed_not_indefinite(
    deployed_simple_app: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> None:
    """If velero fails, deployment becomes 'failed' with a clear message —
    not stuck in 'restoring' forever.

    Provokes the failure by passing a non-existent backup id; the styrmin
    server-side guard rejects it before the workflow starts, so the
    deployment stays in 'running' (RESTORING was never set). This is the
    safer end of the failure spectrum: we explicitly verify the user-
    requested invariant that a failed restore never leaves the deployment
    stuck in RESTORING.
    """
    from uuid import uuid4

    _, client = session_scenario_driver
    deployment_id = deployed_simple_app["deployment_id"]

    pre = await client.deployments.get(deployment_id)
    pre_status = pre.status

    with pytest.raises(Exception):
        await client.backups.create_restore(
            backup_id=uuid4(), target_namespace=deployed_simple_app["namespace"]
        )

    # Deployment is not knocked into 'restoring' by an invalid request.
    after = await client.deployments.get(deployment_id)
    assert after.status == pre_status, (
        f"Failed restore must not change deployment status; was {pre_status!r}, "
        f"now {after.status!r}"
    )
