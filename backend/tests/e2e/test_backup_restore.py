"""E2E tests for the backup and restore lifecycle."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Any, AsyncIterator, NamedTuple, Sequence

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService
from prefect.client.orchestration import PrefectClient
from prefect.client.schemas.filters import FlowFilter, FlowFilterName
from prefect.exceptions import ObjectNotFound
from styrmin_sdk import StyrminClient
from styrmin_sdk._queries import load_query
from styrmin_sdk.exceptions import OperationFailedError, ResourceNotFoundError

from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.drivers import (
    BackupRef,
    EnvironmentBackupRef,
    EnvironmentCloneDeploymentResultRef,
    EnvironmentCloneRef,
    ResourceNotFound,
    RestoreRef,
    ScenarioDriver,
    StepRef,
)

# Shard markers are per test: deployment-level tests run in ``shard_backup``,
# environment-level ones in ``shard_env_backup`` (split for CI wall-clock).

# Environment-scope retention policy exercised by the lifecycle test
# (016-backup-retention-ttl / US1). Deliberately different from the built-in
# ``DEFAULT_BACKUP_TTL`` ("720h") so the assertions cannot pass on the default.
ENVIRONMENT_BACKUP_TTL = "2160h"

# The environment-config mutation the environment-level lifecycle test writes
# between backup and restore (spec SC-005). Distinct from both
# ``ENVIRONMENT_BACKUP_TTL`` above and the built-in default so "config equals
# the captured value" cannot pass by coincidence.
ENVIRONMENT_SNAPSHOT_MUTATED_TTL = "1440h"

# The env-config write fans out a redeploy Task to every deployment in the
# environment; the same budget the 009 fanout E2E allows for a deployment to
# reconcile back to RUNNING.
FANOUT_RECONCILE_TIMEOUT_SECONDS = 480.0

# A fresh deployment reaching RUNNING. Matches the ``wait_for_deployment_running``
# protocol default that the ``deployed_simple_app`` fixture relies on for the
# identical simple-app deployment — a *create* is not a config fanout and does
# not need ``FANOUT_RECONCILE_TIMEOUT_SECONDS``.
DEPLOYMENT_RUNNING_TIMEOUT_SECONDS = 300.0

# Best-effort waits in a ``finally`` block get their own, much smaller budget.
# They exist to hand a sane environment to the sibling tests in the same shard,
# not to prove anything — and every one of them is wrapped in ``suppress``. On
# the failure path a full reconcile budget per cleanup wait is actively harmful:
# it can push the job past ``timeout-minutes`` so the runner kills the cell
# before pytest ever writes the real failure out.
CLEANUP_WAIT_TIMEOUT_SECONDS = 180.0

# A cleanup revert can write the value a deployment already runs with; the
# fanout then skips it and no Task ever appears, so stop waiting after this.
NOOP_FANOUT_GRACE_SECONDS = 15.0

# One coordinated environment backup: N constituent per-instance Velero backups
# dispatched concurrently after the parent commits. Calibrated off the sibling
# per-instance budgets in this shard rather than guessed — 180s for one
# simple-app backup (``test_backup_and_restore_lifecycle``) and 300s for the
# heavier MariaDB+MongoDB one (``test_backup_restore_databases``) — so 300s
# covers a concurrent simple-app fan-out with the shard's widest single-backup
# budget.
ENVIRONMENT_BACKUP_FANOUT_TIMEOUT_SECONDS = 300.0

# The *derived* parent status, once every constituent has already been observed
# in its expected outcome. Deriving happens on read, so the next read after the
# constituents settle is already terminal; this is slack for the UI
# entrypoint's list refetch, not for any backend work.
DERIVED_STATUS_TIMEOUT_SECONDS = 60.0

# One coordinated environment restore. Only one constituent is restorable in
# this scenario (the other's backup is deleted on purpose), so this is a
# single-restore budget: the same 600s ``test_restore_lifecycle_transitions``
# allows for one simple-app Velero restore plus the post-restore reapply.
ENVIRONMENT_RESTORE_TIMEOUT_SECONDS = 600.0

# ``TaskStatus`` values that mean "this Task is still in flight".
_NON_TERMINAL_TASK_STATUSES = frozenset({"pending", "running"})

# Backdated ``status.lastMaintenanceTime`` that makes kopia maintenance overdue. Velero
# never writes this value itself, so it also marks "not maintained yet" for the poll.
MAINTENANCE_OVERDUE_SENTINEL = "1970-01-01T00:00:00Z"

# Parked on the repository after the forced cycle so the shared cluster stops maintaining.
MAINTENANCE_FREQUENCY_AFTER_CHECK = "24h"

# --- Backup and restore steps (spec 019-task-steps / US6) ------------------

# simple-app's components with a backup configuration
# (``driver/examples/simple-app/driver.styrmin.yml``): one backup step each.
SIMPLE_APP_BACKUP_COMPONENTS = ("database",)

# Set on ``server`` after the lifecycle backup so the deployment gets a new
# instance and the backup stays listed only through its history (#304).
BACKUP_HISTORY_SERVER_ENV_VARS = {"STYRMIN_E2E_BACKUP_HISTORY": "1"}

# Set on ``server`` after the lifecycle restore, so the edit after the restore
# gives the deployment a new instance (#426).
AFTER_RESTORE_SERVER_ENV_VARS = {"STYRMIN_E2E_AFTER_RESTORE": "1"}

# The lifecycle test upgrades the session-shared simple-app deployment after the
# backup (the #304 reproduction), and its restore puts 0.1.0 back (#426). It
# never asks for a downgrade: a downgrade would run the driver's action Job a
# second time, which fails while the first Job exists (#374).
SIMPLE_APP_VERSION = "0.1.0"
SIMPLE_APP_UPGRADED_VERSION = "0.2.0"

# The steps of a completed restore, in the order the restore runs them.
COMPLETED_RESTORE_STEPS = (
    ("restore:namespace", "Delete the namespace"),
    ("restore:velero", "Run the Velero restore"),
    ("restore:recovery", "Run the recovery"),
)

# The start of the error "Run the Velero restore" records when Velero rejects
# the restore in validation; Velero's own errors follow, joined by "; ".
VELERO_VALIDATION_ERROR_PREFIX = "Velero restore failed validation:"

# A DeleteBackupRequest removing the backup's data and then its Backup object.
VELERO_BACKUP_REMOVAL_TIMEOUT_SECONDS = 180.0

# --- Environment clone (spec 010-environment-clone) -------------------------

# The retention policy set on the *source* environment before the clone, so the
# captured config has a field the clone can be asked to **clear** (FR-006 /
# US3). A retention policy is the cheapest such field on this session-shared
# environment: it renders to nothing in Helm, so the redeploy fanout it triggers
# is a no-op that still walks the whole reconcile path. Deliberately distinct
# from every other TTL constant in this module so no assertion can pass on a
# coincidence.
CLONE_SOURCE_BACKUP_TTL = "1800h"

# The env var the clone-time config override injects, asserted verbatim on the
# created environment's config. The override is the entire reason a clone of
# production is safe to start (US3's non-interference motive), so the value must
# be one nothing else in the suite sets.
CLONE_OVERRIDE_ENV_VAR_NAME = "CLONE_OVERRIDE_MARKER"
CLONE_OVERRIDE_ENV_VAR_VALUE = "clone-override-sink"

# The captured-config field the clone clears. Snake_case: ``clearConfigFields``
# names persisted ``EnvironmentConfig`` fields, not GraphQL input fields.
CLONE_CLEARED_CONFIG_FIELD = "backup_ttl"

# The attribution reason recorded for a source deployment an explicit selection
# left out. Free text by contract (the vocabulary is open and the backend may
# add to it), so it is asserted as text — mirrored by hand from
# ``services.backup.clone.CLONE_REASON_NOT_SELECTED`` rather than imported, to
# keep the scenario off the service layer's import graph. If the wording
# changes, this is the one place that fails.
CLONE_REASON_NOT_SELECTED = "not included in the requested deployment selection"

# The message of ``UnclonedDeploymentReferenceError`` without the names that follow
# it, mirrored by hand for the same reason as the reason above.
CLONE_REFUSED_UNCLONED_REFERENCE = (
    "An affinity term names a deployment that the clone does not copy"
)

# The ``clone_errors`` step prefix written when the environment a clone created
# is deleted through ordinary environment deletion — the supported discard path
# (SC-005). Entries arrive pre-rendered as ``"step: error"``.
CLONE_DISCARD_STEP_PREFIX = "created_environment_deleted:"

# One whole clone reaching a terminal derived status: the capture fan-out, the
# environment and counterpart creation, and the cross-target constituent
# restore. Calibrated as the sum of the budgets this module already allows for
# those three pieces (``ENVIRONMENT_BACKUP_FANOUT_TIMEOUT_SECONDS`` +
# ``DEPLOYMENT_RUNNING_TIMEOUT_SECONDS`` + ``ENVIRONMENT_RESTORE_TIMEOUT_
# SECONDS``) plus the derived-status slack the UI entrypoint's list refetch
# needs, rather than guessed.
ENVIRONMENT_CLONE_TIMEOUT_SECONDS = (
    ENVIRONMENT_BACKUP_FANOUT_TIMEOUT_SECONDS
    + DEPLOYMENT_RUNNING_TIMEOUT_SECONDS
    + ENVIRONMENT_RESTORE_TIMEOUT_SECONDS
    + DERIVED_STATUS_TIMEOUT_SECONDS
)

# A *configuration-only* clone (empty selection) reaching terminal: a capture
# with no constituents derives ``COMPLETED`` on its first read, the environment
# is created, and there are no counterparts and no restores. Only the clone
# flow's own poll interval stands between registration and terminality, so this
# is deliberately far below ``ENVIRONMENT_CLONE_TIMEOUT_SECONDS`` — a
# config-only clone taking many minutes is a defect, not slowness.
CONFIG_ONLY_CLONE_TIMEOUT_SECONDS = 300.0

# Pods in the *cloned* namespace becoming ready after the cross-target restore.
# Recovery replaces the Velero-restored source-named CR with the counterpart's
# own CR body and Flux rolls the workload, so this is a fresh install's worth of
# waiting on top of the restore rather than a restart.
CLONE_PODS_READY_TIMEOUT_SECONDS = 300.0

# The counterpart's HelmRelease finishing its last reconcile: every Helm upgrade the
# clone causes has run by then, so a prune of the source's objects has happened too.
COUNTERPART_HELMRELEASE_SETTLED_TIMEOUT_SECONDS = 300.0

# Listing the aliases of a restored namespace. Its restore writes them before it
# completes, so the wait covers the read only, never a later flow (spec 030, critique E5).
SERVICE_ALIASES_TIMEOUT_SECONDS = 60.0


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
    """Wait until all pods in *namespace* have ready containers.

    A completed Job pod (phase ``Succeeded``) never becomes ready, so it is skipped.
    """
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
            if pod.status
            and pod.status.container_statuses
            and pod.status.phase != "Succeeded"
            for c in pod.status.container_statuses
        ):
            await api_client.close()
            return
        await asyncio.sleep(5)
    await api_client.close()
    raise TimeoutError(f"Pods in {namespace} did not become ready within {timeout}s")


async def namespace_labels(kubeconfig_path: str, namespace: str) -> dict[str, str]:
    """The labels of *namespace*, as the cluster holds them now."""
    from kubernetes_asyncio import client as kubeclient, config as k8s_config

    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    try:
        read = await kubeclient.CoreV1Api(api_client).read_namespace(name=namespace)
        return dict(read.metadata.labels or {})
    finally:
        await api_client.close()


async def workload_object_names(kubeconfig_path: str, namespace: str) -> set[str]:
    """``kind/name`` of every Deployment, StatefulSet and Service in *namespace*."""
    from kubernetes_asyncio import client as kubeclient, config as k8s_config

    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    try:
        apps_api = kubeclient.AppsV1Api(api_client)
        core_api = kubeclient.CoreV1Api(api_client)
        deployments = await apps_api.list_namespaced_deployment(namespace=namespace)
        stateful_sets = await apps_api.list_namespaced_stateful_set(namespace=namespace)
        services = await core_api.list_namespaced_service(namespace=namespace)
    finally:
        await api_client.close()
    return (
        {f"deployment/{item.metadata.name}" for item in deployments.items}
        | {f"statefulset/{item.metadata.name}" for item in stateful_sets.items}
        | {f"service/{item.metadata.name}" for item in services.items}
    )


class ServiceAlias(NamedTuple):
    """An alias Service: name, owner deployment id, namespace that it points to."""

    name: str
    deployment_id: str
    target_namespace: str


async def service_aliases(kubeconfig_path: str, namespace: str) -> set[ServiceAlias]:
    """Each Service labelled ``styrmin.io/service-alias=true`` in *namespace*."""
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    aliases: set[ServiceAlias] = set()
    async for svc in AsyncService.list(
        namespace=namespace,
        label_selector={"styrmin.io/service-alias": "true"},
        api=kr8s_api,
    ):
        if not isinstance(svc, AsyncService):
            continue
        # ``externalName`` is ``<name>.<namespace>.svc.<cluster domain>``.
        external_name = svc.spec.get("externalName") or ""
        aliases.add(
            ServiceAlias(
                name=svc.name,
                deployment_id=svc.labels.get("styrmin.io/deployment-id", ""),
                target_namespace=(external_name.split(".") + [""])[1],
            )
        )
    return aliases


async def wait_for_service_aliases(
    kubeconfig_path: str,
    namespace: str,
    expected: set[ServiceAlias],
    timeout: float,
    *,
    include: Callable[[ServiceAlias], bool] = lambda _: True,
) -> set[ServiceAlias]:
    """The aliases in *namespace* that *include* keeps, once they equal *expected*.

    Reads every 5 seconds and returns the last set read when *timeout* runs out.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        aliases = {
            alias
            for alias in await service_aliases(kubeconfig_path, namespace)
            if include(alias)
        }
        if aliases == expected or loop.time() >= deadline:
            return aliases
        await asyncio.sleep(5)


