"""Provides the schema for the GraphQL API.

This is where the different routes and their types are defined.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import strawberry
from loguru import logger

from styrmin_backend.api.definitions.backup.backup import Backup as BackupType
from styrmin_backend.api.definitions.backup.restore import Restore as RestoreType
from styrmin_backend.api.definitions.backup.schedule import (
    BackupSchedule as BackupScheduleType,
)
from styrmin_backend.api.definitions.application_driver.model import (
    ApplicationDriverVersion,
)
from styrmin_backend.api.definitions.backup_storage_location.model import (
    BackupStorageLocation as BackupStorageLocationType,
    BackupStorageLocationAlreadyExists,
    BackupStorageLocationInUse,
    BackupStorageLocationNotFound,
    CreateBackupStorageLocationResult,
    DeleteBackupStorageLocationResult,
    DeleteSuccess,
    UpdateBackupStorageLocationResult,
)
from styrmin_backend.api.definitions.callback.model import CallbackResponse
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
from styrmin_backend.services.clusters import create_cluster, delete_cluster
from styrmin_backend.services.deployment import (
    deploy_application,
    update_deployment,
    update_deployment_version,
)
from styrmin_backend.services.environments import create_environment, delete_environment
from styrmin_backend.services.backup.scheduler import (
    create_backup_schedule as create_backup_schedule_service,
    delete_backup_schedule as delete_backup_schedule_service,
    update_backup_schedule as update_backup_schedule_service,
)
from styrmin_backend.services.backup.service import (
    create_backup as create_backup_service,
    create_restore as create_restore_service,
    delete_backup as delete_backup_service,
)
from styrmin_backend.services.deployment import get_deployment
from styrmin_backend.services.exceptions import (
    BackupStorageLocationAlreadyExistsError,
    BackupStorageLocationInUseError,
    BackupStorageLocationNotFoundError,
    InternalDeploymentError,
    TaskNotFoundError,
)
from styrmin_backend.services.primitives import (
    run_job,
    start_components,
    stop_components,
)
from styrmin_backend.services.tasks import update_task_state
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.models import PrefectAction


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_cluster(
        self, name: str, info: strawberry.Info, config: JSON | None = None
    ) -> Cluster | None:
        uow = info.context["uow"]
        cluster = await create_cluster(name=name, config=config, uow=uow)
        return Cluster.from_instance(cluster)

    @strawberry.mutation
    async def delete_cluster(
        self, cluster_id: UUID, info: strawberry.Info
    ) -> str | None:
        uow = info.context["uow"]
        await delete_cluster(cluster_id=cluster_id, uow=uow)
        return "Cluster deleted"

    @strawberry.mutation
    async def create_environment(
        self,
        name: str,
        cluster_id: UUID,
        info: strawberry.Info,
        config: JSON | None = None,
    ) -> Environment | None:
        uow = info.context["uow"]
        environment = await create_environment(
            name=name, cluster_id=cluster_id, config=config, uow=uow
        )
        return Environment.from_instance(environment)

    @strawberry.mutation
    async def delete_environment(
        self, environment_id: UUID, info: strawberry.Info
    ) -> str | None:
        uow = info.context["uow"]
        await delete_environment(environment_id=environment_id, uow=uow)
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
    ) -> CreateBackupStorageLocationResult:  # type: ignore[valid-type]
        uow = info.context["uow"]
        try:
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
        except BackupStorageLocationAlreadyExistsError:
            existing = None
            async with uow:
                existing = await uow.backup_storage_locations.get_by_name(name)
            return BackupStorageLocationAlreadyExists(
                message=f"A backup storage location with name '{name}' already exists.",
                existing_id=existing.id if existing else UUID(int=0),
            )

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
    ) -> UpdateBackupStorageLocationResult:  # type: ignore[valid-type]
        uow = info.context["uow"]
        try:
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
            credentials_changed = (
                access_key_id is not None or secret_access_key is not None
            )
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
        except BackupStorageLocationNotFoundError:
            return BackupStorageLocationNotFound(
                message=f"Backup storage location with id {backup_storage_location_id} not found.",
                backup_storage_location_id=backup_storage_location_id,
            )

    @strawberry.mutation
    async def delete_backup_storage_location(
        self,
        backup_storage_location_id: UUID,
        info: strawberry.Info,
    ) -> DeleteBackupStorageLocationResult:  # type: ignore[valid-type]
        uow = info.context["uow"]
        try:
            await delete_bsl_service(
                backup_storage_location_id=backup_storage_location_id, uow=uow
            )
            return DeleteSuccess(success=True)
        except BackupStorageLocationNotFoundError:
            return DeleteSuccess(success=False)
        except BackupStorageLocationInUseError as exc:
            return BackupStorageLocationInUse(
                message=str(exc),
                environment_names=exc.environment_names,
            )

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
        environment_id: UUID,
        info: strawberry.Info,
        version: str | None = None,
        name: str | None = None,
        config: JSON | None = None,
        parameters: JSON | None = None,
        service_name_overrides: list[ServiceNameOverride] | None = None,
    ) -> Task | None:
        """Deploy an application in an environment."""
        uow = info.context["uow"]
        overrides_dict = (
            {o.driver_service_name: o.override_name for o in service_name_overrides}
            if service_name_overrides
            else None
        )
        task = await deploy_application(
            driver_name=driver,
            version=version,
            environment_id=environment_id,
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
        env: JSON,
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
