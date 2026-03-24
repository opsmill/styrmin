"""Provides the schema for the GraphQL API.

This is where the different routes and their types are defined.
"""

from __future__ import annotations

from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.backup.backup import Backup as BackupType
from styrmin_backend.api.definitions.backup_storage_location.model import (
    BackupStorageLocation as BackupStorageLocationType,
)
from styrmin_backend.api.definitions.backup.restore import Restore as RestoreType
from styrmin_backend.api.definitions.backup.schedule import (
    BackupSchedule as BackupScheduleType,
)
from styrmin_backend.api.definitions.application_driver.model import (
    ApplicationDriver,
)
from styrmin_backend.api.definitions.cluster.model import Cluster
from styrmin_backend.api.definitions.deployment.model import Deployment
from styrmin_backend.api.definitions.environment.model import Environment
from styrmin_backend.api.definitions.service.model import (
    DeployedService as DeployedServiceType,
)
from styrmin_backend.api.definitions.task.model import Task
from styrmin_backend.services.application_drivers import (
    get_application_driver,
    get_application_drivers,
)
from styrmin_backend.services.backup.scheduler import (
    get_backup_schedule,
    get_backup_schedules,
)
from styrmin_backend.services.backup.service import (
    get_backup,
    get_backups,
    get_restore,
    get_restores,
)
from styrmin_backend.services.backup_storage_locations import (
    get_backup_storage_location,
    get_backup_storage_locations,
)
from styrmin_backend.services.clusters import get_cluster, get_clusters
from styrmin_backend.services.deployment import get_deployment
from styrmin_backend.services.environments import get_environment, get_environments
from styrmin_backend.services.tasks import get_task, get_tasks