async def wait_for_helmreleases_settled(
    kubeconfig_path: str, namespace: str, timeout: float
) -> None:
    """Wait until every HelmRelease in *namespace* is Ready at its latest generation."""
    import time

    from kubernetes_asyncio import client as kubeclient, config as k8s_config

    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    custom_api = kubeclient.CustomObjectsApi(api_client)
    deadline = time.time() + timeout
    releases: list[dict[str, Any]] = []
    try:
        while time.time() < deadline:
            releases = (
                await custom_api.list_namespaced_custom_object(
                    group="helm.toolkit.fluxcd.io",
                    version="v2",
                    namespace=namespace,
                    plural="helmreleases",
                )
            )["items"]
            if releases and all(_helmrelease_settled(release) for release in releases):
                return
            await asyncio.sleep(3)
    finally:
        await api_client.close()
    raise TimeoutError(
        f"HelmReleases in {namespace} did not settle within {timeout}s: "
        f"{[release.get('status') for release in releases]!r}"
    )


def _helmrelease_settled(release: dict[str, Any]) -> bool:
    status = release.get("status") or {}
    if status.get("observedGeneration") != release["metadata"].get("generation"):
        return False
    return any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in status.get("conditions") or []
    )


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


async def assert_backup_size_matches_pod_volume_backups(
    kubeconfig_path: str,
    backup_name: str,
    recorded_size: int | None,
) -> None:
    """Verify ``sizeBytes`` is the byte sum of the backup's PodVolumeBackups (#136).

    Selects the PodVolumeBackups by owner reference rather than the
    ``velero.io/backup-uid`` label the workflow uses, so a wrong label still fails.
    """
    from kubernetes_asyncio import client as kubeclient
    from kubernetes_asyncio import config as k8s_config
    from kubernetes_asyncio.client import CustomObjectsApi

    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    try:
        listed = await CustomObjectsApi(api_client).list_namespaced_custom_object(
            group="velero.io",
            version="v1",
            namespace="styrmin",
            plural="podvolumebackups",
        )
    finally:
        await api_client.close()

    owned = [
        item
        for item in listed["items"]
        if any(
            ref.get("kind") == "Backup" and ref.get("name") == backup_name
            for ref in item["metadata"].get("ownerReferences") or []
        )
    ]
    expected = sum(
        int(((item.get("status") or {}).get("progress") or {}).get("totalBytes") or 0)
        for item in owned
        if (item.get("status") or {}).get("phase") == "Completed"
    )
    assert owned and expected > 0, (
        f"Backup {backup_name!r} should have completed PodVolumeBackups with data; "
        f"found {[(i['metadata']['name'], i.get('status')) for i in owned]}"
    )
    assert recorded_size == expected, (
        f"Backup {backup_name!r} sizeBytes should equal the PodVolumeBackup byte "
        f"sum {expected}, got {recorded_size!r}"
    )


async def assert_velero_backup_uses_bsl(
    kubeconfig_path: str,
    backup_name: str,
    expected_bsl_id: str,
) -> None:
    """Verify the Velero Backup CRD on the cluster targets the expected BSL.

    The Velero object is named after the location's id, not its name (#488).
    """
    velero_backup = await read_velero_backup(kubeconfig_path, backup_name)
    actual = velero_backup["spec"].get("storageLocation")
    expected = f"styrmin-bsl-{expected_bsl_id}"
    assert actual == expected, f"Expected storageLocation '{expected}', got '{actual}'"


async def assert_backup_repository_maintenance_succeeds(
    kubeconfig_path: str,
    ready_timeout: float = 120.0,
    maintenance_timeout: float = 300.0,
) -> None:
    """Force a kopia maintenance cycle on a Ready BackupRepository and wait for it to succeed.

    Velero builds the maintenance Job from a Deployment it looks up by the hardcoded name
    ``velero``, so this fails whenever the Helm fullname drifts off that name.
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
    try:
        # Only a Ready repository takes the controller's maintenance branch.
        deadline = time.time() + ready_timeout
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
        history_before = len(
            (ready[0].get("status") or {}).get("recentMaintenance") or []
        )

        # Backdating makes the repository overdue; the spec change is what wakes the controller.
        await custom_api.patch_namespaced_custom_object(
            **repository_crd,
            name=name,
            body=[
                {
                    "op": "add",
                    "path": "/status/lastMaintenanceTime",
                    "value": MAINTENANCE_OVERDUE_SENTINEL,
                },
                {"op": "add", "path": "/spec/maintenanceFrequency", "value": "1s"},
            ],
        )

        # Read the sentinel back so a silently dropped status patch cannot pass the poll below.
        patched = await custom_api.get_namespaced_custom_object(
            **repository_crd, name=name
        )
        stamped = (patched.get("status") or {}).get("lastMaintenanceTime")
        assert stamped == MAINTENANCE_OVERDUE_SENTINEL, (
            f"Backdating status.lastMaintenanceTime on {name!r} did not stick (got "
            f"{stamped!r}); BackupRepository has probably gained a status subresource -- "
            "patch through it instead."
        )

        deadline = time.time() + maintenance_timeout
        status: dict = {}
        while time.time() < deadline:
            repository = await custom_api.get_namespaced_custom_object(
                **repository_crd, name=name
            )
            status = repository.get("status") or {}
            assert status.get("phase") == "Ready", (
                f"BackupRepository {name!r} left Ready while waiting for maintenance: "
                f"phase {status.get('phase')!r}, message {status.get('message')!r}"
            )
            # A failed cycle is appended to recentMaintenance instead of stamping
            # lastMaintenanceTime, so a new Failed entry is a verdict, not a transient.
            failed = [
                entry
                for entry in (status.get("recentMaintenance") or [])[history_before:]
                if entry.get("result") == "Failed"
            ]
            assert not failed, (
                f"Velero could not maintain backup repository {name!r}: "
                f'{failed[0].get("message")!r}. A `Deployment.apps "velero" not found` '
                "here means the Velero Deployment is no longer named `velero` -- see "
                "backend/tests/unit/test_helm_velero_naming.py."
            )
            if status.get("lastMaintenanceTime") != MAINTENANCE_OVERDUE_SENTINEL:
                return
            await asyncio.sleep(5)

        raise AssertionError(
            f"Velero did not maintain backup repository {name!r} within "
            f"{maintenance_timeout}s: status.lastMaintenanceTime is still the backdated "
            f"sentinel (recentMaintenance {status.get('recentMaintenance')!r})"
        )
    finally:
        # Runs even on failure: the 1s frequency must not outlive this assertion.
        if name:
            with suppress(Exception):
                await custom_api.patch_namespaced_custom_object(
                    **repository_crd,
                    name=name,
                    body=[
                        {
                            "op": "add",
                            "path": "/spec/maintenanceFrequency",
                            "value": MAINTENANCE_FREQUENCY_AFTER_CHECK,
                        }
                    ],
                )
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


def _assert_step_times(step: StepRef, *, context: str) -> datetime:
    """Assert the step has a start, an end and a duration; return its start."""
    assert step.started_at and step.ended_at, (
        f"{context}: step {step.key!r} needs a start and an end time, got {step!r}"
    )
    started_at = datetime.fromisoformat(step.started_at)
    assert datetime.fromisoformat(step.ended_at) >= started_at, (
        f"{context}: step {step.key!r} ends before it starts: {step!r}"
    )
    return started_at


def assert_steps_in_order(
    steps: Sequence[StepRef],
    expected: Sequence[tuple[str, str, str]],
    *,
    context: str,
) -> None:
    """Assert ``(key, name, status)`` of each step, and start times in that order."""
    assert [(step.key, step.name, step.status) for step in steps] == list(expected), (
        f"{context}: unexpected steps {steps!r}"
    )
    started = [_assert_step_times(step, context=context) for step in steps]
    assert started == sorted(started), (
        f"{context}: steps are not listed in the order they started: {steps!r}"
    )


def assert_backup_component_steps(backup: BackupRef) -> None:
    """A completed simple-app backup lists one succeeded step per component."""
    assert_steps_in_order(
        backup.steps,
        [
            (f"backup:component:{component}", f"Back up {component}", "SUCCEEDED")
            for component in SIMPLE_APP_BACKUP_COMPONENTS
        ],
        context=f"backup {backup.id}",
    )
    assert {step.kind for step in backup.steps} == {"BACKUP_COMPONENT"}


def assert_completed_restore_steps(restore: RestoreRef) -> None:
    """A completed restore lists its three steps in order, each succeeded."""
    assert_steps_in_order(
        restore.steps,
        [(key, name, "SUCCEEDED") for key, name in COMPLETED_RESTORE_STEPS],
        context=f"restore {restore.id}",
    )
    assert {step.kind for step in restore.steps} == {"RESTORE"}


async def remove_velero_backup(
    kubeconfig_path: str, backup_name: str, timeout: float
) -> None:
    """Remove a Velero backup and its stored data, then wait until the Backup is gone.

    A ``DeleteBackupRequest`` also deletes the data in the storage location, so
    Velero's backup sync cannot create the ``Backup`` object again.
    """
    from kubernetes_asyncio import client as kubeclient
    from kubernetes_asyncio import config as k8s_config
    from kubernetes_asyncio.client import CustomObjectsApi
    from kubernetes_asyncio.client.exceptions import ApiException

    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    custom_api = CustomObjectsApi(api_client)
    loop = asyncio.get_running_loop()
    try:
        await custom_api.create_namespaced_custom_object(
            group="velero.io",
            version="v1",
            namespace="styrmin",
            plural="deletebackuprequests",
            body={
                "apiVersion": "velero.io/v1",
                "kind": "DeleteBackupRequest",
                "metadata": {"generateName": f"{backup_name}-"},
                "spec": {"backupName": backup_name},
            },
        )
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                await custom_api.get_namespaced_custom_object(
                    group="velero.io",
                    version="v1",
                    namespace="styrmin",
                    plural="backups",
                    name=backup_name,
                )
            except ApiException as exc:
                if exc.status == 404:
                    return
                raise
            await asyncio.sleep(3)
    finally:
        await api_client.close()
    raise AssertionError(
        f"Velero Backup {backup_name!r} still exists {timeout}s after its "
        "DeleteBackupRequest"
    )


async def wait_for_env_fanout_steady_state(
    client: StyrminClient,
    deployment_id: str,
    pre_timeline_length: int,
    timeout: float = FANOUT_RECONCILE_TIMEOUT_SECONDS,
    noop_grace: float | None = None,
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

    ``noop_grace`` is for cleanup reverts only: the fanout skips a deployment
    already at the written config, so return if no Task appears within it.
    """
    start = asyncio.get_event_loop().time()
    deadline = start + timeout
    last_reason = "fanout Task never appeared on the timeline"
    while asyncio.get_event_loop().time() < deadline:
        timeline = await client.deployments.get_timeline(deployment_id=deployment_id)
        new_count = len(timeline) - pre_timeline_length
        if new_count <= 0:
            if (
                noop_grace is not None
                and asyncio.get_event_loop().time() - start >= noop_grace
            ):
                return
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


async def served_simple_app_version(
    kubeconfig_path: str, namespace: str, *, expected: str, timeout: float = 120.0
) -> str | None:
    """Poll the simple app's ``/version`` until it serves ``expected``; return the last value.

    Pods restart after an upgrade or a restore, so a request can hit a
    terminating pod; transport errors and a /health timeout count as "try again".
    """
    deadline = asyncio.get_running_loop().time() + timeout
    last_version: str | None = None
    while asyncio.get_running_loop().time() < deadline:
        with suppress(httpx.HTTPError, TimeoutError):
            async with portforward_simple_app(kubeconfig_path, namespace) as port:
                async with httpx.AsyncClient() as http_client:
                    response = await http_client.get(
                        f"http://localhost:{port}/version", timeout=10
                    )
                    if response.status_code == 200:
                        last_version = response.json()["version"]
                        if last_version == expected:
                            return last_version
        await asyncio.sleep(3.0)
    return last_version


