"""Prefect workflow templates for backup and restore operations.

Orchestrates the full Velero lifecycle: build CRDs, create in K8s,
poll status, and update Styrmin records.

INTERNAL flows (styrmin-work-pool): DB operations, CRD spec building,
dispatching USER flows, and updating status from results.

USER flows (user-work-pool / K8s Job): K8s operations only (create CRD,
poll Velero status, return result).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from prefect import flow, task
from prefect.logging import get_run_logger
from prefect.client.schemas.objects import StateType
from prefect.deployments.flow_runs import arun_deployment
from prefect.runtime import flow_run as flow_run_ctx
from prefect.variables import Variable

from styrmin_backend import config
from styrmin_backend.agent.tasks.shared import POLL_INTERVAL, POLL_RETRY_DELAY_SECONDS
from styrmin_backend.agent.service.kubernetes.resources.builders.backup import (
    build_velero_backup,
    build_velero_restore,
)
from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackupHook,
    VeleroRestoreHook,
)
from styrmin_backend.db.models import BackupStatus, RestoreStatus
from styrmin_backend.services.backup.metadata import (
    BackupMetadata,
    read_backup_metadata,
)
from styrmin_backend.services.backup.service import (
    get_backup,
    get_strategy,
    update_backup_status,
    update_restore_status,
)
from styrmin_backend.services.backup.ttl import (
    DEFAULT_BACKUP_TTL,
    resolve_backup_ttl,
)
from styrmin_backend.services.unit_of_work import get_unit_of_work


# ---------------------------------------------------------------------------
# Shared task (pure Python, no K8s access needed)
# ---------------------------------------------------------------------------


@task(task_run_name="Build backup hooks for {component_name}")
def build_component_hooks(
    namespace: str,
    component_name: str,
    component_config: dict[str, Any],
) -> list[VeleroBackupHook]:
    """Build Velero hooks for a single component."""
    kind = component_config.get("kind", "disk")
    strategy = get_strategy(kind)
    return strategy.get_hooks(
        namespace=namespace,
        component_name=component_name,
        config=component_config,
    )


@task(task_run_name="Build restore hooks for {component_name}")
def build_component_restore_hooks(
    namespace: str,
    component_name: str,
    component_config: dict[str, Any],
) -> list[VeleroRestoreHook]:
    """Build Velero restore hooks for a single component."""
    kind = component_config.get("kind", "disk")
    strategy = get_strategy(kind)
    return strategy.get_restore_hooks(
        namespace=namespace,
        component_name=component_name,
        config=component_config,
    )


# ---------------------------------------------------------------------------
# USER flows (user-work-pool, K8s Job — has in-cluster access)
# ---------------------------------------------------------------------------


@flow(name="execute_velero_backup")
async def execute_velero_backup_flow(
    crd_body: dict[str, Any],
    velero_backup_name: str,
    velero_namespace: str,
    timeout: int = 3600,
) -> dict[str, Any]:
    """Create a Velero Backup CRD and poll until completion.

    Runs in the user-work-pool (K8s Job) with in-cluster access.

    Args:
        crd_body: Pre-rendered Velero Backup CRD dict.
        velero_backup_name: Name of the Velero backup resource.
        velero_namespace: Namespace where Velero resources live.
        timeout: Maximum seconds to wait for backup completion.

    Returns:
        The final Velero Backup resource dict from the K8s API.
    """
    from kubernetes_asyncio import client as k8s_client

    from styrmin_backend.agent.service.kubernetes.dependency import (
        load_kubernetes_config,
    )
    from styrmin_backend.agent.service.kubernetes.velero.client import VeleroClient

    await load_kubernetes_config()
    api_client = k8s_client.ApiClient()

    try:
        logger = get_run_logger()
        client = VeleroClient(api_client=api_client)
        await client.create_backup_from_dict(crd_body)
        logger.info(
            f"Created Velero Backup CRD {velero_backup_name} "
            f"in namespace {velero_namespace}"
        )
        result = await client.poll_backup_status(
            name=velero_backup_name,
            namespace=velero_namespace,
            timeout=timeout,
            interval=POLL_RETRY_DELAY_SECONDS,
        )

        # Store result for cross-worker retrieval via Prefect Variable
        status = result.get("status", {})
        await Variable.set(  # type: ignore[misc]
            name=f"velero-result-{flow_run_ctx.id}",
            value={
                "status": {
                    "phase": status.get("phase", ""),
                    "failureReason": status.get("failureReason", ""),
                    "backupItemOperationsCompleted": status.get(
                        "backupItemOperationsCompleted"
                    ),
                    # Velero's own expiration timestamp (creation + spec.ttl),
                    # recorded on the backup record so operators can read
                    # "when does this disappear?" without cluster access.
                    # Set for every backup Velero actually stored, which
                    # includes the PartiallyFailed phase. Absent on a Failed
                    # backup — nothing was stored, so nothing expires.
                    "expiration": status.get("expiration"),
                }
            },
            overwrite=True,
        )

        return result
    finally:
        await api_client.close()


@flow(name="execute_velero_restore")
async def execute_velero_restore_flow(
    crd_body: dict[str, Any],
    velero_restore_name: str,
    velero_namespace: str,
    target_namespace: str,
    timeout: int = 7200,
) -> dict[str, Any]:
    """Create a Velero Restore CRD and poll until completion.

    Deletes the target namespace first (if it exists) to ensure a clean
    deployment state, then creates the Velero Restore CRD.

    Runs in the user-work-pool (K8s Job) with in-cluster access.

    Args:
        crd_body: Pre-rendered Velero Restore CRD dict.
        velero_restore_name: Name of the Velero restore resource.
        velero_namespace: Namespace where Velero resources live.
        target_namespace: K8s namespace to delete before restoring.
        timeout: Maximum seconds to wait for restore completion.

    Returns:
        The final Velero Restore resource dict from the K8s API.
    """
    import asyncio

    from kubernetes_asyncio import client as k8s_client

    from styrmin_backend.agent.service.kubernetes.dependency import (
        load_kubernetes_config,
    )
    from styrmin_backend.agent.service.kubernetes.velero.client import VeleroClient

    await load_kubernetes_config()
    api_client = k8s_client.ApiClient()

    try:
        logger = get_run_logger()

        # Delete target namespace to ensure a clean restore
        core_v1 = k8s_client.CoreV1Api(api_client)
        try:
            await core_v1.delete_namespace(name=target_namespace)
            logger.info(f"Requested deletion of namespace {target_namespace}")
        except k8s_client.ApiException as exc:
            if exc.status != 404:
                raise
            logger.info(
                f"Namespace {target_namespace} does not exist, skipping deletion"
            )

        # Poll until the namespace is gone (404) or timeout. Heavy
        # multi-component deployments (e.g. the Infrahub stack: Neo4j alone
        # ships a 3600s terminationGracePeriod, plus several StatefulSets and
        # PVCs whose volume teardown adds up) can take well over 5 minutes to
        # fully terminate, so allow generous headroom — the overall restore
        # flow budget is 7200s.
        ns_timeout = 600
        poll_interval = POLL_RETRY_DELAY_SECONDS
        elapsed = 0
        while elapsed < ns_timeout:
            try:
                await core_v1.read_namespace(name=target_namespace)
            except k8s_client.ApiException as exc:
                if exc.status == 404:
                    logger.info(f"Namespace {target_namespace} deleted")
                    break
                raise
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        else:
            raise RuntimeError(
                f"Namespace {target_namespace} was not deleted within {ns_timeout}s"
            )

        client = VeleroClient(api_client=api_client)
        await client.create_restore_from_dict(crd_body)
        logger.info(
            f"Created Velero Restore CRD {velero_restore_name} "
            f"in namespace {velero_namespace}"
        )
        result = await client.poll_restore_status(
            name=velero_restore_name,
            namespace=velero_namespace,
            timeout=timeout,
            interval=POLL_RETRY_DELAY_SECONDS,
        )

        # Post-velero recovery: claim the CRD's lifecycle, strip kopf
        # state annotations so on.create/on.resume can fire correctly in
        # the future, and re-apply prerequisites + utility resources so
        # NetworkPolicies / Secrets / Middlewares / Services converge.
        # Velero restored the CRD without status, so the operator's timer
        # would otherwise trip its 300 s readiness timeout — see
        # operator/restore_recovery.py for the contract.
        from styrmin_backend.operator.restore_recovery import (
            mark_failed,
            mark_restoring,
            reapply_and_finalize,
        )

        velero_status = result.get("status", {})
        velero_phase = velero_status.get("phase", "")
        # CRD name matches the target namespace (one StyrminDeployment per
        # deployment namespace).
        crd_name = target_namespace

        recovery_status: dict[str, Any] = {"recovered": False, "error": None}
        if velero_phase == "Completed":
            try:
                await mark_restoring(api_client, target_namespace, crd_name)
                await reapply_and_finalize(api_client, target_namespace, crd_name)
                recovery_status["recovered"] = True
            except Exception as exc:
                error_msg = f"Restore reapply failed: {exc}"
                logger.error(error_msg)
                await mark_failed(api_client, target_namespace, crd_name, error_msg)
                recovery_status["error"] = error_msg
        else:
            failure_reason = velero_status.get("failureReason") or (
                f"Velero restore phase: {velero_phase}"
            )
            await mark_failed(
                api_client,
                target_namespace,
                crd_name,
                f"Velero restore failed: {failure_reason}",
            )

        # Store result for cross-worker retrieval via Prefect Variable
        await Variable.set(  # type: ignore[misc]
            name=f"velero-result-{flow_run_ctx.id}",
            value={
                "status": {
                    "phase": velero_phase,
                    "failureReason": velero_status.get("failureReason", ""),
                },
                "recovery": recovery_status,
            },
            overwrite=True,
        )

        return result
    finally:
        await api_client.close()


# ---------------------------------------------------------------------------
# INTERNAL flows (styrmin-work-pool, no K8s access)
# ---------------------------------------------------------------------------


@flow(name="execute_backup")
async def execute_backup_workflow(
    backup_id: str,
    deployment_id: str,
) -> None:
    """Execute a backup operation: build Velero CRD, dispatch USER flow, update status.

    Runs on styrmin-work-pool (process type, no K8s access). Delegates the
    actual K8s operations to the ``execute_velero_backup`` USER flow via
    ``arun_deployment``.

    Args:
        backup_id: The Styrmin backup record ID (passed as string for serialization).
        deployment_id: The Styrmin deployment ID.
    """
    backup_uuid = UUID(backup_id)
    deployment_uuid = UUID(deployment_id)

    config.SETTINGS.initialize_and_exit()

    logger = get_run_logger()
    uow = await get_unit_of_work()

    try:
        # Mark as in-progress
        await update_backup_status(
            backup_id=backup_uuid,
            status=BackupStatus.IN_PROGRESS,
            uow=uow,
        )

        # Fetch backup record for names
        uow = await get_unit_of_work()
        backup = await get_backup(backup_uuid, uow)
        velero_backup_name = backup.name
        target_namespace = f"styrmin-{deployment_uuid}"
        velero_namespace = "styrmin"

        # Resolve BSL from deployment -> environment -> backup_storage_location,
        # and read the three scopes' config for retention resolution below.
        storage_location: str | None = None
        deployment_config: dict[str, Any] | None = None
        environment_config: dict[str, Any] | None = None
        cluster_config: dict[str, Any] | None = None
        config_read_failed = False
        # The first of the three lookups that came back empty, if any. A
        # ``None`` row is NOT an exception, so without this the flag above stays
        # False, every scope stays None, and the backup silently takes the
        # built-in default with ``ttl_source: "default"`` — indistinguishable
        # from a deployment that genuinely has no retention policy anywhere.
        # Each lookup reaches the next one *through* its result, so a missing
        # row hides its own scope and every shallower scope with it.
        missing_scope: str | None = None
        try:
            uow = await get_unit_of_work()
            async with uow:
                deployment = await uow.deployments.find(deployment_uuid)
                if deployment is None:
                    missing_scope = "deployment"
                else:
                    deployment_config = deployment.config
                    env = await uow.environments.get(deployment.environment_id)
                    if env is None:
                        missing_scope = "environment"
                    else:
                        environment_config = env.config
                        # Assign the BSL from the environment BEFORE reading the
                        # cluster. This block swallows every exception, so a
                        # failing cluster read (pool timeout, connection reset)
                        # would otherwise skip a not-yet-executed assignment and
                        # silently divert the backup to the cluster-default BSL
                        # even though the environment's BSL was already known.
                        if env.backup_storage_location:
                            storage_location = (
                                f"styrmin-bsl-{env.backup_storage_location.name}"
                            )
                            logger.info(
                                f"Using BSL '{storage_location}' "
                                f"for backup {backup_uuid}"
                            )
                        cluster = await uow.clusters.get(env.cluster_id)
                        if cluster is None:
                            missing_scope = "cluster"
                        else:
                            cluster_config = cluster.config
        except Exception as exc:
            config_read_failed = True
            logger.warning(
                f"Failed to resolve BSL for backup {backup_uuid}, "
                "using cluster default",
                exc_info=exc,
            )

        # Resolve retention deliberately OUTSIDE the block above: that block
        # swallows every exception to keep BSL resolution best-effort, and
        # retention must never be quietly reduced to the built-in default by a
        # failure it hid. On a failed config read the scopes are all None, so
        # resolution yields the built-in default — and says so at WARNING.
        ttl, ttl_source = resolve_backup_ttl(
            deployment_config=deployment_config,
            environment_config=environment_config,
            cluster_config=cluster_config,
        )
        if config_read_failed and ttl_source == "default":
            logger.warning(
                f"Backup {backup_uuid}: config read failed, so any configured "
                f"backup_ttl policy was invisible to this backup — applying "
                f"the built-in {DEFAULT_BACKUP_TTL} default instead"
            )
        elif config_read_failed:
            # The read got far enough to hand us a scope value before it threw,
            # so the built-in default was NOT applied. Say which scope supplied
            # the TTL and flag that a deeper scope may have been missed, rather
            # than claiming a default that the INFO line below contradicts.
            logger.warning(
                f"Backup {backup_uuid}: config read failed part-way, so a "
                f"deeper backup_ttl policy may have been invisible to this "
                f"backup — applying {ttl} from {ttl_source} scope, which was "
                f"read before the failure"
            )
        if missing_scope is not None:
            # Reported independently of ``config_read_failed``: a row that is
            # simply not there raises nothing, so the flag above never sees it.
            # Without this line the only trace is the routine INFO below, which
            # reads exactly like a deployment that never set a policy — e.g. a
            # deployment row deleted between backup-record creation and workflow
            # start silently ignores the environment's configured retention.
            logger.warning(
                f"Backup {backup_uuid}: the {missing_scope} lookup returned no "
                f"row, so no backup_ttl policy at {missing_scope} scope or "
                f"shallower could be read for this backup — applying {ttl} "
                f"from {ttl_source} scope"
            )
        logger.info(
            f"resolved backup TTL {ttl} from {ttl_source} scope "
            f"for backup {backup_uuid}"
        )

        # Record the applied retention + its provenance before the Velero
        # object is built, so the audit trail survives a later failure.
        uow = await get_unit_of_work()
        await update_backup_status(
            backup_id=backup_uuid,
            status=BackupStatus.IN_PROGRESS,
            uow=uow,
            metadata_updates={"ttl": ttl, "ttl_source": ttl_source},
        )

        # Build hooks from component configs
        hooks: list[VeleroBackupHook] = []
        if backup.component_statuses:
            for comp_name, comp_data in backup.component_statuses.items():
                if isinstance(comp_data, dict):
                    comp_hooks = build_component_hooks(
                        namespace=target_namespace,
                        component_name=comp_name,
                        component_config=comp_data,
                    )
                    hooks.extend(comp_hooks)

        # Build Velero backup CRD and pre-render to dict
        velero_backup = build_velero_backup(
            name=velero_backup_name,
            velero_namespace=velero_namespace,
            target_namespace=target_namespace,
            instance_id=str(backup.instance_id),
            driver_name="styrmin",
            ttl=ttl,
            hooks=hooks,
            storage_location=storage_location,
        )
        crd_body = velero_backup.render()

        # Determine timeout
        timeout = 3600
        if backup.metadata_ and isinstance(backup.metadata_, dict):
            timeout = read_backup_metadata(backup.metadata_).get("timeout", 3600)

        # Dispatch to USER flow (K8s Job with in-cluster access)
        flow_run = await arun_deployment(
            name="execute_velero_backup/execute_velero_backup",
            parameters={
                "crd_body": crd_body,
                "velero_backup_name": velero_backup_name,
                "velero_namespace": velero_namespace,
                "timeout": timeout,
            },
            poll_interval=POLL_INTERVAL,
        )

        # Read result from the USER flow
        if not flow_run.state:
            raise RuntimeError("Unable to read state from the Velero backup flow run")

        if flow_run.state.type == StateType.CRASHED:
            raise RuntimeError(flow_run.state.message)

        if flow_run.state.is_failed():
            raise RuntimeError(f"Velero backup flow failed: {flow_run.state.message}")

        # Retrieve result via Prefect Variable (cross-worker channel)
        result_data = await Variable.get(  # type: ignore[misc]
            f"velero-result-{flow_run.id}"
        )
        if result_data is None or not isinstance(result_data, dict):
            raise RuntimeError(
                "Velero backup flow completed but result data is missing"
            )
        result: dict[str, Any] = result_data

        # Clean up the temporary variable
        await Variable.unset(f"velero-result-{flow_run.id}")  # type: ignore[misc]

        # Update status based on Velero phase
        status = result.get("status", {})
        velero_phase = status.get("phase", "")

        # Velero reports an expiration only for backups it actually stored, so
        # a Failed one carries none and the record simply has no
        # ``expires_at`` (GraphQL null → "—" in the UI and CLI). Recorded on
        # both branches: a PartiallyFailed backup is stored and does expire,
        # and this workflow folds it into the FAILED branch.
        #
        # The rename is deliberate and is why ``metadata_updates`` is typed:
        # Velero spells this ``expiration`` (and so does the Prefect Variable
        # payload above), the persisted key is ``expires_at``, and carrying the
        # upstream spelling through here would leave ``Backup.expiresAt`` null
        # forever. ``BackupMetadata`` turns that into a type error.
        expiration = status.get("expiration")
        metadata_updates: BackupMetadata | None = (
            {"expires_at": expiration} if expiration else None
        )

        uow = await get_unit_of_work()
        if velero_phase == "Completed":
            size_bytes = status.get("backupItemOperationsCompleted")
            await update_backup_status(
                backup_id=backup_uuid,
                status=BackupStatus.COMPLETED,
                uow=uow,
                size_bytes=size_bytes,
                metadata_updates=metadata_updates,
            )
            if not expiration:
                # A stored backup always expires, so a Completed phase without
                # ``status.expiration`` means we silently lost FR-006's expiry
                # record. Say so — the Failed case below is expected and stays
                # quiet, this one is not.
                logger.warning(
                    f"Backup {backup_uuid} completed but Velero reported no "
                    "status.expiration, so no expiry was recorded — the UI and "
                    "CLI will show no expiry date for a backup that does expire"
                )
            logger.info(f"Backup {backup_uuid} completed successfully")
        else:
            error_msg = status.get(
                "failureReason", f"Velero backup phase: {velero_phase}"
            )
            await update_backup_status(
                backup_id=backup_uuid,
                status=BackupStatus.FAILED,
                uow=uow,
                error_message=error_msg,
                metadata_updates=metadata_updates,
            )
            logger.error(f"Backup {backup_uuid} failed: {error_msg}")

    except Exception as e:
        logger.error(f"Backup {backup_uuid} failed: {e}")
        uow = await get_unit_of_work()
        await update_backup_status(
            backup_id=backup_uuid,
            status=BackupStatus.FAILED,
            uow=uow,
            error_message=str(e),
        )
        raise


@flow(name="execute_restore")
async def execute_restore_workflow(
    restore_id: str,
    backup_id: str,
    deployment_id: str,
    target_namespace: str,
) -> None:
    """Execute a restore operation: build Velero CRD, dispatch USER flow, update status.

    Runs on styrmin-work-pool (process type, no K8s access). Delegates the
    actual K8s operations to the ``execute_velero_restore`` USER flow via
    ``arun_deployment``.

    Args:
        restore_id: The Styrmin restore record ID (passed as string for serialization).
        backup_id: The Styrmin backup ID.
        deployment_id: The Styrmin deployment ID.
        target_namespace: The target Kubernetes namespace for the restore.
    """
    restore_uuid = UUID(restore_id)
    backup_uuid = UUID(backup_id)

    config.SETTINGS.initialize_and_exit()

    logger = get_run_logger()
    uow = await get_unit_of_work()

    try:
        # Mark as in-progress
        await update_restore_status(
            restore_id=restore_uuid,
            status=RestoreStatus.IN_PROGRESS,
            uow=uow,
        )

        # Fetch backup to get Velero backup name
        uow = await get_unit_of_work()
        backup = await get_backup(backup_uuid, uow)
        velero_backup_name = backup.name

        # Fetch restore for names
        from styrmin_backend.services.backup.service import get_restore

        uow = await get_unit_of_work()
        restore = await get_restore(restore_uuid, uow)
        velero_restore_name = restore.name

        velero_namespace = "styrmin"
        source_namespace = f"styrmin-{deployment_id}"

        # Build restore hooks from backup's component configs
        restore_hooks: list[VeleroRestoreHook] = []
        if backup.component_statuses:
            for comp_name, comp_data in backup.component_statuses.items():
                if isinstance(comp_data, dict):
                    comp_hooks = build_component_restore_hooks(
                        namespace=target_namespace,
                        component_name=comp_name,
                        component_config=comp_data,
                    )
                    restore_hooks.extend(comp_hooks)

        # Build Velero restore CRD and pre-render to dict
        velero_restore = build_velero_restore(
            name=velero_restore_name,
            velero_namespace=velero_namespace,
            backup_name=velero_backup_name,
            source_namespace=source_namespace,
            target_namespace=target_namespace,
            instance_id=str(backup.instance_id),
            driver_name="styrmin",
            existing_resource_policy="update",
            hooks=restore_hooks,
        )
        crd_body = velero_restore.render()

        # Determine timeout
        timeout = 7200
        if restore.metadata_ and isinstance(restore.metadata_, dict):
            timeout = restore.metadata_.get("timeout", 7200)

        # Dispatch to USER flow (K8s Job with in-cluster access)
        flow_run = await arun_deployment(
            name="execute_velero_restore/execute_velero_restore",
            parameters={
                "crd_body": crd_body,
                "velero_restore_name": velero_restore_name,
                "velero_namespace": velero_namespace,
                "target_namespace": target_namespace,
                "timeout": timeout,
            },
            poll_interval=POLL_INTERVAL,
        )

        # Read result from the USER flow
        if not flow_run.state:
            raise RuntimeError("Unable to read state from the Velero restore flow run")

        if flow_run.state.type == StateType.CRASHED:
            raise RuntimeError(flow_run.state.message)

        if flow_run.state.is_failed():
            raise RuntimeError(f"Velero restore flow failed: {flow_run.state.message}")

        # Retrieve result via Prefect Variable (cross-worker channel)
        result_data = await Variable.get(  # type: ignore[misc]
            f"velero-result-{flow_run.id}"
        )
        if result_data is None or not isinstance(result_data, dict):
            raise RuntimeError(
                "Velero restore flow completed but result data is missing"
            )
        result: dict[str, Any] = result_data

        # Clean up the temporary variable
        await Variable.unset(f"velero-result-{flow_run.id}")  # type: ignore[misc]

        # Update status based on Velero phase + post-velero recovery result.
        status = result.get("status", {})
        velero_phase = status.get("phase", "")
        recovery = result.get("recovery", {}) if isinstance(result, dict) else {}

        uow = await get_unit_of_work()
        if velero_phase == "Completed" and recovery.get("recovered"):
            await update_restore_status(
                restore_id=restore_uuid,
                status=RestoreStatus.COMPLETED,
                uow=uow,
            )
            await _set_deployment_status_running(
                deployment_id=UUID(deployment_id), uow=uow
            )
            logger.info(f"Restore {restore_uuid} completed successfully")
        else:
            if velero_phase == "Completed":
                error_msg = (
                    recovery.get("error")
                    or "Velero completed but post-restore reapply failed"
                )
            else:
                error_msg = status.get(
                    "failureReason", f"Velero restore phase: {velero_phase}"
                )
            await update_restore_status(
                restore_id=restore_uuid,
                status=RestoreStatus.FAILED,
                uow=uow,
                error_message=error_msg,
            )
            await _set_deployment_status_failed(
                deployment_id=UUID(deployment_id),
                uow=uow,
                error_message=error_msg,
            )
            logger.error(f"Restore {restore_uuid} failed: {error_msg}")

    except Exception as e:
        logger.error(f"Restore {restore_uuid} failed: {e}")
        uow = await get_unit_of_work()
        await update_restore_status(
            restore_id=restore_uuid,
            status=RestoreStatus.FAILED,
            uow=uow,
            error_message=str(e),
        )
        await _set_deployment_status_failed(
            deployment_id=UUID(deployment_id),
            uow=uow,
            error_message=str(e),
        )
        raise


async def _set_deployment_status_running(deployment_id: UUID, uow: Any) -> None:
    """Move the deployment from RESTORING back to RUNNING after recovery.

    Done inline so the UI sees the transition immediately rather than
    waiting on the next agent status poll. Idempotent — if the deployment
    is already RUNNING (e.g. status reporter beat us to it), this no-ops.
    """
    from styrmin_backend.db.models import DeploymentState

    async with uow:
        deployment = await uow.deployments.find(deployment_id)
        if deployment is None:
            return
        if deployment.status != DeploymentState.RUNNING:
            deployment.status = DeploymentState.RUNNING
            await uow.deployments.save(deployment)
            await uow.commit()


async def _set_deployment_status_failed(
    deployment_id: UUID, uow: Any, error_message: str
) -> None:
    """Move the deployment to FAILED after a restore error.

    The error_message ends up in the deployment_status snapshot via the
    operator's status reporter on the next poll; here we just ensure the
    DB-side status reflects failure immediately.
    """
    from styrmin_backend.db.models import DeploymentState

    async with uow:
        deployment = await uow.deployments.find(deployment_id)
        if deployment is None:
            return
        if deployment.status != DeploymentState.FAILED:
            deployment.status = DeploymentState.FAILED
            await uow.deployments.save(deployment)
            await uow.commit()