@strawberry.type
class Query:
    @strawberry.field
    async def clusters(self, info: strawberry.Info) -> list[Cluster]:
        uow = info.context["uow"]
        clusters = await get_clusters(uow=uow)
        return [Cluster.from_instance(cluster) for cluster in clusters]

    @strawberry.field
    async def cluster(self, cluster_id: UUID, info: strawberry.Info) -> Cluster | None:
        uow = info.context["uow"]
        cluster = await get_cluster(cluster_id=cluster_id, uow=uow)
        return Cluster.from_instance(cluster)

    @strawberry.field
    async def backup_storage_locations(
        self, info: strawberry.Info
    ) -> list[BackupStorageLocationType]:
        uow = info.context["uow"]
        bsls = await get_backup_storage_locations(uow=uow)
        return [BackupStorageLocationType.from_instance(bsl) for bsl in bsls]

    @strawberry.field
    async def backup_storage_location(
        self, backup_storage_location_id: UUID, info: strawberry.Info
    ) -> BackupStorageLocationType | None:
        uow = info.context["uow"]
        bsl = await get_backup_storage_location(
            backup_storage_location_id=backup_storage_location_id, uow=uow
        )
        return BackupStorageLocationType.from_instance(bsl)

    @strawberry.field
    async def task(self, task_id: UUID, info: strawberry.Info) -> Task | None:
        uow = info.context["uow"]
        task = await get_task(task_id=task_id, uow=uow)
        return Task.from_instance(task)

    @strawberry.field
    async def tasks(self, info: strawberry.Info) -> list[Task]:
        uow = info.context["uow"]
        tasks = await get_tasks(uow=uow)
        return [Task.from_instance(task) for task in tasks]

    @strawberry.field
    async def environments(self, info: strawberry.Info) -> list[Environment]:
        uow = info.context["uow"]
        environments = await get_environments(uow=uow)
        return [Environment.from_instance(environment) for environment in environments]

    @strawberry.field
    async def environment(
        self, environment_id: UUID, info: strawberry.Info
    ) -> Environment | None:
        uow = info.context["uow"]
        environment = await get_environment(environment_id=environment_id, uow=uow)
        return Environment.from_instance(environment)

    @strawberry.field
    async def deployment(
        self, deployment_id: UUID, info: strawberry.Info
    ) -> Deployment | None:
        """Get a deployment by its ID."""
        uow = info.context["uow"]
        deployment = await get_deployment(deployment_id=deployment_id, uow=uow)
        if deployment.internal:
            return None
        return Deployment.from_instance(deployment)

    @strawberry.field
    async def backup(self, backup_id: UUID, info: strawberry.Info) -> BackupType | None:
        """Get a specific backup by ID."""
        uow = info.context["uow"]
        backup = await get_backup(backup_id=backup_id, uow=uow)
        return BackupType.from_instance(backup)

    @strawberry.field
    async def backups(
        self,
        instance_id: UUID,
        info: strawberry.Info,
        status: str | None = None,
    ) -> list[BackupType]:
        """List all backups for an instance."""
        from styrmin_backend.db.models import BackupStatus

        uow = info.context["uow"]
        backup_status = BackupStatus(status) if status else None
        backups = await get_backups(
            instance_id=instance_id, uow=uow, status=backup_status
        )
        return [BackupType.from_instance(b) for b in backups]

    @strawberry.field
    async def restore(
        self, restore_id: UUID, info: strawberry.Info
    ) -> RestoreType | None:
        """Get a specific restore by ID."""
        uow = info.context["uow"]
        restore = await get_restore(restore_id=restore_id, uow=uow)
        return RestoreType.from_instance(restore)

    @strawberry.field
    async def restores(
        self,
        backup_id: UUID,
        info: strawberry.Info,
        status: str | None = None,
    ) -> list[RestoreType]:
        """List all restores for a backup."""
        from styrmin_backend.db.models import RestoreStatus

        uow = info.context["uow"]
        restore_status = RestoreStatus(status) if status else None
        restores = await get_restores(
            backup_id=backup_id, uow=uow, status=restore_status
        )
        return [RestoreType.from_instance(r) for r in restores]

    @strawberry.field
    async def backup_schedule(
        self, schedule_id: UUID, info: strawberry.Info
    ) -> BackupScheduleType | None:
        """Get a specific backup schedule by ID."""
        uow = info.context["uow"]
        schedule = await get_backup_schedule(schedule_id=schedule_id, uow=uow)
        return BackupScheduleType.from_instance(schedule)

    @strawberry.field
    async def backup_schedules(
        self,
        deployment_id: UUID,
        info: strawberry.Info,
    ) -> list[BackupScheduleType]:
        """List all backup schedules for a deployment."""
        uow = info.context["uow"]
        schedules = await get_backup_schedules(deployment_id=deployment_id, uow=uow)
        return [BackupScheduleType.from_instance(s) for s in schedules]

    @strawberry.field
    async def application_drivers(
        self, info: strawberry.Info
    ) -> list[ApplicationDriver]:
        """List all application drivers with their versions."""
        uow = info.context["uow"]
        drivers = await get_application_drivers(uow=uow)
        return [ApplicationDriver.from_instance(driver) for driver in drivers]

    @strawberry.field
    async def application_driver(
        self, application_driver_id: UUID, info: strawberry.Info
    ) -> ApplicationDriver | None:
        """Get an application driver by its ID."""
        uow = info.context["uow"]
        driver = await get_application_driver(
            application_driver_id=application_driver_id, uow=uow
        )
        return ApplicationDriver.from_instance(driver)

    @strawberry.field
    async def environment_services(
        self, environment_id: UUID, info: strawberry.Info
    ) -> list[DeployedServiceType]:
        """List all deployed services in an environment."""
        uow = info.context["uow"]
        async with uow:
            services = await uow.deployed_services.get_by_environment_id(environment_id)
            return [DeployedServiceType.from_instance(s) for s in services]

    @strawberry.field
    async def deployment_services(
        self, deployment_id: UUID, info: strawberry.Info
    ) -> list[DeployedServiceType]:
        """List deployed services for a specific deployment."""
        uow = info.context["uow"]
        async with uow:
            services = await uow.deployed_services.get_by_deployment_id(deployment_id)
            return [DeployedServiceType.from_instance(s) for s in services]

    @strawberry.field(description="Health check probe")
    def ok(self) -> bool:
        return True