@pytest.mark.ci
@pytest.mark.shard_backup
async def test_backup_and_restore_lifecycle(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,
    deployed_simple_app: dict,
    simple_app_image_v2: str,  # noqa: ARG001 — ensures the 0.2.0 image is built
    velero_ready: None,  # noqa: ARG001 — ensures Velero is up before backup/restore
    vcluster: dict,
) -> None:
    """Full lifecycle: write data -> backup -> modify -> restore -> verify.

    Also covers 016-backup-retention-ttl / US1: the environment-scope
    ``backup_ttl`` policy set below must land on the Velero Backup CRD's
    ``spec.ttl`` and be readable back off the backup record together with
    Velero's own expiry.

    And #304: a config edit and then an upgrade after the backup each give
    the deployment a new instance; the backup stays in the deployment's
    backup history with the application version it was taken at, and the
    restore and delete below act on that backup of an earlier instance. The
    restore puts the 0.1.0 instance's resources back and makes that instance
    the deployment's active instance (#426). A config edit after the restore
    then gives the deployment a new instance at 0.1.0, not at 0.2.0.

    And #532: the restore names only the backup. The server records the
    namespace of the backup's deployment and that deployment's active 0.2.0
    instance, at the time of the restore, as the restore's target, not the
    0.1.0 instance the backup belongs to.
    """
    client: StyrminClient = styrmin_resources["client"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    deployment_id = deployed_simple_app["deployment_id"]
    namespace = deployed_simple_app["namespace"]
    # Set just before the config edit, so the ``finally`` reverts only an edit it attempted.
    previous_server_env_vars: dict[str, str] | None = None

    # Verify environment exposes backup capability (BSL was assigned by the fixture)
    environment = await client.environments.get(environment_id=scenario_environment_id)
    assert environment.capabilities is not None, "Environment should have capabilities"
    assert "backup" in environment.capabilities, (
        "Environment should have backup capability"
    )
    assert "velero" in environment.capabilities["backup"], (
        "Environment should have velero backup provider"
    )
    # #509: the capability names the location's Velero object, which the backup below uses.
    expected_storage_location = f"styrmin-bsl-{styrmin_resources['bsl_id']}"
    assert (
        environment.capabilities["backup"]["velero"]["storage_location"]
        == expected_storage_location
    ), f"Backup storage_location should be '{expected_storage_location}'"

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

        # The fanout gave the deployment a new instance; back up that one.
        active_instance = (
            await client.deployments.get(deployment_id)
        ).application_instance
        assert active_instance is not None, "Deployment should have an active instance"
        backed_up_instance_id = str(active_instance.id)

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
        created_backup = await scenario_driver.create_backup(
            instance_id=backed_up_instance_id
        )
        assert created_backup.status in {"pending", "in_progress", "completed"}
        backup = await scenario_driver.wait_for_backup(
            backup_id=created_backup.id, max_wait=180
        )
        assert backup.status == "completed"

        # 2a. One step per component with a backup configuration (spec 019 US6).
        assert_backup_component_steps(backup)

        # 2b. Verify backup targets the assigned BSL and carries the
        #     environment-scope retention (016 / FR-002).
        await assert_velero_backup_uses_bsl(
            kubeconfig_path=kubeconfig_path,
            backup_name=backup.name,
            expected_bsl_id=str(styrmin_resources["bsl_id"]),
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

        # 2c'. The size is the volume data Velero read, not an operation count (#136).
        await assert_backup_size_matches_pod_volume_backups(
            kubeconfig_path=kubeconfig_path,
            backup_name=backup.name,
            recorded_size=recorded_backup.size_bytes,
        )

        # 2d. Velero can kopia-prune the repository the backup just wrote to.
        await assert_backup_repository_maintenance_succeeds(kubeconfig_path)

        # 2e. A config edit gives the deployment a new instance; the backup of
        #     the earlier one stays in the deployment's backup history (#304).
        stored_config = (await client.deployments.get(deployment_id)).config or {}
        previous_server_env_vars = dict(
            ((stored_config.get("components") or {}).get("server") or {}).get(
                "env_vars"
            )
            or {}
        )
        await scenario_driver.set_component_env_vars(
            deployment_id=deployment_id,
            component="server",
            env_vars={**previous_server_env_vars, **BACKUP_HISTORY_SERVER_ENV_VARS},
        )
        await scenario_driver.wait_for_deployment_running(
            deployment_id=deployment_id, timeout=FANOUT_RECONCILE_TIMEOUT_SECONDS
        )
        await wait_for_pods_ready(kubeconfig_path, namespace)

        edited_instance = (
            await client.deployments.get(deployment_id)
        ).application_instance
        assert edited_instance is not None, "Deployment should have an active instance"
        assert str(edited_instance.id) != backed_up_instance_id, (
            "The config edit should give the deployment a new active instance"
        )

        history = await scenario_driver.list_backups(deployment_id=deployment_id)
        listed_backup = next((b for b in history if b.id == backup.id), None)
        assert listed_backup is not None, (
            f"Backup {backup.id} of an earlier instance should stay in the "
            f"deployment's backup history, got {[b.id for b in history]}"
        )
        assert listed_backup.application_version == SIMPLE_APP_VERSION, (
            "The backup should show the application version it was taken at, "
            f"got {listed_backup.application_version!r}"
        )

        # 2f. The #304 reproduction: an upgrade gives the deployment another
        #     instance, and the backup taken at 0.1.0 stays listed.
        await scenario_driver.upgrade_deployment(
            deployment_id=deployment_id, version=SIMPLE_APP_UPGRADED_VERSION
        )
        await scenario_driver.wait_for_deployment_running(
            deployment_id=deployment_id, timeout=FANOUT_RECONCILE_TIMEOUT_SECONDS
        )
        await wait_for_pods_ready(kubeconfig_path, namespace)

        upgraded_deployment = await client.deployments.get(deployment_id)
        upgraded_instance = upgraded_deployment.application_instance
        assert upgraded_instance is not None, (
            "Deployment should have an active instance"
        )
        assert str(upgraded_instance.id) not in {
            backed_up_instance_id,
            str(edited_instance.id),
        }, "The upgrade should give the deployment a new active instance"
        assert upgraded_deployment.application_version == SIMPLE_APP_UPGRADED_VERSION

        history = await scenario_driver.list_backups(deployment_id=deployment_id)
        listed_backup = next((b for b in history if b.id == backup.id), None)
        assert listed_backup is not None, (
            f"Backup {backup.id} taken before the upgrade should stay in the "
            f"deployment's backup history, got {[b.id for b in history]}"
        )
        assert listed_backup.application_version == SIMPLE_APP_VERSION, (
            "After the upgrade the backup should still show the version it was "
            f"taken at, got {listed_backup.application_version!r}"
        )

        # 3. Write more data (counter goes higher)
        async with portforward_simple_app(kubeconfig_path, namespace) as port:
            async with httpx.AsyncClient() as http_client:
                for _ in range(5):
                    await http_client.get(f"http://localhost:{port}/count", timeout=10)

        # 3a. The namespace carries the labels that network policies select on.
        labels_before_restore = await namespace_labels(kubeconfig_path, namespace)
        assert {"styrmin/environment_id", "styrmin/deployment_id"} <= set(
            labels_before_restore
        ), (
            f"the namespace should carry the Styrmin labels, got {labels_before_restore!r}"
        )

        # 4. Restore from backup via scenario_driver. The restore names only the
        #    backup; the server restores into the backup's deployment (#532).
        created_restore = await scenario_driver.create_restore(backup_id=backup.id)
        assert created_restore.status in {"pending", "in_progress", "completed"}
        restore = await scenario_driver.wait_for_restore(
            restore_id=created_restore.id, max_wait=300
        )
        assert restore.status == "completed"

        # 4a. The three restore steps in order, each with a duration (spec 019 US6).
        assert_completed_restore_steps(restore)

        # 5. Wait for pods to recover, verify data restored
        await wait_for_pods_ready(kubeconfig_path, namespace)

        # 5-labels. Velero creates the namespace without its labels (the backup
        #     leaves out cluster-scoped objects): the recovery puts them back.
        assert await namespace_labels(kubeconfig_path, namespace) == (
            labels_before_restore
        ), "the restore must put the namespace labels back"
        async with portforward_simple_app(kubeconfig_path, namespace) as port:
            async with httpx.AsyncClient() as http_client:
                resp = await http_client.get(
                    f"http://localhost:{port}/count", timeout=10
                )
                # Counter should be back near pre-backup value
                assert resp.json()["counter"] == pre_backup_count + 1

        # 5a. The restore put back the 0.1.0 instance's StyrminDeployment and
        #     HelmRelease, and Styrmin records that instance as the deployment's
        #     active instance (#426): what the docs describe for a backup of an
        #     earlier instance.
        assert (
            await served_simple_app_version(
                kubeconfig_path, namespace, expected=SIMPLE_APP_VERSION
            )
            == SIMPLE_APP_VERSION
        )
        restored_deployment = await client.deployments.get(deployment_id)
        assert restored_deployment.application_version == SIMPLE_APP_VERSION
        assert restored_deployment.application_instance is not None
        assert str(restored_deployment.application_instance.id) == (
            backed_up_instance_id
        ), "The restore should make the backup's instance the active instance"

        # 5b. #532: the server chose where the restore lands. It recorded the
        #     backup's deployment's namespace and that deployment's active
        #     0.2.0 instance, which was the active one when the restore was
        #     created, although the backup belongs to the 0.1.0 instance (FR-001,
        #     FR-004, ADR-063). The restore then made the 0.1.0 instance active.
        recorded_restore = await client.backups.get_restore(created_restore.id)
        assert recorded_restore.target_namespace == f"styrmin-{deployment_id}", (
            "An in-place restore should land in the namespace of the backup's "
            f"deployment, got {recorded_restore.target_namespace!r}"
        )
        assert str(recorded_restore.target_instance_id) == str(upgraded_instance.id), (
            "An in-place restore should record the deployment's active instance "
            f"when it is created, got {recorded_restore.target_instance_id!r}"
        )

        # 5c. #426: the next config edit builds its instance from the restored
        #     0.1.0 instance, so it gives the deployment a new instance and
        #     does not put 0.2.0 back. The ``finally`` reverts the edit.
        await scenario_driver.set_component_env_vars(
            deployment_id=deployment_id,
            component="server",
            env_vars={**previous_server_env_vars, **AFTER_RESTORE_SERVER_ENV_VARS},
        )
        await scenario_driver.wait_for_deployment_running(
            deployment_id=deployment_id, timeout=FANOUT_RECONCILE_TIMEOUT_SECONDS
        )
        await wait_for_pods_ready(kubeconfig_path, namespace)

        edited_after_restore = await client.deployments.get(deployment_id)
        assert edited_after_restore.application_instance is not None
        assert str(edited_after_restore.application_instance.id) not in {
            backed_up_instance_id,
            str(edited_instance.id),
            str(upgraded_instance.id),
        }, "The config edit after the restore should give the deployment a new instance"
        assert edited_after_restore.application_version == SIMPLE_APP_VERSION, (
            "The config edit after the restore should keep the restored version, "
            f"got {edited_after_restore.application_version!r}"
        )
        assert (
            await served_simple_app_version(
                kubeconfig_path, namespace, expected=SIMPLE_APP_VERSION
            )
            == SIMPLE_APP_VERSION
        ), "The config edit after the restore should keep serving the restored version"

        # 6. Delete backup and verify
        await scenario_driver.delete_backup(backup_id=backup.id)
        with pytest.raises(ResourceNotFound):
            await scenario_driver.get_backup(backup_id=backup.id)
    finally:
        # Its own try/finally, so a failed env-var revert cannot skip the
        # retention revert below (critique E5).
        try:
            if previous_server_env_vars is not None:
                scenario_driver.attach_to_deployment(
                    environment_id=scenario_environment_id
                )
                await scenario_driver.set_component_env_vars(
                    deployment_id=deployment_id,
                    component="server",
                    env_vars=previous_server_env_vars,
                )
                with suppress(Exception):
                    await scenario_driver.wait_for_deployment_running(
                        deployment_id=deployment_id,
                        timeout=CLEANUP_WAIT_TIMEOUT_SECONDS,
                    )
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
                    noop_grace=NOOP_FANOUT_GRACE_SECONDS,
                )
            # Leave the driver back on the deployment detail page: the UI
            # driver's page is session-scoped, and the sibling backup tests that
            # follow act on whatever page is open. Best-effort like the wait
            # above — a cleanup hiccup must never mask the test's own failure.
            scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)
            with suppress(Exception):
                await scenario_driver.wait_for_deployment_running(
                    deployment_id=deployment_id,
                    timeout=FANOUT_RECONCILE_TIMEOUT_SECONDS,
                )


# ---------------------------------------------------------------------------
# Environment-level backup and restore (spec 001-env-backup-restore)
# ---------------------------------------------------------------------------


async def instanced_deployment_ids(
    client: StyrminClient, environment_id: str
) -> set[str]:
    """Every live deployment in ``environment_id`` that has an active instance.

    A **superset** of the snapshot's eligible set: ``ListDeployments`` excludes
    tombstones but is asked for internal deployments too, and every environment
    built on a ``dedicated_ingress`` cluster owns an internal ingress-controller
    deployment (``services/deployment.py`` creates it with ``internal=True``).
    That controller has an active instance and therefore appears here, while the
    snapshot must exclude it (spec FR-001) — which is exactly what the SC-001
    assertion below checks by requiring the constituent set to equal only the
    two operator-created deployments.

    Used unchanged on both sides of the restore for the FR-008 "no deployment
    created or deleted" check, where counting the internal controller too is a
    feature rather than a caveat.
    """
    deployments = await client.deployments.list(
        environment_id=environment_id, include_internal=True
    )
    return {
        str(deployment.id)
        for deployment in deployments
        if deployment.application_instance is not None
    }


