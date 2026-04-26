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
from styrmin_backend.services.backup.service import (
    get_backup,
    get_strategy,
    update_backup_status,
    update_restore_status,
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

        # Poll until the namespace is gone (404) or timeout
        ns_timeout = 300
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

        # Resolve BSL from deployment -> environment -> backup_storage_location
        storage_location: str | None = None
        try:
            uow = await get_unit_of_work()
            async with uow:
                deployment = await uow.deployments.find(deployment_uuid)
                if deployment:
                    env = await uow.environments.get(deployment.environment_id)
                    if env and env.backup_storage_location:
                        storage_location = (
                            f"styrmin-bsl-{env.backup_storage_location.name}"
                        )
                        logger.info(
                            f"Using BSL '{storage_location}' for backup {backup_uuid}"
                        )
        except Exception as exc:
            logger.warning(
                f"Failed to resolve BSL for backup {backup_uuid}, "
                "using cluster default",
                exc_info=exc,
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
            hooks=hooks,
            storage_location=storage_location,
        )
        crd_body = velero_backup.render()

        # Determine timeout
        timeout = 3600
        if backup.metadata_ and isinstance(backup.metadata_, dict):
            timeout = backup.metadata_.get("timeout", 3600)

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

        uow = await get_unit_of_work()
        if velero_phase == "Completed":
            size_bytes = status.get("backupItemOperationsCompleted")
            await update_backup_status(
                backup_id=backup_uuid,
                status=BackupStatus.COMPLETED,
                uow=uow,
                size_bytes=size_bytes,
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
