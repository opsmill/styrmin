"""Provides the schema for the GraphQL API.

This is where the different routes and their types are defined.
"""

from __future__ import annotations

from uuid import UUID

import strawberry
from strawberry.permission import PermissionExtension

from styrmin_backend.api.auth.permissions import RequiresRole
from styrmin_backend.api.definitions.backup.backup import (
    Backup as BackupType,
    BackupStatusType,
)
from styrmin_backend.api.definitions.backup.environment_backup import (
    EnvironmentBackup as EnvironmentBackupType,
)
from styrmin_backend.api.definitions.backup.environment_clone import (
    EnvironmentClone as EnvironmentCloneType,
)
from styrmin_backend.api.definitions.backup.environment_restore import (
    EnvironmentRestore as EnvironmentRestoreType,
)
from styrmin_backend.api.definitions.backup_storage_location.model import (
    BackupStorageLocation as BackupStorageLocationType,
)
from styrmin_backend.api.definitions.backup.restore import (
    Restore as RestoreType,
    RestoreStatusType,
)
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
from styrmin_backend.api.definitions.step.model import Step as StepType
from styrmin_backend.api.definitions.task.model import Task
from styrmin_backend.api.definitions.user.model import (
    Group as GroupType,
    Role as RoleType,
    User as UserType,
)
from styrmin_backend.db.models import Role as RoleModel
from styrmin_backend.services.application_drivers import (
    get_application_driver,
    get_application_drivers,
)
from styrmin_backend.services.auth.groups import (
    get_group as get_group_service,
    list_groups as list_groups_service,
)
from styrmin_backend.services.auth.users import (
    get_user as get_user_service,
    list_users as list_users_service,
)
from styrmin_backend.services.backup.scheduler import (
    get_backup_schedule,
    get_backup_schedules,
)
from styrmin_backend.services.backup.clone import (
    get_environment_clone,
    get_environment_clones,
)
from styrmin_backend.services.backup.environment import (
    get_environment_backup,
    get_environment_backups,
    get_environment_restore,
    get_environment_restores,
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
from styrmin_backend.services.clusters import get_clusters, resolve_cluster
from styrmin_backend.services.deployment import (
    get_deployment,
    get_deployment_by_name,
)
from styrmin_backend.services.environments import (
    get_environments,
    resolve_environment,
)
from styrmin_backend.services.exceptions import InvalidDeploymentLookupArgsError
from styrmin_backend.api.definitions.deployment_timeline.model import (
    DeploymentTimelineEntry,
)
from styrmin_backend.services.deployment_timeline import build_deployment_timeline
from styrmin_backend.api.definitions.pod_status.model import (
    PodStatus as PodStatusType,
)
from styrmin_backend.services.pod_status import get_pod_statuses
from styrmin_backend.services.steps.reads import get_step
from styrmin_backend.services.tasks import get_task, get_tasks


def _requires_admin() -> PermissionExtension:
    """Sugar for admin-only query fields. See ADR-017."""
    return PermissionExtension([RequiresRole(RoleModel.ADMIN)])


@strawberry.type
class Query:
    @strawberry.field
    async def current_user(self, info: strawberry.Info) -> UserType | None:
        user = info.context.get("current_user")
        if user is None:
            return None
        return UserType.from_instance(user)

    @strawberry.field(extensions=[_requires_admin()])
    async def users(
        self,
        info: strawberry.Info,
        active: bool | None = None,
        role: RoleType | None = None,
        search: str | None = None,
    ) -> list[UserType]:
        """Admin-only filtered listing of users.

        See specs/011-admin-user-group-mgmt/contracts/graphql.md. Filters
        apply independently in any combination. Search is a substring
        match (case-insensitive) over username and display_name.
        """
        uow = info.context["uow"]
        role_model = RoleModel[role.value] if role is not None else None
        users = await list_users_service(
            uow, active=active, role=role_model, search=search
        )
        return [UserType.from_instance(u) for u in users]

    @strawberry.field(extensions=[_requires_admin()])
    async def groups(
        self,
        info: strawberry.Info,
        search: str | None = None,
    ) -> list[GroupType]:
        """Admin-only filtered listing of groups.

        See specs/011-admin-user-group-mgmt/contracts/graphql.md. ``search``
        is a substring match (case-insensitive) over ``name``.
        """
        uow = info.context["uow"]
        groups = await list_groups_service(uow, search=search)
        return [GroupType.from_instance(g) for g in groups]

    @strawberry.field(extensions=[_requires_admin()])
    async def user(
        self,
        info: strawberry.Info,
        id: UUID,  # noqa: A002 — GraphQL convention; the field is named `id`.
    ) -> UserType | None:
        """Admin-only single-user lookup by id.

        Surfaces ``USER_NOT_FOUND`` via ``extensions.code`` when the id is
        unknown. The field is nullable to keep the schema honest about the
        possibility of a missing row, but the not-found path is delivered
        as a structured error rather than a silent null so SDK callers can
        branch on the code.
        """
        uow = info.context["uow"]
        user = await get_user_service(uow, user_id=id)
        return UserType.from_instance(user)

    @strawberry.field(extensions=[_requires_admin()])
    async def group(
        self,
        info: strawberry.Info,
        id: UUID,  # noqa: A002 — GraphQL convention; the field is named `id`.
    ) -> GroupType | None:
        """Admin-only single-group lookup by id.

        Surfaces ``GROUP_NOT_FOUND`` via ``extensions.code`` when the id is
        unknown — see :py:meth:`Query.user` for the rationale.
        """
        uow = info.context["uow"]
        group = await get_group_service(uow, group_id=id)
        return GroupType.from_instance(group)

    @strawberry.field
    async def clusters(self, info: strawberry.Info) -> list[Cluster]:
        uow = info.context["uow"]
        clusters = await get_clusters(uow=uow)
        return [Cluster.from_instance(cluster) for cluster in clusters]

    @strawberry.field
    async def cluster(
        self,
        info: strawberry.Info,
        cluster_id: UUID | None = None,
        cluster_name: str | None = None,
    ) -> Cluster | None:
        uow = info.context["uow"]
        cluster = await resolve_cluster(
            uow, cluster_id=cluster_id, cluster_name=cluster_name
        )
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

    @strawberry.field(
        description="One step, for example to load its output. Any signed-in user."
    )
    async def step(self, step_id: UUID, info: strawberry.Info) -> StepType | None:
        uow = info.context["uow"]
        step = await get_step(step_id=step_id, uow=uow)
        return StepType.from_instance(step)

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
        self,
        info: strawberry.Info,
        environment_id: UUID | None = None,
        environment_name: str | None = None,
        cluster_id: UUID | None = None,
        cluster_name: str | None = None,
    ) -> Environment | None:
        uow = info.context["uow"]
        environment = await resolve_environment(
            uow,
            environment_id=environment_id,
            environment_name=environment_name,
            cluster_id=cluster_id,
            cluster_name=cluster_name,
        )
        return Environment.from_instance(environment)

    @strawberry.field
    async def deployment(
        self,
        info: strawberry.Info,
        deployment_id: UUID | None = None,
        name: str | None = None,
        environment_id: UUID | None = None,
    ) -> Deployment | None:
        """Look up a deployment by its ID or its natural identity.

        Provide exactly one of:

        - ``deploymentId``, or
        - ``name`` and ``environmentId``.

        Internal/system-managed deployments are hidden (returns null).
        Returns null if no matching deployment exists.
        """
        uow = info.context["uow"]

        # Exactly one of {deploymentId, (name + environmentId)} must be set.
        by_id = deployment_id is not None
        by_name_pair = name is not None and environment_id is not None
        if by_id == by_name_pair or (name is None) != (environment_id is None):
            raise InvalidDeploymentLookupArgsError()

        if by_id:
            deployment = await get_deployment(deployment_id=deployment_id, uow=uow)
            if deployment.internal:
                return None
            return Deployment.from_instance(deployment)

        deployment = await get_deployment_by_name(
            name=name, environment_id=environment_id, uow=uow
        )
        if deployment is None:
            return None
        return Deployment.from_instance(deployment)

    @strawberry.field
    async def backup(self, backup_id: UUID, info: strawberry.Info) -> BackupType | None:
        """Get a specific backup by ID."""
        uow = info.context["uow"]
        backup = await get_backup(backup_id=backup_id, uow=uow)
        return BackupType.from_instance(backup)

    @strawberry.field(
        description=(
            "List backups. Pass exactly one of deploymentId or instanceId. "
            "deploymentId lists the deployment's backup history: the backups of "
            "every instance the deployment has had, newest first. instanceId "
            "lists the backups of that one instance."
        )
    )
    async def backups(
        self,
        info: strawberry.Info,
        deployment_id: UUID | None = None,
        instance_id: UUID | None = None,
        status: BackupStatusType | None = None,  # type: ignore[valid-type]
    ) -> list[BackupType]:
        uow = info.context["uow"]
        backups = await get_backups(
            uow,
            deployment_id=deployment_id,
            instance_id=instance_id,
            status=status,
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
        status: RestoreStatusType | None = None,  # type: ignore[valid-type]
    ) -> list[RestoreType]:
        """List all restores for a backup."""
        uow = info.context["uow"]
        restores = await get_restores(backup_id=backup_id, uow=uow, status=status)
        return [RestoreType.from_instance(r) for r in restores]

    @strawberry.field
    async def environment_backup(
        self, environment_backup_id: UUID, info: strawberry.Info
    ) -> EnvironmentBackupType | None:
        """Get a specific environment backup by ID."""
        uow = info.context["uow"]
        environment_backup = await get_environment_backup(
            environment_backup_id=environment_backup_id, uow=uow
        )
        return EnvironmentBackupType.from_instance(environment_backup)

    @strawberry.field
    async def environment_backups(
        self, environment_id: UUID, info: strawberry.Info
    ) -> list[EnvironmentBackupType]:
        """List an environment's environment backups, newest first."""
        uow = info.context["uow"]
        environment_backups = await get_environment_backups(
            environment_id=environment_id, uow=uow
        )
        return [
            EnvironmentBackupType.from_instance(environment_backup)
            for environment_backup in environment_backups
        ]

    @strawberry.field
    async def environment_restore(
        self, environment_restore_id: UUID, info: strawberry.Info
    ) -> EnvironmentRestoreType | None:
        """Get a specific environment restore by ID."""
        uow = info.context["uow"]
        environment_restore = await get_environment_restore(
            environment_restore_id=environment_restore_id, uow=uow
        )
        return EnvironmentRestoreType.from_instance(environment_restore)

    @strawberry.field
    async def environment_restores(
        self, environment_backup_id: UUID, info: strawberry.Info
    ) -> list[EnvironmentRestoreType]:
        """List a snapshot's environment restores, newest first."""
        uow = info.context["uow"]
        environment_restores = await get_environment_restores(
            environment_backup_id=environment_backup_id, uow=uow
        )
        return [
            EnvironmentRestoreType.from_instance(environment_restore)
            for environment_restore in environment_restores
        ]

    @strawberry.field
    async def environment_clone(
        self, environment_clone_id: UUID, info: strawberry.Info
    ) -> EnvironmentCloneType:
        """Get a specific environment clone by ID.

        ``NOT_FOUND`` when the id is unknown. Read access is ungated, matching
        ``environmentBackup`` — which already exposes the captured
        ``environmentConfig``, the same value class as ``configOverride``
        (research D10, a deliberate parity decision).
        """
        uow = info.context["uow"]
        readout = await get_environment_clone(
            environment_clone_id=environment_clone_id, uow=uow
        )
        return EnvironmentCloneType.from_instance(readout.clones[0], readout.restores)

    @strawberry.field
    async def environment_clones(
        self, environment_id: UUID, info: strawberry.Info
    ) -> list[EnvironmentCloneType]:
        """List the clones made *from* an environment, newest first.

        The referenced constituent restores are fetched once for the whole batch
        and shared across the rows, so deriving every ``status`` in the list
        costs one extra query rather than one per clone.
        """
        uow = info.context["uow"]
        readout = await get_environment_clones(environment_id=environment_id, uow=uow)
        return [
            EnvironmentCloneType.from_instance(clone, readout.restores)
            for clone in readout.clones
        ]

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

    @strawberry.field
    async def deployment_timeline(
        self, deployment_id: UUID, info: strawberry.Info
    ) -> list[DeploymentTimelineEntry]:
        """Get the deployment history timeline: tasks with version info, newest-first."""
        uow = info.context["uow"]
        entries = await build_deployment_timeline(deployment_id=deployment_id, uow=uow)
        return [DeploymentTimelineEntry.from_data(entry) for entry in entries]

    @strawberry.field
    async def pod_statuses(
        self,
        info: strawberry.Info,
        deployment_id: UUID | None = None,
        environment_id: UUID | None = None,
        cluster_id: UUID | None = None,
    ) -> list[PodStatusType]:
        """Get pod statuses with optional filtering by deployment, environment, or cluster."""
        uow = info.context["uow"]
        statuses = await get_pod_statuses(
            uow=uow,
            deployment_id=deployment_id,
            environment_id=environment_id,
            cluster_id=cluster_id,
        )
        return [PodStatusType.from_instance(s) for s in statuses]

    @strawberry.field(description="Health check probe")
    def ok(self) -> bool:
        return True