async def source_deployment_state(
    client: StyrminClient, deployment_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """The declared state of each source deployment a clone must leave alone.

    SC-002 says the source is *byte-identical* before and after, and a set of
    deployment ids cannot see what that sentence is actually protecting against:
    a cross-target restore whose target resolved to the source would flip that
    deployment out of ``running``, delete and rebuild its namespace, and hand
    the source's services back with whatever names the counterpart wanted —
    all with the id roster unchanged.

    ``parameters`` is deliberately absent: ``GetDeployment`` does not project
    it, and widening an SDK query is a production change. The source-vs-clone
    parameter comparison lives in the functional propagation suite
    (``test_the_counterpart_row_reproduces_the_source_declared_state``).
    """
    state: dict[str, dict[str, Any]] = {}
    for deployment_id in deployment_ids:
        deployment = await client.deployments.get(deployment_id)
        driver_version = deployment.application_driver_version
        instance = deployment.application_instance
        state[str(deployment.id)] = {
            "name": deployment.name,
            "status": deployment.status,
            "config": deployment.config,
            "application_version": deployment.application_version,
            "driver_version_id": str(deployment.application_driver_version_id),
            "driver_version": driver_version.version,
            "driver_fingerprint": (
                driver_version.content_hash or driver_version.source_commit_sha
            ),
            "instance_id": str(instance.id) if instance is not None else None,
            "services": sorted(
                (service.driver_service_name, service.resolved_name)
                for service in deployment.deployed_services
            ),
        }
    return state


async def wait_for_constituent_outcomes(
    driver: ScenarioDriver,
    *,
    environment_backup_id: str,
    expected: dict[str, str],
    timeout: float,
) -> EnvironmentBackupRef:
    """Block until every named constituent reports its expected outcome.

    Waiting on the children rather than on the parent status, for two reasons
    that are both properties of the feature rather than of this test:

    * the derived parent status only says that every constituent row which
      *exists* is terminal. It cannot express the per-constituent outcomes these
      assertions are about — which deployment completed, and which one is the
      gap left by an individually deleted constituent — and a ``COMPLETED``
      parent is compatible with both. The ``constituents`` projection
      (``deployment_snapshots`` ⋈ linked backups ⋈ ``constituent_errors``) is
      what carries them.
    * the UI entrypoint reads a list that refetches on a 10s interval, so a
      change made out-of-band (deleting one constituent) needs a poll to become
      visible. The API entrypoint re-reads on every call, so the same poll is a
      no-op there.

    Note that a constituent no longer reads ``missing`` merely because the
    fan-out has not reached it yet: the parent row, every constituent ``Backup``
    row and every recorded creation error now commit in one transaction before
    anything is dispatched, so ``missing`` means the row was deleted.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    observed: dict[str, str] = {}
    ref: EnvironmentBackupRef | None = None
    while asyncio.get_event_loop().time() < deadline:
        ref = await driver.get_environment_backup(
            environment_backup_id=environment_backup_id
        )
        observed = {
            constituent.deployment_id: constituent.outcome
            for constituent in ref.constituents
        }
        if all(observed.get(did) == outcome for did, outcome in expected.items()):
            return ref
        await asyncio.sleep(5)
    raise AssertionError(
        f"environment backup {environment_backup_id} constituents did not reach "
        f"{expected!r} within {timeout}s — observed {observed!r} "
        f"(parent status {ref.status if ref else '<unread>'!r})"
    )


@pytest.mark.ci
@pytest.mark.shard_env_backup
async def test_environment_backup_and_restore_lifecycle(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,
    deployed_simple_app: dict,
    velero_ready: None,  # noqa: ARG001 — ensures Velero is up before backup/restore
    vcluster: dict,
) -> None:
    """One coordinated snapshot of a multi-deployment environment, then restore.

    Covers the whole 001-env-backup-restore feature in one dual-entrypoint node
    (Constitution §V "reuse before you boot"): US1 (coordinated backup), US2
    (coordinated in-place restore with attributed skips) and US3 (per-constituent
    visibility + cascade delete).

    Success criteria asserted here:

    * **SC-001** — one action produces one constituent per eligible deployment,
      for N > 1: ``deployed_simple_app`` plus a second deployment created below.
    * **SC-002** — the restored deployment's application data is back to its
      backup-time value, with no further operator input.
    * **SC-003** — the derived parent status matches its constituents at each
      step: ``COMPLETED`` once every constituent completed, and ``PARTIAL`` for a
      restore that restored one constituent and skipped another.
    * **SC-004** — the skipped constituent is attributed by deployment *name*
      and reason. Zero silent skips.
    * **SC-005** — after the restore, the environment's config equals the config
      captured at backup time (an env-config write happens in between).
    * **SC-003 of spec 030** — after the restore, the primary's namespace still
      holds its alias for the second deployment's service.

    The environment is session-shared, so the config write is deliberately the
    retention policy (a Helm-level no-op that still walks the whole reconcile
    path) and the ``finally`` block restores the pre-test policy.
    """
    from uuid import uuid4

    client: StyrminClient = styrmin_resources["client"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    primary_deployment_id = deployed_simple_app["deployment_id"]
    primary_namespace = deployed_simple_app["namespace"]

    # A second deployment makes SC-001's "for any N" meaningful and gives the
    # restore something to skip. The shared environment enforces per-env service
    # name uniqueness, hence the override (see ``scenario_environment_id``).
    suffix = uuid4().hex[:8]
    secondary_service_name = f"envsnap{suffix}"
    secondary = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
        name=f"env-snapshot-{suffix}",
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": secondary_service_name}
        ],
    )
    secondary_deployment_id = secondary.id
    await scenario_driver.wait_for_deployment_running(
        deployment_id=secondary_deployment_id,
        timeout=DEPLOYMENT_RUNNING_TIMEOUT_SECONDS,
    )
    secondary_name = (await client.deployments.get(secondary_deployment_id)).name

    previous_backup_ttl = (
        (await client.environments.get(environment_id=scenario_environment_id)).config
        or {}
    ).get("backup_ttl")

    try:
        # 1. Write data into the primary deployment so the restore has something
        #    observable to bring back (SC-002).
        scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)
        async with portforward_simple_app(kubeconfig_path, primary_namespace) as port:
            async with httpx.AsyncClient() as http_client:
                for _ in range(5):
                    await http_client.get(f"http://localhost:{port}/count", timeout=10)
                resp = await http_client.get(
                    f"http://localhost:{port}/count", timeout=10
                )
                pre_backup_count = resp.json()["counter"]

        # 2. One action snapshots the whole environment (SC-001).
        #    ``expected_constituents`` is the two operator-created deployments.
        #    The environment also owns an internal ingress-controller deployment
        #    with an active instance, so requiring *equality* below is both the
        #    SC-001 "one per eligible deployment" check and the FR-001
        #    "internal deployments excluded" check.
        expected_constituents = {primary_deployment_id, secondary_deployment_id}
        instanced_before = await instanced_deployment_ids(
            client, scenario_environment_id
        )
        assert expected_constituents <= instanced_before, (
            "both deployments must carry an active instance before the "
            f"snapshot, got {instanced_before!r}"
        )

        created = await scenario_driver.create_environment_backup(
            environment_id=scenario_environment_id
        )
        environment_backup_id = created.id
        assert created.status in {"PENDING", "IN_PROGRESS", "COMPLETED"}, (
            f"unexpected derived status right after creation: {created.status!r}"
        )
        constituent_ids = [c.deployment_id for c in created.constituents]
        assert set(constituent_ids) == expected_constituents, (
            "one constituent per eligible deployment, internal deployments "
            f"excluded (SC-001 / FR-001): expected {expected_constituents!r}, "
            f"got {set(constituent_ids)!r}"
        )
        assert len(constituent_ids) == len(set(constituent_ids)), (
            f"a deployment appears twice in the snapshot: {constituent_ids!r}"
        )

        # 3. Every constituent completes, and the derived parent status agrees
        #    with its constituents (SC-003).
        await wait_for_constituent_outcomes(
            scenario_driver,
            environment_backup_id=environment_backup_id,
            expected=dict.fromkeys(expected_constituents, "completed"),
            timeout=ENVIRONMENT_BACKUP_FANOUT_TIMEOUT_SECONDS,
        )
        completed = await scenario_driver.wait_for_environment_backup(
            environment_backup_id=environment_backup_id,
            max_wait=DERIVED_STATUS_TIMEOUT_SECONDS,
        )
        assert completed.status == "COMPLETED", (
            "every constituent completed, so the derived parent status must be "
            f"COMPLETED (SC-003); got {completed.status!r}"
        )

        # 4. The snapshot captured the environment config and each deployment's
        #    declared state including the ADR-0053 driver fingerprint
        #    (FR-002/FR-003). Read through the SDK on both entrypoints — the
        #    frontend does not surface the captured payload, and it is the
        #    snapshot's *content*, not a UI affordance, that is under test.
        persisted = await client.environment_backups.get(environment_backup_id)
        captured_config = persisted.environment_config
        assert captured_config is not None, (
            "the snapshot must capture the environment config (FR-002)"
        )
        snapshots_by_deployment = {
            str(snapshot.deployment_id): snapshot
            for snapshot in persisted.deployment_snapshots
        }
        assert set(snapshots_by_deployment) == expected_constituents
        for deployment_id, snapshot in snapshots_by_deployment.items():
            assert snapshot.driver_name == "simple-app", (
                f"{deployment_id}: captured driver name {snapshot.driver_name!r}"
            )
            assert snapshot.application_version == "0.1.0"
            assert snapshot.driver_fingerprint, (
                f"{deployment_id}: declared state must record the driver "
                "provenance fingerprint (FR-003 / ADR-0053)"
            )

        secondary_backup_id = next(
            c.backup_id
            for c in completed.constituents
            if c.deployment_id == secondary_deployment_id
        )
        primary_backup_id = next(
            c.backup_id
            for c in completed.constituents
            if c.deployment_id == primary_deployment_id
        )
        assert secondary_backup_id and primary_backup_id

        # 5. US3 — delete one constituent individually. The parent survives and
        #    the gap is visible, which is also what makes the restore below skip
        #    that deployment with an attributable reason. Done through the SDK
        #    rather than the scenario driver on purpose: the UI's per-backup
        #    delete lives on the *deployment* detail page, and this is snapshot
        #    setup, not the environment-level flow under test.
        await client.backups.delete_backup(secondary_backup_id)
        with_gap = await wait_for_constituent_outcomes(
            scenario_driver,
            environment_backup_id=environment_backup_id,
            expected={
                primary_deployment_id: "completed",
                secondary_deployment_id: "missing",
            },
            # The delete is already committed; the only latency left is the UI
            # entrypoint's 10s list refetch.
            timeout=DERIVED_STATUS_TIMEOUT_SECONDS,
        )
        assert len(with_gap.constituents) == len(expected_constituents), (
            "deleting a constituent must leave the parent's snapshot list intact "
            "so the gap stays visible (US3)"
        )
        assert with_gap.status == "COMPLETED", (
            "the surviving constituent completed, so the snapshot is still "
            f"restorable; got {with_gap.status!r}"
        )

        # 6. Mutate the environment config and the application data, so the
        #    restore has both to revert (SC-005 / SC-002).
        pre_write_timeline = {
            deployment_id: len(
                await client.deployments.get_timeline(deployment_id=deployment_id)
            )
            for deployment_id in (primary_deployment_id, secondary_deployment_id)
        }
        await scenario_driver.set_environment_backup_ttl(
            environment_id=scenario_environment_id,
            ttl=ENVIRONMENT_SNAPSHOT_MUTATED_TTL,
        )
        mutated = await client.environments.get(environment_id=scenario_environment_id)
        assert (mutated.config or {}).get("backup_ttl") == (
            ENVIRONMENT_SNAPSHOT_MUTATED_TTL
        ), f"env config should carry the mutation, got {mutated.config!r}"
        assert mutated.config != captured_config, (
            "the config write must actually diverge from the captured snapshot, "
            "otherwise SC-005 would pass without a revert happening"
        )
        # One env-config write queues the redeploy Task on *every* deployment in
        # the environment at once, so the two fanouts run concurrently. Awaiting
        # them sequentially gave each its own full ``FANOUT_RECONCILE_TIMEOUT_
        # SECONDS``, making the worst case 2× the wall-clock the platform can
        # actually take; gathering them shares one budget.
        await asyncio.gather(
            *(
                wait_for_env_fanout_steady_state(
                    client, deployment_id=deployment_id, pre_timeline_length=length
                )
                for deployment_id, length in pre_write_timeline.items()
            )
        )
        await wait_for_pods_ready(kubeconfig_path, primary_namespace)

        async with portforward_simple_app(kubeconfig_path, primary_namespace) as port:
            async with httpx.AsyncClient() as http_client:
                for _ in range(5):
                    await http_client.get(f"http://localhost:{port}/count", timeout=10)

        # 7. US2 — one action restores the environment. Classification is
        #    synchronous, so the skips are complete on the returned record.
        environment_restore = await scenario_driver.restore_environment_backup(
            environment_backup_id=environment_backup_id
        )
        skipped_by_deployment = {
            skip.deployment_id: skip for skip in environment_restore.skipped
        }
        assert set(skipped_by_deployment) == {secondary_deployment_id}, (
            "exactly the constituent whose backup was deleted must be skipped, "
            f"got {set(skipped_by_deployment)!r}"
        )
        skip = skipped_by_deployment[secondary_deployment_id]
        assert skip.deployment_name == secondary_name, (
            "a skip is attributed by deployment name (SC-004); got "
            f"{skip.deployment_name!r}, expected {secondary_name!r}"
        )
        # Free text by contract, not a closed enum — asserted as text.
        assert skip.reason == "backup deleted", (
            f"unexpected skip reason {skip.reason!r} (SC-004)"
        )
        assert len(environment_restore.restore_ids) == (
            len(expected_constituents) - 1
        ), (
            "every usable constituent must be restored without further operator "
            f"input (SC-002); got {environment_restore.restore_ids!r}"
        )

        finished = await scenario_driver.wait_for_environment_restore(
            environment_restore_id=environment_restore.id,
            max_wait=ENVIRONMENT_RESTORE_TIMEOUT_SECONDS,
        )
        assert finished.status == "PARTIAL", (
            "one constituent restored and one skipped derives to PARTIAL "
            f"(SC-003); got {finished.status!r}"
        )

        # 8. SC-005 — the config is back to the captured value, exactly.
        reverted = await client.environments.get(environment_id=scenario_environment_id)
        assert reverted.config == captured_config, (
            "after the restore the environment config must equal the config "
            f"captured at backup time (SC-005): {reverted.config!r} != "
            f"{captured_config!r}"
        )

        # 9. SC-002 — the restored deployment's data is back, and the deployment
        #    count is unchanged (FR-008: restore never creates or deletes one).
        await wait_for_pods_ready(kubeconfig_path, primary_namespace)
        async with portforward_simple_app(kubeconfig_path, primary_namespace) as port:
            async with httpx.AsyncClient() as http_client:
                resp = await http_client.get(
                    f"http://localhost:{port}/count", timeout=10
                )
                assert resp.json()["counter"] == pre_backup_count + 1, (
                    "restored application data should be back at its backup-time "
                    "value (the +1 is this read itself)"
                )
        assert (
            await instanced_deployment_ids(client, scenario_environment_id)
        ) == instanced_before, (
            "an environment restore must not create or delete deployments (FR-008)"
        )

        # SC-003 of spec 030: the primary keeps its alias for the second deployment's
        # service. Only that alias is compared, because other deployments of the
        # shared environment add their own.
        expected_aliases = {
            ServiceAlias(
                secondary_service_name,
                secondary_deployment_id,
                f"styrmin-{secondary_deployment_id}",
            )
        }
        aliases = await wait_for_service_aliases(
            kubeconfig_path,
            primary_namespace,
            expected_aliases,
            timeout=SERVICE_ALIASES_TIMEOUT_SECONDS,
            include=lambda alias: alias.name == secondary_service_name,
        )
        assert aliases == expected_aliases, (
            "after the environment restore, the primary's namespace must hold the "
            f"alias {secondary_service_name!r} of deployment {secondary_deployment_id}, "
            f"pointing to its namespace (SC-003 of spec 030); got {sorted(aliases)!r}"
        )

        # 10. US3 — deleting the snapshot cascades through its constituents and
        #     its restores.
        await scenario_driver.delete_environment_backup(
            environment_backup_id=environment_backup_id
        )
        with pytest.raises(ResourceNotFound):
            await scenario_driver.get_environment_backup(
                environment_backup_id=environment_backup_id
            )
        with pytest.raises(ResourceNotFoundError):
            await client.backups.get_backup(primary_backup_id)
        with pytest.raises(ResourceNotFoundError):
            await client.environment_backups.get_restore(environment_restore.id)
    finally:
        # The environment is session-shared. The restore above already reverts
        # the config, but a failure before that point would leave the mutated
        # retention policy behind for every later ``shard_env_backup`` test — so the
        # revert runs unconditionally. The waits afterwards are best-effort so a
        # cleanup timeout can never mask the test's own failure.
        revert_timeline = {
            deployment_id: len(
                await client.deployments.get_timeline(deployment_id=deployment_id)
            )
            for deployment_id in (primary_deployment_id, secondary_deployment_id)
        }
        await scenario_driver.set_environment_backup_ttl(
            environment_id=scenario_environment_id, ttl=previous_backup_ttl
        )
        with suppress(AssertionError):
            await asyncio.gather(
                *(
                    wait_for_env_fanout_steady_state(
                        client,
                        deployment_id=deployment_id,
                        pre_timeline_length=length,
                        timeout=CLEANUP_WAIT_TIMEOUT_SECONDS,
                        noop_grace=NOOP_FANOUT_GRACE_SECONDS,
                    )
                    for deployment_id, length in revert_timeline.items()
                )
            )
        # Delete the deployment this test created. The environment is
        # session-shared, so leaving it behind hands every later
        # ``shard_env_backup`` test an extra peer: one more constituent in any
        # snapshot they take, one more redeploy in any env-config fanout they
        # wait on, and a service-name that the next ``simple-app`` peer has to
        # avoid. Best-effort like the waits — a cleanup failure must not mask
        # the test's own.
        with suppress(Exception):
            await client.deployments.delete(secondary_deployment_id)
        # The UI driver's page is session-scoped and the sibling backup tests act
        # on whatever page is open, so hand it back on a deployment detail page.
        scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)
        with suppress(Exception):
            await scenario_driver.wait_for_deployment_running(
                deployment_id=primary_deployment_id,
                timeout=CLEANUP_WAIT_TIMEOUT_SECONDS,
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


async def _read_status_and_last_poll(
    client: StyrminClient, deployment_id
) -> tuple[str, str | None]:
    """Read ``deployment.status`` and the last agent status report time together."""
    raw = await client._transport.execute(
        load_query("get_deployment_status"), {"deploymentId": str(deployment_id)}
    )
    assert "errors" not in raw, raw
    deployment = raw["data"]["deployment"]
    return deployment["status"], (deployment.get("crdStatus") or {}).get("lastPolledAt")


async def _status_after_next_report(
    client: StyrminClient,
    deployment_id,
    restore_id: str,
    max_wait: float,
    poll: float = 1.0,
) -> str:
    """Return ``deployment.status`` read after the next agent status report.

    Fails if the restore is no longer in flight once that report has landed,
    because the report would then prove nothing about the restore window.
    """
    _, baseline = await _read_status_and_last_poll(client, deployment_id)
    deadline = asyncio.get_event_loop().time() + max_wait
    while asyncio.get_event_loop().time() < deadline:
        status, last_polled_at = await _read_status_and_last_poll(client, deployment_id)
        if last_polled_at != baseline:
            # Read after the deployment: a restore still in flight now was in
            # flight when the status above was read.
            restore = await client.backups.get_restore(restore_id)
            assert restore.status in {"pending", "in_progress"}, (
                f"Restore {restore_id} reached {restore.status!r} before an agent "
                f"status report landed during it"
            )
            return status
        await asyncio.sleep(poll)
    raise AssertionError(
        f"No agent status report for deployment {deployment_id} within {max_wait}s"
    )


@pytest.mark.ci
@pytest.mark.shard_backup
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
    created_restore = await driver.create_restore(backup_id=backup.id)

    observed = await _wait_for_deployment_status(
        client,
        deployment_id,
        expected={"restoring"},
        max_wait=10,
    )
    assert observed == "restoring"

    # #389: an agent status report sent before Velero finishes used to
    # overwrite RESTORING with the CR's pre-restore state. Wait for one.
    after_report = await _status_after_next_report(
        client, deployment_id, restore_id=created_restore.id, max_wait=300
    )
    assert after_report == "restoring"

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
@pytest.mark.shard_backup
@pytest.mark.api_only(
    reason="Every action is a raw SDK call — the driver half of "
    "``session_scenario_driver`` is discarded (``_, client = ...``) and no "
    "dual-entrypoint driver method is invoked. The flow provokes a rejected "
    "restore by passing a non-existent backup id, which the UI cannot express: "
    "the restore button is bound to a listed backup row, so there is no "
    "Playwright path to submit an unknown id. The [ui-chromium] variant would "
    "replay the identical GraphQL calls for ~20 minutes of extra CI time."
)
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
        await client.backups.create_restore(backup_id=uuid4())

    # Deployment is not knocked into 'restoring' by an invalid request.
    after = await client.deployments.get(deployment_id)
    assert after.status == pre_status, (
        f"Failed restore must not change deployment status; was {pre_status!r}, "
        f"now {after.status!r}"
    )


async def _wait_for_sdk_deployment_running(
    client: StyrminClient, deployment_id: str, timeout: float
) -> str:
    """Poll the deployment until it runs; return its instance id."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    status = None
    while loop.time() < deadline:
        with suppress(ResourceNotFoundError):
            deployment = await client.deployments.get(deployment_id)
            status = deployment.status
            if status == "running" and deployment.application_instance:
                return str(deployment.application_instance.id)
        await asyncio.sleep(2)
    raise AssertionError(
        f"Deployment {deployment_id} did not run within {timeout}s (status {status!r})"
    )


@pytest.mark.ci
@pytest.mark.shard_backup
@pytest.mark.api_only(
    reason="Every action is a raw SDK or Kubernetes call and no dual-entrypoint "
    "driver method is invoked. Component tests in BackupRestoreSteps.test.tsx "
    "cover how a failed restore step and its error appear on the Backups tab, "
    "and test_backup_and_restore_lifecycle[ui-chromium] reads restore steps "
    "from the page; a [ui-chromium] variant would repeat the same GraphQL "
    "calls with one more deployment boot."
)
async def test_restore_of_removed_velero_backup_fails_velero_step(
    styrmin_resources: dict,
    simple_app_image: str,  # noqa: ARG001 — builds the image
    velero_ready: None,  # noqa: ARG001 — ensures Velero is up before backup/restore
    vcluster: dict,
) -> None:
    """A restore of a backup that Velero no longer has fails "Run the Velero restore".

    Spec 019 US6 acceptance scenario 1 and SC-005: the restore lists its steps
    in order with durations, and the Velero step is failed with Velero's
    validation error, which is also the restore's error message. The restore
    deletes the deployment's namespace before
    Velero rejects it, so the test uses its own environment and deployment;
    deleting the environment removes them even though their CR is gone.
    """
    from uuid import uuid4

    client: StyrminClient = styrmin_resources["client"]
    suffix = uuid4().hex[:8]
    environment = await client.environments.create(
        name=f"restore-fail-{suffix}",
        cluster_id=styrmin_resources["cluster_id"],
        config={},
    )
    try:
        await client.backup_storage_locations.assign(
            environment_id=environment.id, bsl_id=styrmin_resources["bsl_id"]
        )
        task = await client.deployments.create(
            driver="simple-app",
            version="0.1.0",
            environment_id=environment.id,
            name=f"restore-fail-{suffix}",
        )
        assert task.deployment_id is not None, task
        deployment_id = str(task.deployment_id)
        instance_id = await _wait_for_sdk_deployment_running(
            client, deployment_id, timeout=DEPLOYMENT_RUNNING_TIMEOUT_SECONDS
        )

        created_backup = await client.backups.create_backup(instance_id=instance_id)
        backup = await client.backups.wait_for_backup(created_backup.id, max_wait=180)
        assert backup.status == "completed", backup

        # Remove the Velero backup behind Styrmin's record, which stays completed.
        await remove_velero_backup(
            vcluster["kubeconfig_path"],
            backup.name,
            timeout=VELERO_BACKUP_REMOVAL_TIMEOUT_SECONDS,
        )

        created_restore = await client.backups.create_restore(backup_id=backup.id)
        restore = await client.backups.wait_for_restore(
            created_restore.id, max_wait=600
        )
        velero_step = next(
            (step for step in restore.steps if step.key == "restore:velero"), None
        )
        print(
            f"failed restore {restore.id}: status={restore.status!r} "
            f"error_message={restore.error_message!r} "
            f"velero_step_error={velero_step.error if velero_step else None!r}"
        )
        assert restore.status == "failed", restore

        # The recovery step runs only after a completed Velero restore.
        steps = [(step.key, step.name, step.status.value) for step in restore.steps]
        assert steps == [
            ("restore:namespace", "Delete the namespace", "SUCCEEDED"),
            ("restore:velero", "Run the Velero restore", "FAILED"),
        ], restore.steps
        started = []
        for step in restore.steps:
            assert step.started_at and step.ended_at, step
            assert step.duration_seconds is not None, step
            assert step.ended_at >= step.started_at, step
            started.append(step.started_at)
        assert started == sorted(started), restore.steps

        assert velero_step is not None
        assert velero_step.error is not None, velero_step
        assert velero_step.error.startswith(VELERO_VALIDATION_ERROR_PREFIX), (
            velero_step.error
        )
        # Velero's own error names the backup it cannot find.
        assert backup.name in velero_step.error, velero_step.error
        assert [(error.attempt, error.message) for error in velero_step.errors] == [
            (1, velero_step.error)
        ], velero_step.errors
        # The restore record carries the same error as the step.
        assert restore.error_message, restore
        assert restore.error_message.startswith(VELERO_VALIDATION_ERROR_PREFIX), (
            restore.error_message
        )
        assert restore.error_message == velero_step.error, restore
    finally:
        with suppress(Exception):
            await client.environments.delete(environment_id=environment.id)


BSL_OBJECTS_TIMEOUT_SECONDS = 180.0


async def bsl_cluster_objects(
    kubeconfig_path: str, bsl_id: str
) -> tuple[set[str], dict[str, str]]:
    """Velero BSL names and Secret credentials labelled with the location id, in ``styrmin``."""
    import base64

    from kubernetes_asyncio import client as kubeclient
    from kubernetes_asyncio import config as k8s_config

    selector = f"styrmin.io/bsl-id={bsl_id}"
    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    try:
        listed = await kubeclient.CustomObjectsApi(
            api_client
        ).list_namespaced_custom_object(
            group="velero.io",
            version="v1",
            namespace="styrmin",
            plural="backupstoragelocations",
            label_selector=selector,
        )
        secrets = await kubeclient.CoreV1Api(api_client).list_namespaced_secret(
            namespace="styrmin", label_selector=selector
        )
    finally:
        await api_client.close()
    return (
        {item["metadata"]["name"] for item in listed["items"]},
        {
            secret.metadata.name: base64.b64decode(secret.data["cloud"]).decode()
            for secret in secrets.items
        },
    )


async def wait_for_bsl_cluster_objects(
    kubeconfig_path: str,
    bsl_id: str,
    expected: Callable[[set[str], dict[str, str]], bool],
    description: str,
) -> tuple[set[str], dict[str, str]]:
    """Poll the location's cluster objects until ``expected(bsls, secrets)`` holds."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + BSL_OBJECTS_TIMEOUT_SECONDS
    found = await bsl_cluster_objects(kubeconfig_path, bsl_id)
    while not expected(*found):
        assert loop.time() < deadline, (
            f"{description} within {BSL_OBJECTS_TIMEOUT_SECONDS}s; found {found}"
        )
        await asyncio.sleep(3)
        found = await bsl_cluster_objects(kubeconfig_path, bsl_id)
    return found


async def create_name_based_bsl_objects(
    kubeconfig_path: str, bsl_id: str, bsl_name: str, bucket: str
) -> None:
    """Create the Velero BSL and Secret as Styrmin did before #488, named after the location name."""
    from kubernetes_asyncio import client as kubeclient
    from kubernetes_asyncio import config as k8s_config

    name = f"styrmin-bsl-{bsl_name}"
    labels = {"styrmin.io/managed": "true", "styrmin.io/bsl-id": bsl_id}
    await k8s_config.load_config(config_file=kubeconfig_path)
    api_client = kubeclient.ApiClient()
    try:
        await kubeclient.CoreV1Api(api_client).create_namespaced_secret(
            namespace="styrmin",
            body={
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": f"{name}-credentials", "labels": labels},
                "stringData": {"cloud": "[default]\naws_access_key_id = old\n"},
            },
        )
        await kubeclient.CustomObjectsApi(api_client).create_namespaced_custom_object(
            group="velero.io",
            version="v1",
            namespace="styrmin",
            plural="backupstoragelocations",
            body={
                "apiVersion": "velero.io/v1",
                "kind": "BackupStorageLocation",
                "metadata": {"name": name, "labels": labels},
                "spec": {
                    "provider": "aws",
                    "objectStorage": {"bucket": bucket},
                    "config": {
                        "region": "garage",
                        "s3Url": "http://garage.styrmin.svc:3900",
                    },
                    "credential": {"name": f"{name}-credentials", "key": "cloud"},
                },
            },
        )
    finally:
        await api_client.close()


@asynccontextmanager
async def prefect_api(kubeconfig_path: str) -> AsyncIterator[PrefectClient]:
    """A Prefect client on a port-forward to the in-cluster Prefect server."""
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    service = await AsyncService.get(
        "prefect-server", namespace="styrmin", api=kr8s_api
    )
    async with _portforward(service, remote_port=4200) as port:
        url = f"http://localhost:{port}/api"
        await _wait_for_http(f"{url}/health", timeout=60.0)
        async with PrefectClient(api=url) as client:
            yield client


async def assert_bsl_keys_not_readable_from_prefect(
    kubeconfig_path: str, bsl_id: str, keys: Sequence[str]
) -> None:
    """#497: the location's sync flow runs and its Secret block do not show its S3 keys."""
    block_name = f"styrmin-bsl-{bsl_id}-credentials"
    async with prefect_api(kubeconfig_path) as client:
        runs = await client.read_flow_runs(
            flow_filter=FlowFilter(
                name=FlowFilterName(
                    any_=["sync_bsl_create", "sync_bsl_update_credentials"]
                )
            )
        )
        block = await client.read_block_document_by_name(
            block_name, block_type_slug="secret", include_secrets=False
        )
    runs = [run for run in runs if run.parameters.get("bsl_id") == bsl_id]
    assert len(runs) >= 2, (
        f"Expected a create and a credentials update flow run of location {bsl_id}, "
        f"found {[run.name for run in runs]}"
    )
    for run in runs:
        parameters = json.dumps(run.parameters)
        leaked = [key for key in keys if key in parameters]
        assert not leaked, (
            f"Flow run {run.name} has S3 keys in its parameters: {leaked}"
        )
    shown = json.dumps(block.data)
    leaked = [key for key in keys if key in shown]
    assert not leaked, (
        f"Block {block_name} shows S3 keys without include_secrets: {leaked}"
    )


async def bsl_credentials_block_exists(kubeconfig_path: str, bsl_id: str) -> bool:
    async with prefect_api(kubeconfig_path) as client:
        try:
            await client.read_block_document_by_name(
                f"styrmin-bsl-{bsl_id}-credentials",
                block_type_slug="secret",
                include_secrets=False,
            )
        except ObjectNotFound:
            return False
    return True


async def _velero_storage_location(client: StyrminClient, environment_id: str) -> str:
    environment = await client.environments.get(environment_id=environment_id)
    assert environment.capabilities is not None
    return environment.capabilities["backup"]["velero"]["storage_location"]


@pytest.mark.ci
@pytest.mark.shard_backup
@pytest.mark.api_only(
    reason="Every action is an SDK or Kubernetes call and no dual-entrypoint "
    "driver method is invoked; the assertions read cluster objects that the "
    "UI does not show."
)
async def test_renamed_bsl_cluster_objects_follow_the_location_id(
    styrmin_resources: dict,
    velero_ready: None,  # noqa: ARG001 — the Velero CRDs must exist
    vcluster: dict,
) -> None:
    """#488: a location's cluster objects are named and found by its id, not its name.

    After a rename, a credentials update still reaches the Secret and an
    unassign still removes the Velero object and the Secret. Objects that an
    earlier Styrmin named after the location name, which carry the same id
    label, are updated and removed too.

    And #497: the sync flows load the S3 keys from the location's Prefect
    Secret block, so the keys reach the Secret but are not in the parameters
    of the flow runs. Deleting the location deletes the block.
    """
    from uuid import uuid4

    client: StyrminClient = styrmin_resources["client"]
    kubeconfig_path = vcluster["kubeconfig_path"]
    suffix = uuid4().hex[:8]
    # A bucket of its own keeps Velero's backup sync away from the shared one.
    bucket = f"velero-rename-{suffix}"
    environment = await client.environments.create(
        name=f"bsl-rename-{suffix}",
        cluster_id=styrmin_resources["cluster_id"],
        config={},
    )
    bsl = await client.backup_storage_locations.create(
        name=f"before-rename-{suffix}",
        endpoint="http://garage.styrmin.svc:3900",
        bucket=bucket,
        region="garage",
        access_key_id="GKbeforerenamebeforerename",
        secret_access_key="before-rename-secret",
    )
    bsl_id = str(bsl.id)
    id_name = f"styrmin-bsl-{bsl_id}"
    try:
        await client.backup_storage_locations.assign(
            environment_id=environment.id, bsl_id=bsl_id
        )
        await wait_for_bsl_cluster_objects(
            kubeconfig_path,
            bsl_id,
            lambda bsls, secrets: (
                bsls == {id_name}
                and set(secrets) == {f"{id_name}-credentials"}
                and "GKbeforerenamebeforerename" in secrets[f"{id_name}-credentials"]
            ),
            "Assigning the location should create its objects named after its id, "
            "with the location's keys in the Secret",
        )
        assert await _velero_storage_location(client, environment.id) == id_name, (
            "The backup capability should name the location's Velero object"
        )

        await client.backup_storage_locations.update(
            bsl_id, name=f"after-rename-{suffix}"
        )
        assert await _velero_storage_location(client, environment.id) == id_name, (
            "A rename should not change the backup capability (#509)"
        )
        await create_name_based_bsl_objects(
            kubeconfig_path, bsl_id, f"before-rename-{suffix}", bucket
        )

        await client.backup_storage_locations.update(
            bsl_id,
            access_key_id="GKafterrenameafterrename",
            secret_access_key="after-rename-secret",
        )
        await wait_for_bsl_cluster_objects(
            kubeconfig_path,
            bsl_id,
            lambda _bsls, secrets: (
                len(secrets) == 2
                and all(
                    "GKafterrenameafterrename" in cloud for cloud in secrets.values()
                )
            ),
            "A credentials update after a rename should reach every Secret of the location",
        )

        await client.backup_storage_locations.unassign(environment_id=environment.id)
        await wait_for_bsl_cluster_objects(
            kubeconfig_path,
            bsl_id,
            lambda bsls, secrets: not bsls and not secrets,
            "Unassigning the renamed location should remove all its objects",
        )

        await assert_bsl_keys_not_readable_from_prefect(
            kubeconfig_path,
            bsl_id,
            [
                "GKbeforerenamebeforerename",
                "before-rename-secret",
                "GKafterrenameafterrename",
                "after-rename-secret",
            ],
        )
        await client.environments.delete(environment_id=environment.id)
        await client.backup_storage_locations.delete(bsl_id)
        assert not await bsl_credentials_block_exists(kubeconfig_path, bsl_id), (
            "Deleting the location should delete its Prefect Secret block"
        )
    finally:
        with suppress(Exception):
            await client.backup_storage_locations.unassign(
                environment_id=environment.id
            )
        with suppress(Exception):
            await client.environments.delete(environment_id=environment.id)
        with suppress(Exception):
            await client.backup_storage_locations.delete(bsl_id)


# ---------------------------------------------------------------------------
# Environment clone (spec 010-environment-clone)
# ---------------------------------------------------------------------------


def _clone_results_by_deployment(
    clone: EnvironmentCloneRef,
) -> dict[str, EnvironmentCloneDeploymentResultRef]:
    """Index a clone's attribution entries, asserting each deployment appears once.

    The uniqueness check is half of SC-003: "every source deployment considered
    appears exactly once" is only a coverage guarantee if a duplicate entry
    cannot hide a contradicting one.
    """
    results = {result.deployment_id: result for result in clone.deployment_results}
    assert len(results) == len(clone.deployment_results), (
        "a source deployment appears twice on the clone record: "
        f"{[r.deployment_id for r in clone.deployment_results]!r}"
    )
    return results


def _referenced_deployment_ids(value: Any) -> set[str]:
    """Every ``deployment_ref.deployment_id`` in a stored config, at any depth."""
    if isinstance(value, list):
        return set().union(*(_referenced_deployment_ids(item) for item in value))
    if not isinstance(value, dict):
        return set()
    found = set().union(*(_referenced_deployment_ids(item) for item in value.values()))
    reference = value.get("deployment_ref")
    if isinstance(reference, dict) and reference.get("deployment_id"):
        found.add(str(reference["deployment_id"]))
    return found


@pytest.mark.ci
@pytest.mark.shard_env_backup
async def test_environment_clone_lifecycle(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,
    deployed_simple_app: dict,
    velero_ready: None,  # noqa: ARG001 — ensures Velero is up before the capture
    vcluster: dict,
) -> None:
    """One clone of a live environment, its discard, a re-clone and a partial clone.

    Covers the whole 010-environment-clone feature in one dual-entrypoint node
    (Constitution §V "reuse before you boot", research D12): US1 (running,
    data-bearing copy), US2 (explicit deployment selection), US3 (clone-time
    config override including field clearing) and US4 (derived tracking, full
    attribution, discard-and-re-clone). It reuses the stack the environment
    backup/restore node already deploys — ``scenario_environment_id``,
    ``deployed_simple_app``, ``velero_ready`` — and adds one peer deployment
    whose preferred pod affinity term names the primary.

    027-deployment-reference-by-id (US5, US6, research R-013): the peer's term is
    written with the primary's name and stored with the primary's id. A clone
    request that selects only the peer is refused before any clone record or
    backup exists, with the primary's name and the path of the peer's term. The
    clone then selects both, and the peer's counterpart's term gives the primary's
    counterpart id; no term in the new environment gives a source deployment's id.
    The UI cannot write a deployment reference, so both variants write the term
    and send the refused request through the SDK.

    030-clone-service-aliases (#530): after the first clone, each counterpart's
    namespace holds one alias for each service of the new environment's other
    deployments (SC-001). The re-clone of step 11 selects no deployment, so it
    restores nothing. A partial clone under its own name (step 12) then selects
    only the primary: no alias in its environment names a namespace outside that
    environment, and the primary's counterpart has no alias for the peer's
    service (SC-002).

    Success criteria asserted here:

    * **SC-001** — a single operation yields a counterpart deployment that
      reaches ``running`` in a brand-new environment, with zero per-deployment
      operator steps.
    * **SC-002** — the source is untouched: its config is byte-identical either
      side of the clone, its deployment roster is unchanged, and the only
      source-side artefact gained is the one environment backup the clone was
      built from.
    * **SC-003** — every source deployment considered is attributed exactly
      once: both selected ones ``CLONED`` with a counterpart and a restore; the
      configuration-only re-clone's empty selection gives each ``SKIPPED`` with
      the not-selected reason; the partial clone gives the primary ``CLONED``
      and the peer ``SKIPPED`` with the not-selected reason. Internal
      deployments are omitted entirely (not reported as skips), which is what
      makes set *equality* the right assertion.
    * **SC-004** — the clone holds the data as of the capture, not the source
      mutation written after it, proved by an **authenticated write** against
      the counterpart (step 9 explains why ``/count`` is that write).
    * **SC-005** — deleting the created environment discards the clone and frees
      its name: a configuration-only re-clone under the same name is accepted
      and materialises.

    Also FR-006: the created environment's config is the captured config with
    one field cleared and the override merged over the rest, asserted as an
    exact dict.
    """
    from uuid import uuid4

    from styrmin_sdk.graphql._generated.input_types import (
        AffinityBlockInput,
        AffinityTermInput,
        DeploymentReferenceInput,
        SchedulingInput,
        UpdateDeploymentInput,
        WeightedAffinityTermInput,
    )

    client: StyrminClient = styrmin_resources["client"]
    kubeconfig_path = vcluster["kubeconfig_path"]

    primary_deployment_id = deployed_simple_app["deployment_id"]
    primary_namespace = deployed_simple_app["namespace"]
    primary_name = (await client.deployments.get(primary_deployment_id)).name

    suffix = uuid4().hex[:8]
    clone_name = f"clone-target-{suffix}"
    peer_service_name = f"envclone{suffix}"

    def _peer_scheduling(deployment_id: str) -> dict[str, Any]:
        # The peer's stored scheduling: one preferred pod affinity term that names
        # ``deployment_id``; preferred, so it never leaves a pod Pending.
        return {
            "pod_affinity": {
                "preferred": [
                    {
                        "weight": 1,
                        "term": {
                            "topology_key": "kubernetes.io/hostname",
                            "deployment_ref": {"deployment_id": deployment_id},
                        },
                    }
                ]
            }
        }

    # A second eligible deployment, whose affinity term names the primary, is
    # what makes the refused selection and the counterpart remap meaningful. The
    # shared environment enforces per-env service-name uniqueness, hence the
    # override (see ``scenario_environment_id``).
    peer = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
        name=f"env-clone-{suffix}",
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": peer_service_name}
        ],
    )
    peer_deployment_id = peer.id
    await scenario_driver.wait_for_deployment_running(
        deployment_id=peer_deployment_id,
        timeout=DEPLOYMENT_RUNNING_TIMEOUT_SECONDS,
    )
    peer_name = (await client.deployments.get(peer_deployment_id)).name

    previous_backup_ttl = (
        (await client.environments.get(environment_id=scenario_environment_id)).config
        or {}
    ).get("backup_ttl")
    source_backups_before = {
        str(backup.id)
        for backup in await client.environment_backups.list(scenario_environment_id)
    }
    created_environment_ids: list[str] = []

    try:
        # 0. The peer's affinity term names the primary by name and is stored with
        #    the primary's id (027 US2). The wait is the fanout rule applied to
        #    the update's own Task: it ends and the peer runs again.
        peer_timeline_length = len(
            await client.deployments.get_timeline(deployment_id=peer_deployment_id)
        )
        peer_task = await client.deployments.update(
            peer_deployment_id,
            input=UpdateDeploymentInput(
                scheduling=SchedulingInput(
                    podAffinity=AffinityBlockInput(
                        preferred=[
                            WeightedAffinityTermInput(
                                weight=1,
                                term=AffinityTermInput(
                                    topologyKey="kubernetes.io/hostname",
                                    deploymentRef=DeploymentReferenceInput(
                                        deploymentName=primary_name
                                    ),
                                ),
                            )
                        ]
                    )
                )
            ),
        )
        assert peer_task is not None, "adding the affinity term must reconcile the peer"
        await wait_for_env_fanout_steady_state(
            client,
            deployment_id=peer_deployment_id,
            pre_timeline_length=peer_timeline_length,
        )
        peer_config = (await client.deployments.get(peer_deployment_id)).config or {}
        assert peer_config.get("scheduling") == _peer_scheduling(
            primary_deployment_id
        ), (
            "the peer's term written with the primary's name must be stored with "
            f"the primary's id (027 FR-001); got {peer_config!r}"
        )

        # 1. Give the source a config field worth clearing (FR-006 / US3), then
        #    let the redeploy fanout settle before anything is captured — the
        #    environment is session-shared and a capture must not race a
        #    reconcile (the same rule the sibling snapshot node follows).
        pre_ttl_timeline = {
            deployment_id: len(
                await client.deployments.get_timeline(deployment_id=deployment_id)
            )
            for deployment_id in (primary_deployment_id, peer_deployment_id)
        }
        await scenario_driver.set_environment_backup_ttl(
            environment_id=scenario_environment_id,
            ttl=CLONE_SOURCE_BACKUP_TTL,
        )
        await asyncio.gather(
            *(
                wait_for_env_fanout_steady_state(
                    client, deployment_id=deployment_id, pre_timeline_length=length
                )
                for deployment_id, length in pre_ttl_timeline.items()
            )
        )
        await wait_for_pods_ready(kubeconfig_path, primary_namespace)

        # The retention write left the UI driver on the environment detail page;
        # the marker write below needs the primary deployment's page. For the API
        # driver ``attach_to_deployment`` is a no-op and the wait is one SDK read
        # on an already-running deployment, so this needs no ``driver_mode``
        # branch.
        scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)
        await scenario_driver.wait_for_deployment_running(
            deployment_id=primary_deployment_id
        )

        # 2. Write the data marker the clone must reproduce (SC-004).
        async with portforward_simple_app(kubeconfig_path, primary_namespace) as port:
            async with httpx.AsyncClient() as http_client:
                for _ in range(5):
                    await http_client.get(f"http://localhost:{port}/count", timeout=10)
                resp = await http_client.get(
                    f"http://localhost:{port}/count", timeout=10
                )
                marker_count = resp.json()["counter"]

        source_config_before = (
            await client.environments.get(environment_id=scenario_environment_id)
        ).config
        assert (source_config_before or {}).get("backup_ttl") == (
            CLONE_SOURCE_BACKUP_TTL
        ), (
            "the captured config must actually carry the field the clone is "
            f"asked to clear, got {source_config_before!r}"
        )
        source_deployments_before = await instanced_deployment_ids(
            client, scenario_environment_id
        )
        assert {primary_deployment_id, peer_deployment_id} <= (
            source_deployments_before
        ), (
            "both source deployments must carry an active instance before the "
            f"clone, got {source_deployments_before!r}"
        )
        source_state_before = await source_deployment_state(
            client, (primary_deployment_id, peer_deployment_id)
        )
        source_objects_before = await workload_object_names(
            kubeconfig_path, primary_namespace
        )
        assert all(
            entry["status"] == "running" for entry in source_state_before.values()
        ), (
            "the SC-002 baseline must be taken with both source deployments "
            f"settled, otherwise the comparison is meaningless: {source_state_before!r}"
        )

        # 3. A request that selects only the peer leaves out the primary its term
        #    names, so it is refused before any clone record or backup (027 US6;
        #    step 7 checks that the source gained no backup). The message names the
        #    term's path, and the SDK exception gives the error's extensions (#522).
        clones_before = {
            str(c.id)
            for c in await client.environment_clones.list(scenario_environment_id)
        }
        with pytest.raises(OperationFailedError) as refused:
            await client.environment_clones.create(
                clone_name,
                environment_id=scenario_environment_id,
                deployment_ids=[peer_deployment_id],
            )
        assert refused.value.typename == "VALIDATION_ERROR", refused.value
        peer_term_path = (
            f"deployment[{peer_name}].config.scheduling.pod_affinity.preferred[0].term"
        )
        assert str(refused.value).startswith(
            f"{CLONE_REFUSED_UNCLONED_REFERENCE}: {primary_name!r} "
            f"(not included in the requested deployment selection), named at "
            f"{peer_term_path}. Add the deployment to the selection"
        ), str(refused.value)
        assert refused.value.extensions.get("deployments") == [
            {
                "deployment_id": primary_deployment_id,
                "deployment_name": primary_name,
                "paths": [peer_term_path],
                "reason": "not included in the requested deployment selection",
            }
        ], refused.value.extensions
        assert {
            str(c.id)
            for c in await client.environment_clones.list(scenario_environment_id)
        } == clones_before, "a refused clone request must create no clone record"

        #    One operation then clones the environment: both deployments are
        #    selected (US2), the override injects an env var and clears the
        #    captured retention policy (US3).
        clone = await scenario_driver.clone_environment(
            environment_id=scenario_environment_id,
            name=clone_name,
            deployment_ids=[primary_deployment_id, peer_deployment_id],
            config_override={
                "envVars": [
                    {
                        "name": CLONE_OVERRIDE_ENV_VAR_NAME,
                        "value": CLONE_OVERRIDE_ENV_VAR_VALUE,
                    }
                ]
            },
            clear_config_fields=[CLONE_CLEARED_CONFIG_FIELD],
        )
        assert clone.name == clone_name
        # ``PENDING`` is deliberately not required: the derivation may already
        # read ``IN_PROGRESS`` on the very first observation.
        assert clone.status in {"PENDING", "IN_PROGRESS"}, (
            f"a just-registered clone must not be terminal, got {clone.status!r}"
        )
        assert clone.created_environment_id is None, (
            "nothing may materialise before the capture reaches a restorable "
            f"terminal status (FR-002), got {clone.created_environment_id!r}"
        )
        environment_backup_id = clone.environment_backup_id
        assert environment_backup_id is not None, (
            "registration must link the capture the clone is built from (FR-002)"
        )

        # Both source deployments are accounted for from the very first read
        # (SC-003). The environment also owns an internal ingress-controller
        # deployment with an active instance, and it is *omitted* rather than
        # reported as a skip, which is why equality is the right assertion.
        registered = _clone_results_by_deployment(clone)
        assert set(registered) == {primary_deployment_id, peer_deployment_id}, (
            "every source deployment considered must be attributed, internal "
            f"deployments omitted (SC-003): got {set(registered)!r}"
        )
        for deployment_id, name in (
            (primary_deployment_id, primary_name),
            (peer_deployment_id, peer_name),
        ):
            assert registered[deployment_id].outcome == "PENDING", (
                f"a selected deployment starts PENDING, got "
                f"{registered[deployment_id].outcome!r} "
                f"({registered[deployment_id].reason!r})"
            )
            assert registered[deployment_id].deployment_name == name

        # 4. The capture is the *selected* deployments only (US2 at the cluster
        #    level, not merely in the record), and it goes terminal before the
        #    source is mutated again.
        capture = await scenario_driver.wait_for_environment_backup(
            environment_backup_id=environment_backup_id,
            max_wait=ENVIRONMENT_BACKUP_FANOUT_TIMEOUT_SECONDS,
        )
        assert capture.status == "COMPLETED", (
            "the clone's capture must complete for the clone to be built from "
            f"it (FR-002); got {capture.status!r}"
        )
        assert {c.deployment_id for c in capture.constituents} == {
            primary_deployment_id,
            peer_deployment_id,
        }, (
            "the selection must filter the capture itself, not just the clone "
            f"record (US2 / FR-003); got {[c.deployment_id for c in capture.constituents]!r}"
        )

        # 5. Mutate the source data *after* the capture. The finished clone must
        #    not contain this (FR-007: the clone is built entirely from the
        #    capture; the live source is never re-read).
        async with portforward_simple_app(kubeconfig_path, primary_namespace) as port:
            async with httpx.AsyncClient() as http_client:
                for _ in range(5):
                    await http_client.get(f"http://localhost:{port}/count", timeout=10)
                resp = await http_client.get(
                    f"http://localhost:{port}/count", timeout=10
                )
                post_capture_count = resp.json()["counter"]
        assert post_capture_count > marker_count, (
            "the post-capture write must actually diverge from the marker, "
            "otherwise SC-004 would pass without the capture point mattering: "
            f"{post_capture_count} !> {marker_count}"
        )

        # 6. The clone reaches a terminal derived status with full attribution.
        finished = await scenario_driver.wait_for_environment_clone(
            environment_clone_id=clone.id,
            max_wait=ENVIRONMENT_CLONE_TIMEOUT_SECONDS,
        )
        assert finished.status == "COMPLETED", (
            "both selected deployments cloned and restored cleanly, so the derived "
            f"status must be COMPLETED; got {finished.status!r} with events "
            f"{finished.clone_errors!r}"
        )
        assert not finished.discarded
        created_environment_id = finished.created_environment_id
        assert created_environment_id is not None, (
            "a COMPLETED clone must have created its environment"
        )
        created_environment_ids.append(created_environment_id)

        results = _clone_results_by_deployment(finished)
        assert set(results) == {primary_deployment_id, peer_deployment_id}, (
            f"attribution must still cover every source deployment (SC-003): "
            f"got {set(results)!r}"
        )
        counterpart_ids: dict[str, str] = {}
        for deployment_id, name in (
            (primary_deployment_id, primary_name),
            (peer_deployment_id, peer_name),
        ):
            cloned_result = results[deployment_id]
            assert cloned_result.outcome == "CLONED", (
                f"the selected deployment {name!r} must be cloned, got "
                f"{cloned_result.outcome!r} ({cloned_result.reason!r})"
            )
            assert cloned_result.deployment_name == name
            assert cloned_result.counterpart_deployment_id is not None, (
                "a CLONED entry must name the counterpart deployment it created"
            )
            assert cloned_result.restore_id is not None, (
                "a CLONED entry must name the cross-target restore carrying its data"
            )
            counterpart_ids[deployment_id] = cloned_result.counterpart_deployment_id
        counterpart_deployment_id = counterpart_ids[primary_deployment_id]
        peer_counterpart_deployment_id = counterpart_ids[peer_deployment_id]

        # SC-001 of spec 030, FR-016 of #518: each counterpart holds its peers' aliases.
        # ``environmentServices`` also lists internal deployments, which the
        # ``deployment`` query hides.
        raw_services = await client._transport.execute(
            load_query("get_environment_services"),
            {"environmentId": str(created_environment_id)},
        )
        assert "errors" not in raw_services, raw_services
        created_services: dict[str, list[str]] = {}
        for service in raw_services["data"]["environmentServices"]:
            created_services.setdefault(str(service["deploymentId"]), []).append(
                service["resolvedName"]
            )
        for counterpart_id in counterpart_ids.values():
            expected_aliases = {
                ServiceAlias(resolved_name, deployment_id, f"styrmin-{deployment_id}")
                for deployment_id, resolved_names in created_services.items()
                if deployment_id != counterpart_id
                for resolved_name in resolved_names
            }
            aliases = await wait_for_service_aliases(
                kubeconfig_path,
                f"styrmin-{counterpart_id}",
                expected_aliases,
                timeout=SERVICE_ALIASES_TIMEOUT_SECONDS,
            )
            assert aliases == expected_aliases, (
                f"the aliases in the namespace of counterpart {counterpart_id} must "
                "be those of the services of the new environment's other "
                "deployments (SC-001 of spec 030); "
                f"unexpected: {sorted(aliases - expected_aliases)!r}; "
                f"missing: {sorted(expected_aliases - aliases)!r}"
            )

        # 7. SC-002 — the source is untouched. Read through the SDK on both
        #    entrypoints: this is the source's *state*, not a UI affordance, and
        #    the frontend surfaces neither the persisted config dict nor the
        #    full deployment roster in a comparable form.
        source_after = await client.environments.get(
            environment_id=scenario_environment_id
        )
        assert source_after.config == source_config_before, (
            "cloning must not mutate the source environment's config (SC-002): "
            f"{source_after.config!r} != {source_config_before!r}"
        )
        assert (
            await instanced_deployment_ids(client, scenario_environment_id)
        ) == source_deployments_before, (
            "cloning must not create or delete a source deployment (SC-002)"
        )
        # ...and the roster is only the shallow half of "byte-identical". Each
        # source deployment's own declared state — its state machine position,
        # its config, its driver pin and fingerprint, its active instance and
        # its resolved service names — must be exactly what it was.
        assert (
            await source_deployment_state(
                client, (primary_deployment_id, peer_deployment_id)
            )
        ) == source_state_before, (
            "cloning mutated a source deployment's declared state (SC-002); "
            f"expected {source_state_before!r}"
        )
        # The source's *objects*. The counterpart's Helm upgrade diffs against the
        # restored release record, which names the source namespace; left
        # unretargeted it deletes the source's namespace-pinned chart objects
        # (its postgres). Waiting for that upgrade makes the check deterministic.
        await wait_for_helmreleases_settled(
            kubeconfig_path,
            f"styrmin-{counterpart_deployment_id}",
            timeout=COUNTERPART_HELMRELEASE_SETTLED_TIMEOUT_SECONDS,
        )
        missing_source_objects = source_objects_before - await workload_object_names(
            kubeconfig_path, primary_namespace
        )
        assert not missing_source_objects, (
            "cloning deleted objects from the source namespace (SC-002): "
            f"{sorted(missing_source_objects)!r}"
        )
        # The source's *health*, asserted where a failure can actually fail the
        # test. This used to exist only in the ``finally`` block below, wrapped
        # in ``suppress(Exception)`` for the UI driver's page hand-back, so a
        # source left in RESTORING or FAILED by a mis-targeted cross-target
        # restore could not be reported by this node at all.
        scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)
        await scenario_driver.wait_for_deployment_running(
            deployment_id=primary_deployment_id,
            timeout=DEPLOYMENT_RUNNING_TIMEOUT_SECONDS,
        )
        # The source's *data*, which is what a restore aimed at the source
        # namespace would silently roll back: the post-capture write from step 5
        # must still be there. A source rebuilt from the capture would read back
        # around ``marker_count``, far below this.
        async with portforward_simple_app(kubeconfig_path, primary_namespace) as port:
            async with httpx.AsyncClient() as http_client:
                resp = await http_client.get(
                    f"http://localhost:{port}/count", timeout=10
                )
        assert resp.status_code == 200, (
            "the source app must still serve authenticated writes after the "
            f"clone (SC-002); got {resp.status_code} {resp.text!r}"
        )
        source_count_after = resp.json()["counter"]
        assert source_count_after > post_capture_count, (
            "the clone rolled the source's data back to the capture point "
            f"(SC-002): expected {post_capture_count + 1} (the +1 is this read "
            f"itself), got {source_count_after} with the pre-capture marker at "
            f"{marker_count}"
        )
        source_backups_after = {
            str(backup.id)
            for backup in await client.environment_backups.list(scenario_environment_id)
        }
        assert source_backups_after - source_backups_before == {
            environment_backup_id
        }, (
            "the only source-side artefact a clone leaves behind is the "
            "environment backup it was built from (SC-002); gained "
            f"{source_backups_after - source_backups_before!r}"
        )

        # 8. FR-006 — the created environment's config is the captured config
        #    with the named field cleared and the override merged over the rest.
        #    Asserted as an exact dict: "override present" alone would pass even
        #    if the cleared field survived.
        created_environment = await client.environments.get(
            environment_id=created_environment_id
        )
        assert created_environment.name == clone_name
        assert created_environment.config == {
            "env_vars": {CLONE_OVERRIDE_ENV_VAR_NAME: CLONE_OVERRIDE_ENV_VAR_VALUE}
        }, (
            "the cloned environment's config must be the captured config with "
            f"{CLONE_CLEARED_CONFIG_FIELD!r} cleared and the override merged "
            f"over it (FR-006); got {created_environment.config!r}"
        )
        # 027 US5 — the peer's counterpart's term gives the primary's counterpart
        # id, and no term in the new environment gives a source deployment's id.
        # The simple-app driver's component definitions carry no term.
        counterpart_configs = {
            deployment_id: (await client.deployments.get(deployment_id)).config or {}
            for deployment_id in (
                counterpart_deployment_id,
                peer_counterpart_deployment_id,
            )
        }
        assert counterpart_configs[peer_counterpart_deployment_id].get(
            "scheduling"
        ) == _peer_scheduling(counterpart_deployment_id), (
            "the peer's counterpart's term must name the primary's counterpart "
            f"{counterpart_deployment_id} (027 US5); got "
            f"{counterpart_configs[peer_counterpart_deployment_id]!r}"
        )
        new_environment_references = _referenced_deployment_ids(
            created_environment.config
        ).union(*(_referenced_deployment_ids(c) for c in counterpart_configs.values()))
        assert new_environment_references == {counterpart_deployment_id}, (
            "every term in the new environment must name a counterpart and none a "
            f"source deployment (027 FR-008); got {new_environment_references!r}"
        )

        # 9. SC-001 / SC-004 — the counterparts run in the new environment and
        #    the primary's holds the data as of the capture. The peer's
        #    counterpart must leave RESTORING before step 10 deletes it.
        await _wait_for_sdk_deployment_running(
            client, peer_counterpart_deployment_id, DEPLOYMENT_RUNNING_TIMEOUT_SECONDS
        )
        scenario_driver.attach_to_deployment(environment_id=created_environment_id)
        await scenario_driver.wait_for_deployment_running(
            deployment_id=counterpart_deployment_id,
            timeout=DEPLOYMENT_RUNNING_TIMEOUT_SECONDS,
        )
        counterpart_namespace = f"styrmin-{counterpart_deployment_id}"
        await wait_for_pods_ready(
            kubeconfig_path,
            counterpart_namespace,
            timeout=CLONE_PODS_READY_TIMEOUT_SECONDS,
        )
        # 9-labels. The counterpart's namespace carries the labels of the new
        #     environment and of the counterpart, not the source's: network
        #     policies select namespaces by them.
        counterpart_labels = await namespace_labels(
            kubeconfig_path, counterpart_namespace
        )
        assert counterpart_labels.get("styrmin/environment_id") == str(
            created_environment_id
        ), (
            f"the clone's namespace must carry the new environment's id, got {counterpart_labels!r}"
        )
        assert counterpart_labels.get("styrmin/deployment_id") == str(
            counterpart_deployment_id
        ), (
            f"the clone's namespace must carry the counterpart's id, got {counterpart_labels!r}"
        )
        async with portforward_simple_app(
            kubeconfig_path, counterpart_namespace
        ) as port:
            async with httpx.AsyncClient() as http_client:
                resp = await http_client.get(
                    f"http://localhost:{port}/count", timeout=10
                )
        # ``/count`` is an *authenticated write*, which is the whole point of
        # reading it here rather than a read-only endpoint (research D2): the
        # app opens a PostgreSQL session with the credentials in the restored
        # Secret and commits an UPDATE. So a 200 proves the counterpart's
        # re-rendered credentials still match the restored data — the failure
        # mode a chart that generates credentials at install time would produce
        # — while the value proves the capture point. A 500 here means
        # credentials; a wrong counter means the wrong data.
        assert resp.status_code == 200, (
            "an authenticated write against the counterpart must succeed — a "
            "failure here means the restored data is unreachable with the "
            f"counterpart's credentials (research D2); got {resp.status_code} "
            f"{resp.text!r}"
        )
        assert resp.json()["counter"] == marker_count + 1, (
            "the clone must hold the source's data as of the capture, not the "
            f"post-capture write (SC-004 / FR-007): expected "
            f"{marker_count + 1} (the +1 is this read itself), post-capture "
            f"source value was {post_capture_count}"
        )

        # 10. SC-005 — discard the clone by deleting the environment it created.
        #     Driven through the SDK on both entrypoints: the frontend exposes no
        #     delete-environment surface at all (the UI driver refuses the call
        #     by contract), so there is no UI flow to exercise here. What *is*
        #     under test is the record's reaction, and that is read back through
        #     the dual-entrypoint driver below.
        await client.environments.delete(environment_id=created_environment_id)
        created_environment_ids.remove(created_environment_id)
        discarded = await scenario_driver.get_environment_clone(
            environment_clone_id=clone.id
        )
        assert discarded.created_environment_id is None, (
            "discarding must release the created environment on the record"
        )
        assert discarded.discarded, (
            "the record must say it was discarded rather than merely showing no "
            f"environment; events: {discarded.clone_errors!r}"
        )
        assert any(
            entry.startswith(CLONE_DISCARD_STEP_PREFIX)
            for entry in discarded.clone_errors
        ), (
            "the discard must be attributed as an event, not left implicit: "
            f"{discarded.clone_errors!r}"
        )
        assert discarded.status == "COMPLETED", (
            "discarding the environment of a clone that already finished keeps "
            f"the finished outcome as history; got {discarded.status!r}"
        )

        # 11. SC-005 — the name is free again and a re-clone materialises.
        #     Deliberately a *configuration-only* re-clone (empty selection, a
        #     legal request distinct from omitting the argument): the restore
        #     path is already proven by the first cycle, and a second full cycle
        #     would put this node roughly 2.5 clone-cycles deep on the heaviest
        #     shard (research D12). What SC-005 needs is that the name is free,
        #     the record is created, and the environment row exists.
        reclone = await scenario_driver.clone_environment(
            environment_id=scenario_environment_id,
            name=clone_name,
            deployment_ids=[],
        )
        assert reclone.id != clone.id
        assert reclone.name == clone_name, (
            "re-cloning under the discarded clone's name must be accepted "
            "(SC-005) — the clone record's name is deliberately not unique"
        )
        rematerialised = await scenario_driver.wait_for_environment_clone(
            environment_clone_id=reclone.id,
            max_wait=CONFIG_ONLY_CLONE_TIMEOUT_SECONDS,
        )
        assert rematerialised.status == "COMPLETED", (
            "a configuration-only clone has nothing that can fail, so it must "
            f"reach COMPLETED; got {rematerialised.status!r} with events "
            f"{rematerialised.clone_errors!r}"
        )
        recreated_environment_id = rematerialised.created_environment_id
        assert recreated_environment_id is not None, (
            "the re-clone must materialise an environment (SC-005)"
        )
        created_environment_ids.append(recreated_environment_id)
        assert recreated_environment_id != created_environment_id, (
            "the re-clone must create a new environment, not resurrect the "
            "discarded one"
        )
        recreated = await client.environments.get(
            environment_id=recreated_environment_id
        )
        assert recreated.name == clone_name
        # Coverage identity holds for a configuration-only clone too: both
        # source deployments are accounted for, neither is included.
        reclone_results = _clone_results_by_deployment(rematerialised)
        assert set(reclone_results) == {
            primary_deployment_id,
            peer_deployment_id,
        }, f"SC-003 must hold for a config-only clone too: {set(reclone_results)!r}"
        assert all(
            result.outcome == "SKIPPED" for result in reclone_results.values()
        ), (
            "an empty selection includes nothing, so every source deployment is "
            f"a skip: {[(r.deployment_id, r.outcome) for r in reclone_results.values()]!r}"
        )
        for deployment_id, name in (
            (primary_deployment_id, primary_name),
            (peer_deployment_id, peer_name),
        ):
            skipped_result = reclone_results[deployment_id]
            assert skipped_result.deployment_name == name, (
                "a skip is attributed by deployment name (SC-003); got "
                f"{skipped_result.deployment_name!r}"
            )
            assert skipped_result.reason == CLONE_REASON_NOT_SELECTED, (
                f"unexpected skip reason {skipped_result.reason!r}"
            )
            assert skipped_result.counterpart_deployment_id is None, (
                "an unselected deployment must not get a counterpart"
            )

        # 12. SC-002 of spec 030 — a clone of some deployments reaches no
        #     deployment of the source. This clone selects only the primary, so it
        #     restores one deployment. It takes its own name, because the
        #     environment that step 11 created still holds ``clone_name``.
        partial_clone_name = f"clone-partial-{suffix}"
        partial_clone = await scenario_driver.clone_environment(
            environment_id=scenario_environment_id,
            name=partial_clone_name,
            deployment_ids=[primary_deployment_id],
        )
        partial_finished = await scenario_driver.wait_for_environment_clone(
            environment_clone_id=partial_clone.id,
            max_wait=ENVIRONMENT_CLONE_TIMEOUT_SECONDS,
        )
        partial_environment_id = partial_finished.created_environment_id
        # Recorded before the status check, so that the ``finally`` block deletes
        # the partial clone's counterpart even when the partial clone fails.
        if partial_environment_id is not None:
            created_environment_ids.append(partial_environment_id)
        assert partial_finished.status == "COMPLETED", (
            "the selected primary cloned and restored cleanly, so the derived "
            f"status must be COMPLETED; got {partial_finished.status!r} with events "
            f"{partial_finished.clone_errors!r}"
        )
        assert partial_environment_id is not None, (
            "a COMPLETED clone must have created its environment"
        )
        # Both source deployments are accounted for: the primary is cloned and
        # the peer, which the selection leaves out, is a skip (SC-003).
        partial_results = _clone_results_by_deployment(partial_finished)
        assert set(partial_results) == {
            primary_deployment_id,
            peer_deployment_id,
        }, f"SC-003 must hold for a partial clone too: {set(partial_results)!r}"
        partial_cloned_result = partial_results[primary_deployment_id]
        assert partial_cloned_result.outcome == "CLONED", (
            "the selected primary must be cloned, got "
            f"{partial_cloned_result.outcome!r} ({partial_cloned_result.reason!r})"
        )
        assert partial_cloned_result.deployment_name == primary_name
        assert partial_cloned_result.restore_id is not None, (
            "a CLONED entry must name the cross-target restore carrying its data"
        )
        partial_counterpart_id = partial_cloned_result.counterpart_deployment_id
        assert partial_counterpart_id is not None, (
            "a CLONED entry must name the counterpart deployment it created"
        )
        partial_skipped_result = partial_results[peer_deployment_id]
        assert partial_skipped_result.outcome == "SKIPPED", (
            "the selection leaves the peer out, so the peer must be a skip; got "
            f"{partial_skipped_result.outcome!r} ({partial_skipped_result.reason!r})"
        )
        assert partial_skipped_result.deployment_name == peer_name, (
            "a skip is attributed by deployment name (SC-003); got "
            f"{partial_skipped_result.deployment_name!r}"
        )
        assert partial_skipped_result.reason == CLONE_REASON_NOT_SELECTED, (
            f"unexpected skip reason {partial_skipped_result.reason!r}"
        )
        assert partial_skipped_result.counterpart_deployment_id is None, (
            "an unselected deployment must not get a counterpart"
        )

        # SC-002 of spec 030. The restore writes its aliases before it completes, so
        # one read after the clone completes is enough.
        partial_namespaces = {
            f"styrmin-{deployment.id}"
            for deployment in await client.deployments.list(
                partial_environment_id, include_internal=True
            )
        }
        partial_counterpart_namespace = f"styrmin-{partial_counterpart_id}"
        assert partial_counterpart_namespace in partial_namespaces, (
            "the partial clone's environment must list its counterpart "
            f"{partial_counterpart_id}; got {sorted(partial_namespaces)!r}"
        )
        partial_aliases = {
            namespace: await service_aliases(kubeconfig_path, namespace)
            for namespace in partial_namespaces
        }
        aliases_outside = sorted(
            (namespace, alias)
            for namespace, aliases in partial_aliases.items()
            for alias in aliases
            if alias.target_namespace not in partial_namespaces
        )
        assert not aliases_outside, (
            "no alias in the partial clone's environment may point to a namespace "
            "outside it (SC-002 of spec 030); got (namespace, alias): "
            f"{aliases_outside!r}"
        )
        peer_aliases = sorted(
            alias
            for alias in partial_aliases[partial_counterpart_namespace]
            if alias.name == peer_service_name
        )
        assert not peer_aliases, (
            "the primary's counterpart must have no alias for the peer's service "
            f"{peer_service_name!r}, because the peer was not cloned (SC-002 of "
            f"spec 030); got {peer_aliases!r}"
        )
        # The counterpart must leave RESTORING before the ``finally`` block deletes
        # its environment, as the peer's counterpart does in step 9.
        await _wait_for_sdk_deployment_running(
            client, partial_counterpart_id, DEPLOYMENT_RUNNING_TIMEOUT_SECONDS
        )
    finally:
        # Every cleanup step below is best-effort *except* the retention revert:
        # the environment is session-shared, so leaving a 1800h policy behind
        # would silently hand it to every later ``shard_env_backup`` test. A cleanup
        # timeout must never mask the test's own failure.
        #
        # Clone-created environments go first: deleting them settles any clone
        # record still non-terminal (which is what releases the environment-level
        # guards) before anything else touches the source.
        for environment_id in created_environment_ids:
            with suppress(Exception):
                await client.environments.delete(environment_id=environment_id)

        revert_timeline = {
            deployment_id: len(
                await client.deployments.get_timeline(deployment_id=deployment_id)
            )
            for deployment_id in (primary_deployment_id, peer_deployment_id)
        }
        await scenario_driver.set_environment_backup_ttl(
            environment_id=scenario_environment_id, ttl=previous_backup_ttl
        )
        with suppress(AssertionError):
            await asyncio.gather(
                *(
                    wait_for_env_fanout_steady_state(
                        client,
                        deployment_id=deployment_id,
                        pre_timeline_length=length,
                        timeout=CLEANUP_WAIT_TIMEOUT_SECONDS,
                        noop_grace=NOOP_FANOUT_GRACE_SECONDS,
                    )
                    for deployment_id, length in revert_timeline.items()
                )
            )
        # Delete the peer this test created. The environment is session-shared,
        # so leaving it behind hands every later ``shard_env_backup`` test an extra
        # constituent in any snapshot, an extra redeploy in any env-config
        # fanout, and a service name the next ``simple-app`` peer must avoid.
        with suppress(Exception):
            await client.deployments.delete(peer_deployment_id)
        # The UI driver's page is session-scoped and sibling tests act on
        # whatever page is open, so hand it back on the source environment's
        # primary deployment. Teardown only — the load-bearing source health
        # check is the un-suppressed one in step 7; this one exists so a
        # cleanup timeout cannot mask the test's own failure.
        scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)
        with suppress(Exception):
            await scenario_driver.wait_for_deployment_running(
                deployment_id=primary_deployment_id,
                timeout=CLEANUP_WAIT_TIMEOUT_SECONDS,
            )
