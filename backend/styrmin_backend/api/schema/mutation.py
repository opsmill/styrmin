"""Provides the schema for the GraphQL API.

This is where the different routes and their types are defined.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import strawberry
from loguru import logger

from styrmin_backend.api.definitions.backup.backup import Backup as BackupType
from styrmin_backend.api.definitions.backup.environment_backup import (
    EnvironmentBackup as EnvironmentBackupType,
    EnvironmentRestore as EnvironmentRestoreType,
)
from styrmin_backend.api.definitions.backup.restore import Restore as RestoreType
from styrmin_backend.api.definitions.backup.schedule import (
    BackupSchedule as BackupScheduleType,
)
from styrmin_backend.api.definitions.application_driver.model import (
    ApplicationDriverVersion,
)
from styrmin_backend.api.definitions.backup_storage_location.model import (
    BackupStorageLocation as BackupStorageLocationType,
)
from styrmin_backend.api.definitions.callback.model import CallbackResponse
from styrmin_backend.api.definitions.pod_status.model import (
    DeploymentPodStatusReport,
    ReportPodStatusesResponse,
)
from styrmin_backend.api.definitions.deployment_status.model import (
    DeploymentStatusReportInput,
    ReportDeploymentStatusesResponse,
)
from styrmin_backend.api.definitions.cluster.model import Cluster
from styrmin_backend.api.definitions.environment.model import Environment
from styrmin_backend.api.definitions.service.model import ServiceNameOverride
from styrmin_backend.api.definitions.task.model import Task
from styrmin_backend.api.scalars import JSON
from styrmin_backend.services.applications import (
    load_application_driver_from_git_repository,
    load_application_driver_from_local_directory,
)
from styrmin_backend.services.backup_storage_locations import (
    assign_backup_storage_location as assign_bsl_service,
    create_backup_storage_location as create_bsl_service,
    delete_backup_storage_location as delete_bsl_service,
    unassign_backup_storage_location as unassign_bsl_service,
    update_backup_storage_location as update_bsl_service,
)
from styrmin_backend.services.clusters import (
    create_cluster,
    delete_cluster,
    resolve_cluster,
)
from styrmin_backend.services.deployment import (
    deploy_application,
    update_deployment,
    update_deployment_version,
)
from styrmin_backend.services.environments import (
    create_environment,
    delete_environment,
    resolve_environment,
)
from styrmin_backend.services.backup.scheduler import (
    create_backup_schedule as create_backup_schedule_service,
    delete_backup_schedule as delete_backup_schedule_service,
    update_backup_schedule as update_backup_schedule_service,
)
from styrmin_backend.services.backup.environment import (
    create_environment_backup as create_env_backup_service,
    create_environment_restore as create_env_restore_service,
    delete_environment_backup as delete_env_backup_service,
)
from styrmin_backend.services.backup.service import (
    create_backup as create_backup_service,
    create_restore as create_restore_service,
    delete_backup as delete_backup_service,
)
from styrmin_backend.services.deployment import get_deployment
from styrmin_backend.services.exceptions import (
    InternalDeploymentError,
    TaskNotFoundError,
)
from styrmin_backend.services.primitives import (
    run_job,
    start_components,
    stop_components,
)
from styrmin_backend.services.deployment_status import (
    report_deployment_statuses,
)
from styrmin_backend.services.pod_status import report_pod_statuses
from styrmin_backend.services.tasks import update_task_state
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.models import PrefectAction


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_cluster(
        self, info: strawberry.Info, name: str = "default", config: JSON | None = None
    ) -> Cluster | None:
        uow = info.context["uow"]
        cluster = await create_cluster(uow=uow, name=name, config=config)
        return Cluster.from_instance(cluster)

    @strawberry.mutation
    async def delete_cluster(
        self,
        info: strawberry.Info,
        cluster_id: UUID | None = None,
        cluster_name: str | None = None,
    ) -> str | None:
        uow = info.context["uow"]
        cluster = await resolve_cluster(
            uow, cluster_id=cluster_id, cluster_name=cluster_name
        )
        await delete_cluster(cluster_id=cluster.id, uow=uow)
        return "Cluster deleted"

    @strawberry.mutation
    async def create_environment(
        self,
        name: str,
        info: strawberry.Info,
        cluster_id: UUID | None = None,
        cluster_name: str | None = None,
        config: JSON | None = None,
    ) -> Environment | None:
        uow = info.context["uow"]
        cluster = await resolve_cluster(
            uow, cluster_id=cluster_id, cluster_name=cluster_name
        )
        environment = await create_environment(
            name=name, cluster_id=cluster.id, config=config, uow=uow
        )
        return Environment.from_instance(environment)

    @strawberry.mutation
    async def delete_environment(
        self,
        info: strawberry.Info,
        environment_id: UUID | None = None,
        environment_name: str | None = None,
        cluster_id: UUID | None = None,
        cluster_name: str | None = None,
    ) -> str | None:
        uow = info.context["uow"]
        environment = await resolve_environment(
            uow,
            environment_id=environment_id,
            environment_name=environment_name,
            cluster_id=cluster_id,
            cluster_name=cluster_name,
        )
        await delete_environment(environment_id=environment.id, uow=uow)
        return "Environment deleted"

    @strawberry.mutation
    async def create_backup_storage_location(
        self,
        name: str,
        endpoint: str,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        info: strawberry.Info,
    ) -> BackupStorageLocationType | None:
        uow = info.context["uow"]
        bsl = await create_bsl_service(
            name=name,
            endpoint=endpoint,
            bucket=bucket,
            region=region,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            uow=uow,
        )
        return BackupStorageLocationType.from_instance(bsl)

    @strawberry.mutation
    async def update_backup_storage_location(
        self,
        backup_storage_location_id: UUID,
        info: strawberry.Info,
        name: str | None = None,
        endpoint: str | None = None,
        bucket: str | None = None,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> BackupStorageLocationType | None:
        uow = info.context["uow"]
        bsl = await update_bsl_service(
            backup_storage_location_id=backup_storage_location_id,
            uow=uow,
            name=name,
            endpoint=endpoint,
            bucket=bucket,
            region=region,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )

        # Sync credentials to all clusters where this BSL is deployed
        credentials_changed = access_key_id is not None or secret_access_key is not None
        if credentials_changed and bsl.environments:
            try:
                cluster_ids = {env.cluster_id for env in bsl.environments}
                prefect_manager = get_manager()
                for _cluster_id in cluster_ids:
                    await prefect_manager.run_action(
                        action=PrefectAction.SYNC_BSL_UPDATE_CREDENTIALS,
                        parameters={
                            "bsl_name": bsl.name,
                            "namespace": "styrmin",
                            "access_key_id": bsl.access_key_id,
                            "secret_access_key": bsl.secret_access_key,
                        },
                    )
            except Exception as exc:
                logger.warning(
                    f"Failed to dispatch BSL credentials update workflow for BSL {backup_storage_location_id}",
                    exc_info=exc,
                )

        return BackupStorageLocationType.from_instance(bsl)

    @strawberry.mutation
    async def delete_backup_storage_location(
        self,
        backup_storage_location_id: UUID,
        info: strawberry.Info,
    ) -> str | None:
        uow = info.context["uow"]
        await delete_bsl_service(
            backup_storage_location_id=backup_storage_location_id, uow=uow
        )
        return "Backup storage location deleted"

    @strawberry.mutation
    async def assign_backup_storage_location(
        self,
        environment_id: UUID,
        backup_storage_location_id: UUID,
        info: strawberry.Info,
    ) -> Environment | None:
        uow = info.context["uow"]

        # Capture previous BSL before reassignment
        old_bsl_id: UUID | None = None
        old_bsl_name: str | None = None
        cluster_id: UUID | None = None
        async with uow:
            env = await uow.environments.get(environment_id)
            if env:
                old_bsl_id = env.backup_storage_location_id
                cluster_id = env.cluster_id
                if old_bsl_id:
                    old_bsl = await uow.backup_storage_locations.get(old_bsl_id)
                    if old_bsl:
                        old_bsl_name = old_bsl.name

        await assign_bsl_service(
            environment_id=environment_id,
            backup_storage_location_id=backup_storage_location_id,
            uow=uow,
        )

        # Dispatch BSL sync flows
        try:
            async with uow:
                env = await uow.environments.get(environment_id)
                bsl = await uow.backup_storage_locations.get(backup_storage_location_id)
                if env and bsl and cluster_id:
                    # Check if this is the first env on the cluster referencing this BSL
                    other_envs_on_cluster = [
                        e
                        for e in bsl.environments
                        if e.cluster_id == cluster_id and e.id != environment_id
                    ]
                    if not other_envs_on_cluster:
                        prefect_manager = get_manager()
                        await prefect_manager.run_action(
                            action=PrefectAction.SYNC_BSL_CREATE,
                            parameters={
                                "bsl_id": str(bsl.id),
                                "bsl_name": bsl.name,
                                "namespace": "styrmin",
                                "bucket": bsl.bucket,
                                "region": bsl.region,
                                "endpoint": bsl.endpoint,
                                "access_key_id": bsl.access_key_id,
                                "secret_access_key": bsl.secret_access_key,
                            },
                        )

                    # Handle reassignment: delete old BSL from cluster if it was the last reference
                    if (
                        old_bsl_id
                        and old_bsl_id != backup_storage_location_id
                        and old_bsl_name
                    ):
                        old_bsl = await uow.backup_storage_locations.get(old_bsl_id)
                        if old_bsl:
                            old_remaining = [
                                e
                                for e in old_bsl.environments
                                if e.cluster_id == cluster_id
                            ]
                            if not old_remaining:
                                prefect_manager = get_manager()
                                await prefect_manager.run_action(
                                    action=PrefectAction.SYNC_BSL_DELETE,
                                    parameters={
                                        "bsl_name": old_bsl_name,
                                        "namespace": "styrmin",
                                    },
                                )
        except Exception as exc:
            logger.warning(
                f"Failed to dispatch BSL sync workflow for environment {environment_id}",
                exc_info=exc,
            )

        from styrmin_backend.services.environments import get_environment

        environment = await get_environment(environment_id=environment_id, uow=uow)
        return Environment.from_instance(environment)

    @strawberry.mutation
    async def unassign_backup_storage_location(
        self,
        environment_id: UUID,
        info: strawberry.Info,
    ) -> Environment | None:
        uow = info.context["uow"]

        # Capture current BSL info before unassigning
        bsl_name: str | None = None
        cluster_id: UUID | None = None
        is_last_on_cluster = False
        async with uow:
            env = await uow.environments.get(environment_id)
            if env and env.backup_storage_location_id:
                cluster_id = env.cluster_id
                bsl = await uow.backup_storage_locations.get(
                    env.backup_storage_location_id
                )
                if bsl:
                    bsl_name = bsl.name
                    other_envs_on_cluster = [
                        e
                        for e in bsl.environments
                        if e.cluster_id == cluster_id and e.id != environment_id
                    ]
                    is_last_on_cluster = len(other_envs_on_cluster) == 0

        await unassign_bsl_service(environment_id=environment_id, uow=uow)

        # Delete BSL from cluster if this was the last environment referencing it
        if is_last_on_cluster and bsl_name:
            try:
                prefect_manager = get_manager()
                await prefect_manager.run_action(
                    action=PrefectAction.SYNC_BSL_DELETE,
                    parameters={
                        "bsl_name": bsl_name,
                        "namespace": "styrmin",
                    },
                )
            except Exception as exc:
                logger.warning(
                    f"Failed to dispatch BSL delete workflow for environment {environment_id}",
                    exc_info=exc,
                )

        from styrmin_backend.services.environments import get_environment

        environment = await get_environment(environment_id=environment_id, uow=uow)
        return Environment.from_instance(environment)

    @strawberry.mutation
    async def load_local_application_driver_version(
        self, path: str, info: strawberry.Info
    ) -> ApplicationDriverVersion | None:
        uow = info.context["uow"]
        application = await load_application_driver_from_local_directory(
            path=path, uow=uow
        )
        return ApplicationDriverVersion.from_instance(application)

    @strawberry.mutation
    async def load_remote_application_driver_version(
        self, repository_url: str, branch: str, info: strawberry.Info
    ) -> ApplicationDriverVersion | None:
        uow = info.context["uow"]
        application = await load_application_driver_from_git_repository(
            repository_url=repository_url, branch=branch, uow=uow
        )
        return ApplicationDriverVersion.from_instance(application)

    @strawberry.mutation
    async def deploy(
        self,
        driver: str,
        info: strawberry.Info,
        environment_id: UUID | None = None,
        environment_name: str | None = None,
        cluster_id: UUID | None = None,
        cluster_name: str | None = None,
        version: str | None = None,
        name: str | None = None,
        config: JSON | None = None,
        parameters: JSON | None = None,
        service_name_overrides: list[ServiceNameOverride] | None = None,
    ) -> Task | None:
        """Deploy an application in an environment."""
        uow = info.context["uow"]
        environment = await resolve_environment(
            uow,
            environment_id=environment_id,
            environment_name=environment_name,
            cluster_id=cluster_id,
            cluster_name=cluster_name,
        )
        overrides_dict = (
            {o.driver_service_name: o.override_name for o in service_name_overrides}
            if service_name_overrides
            else None
        )
        task = await deploy_application(
            driver_name=driver,
            version=version,
            environment_id=environment.id,
            deployment_config=config,
            deployment_parameters=parameters,
            deployment_name=name,
            service_name_overrides=overrides_dict,
            uow=uow,
        )
        return Task.from_instance(task)

    @strawberry.mutation
    async def update_deployment(
        self,
        deployment_id: UUID,
        info: strawberry.Info,
        name: str | None = None,
        config: JSON | None = None,
        parameters: JSON | None = None,
        service_name_overrides: list[ServiceNameOverride] | None = None,
    ) -> Task | None:
        """Update the configuration and/or name of a deployment."""
        uow = info.context["uow"]
        deployment = await get_deployment(deployment_id=deployment_id, uow=uow)
        if deployment.internal:
            raise InternalDeploymentError()
        overrides_dict = (
            {o.driver_service_name: o.override_name for o in service_name_overrides}
            if service_name_overrides
            else None
        )
        task = await update_deployment(
            deployment_id=deployment_id,
            deployment_config=config,
            deployment_parameters=parameters,
            deployment_name=name,
            service_name_overrides=overrides_dict,
            uow=uow,
        )
        return Task.from_instance(task)

    @strawberry.mutation
    async def create_backup(
        self,
        instance_id: UUID,
        info: strawberry.Info,
        name: str | None = None,
    ) -> BackupType | None:
        """Create a new on-demand backup for an instance."""
        uow = info.context["uow"]

        # Step 1: Resolve component backup configs from the instance's driver version
        component_configs: dict[str, dict[str, Any]] | None = None
        target_namespace = ""
        deployment_id = None

        try:
            from styrmin_backend.db.models import ApplicationInstance

            async with uow:
                instance = await uow.session.get(ApplicationInstance, instance_id)
                if instance:
                    deployment_id = instance.deployment_id
                    target_namespace = (
                        f"styrmin-{deployment_id}" if deployment_id else ""
                    )

                    driver_version = await uow.application_driver_versions.get(
                        instance.application_driver_version_id
                    )
                    if driver_version and driver_version.component_configs:
                        resolved: dict[str, dict[str, Any]] = {}
                        for cc in driver_version.component_configs:
                            backup_raw = cc.config.get("backup")
                            if isinstance(backup_raw, dict) and backup_raw.get(
                                "enabled"
                            ):
                                resolved[cc.name] = backup_raw
                        if resolved:
                            component_configs = resolved
        except Exception as exc:
            logger.warning(
                f"Failed to resolve component configs for instance {instance_id}, "
                "backup will be created without hooks",
                exc_info=exc,
            )

        # Step 2: Create backup with resolved configs
        backup = await create_backup_service(
            instance_id=instance_id,
            name=name,
            uow=uow,
            target_namespace=target_namespace,
            component_configs=component_configs,
        )

        # Step 3: Submit workflow
        try:
            if deployment_id:
                prefect_manager = get_manager()
                await prefect_manager.run_action(
                    action=PrefectAction.EXECUTE_BACKUP,
                    parameters={
                        "backup_id": str(backup.id),
                        "deployment_id": str(deployment_id),
                    },
                )
        except Exception as exc:
            logger.warning(
                f"Failed to submit backup workflow for backup {backup.id}, "
                "backup record created but Velero execution not triggered",
                exc_info=exc,
            )

        return BackupType.from_instance(backup)

    @strawberry.mutation
    async def delete_backup(
        self,
        backup_id: UUID,
        info: strawberry.Info,
    ) -> str | None:
        """Delete a backup and its associated data."""
        uow = info.context["uow"]
        await delete_backup_service(backup_id=backup_id, uow=uow)
        return "Backup deleted"

    @strawberry.mutation
    async def create_restore(
        self,
        backup_id: UUID,
        target_namespace: str,
        info: strawberry.Info,
        target_instance_id: UUID | None = None,
    ) -> RestoreType | None:
        """Create a restore operation from a backup."""
        uow = info.context["uow"]

        restore = await create_restore_service(
            backup_id=backup_id,
            target_namespace=target_namespace,
            target_instance_id=target_instance_id,
            uow=uow,
        )

        # Look up backup -> instance -> deployment to get deployment_id
        try:
            from styrmin_backend.db.models import ApplicationInstance

            async with uow:
                backup_record = await uow.backups.get(backup_id)
                if backup_record:
                    instance_record = await uow.session.get(
                        ApplicationInstance, backup_record.instance_id
                    )
                    if instance_record and instance_record.deployment_id:
                        prefect_manager = get_manager()
                        await prefect_manager.run_action(
                            action=PrefectAction.EXECUTE_RESTORE,
                            parameters={
                                "restore_id": str(restore.id),
                                "backup_id": str(backup_id),
                                "deployment_id": str(instance_record.deployment_id),
                                "target_namespace": target_namespace,
                            },
                        )
        except Exception as exc:
            logger.warning(
                f"Failed to submit restore workflow for restore {restore.id}, "
                "restore record created but Velero execution not triggered",
                exc_info=exc,
            )

        return RestoreType.from_instance(restore)

    @strawberry.mutation
    async def create_backup_schedule(
        self,
        deployment_id: UUID,
        name: str,
        cron_expression: str,
        info: strawberry.Info,
        retention_count: int = 10,
        enabled: bool = True,
    ) -> BackupScheduleType | None:
        """Create a new backup schedule for a deployment."""
        uow = info.context["uow"]
        schedule = await create_backup_schedule_service(
            deployment_id=deployment_id,
            name=name,
            cron_expression=cron_expression,
            retention_count=retention_count,
            enabled=enabled,
            uow=uow,
        )
        return BackupScheduleType.from_instance(schedule)

    @strawberry.mutation
    async def update_backup_schedule(
        self,
        schedule_id: UUID,
        info: strawberry.Info,
        name: str | None = None,
        cron_expression: str | None = None,
        retention_count: int | None = None,
        enabled: bool | None = None,
    ) -> BackupScheduleType | None:
        """Update an existing backup schedule."""
        uow = info.context["uow"]
        schedule = await update_backup_schedule_service(
            schedule_id=schedule_id,
            name=name,
            cron_expression=cron_expression,
            retention_count=retention_count,
            enabled=enabled,
            uow=uow,
        )
        return BackupScheduleType.from_instance(schedule)

    @strawberry.mutation
    async def delete_backup_schedule(
        self,
        schedule_id: UUID,
        info: strawberry.Info,
    ) -> str | None:
        """Delete a backup schedule."""
        uow = info.context["uow"]
        await delete_backup_schedule_service(schedule_id=schedule_id, uow=uow)
        return "Backup schedule deleted"

    @strawberry.mutation
    async def callback(
        self,
        task_id: UUID,
        state_name: str,
        state_message: str | None,
        state_type: str,
        info: strawberry.Info,
    ) -> CallbackResponse:
        logger.info(
            f"Callback triggered from {task_id} with state {state_name}: {state_message} ({state_type})..."
        )
        uow = info.context["uow"]

        try:
            await update_task_state(
                task_id=task_id,
                state_name=state_name,
                state_message=state_message,
                uow=uow,
            )
        except TaskNotFoundError as e:
            logger.error(f"Task not found: {e}")
            return CallbackResponse(
                message=f"Task not found: {e}",
                success=False,
            )
        return CallbackResponse(
            message=f"Callback triggered from {task_id} with state {state_name}: {state_message} ({state_type})..."
        )

    @strawberry.mutation
    async def stop_components(
        self,
        deployment_id: UUID,
        components: list[str],
        info: strawberry.Info,
    ) -> Task | None:
        """Stop the components of an application instance."""
        uow = info.context["uow"]
        task = await stop_components(
            deployment_id=deployment_id,
            components=components,
            uow=uow,
        )
        return Task.from_instance(task)

    @strawberry.mutation
    async def start_components(
        self,
        deployment_id: UUID,
        components: list[str],
        info: strawberry.Info,
    ) -> Task | None:
        """Start the components of an application instance."""
        uow = info.context["uow"]
        task = await start_components(
            deployment_id=deployment_id,
            components=components,
            uow=uow,
        )
        return Task.from_instance(task)

    @strawberry.mutation
    async def run_job(
        self,
        deployment_id: UUID,
        commands: list[str],
        env: list[JSON],
        image: str,
        info: strawberry.Info,
    ) -> Task | None:
        """Run a job in the context of an application instance."""
        uow = info.context["uow"]
        task = await run_job(
            deployment_id=deployment_id,
            commands=commands,
            env=env,
            image=image,
            uow=uow,
        )
        return Task.from_instance(task)

    @strawberry.mutation
    async def update_deployment_version(
        self,
        deployment_id: UUID,
        version: str,
        info: strawberry.Info,
        parameters: JSON | None = None,
    ) -> Task | None:
        """Update the version of an application instance."""
        uow = info.context["uow"]
        deployment = await get_deployment(deployment_id=deployment_id, uow=uow)
        if deployment.internal:
            raise InternalDeploymentError()
        task = await update_deployment_version(
            deployment_id=deployment_id,
            deployment_parameters=parameters,
            version=version,
            uow=uow,
        )
        return Task.from_instance(task)

    @strawberry.mutation
    async def report_pod_statuses(
        self,
        reports: list[DeploymentPodStatusReport],
        info: strawberry.Info,
    ) -> ReportPodStatusesResponse:
        """Report pod statuses from the agent. Upserts pods and removes stale ones."""
        uow = info.context["uow"]

        report_dicts = [
            {
                "deployment_id": report.deployment_id,
                "pods": [
                    {
                        "pod_name": pod.pod_name,
                        "namespace": pod.namespace,
                        "phase": pod.phase.value,
                        "ready": pod.ready,
                        "restart_count": pod.restart_count,
                        "container_statuses": pod.container_statuses,
                        "node_name": pod.node_name,
                        "started_at": pod.started_at,
                    }
                    for pod in report.pods
                ],
            }
            for report in reports
        ]

        total_updated, total_removed = await report_pod_statuses(
            reports=report_dicts,
            uow=uow,
        )

        return ReportPodStatusesResponse(
            success=True,
            message=f"Updated {total_updated} pods, removed {total_removed} stale pods",
            pods_updated=total_updated,
            pods_removed=total_removed,
        )

    @strawberry.mutation
    async def report_deployment_statuses(
        self,
        reports: list[DeploymentStatusReportInput],
        info: strawberry.Info,
    ) -> ReportDeploymentStatusesResponse:
        """Report deployment statuses from the agent. Upserts status snapshot and updates Deployment state."""
        uow = info.context["uow"]

        report_dicts = [
            {
                "deployment_id": report.deployment_id,
                "instance_id": report.instance_id,
                "phase": report.phase,
                "display_state": report.display_state,
                "message": report.message,
                "conditions": (
                    [
                        {
                            "type": c.type,
                            "status": c.status,
                            "reason": c.reason,
                            "message": c.message,
                            "lastTransitionTime": (
                                c.last_transition_time.isoformat()
                                if c.last_transition_time
                                else None
                            ),
                        }
                        for c in report.conditions
                    ]
                    if report.conditions
                    else None
                ),
                "managed_resource_counts": (
                    {
                        "networkPolicies": report.managed_resource_counts.network_policies,
                        "secrets": report.managed_resource_counts.secrets,
                        "helmReleases": report.managed_resource_counts.helm_releases,
                        "services": report.managed_resource_counts.services,
                        "middlewares": report.managed_resource_counts.middlewares,
                    }
                    if report.managed_resource_counts
                    else None
                ),
            }
            for report in reports
        ]

        statuses_updated, deployments_updated = await report_deployment_statuses(
            reports=report_dicts,
            uow=uow,
        )

        return ReportDeploymentStatusesResponse(
            success=True,
            message=f"Updated {statuses_updated} status snapshots, {deployments_updated} deployment states synced",
            statuses_updated=statuses_updated,
            deployments_updated=deployments_updated,
        )

    # ---- Environment Backup/Restore Mutations ----

    @strawberry.mutation
    async def create_environment_backup(
        self,
        environment_id: UUID,
        info: strawberry.Info,
        name: str | None = None,
        max_concurrency: int | None = None,
        timeout: int | None = None,
    ) -> EnvironmentBackupType | None:
        """Create a coordinated backup of all active instances in an environment."""
        uow = info.context["uow"]

        env_backup = await create_env_backup_service(
            environment_id=environment_id,
            uow=uow,
            name=name,
            max_concurrency=max_concurrency or 5,
            timeout=timeout or 3600,
        )

        # Dispatch orchestration workflow
        try:
            prefect_manager = get_manager()
            await prefect_manager.run_action(
                action=PrefectAction.EXECUTE_ENV_BACKUP,
                parameters={
                    "environment_backup_id": str(env_backup.id),
                },
            )
        except Exception as exc:
            logger.error(
                f"Failed to submit environment backup workflow for {env_backup.id}, "
                "marking as FAILED",
                exc_info=exc,
            )
            from styrmin_backend.services.backup.environment import (
                update_environment_backup_status,
            )
            from styrmin_backend.db.models import EnvironmentBackupStatus

            uow = info.context["uow"]
            env_backup = await update_environment_backup_status(
                environment_backup_id=env_backup.id,
                uow=uow,
                status=EnvironmentBackupStatus.FAILED,
                error_message=f"Workflow dispatch failed: {exc}",
            )

        return EnvironmentBackupType.from_instance(env_backup)

    @strawberry.mutation
    async def create_environment_restore(
        self,
        environment_backup_id: UUID,
        info: strawberry.Info,
    ) -> EnvironmentRestoreType | None:
        """Create a coordinated restore from a completed environment backup."""
        uow = info.context["uow"]

        env_restore = await create_env_restore_service(
            environment_backup_id=environment_backup_id,
            uow=uow,
        )

        # Dispatch orchestration workflow
        try:
            prefect_manager = get_manager()
            await prefect_manager.run_action(
                action=PrefectAction.EXECUTE_ENV_RESTORE,
                parameters={
                    "environment_restore_id": str(env_restore.id),
                },
            )
        except Exception as exc:
            logger.error(
                f"Failed to submit environment restore workflow for {env_restore.id}, "
                "marking as FAILED",
                exc_info=exc,
            )
            from styrmin_backend.services.backup.environment import (
                update_environment_restore_status,
            )
            from styrmin_backend.db.models import EnvironmentRestoreStatus

            uow = info.context["uow"]
            env_restore = await update_environment_restore_status(
                environment_restore_id=env_restore.id,
                uow=uow,
                status=EnvironmentRestoreStatus.FAILED,
                error_message=f"Workflow dispatch failed: {exc}",
            )

        return EnvironmentRestoreType.from_instance(env_restore)

    @strawberry.mutation
    async def delete_environment_backup(
        self,
        environment_backup_id: UUID,
        info: strawberry.Info,
    ) -> str | None:
        """Delete an environment backup and all its constituent backups/restores."""
        uow = info.context["uow"]
        await delete_env_backup_service(
            environment_backup_id=environment_backup_id, uow=uow
        )
        return "Environment backup deleted"
