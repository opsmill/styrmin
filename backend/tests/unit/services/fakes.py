import contextlib
from collections.abc import Collection
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from styrmin_backend.db.models import (
    Action,
    ApplicationDriver,
    ApplicationDriverVersion,
    ApplicationInstance,
    Backup,
    BackupSchedule,
    BackupStatus,
    BackupStorageLocation,
    Cluster,
    Deployment,
    DeployedService,
    DeploymentStatus,
    Environment,
    EnvironmentBackup,
    EnvironmentClone,
    EnvironmentRestore,
    HelmChart,
    HelmRepository,
    PodStatus,
    Restore,
    RestoreStatus,
    Task,
    Utility,
)
from styrmin_backend.domain.models import Deployment as DeploymentEntity
from styrmin_backend.repository.backup_storage_location import (
    BackupStorageLocationRepository,
)
from styrmin_backend.repository.deployed_service import DeployedServiceRepository
from styrmin_backend.repository.deployment import DeploymentRepository
from styrmin_backend.repository.action import ActionRepository
from styrmin_backend.repository.application_driver import ApplicationDriverRepository
from styrmin_backend.repository.application_driver_version import (
    ApplicationDriverVersionRepository,
)
from styrmin_backend.repository.application_instance import (
    ApplicationInstanceRepository,
)
from styrmin_backend.repository.backup import BackupRepository
from styrmin_backend.repository.backup_schedule import BackupScheduleRepository
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.cluster import ClusterRepository
from styrmin_backend.repository.environment import EnvironmentRepository
from styrmin_backend.repository.environment_backup import (
    EnvironmentBackupRepository,
    EnvironmentRestoreRepository,
)
from styrmin_backend.repository.environment_clone import (
    EnvironmentCloneRepository,
    referenced_restore_ids,
)
from styrmin_backend.repository.deployment_status import (
    DeploymentStatusRepository,
)
from styrmin_backend.repository.pod_status import PodStatusRepository
from styrmin_backend.repository.helm_chart import HelmChartRepository
from styrmin_backend.repository.helm_repository import HelmRepositoryRepository
from styrmin_backend.repository.restore import RestoreRepository
from styrmin_backend.repository.tasks import TaskRepository
from styrmin_backend.repository.utility import UtilityRepository
from styrmin_backend.services.unit_of_work import UnitOfWork

ModelType = TypeVar("ModelType")
_NO_TIME = datetime.min.replace(tzinfo=UTC)


class FakeRepository(BaseRepository[ModelType]):
    def __init__(self, models: list[ModelType] | None = None):
        self.models = models if models else []

    async def create(self, model: ModelType) -> ModelType:
        self.models.append(model)
        return model

    async def get(self, id: int) -> ModelType | None:  # type: ignore[override]
        for model in self.models:
            if model.id == id:  # type: ignore[attr-defined]
                return model
        return None

    async def get_all(self) -> list[ModelType]:
        return self.models

    async def delete(self, model: ModelType) -> None:
        for i, m in enumerate(self.models):
            if m.id == model.id:  # type: ignore[attr-defined]
                self.models.pop(i)
                return


class FakeClusterRepository(FakeRepository[Cluster], ClusterRepository):
    """Fake cluster repository for testing purposes."""

    async def get_by_name(self, name: str) -> Cluster | None:
        for cluster in self.models:
            if cluster.name == name:
                return cluster
        return None


class FakeBackupStorageLocationRepository(
    FakeRepository[BackupStorageLocation], BackupStorageLocationRepository
):
    """Fake backup storage location repository for testing purposes."""

    async def get_by_name(self, name: str) -> BackupStorageLocation | None:
        for bsl in self.models:
            if bsl.name == name:
                return bsl
        return None


class FakeEnvironmentRepository(FakeRepository[Environment], EnvironmentRepository):
    async def get_by_name(self, name) -> Environment | None:
        for environment in self.models:
            if environment.name == name:
                return environment
        return None

    async def get_by_name_in_cluster(
        self, name: str, cluster_id: UUID
    ) -> Environment | None:
        for environment in self.models:
            if environment.name == name and environment.cluster_id == cluster_id:
                return environment
        return None


class FakeHelmRepositoryRepository(
    FakeRepository[HelmRepository], HelmRepositoryRepository
):
    async def get_by_url(self, url):
        for repository in self.models:
            if repository.url == url:
                return repository
        return None


class FakeApplicationRepository(
    FakeRepository[ApplicationDriverVersion], ApplicationDriverVersionRepository
):
    async def get_by_supported_versions(
        self, application_driver_id: UUID, versions: str
    ) -> ApplicationDriverVersion | None:
        for application in self.models:
            if (
                application.id == application_driver_id
                and application.application_supported_versions == versions
            ):
                return application
        return None

    async def get_by_driver_and_version(
        self, application_driver_id: UUID, version: str
    ) -> ApplicationDriverVersion | None:
        for application in self.models:
            if (
                application.application_driver_id == application_driver_id
                and application.version == version
            ):
                return application
        return None

    async def get_by_identity(
        self,
        *,
        application_driver_id: UUID,
        source_type: str,
        source_repository: str,
        source_branch: str | None,
        source_path: str | None,
        version: str,
        content_hash: str | None,
        source_commit_sha: str | None,
    ) -> ApplicationDriverVersion | None:
        """Spec 013 / T024 — match every column in the identity tuple.

        Mirrors the SQLModel repository's nullability semantics: when the
        caller passes ``None`` for an optional column, only rows whose
        column is also ``None`` match (the in-memory equivalent of
        ``IS NULL`` / ``nulls_not_distinct``).
        """
        for application in self.models:
            if (
                application.application_driver_id == application_driver_id
                and application.source_type == source_type
                and application.source_repository == source_repository
                and application.source_branch == source_branch
                and application.source_path == source_path
                and application.version == version
                and application.content_hash == content_hash
                and application.source_commit_sha == source_commit_sha
            ):
                return application
        return None


# FakeApplicationRepository is already a FakeRepository[ApplicationDriverVersion]
# that implements ApplicationDriverVersionRepository; this alias just names it
# after the interface it implements, for clarity at the point of use.
FakeApplicationDriverVersionRepository = FakeApplicationRepository


class FakeHelmChartRepository(FakeRepository[HelmChart], HelmChartRepository):
    async def get_by_name_version(self, name: str, version: str):
        for chart in self.models:
            if chart.name == name and chart.version == version:
                return chart
        return None


class FakeApplicationInstanceRepository(
    FakeRepository[ApplicationInstance], ApplicationInstanceRepository
):
    async def update(
        self,
        instance: ApplicationInstance,
    ) -> ApplicationInstance:
        for i, m in enumerate(self.models):
            if m.id == instance.id:
                self.models[i] = instance
                return instance
        return instance

    async def find_by_deployment(
        self, deployment_id: UUID
    ) -> list[ApplicationInstance]:
        return [m for m in self.models if m.deployment_id == deployment_id]


class FakeApplicationDriverRepository(
    FakeRepository[ApplicationDriver], ApplicationDriverRepository
):
    async def get_by_name(self, name: str) -> ApplicationDriver | None:
        for driver in self.models:
            if driver.name == name:
                return driver
        return None


class FakeActionRepository(FakeRepository[Action], ActionRepository):
    pass


class FakeTaskRepository(FakeRepository[Task], TaskRepository):
    async def update(self, task: Task) -> Task:
        for i, m in enumerate(self.models):
            if m.id == task.id:
                self.models[i] = task
                return task
        return task

    async def save(self, task) -> None:
        for i, m in enumerate(self.models):
            if m.id == task.id:
                self.models[i] = task
                return
        self.models.append(task)

    async def find(self, id: UUID):
        for model in self.models:
            if model.id == id:
                return model
        return None

    async def all(self):
        return self.models

    async def find_by_deployment(self, deployment_id: UUID):
        return [m for m in self.models if m.deployment_id == deployment_id]

    @staticmethod
    def _newest(matches: list[Task]) -> Task | None:
        # Newest created_on first, like production; equal or unset times keep the last inserted.
        if not matches:
            return None
        return max(
            enumerate(matches),
            key=lambda item: (
                item[1].created_on is not None,
                item[1].created_on or _NO_TIME,
                item[0],
            ),
        )[1]

    async def find_by_instance(self, instance_id: UUID):
        return self._newest([m for m in self.models if m.instance_id == instance_id])

    async def find_latest_by_type(self, deployment_id: UUID, type):
        return self._newest(
            [
                m
                for m in self.models
                if m.deployment_id == deployment_id and m.type == type
            ]
        )

    async def find_started_by_steps(self, step_ids):
        return [m for m in self.models if m.started_by_step_id in set(step_ids)]


class FakeBackupRepository(FakeRepository[Backup], BackupRepository):
    async def get_by_instance_id(
        self, instance_id: UUID, status: BackupStatus | None = None
    ) -> list[Backup]:
        results = [b for b in self.models if b.instance_id == instance_id]
        if status is not None:
            results = [b for b in results if b.status == status]
        return results

    async def has_in_progress_backup(self, instance_id: UUID) -> Backup | None:
        for b in self.models:
            if b.instance_id == instance_id and b.status == BackupStatus.IN_PROGRESS:
                return b
        return None


class FakeRestoreRepository(FakeRepository[Restore], RestoreRepository):
    """In-memory restore repository.

    ``backup_source`` and ``instance_source`` are wired by
    :class:`FakeUnitOfWork` so the source-deployment lookup walks the same
    restore -> backup -> instance join as the production query.
    """

    def __init__(self, models: list[Restore] | None = None) -> None:
        super().__init__(models)
        self.backup_source: "FakeBackupRepository | None" = None
        self.instance_source: "FakeApplicationInstanceRepository | None" = None

    async def get_by_backup_id(
        self, backup_id: UUID, status: RestoreStatus | None = None
    ) -> list[Restore]:
        results = [r for r in self.models if r.backup_id == backup_id]
        if status is not None:
            results = [r for r in results if r.status == status]
        return results

    async def get_by_target_namespace(
        self, target_namespace: str, status: RestoreStatus | None = None
    ) -> list[Restore]:
        results = [r for r in self.models if r.target_namespace == target_namespace]
        if status is not None:
            results = [r for r in results if r.status == status]
        return results

    async def get_non_terminal_by_source_deployment_id(
        self, deployment_id: UUID
    ) -> list[Restore]:
        backups = self.backup_source.models if self.backup_source else []
        instances = self.instance_source.models if self.instance_source else []
        instance_ids = {i.id for i in instances if i.deployment_id == deployment_id}
        backup_ids = {b.id for b in backups if b.instance_id in instance_ids}
        return [
            r
            for r in self.models
            if r.backup_id in backup_ids
            and r.status in (RestoreStatus.PENDING, RestoreStatus.IN_PROGRESS)
        ][::-1]


class FakeEnvironmentBackupRepository(
    FakeRepository[EnvironmentBackup], EnvironmentBackupRepository
):
    """In-memory environment backup repository.

    ``constituent_source`` is wired by :class:`FakeUnitOfWork` so the guard
    derives "in progress" from the constituent ``Backup`` rows exactly as the
    real EXISTS subquery does. Without it the fake could report a state the
    production query can never produce.
    """

    def __init__(
        self,
        models: list[EnvironmentBackup] | None = None,
        constituent_source: "FakeBackupRepository | None" = None,
    ) -> None:
        super().__init__(models)
        self.constituent_source = constituent_source

    async def get_by_environment_id(
        self, environment_id: UUID
    ) -> list[EnvironmentBackup]:
        return [m for m in self.models if m.environment_id == environment_id][::-1]

    async def has_in_progress_environment_backup(
        self, environment_id: UUID
    ) -> EnvironmentBackup | None:
        constituents = self.constituent_source.models if self.constituent_source else []
        for parent in self.models:
            if parent.environment_id != environment_id:
                continue
            if any(
                backup.environment_backup_id == parent.id
                and backup.status in (BackupStatus.PENDING, BackupStatus.IN_PROGRESS)
                for backup in constituents
            ):
                return parent
        return None


class FakeEnvironmentCloneRepository(
    FakeRepository[EnvironmentClone], EnvironmentCloneRepository
):
    """In-memory environment clone repository.

    ``restore_source`` is wired by :class:`FakeUnitOfWork` so
    ``get_referenced_restores`` resolves the same rows the production ``IN``
    query would: the derivation reads restore status through those rows, and a
    fake that returned nothing would make every clone look terminal.
    """

    def __init__(
        self,
        models: list[EnvironmentClone] | None = None,
        restore_source: "FakeRestoreRepository | None" = None,
    ) -> None:
        super().__init__(models)
        self.restore_source = restore_source
        self.environment_backup_source: "FakeEnvironmentBackupRepository | None" = None
        self.backup_source: "FakeBackupRepository | None" = None
        self.environment_source: "FakeEnvironmentRepository | None" = None

    def _hydrate(self, clone: EnvironmentClone) -> EnvironmentClone:
        """Attach what the real repository eager-loads.

        The clone derivation reads the backing capture's *own* derived status,
        which means walking ``clone.environment_backup.backups``. On a transient
        SQLModel instance those relationships are empty, so a fake that skipped
        this would make every clone look like it had no capture at all — the one
        state the derivation reads as "nothing in flight".
        """
        if self.environment_backup_source is not None:
            clone.environment_backup = next(
                (
                    parent
                    for parent in self.environment_backup_source.models
                    if parent.id == clone.environment_backup_id
                ),
                None,
            )
        if clone.environment_backup is not None and self.backup_source is not None:
            clone.environment_backup.backups = [
                backup
                for backup in self.backup_source.models
                if backup.environment_backup_id == clone.environment_backup.id
            ]
        if self.environment_source is not None:
            by_id = {
                environment.id: environment
                for environment in self.environment_source.models
            }
            clone.source_environment = by_id.get(clone.source_environment_id)  # type: ignore[arg-type]
            clone.created_environment = by_id.get(clone.created_environment_id)  # type: ignore[arg-type]
        return clone

    async def get(self, id: UUID) -> EnvironmentClone | None:  # type: ignore[override]
        for clone in self.models:
            if clone.id == id:
                return self._hydrate(clone)
        return None

    async def save(self, clone: EnvironmentClone) -> EnvironmentClone:
        for index, existing in enumerate(self.models):
            if existing.id == clone.id:
                self.models[index] = clone
                return clone
        self.models.append(clone)
        return clone

    async def get_by_source_environment_id(
        self, environment_id: UUID
    ) -> list[EnvironmentClone]:
        return [
            self._hydrate(m)
            for m in self.models
            if m.source_environment_id == environment_id
        ][::-1]

    async def get_by_created_environment_id(
        self, environment_id: UUID
    ) -> list[EnvironmentClone]:
        return [
            self._hydrate(m)
            for m in self.models
            if m.created_environment_id == environment_id
        ][::-1]

    async def get_by_environment_backup_id(
        self, environment_backup_id: UUID
    ) -> list[EnvironmentClone]:
        return [
            self._hydrate(clone)
            for clone in self.models
            if clone.environment_backup_id == environment_backup_id
        ][::-1]

    async def get_referenced_restores(
        self, clones: "list[EnvironmentClone]"
    ) -> dict[UUID, Restore]:
        ids = referenced_restore_ids(clones)
        rows = self.restore_source.models if self.restore_source else []
        return {restore.id: restore for restore in rows if restore.id in ids}


class FakeEnvironmentRestoreRepository(
    FakeRepository[EnvironmentRestore], EnvironmentRestoreRepository
):
    """In-memory environment restore repository (see the backup fake above)."""

    def __init__(
        self,
        models: list[EnvironmentRestore] | None = None,
        constituent_source: "FakeRestoreRepository | None" = None,
        parent_source: "FakeEnvironmentBackupRepository | None" = None,
    ) -> None:
        super().__init__(models)
        self.constituent_source = constituent_source
        self.parent_source = parent_source

    async def get_by_environment_backup_id(
        self, environment_backup_id: UUID
    ) -> list[EnvironmentRestore]:
        return [
            m for m in self.models if m.environment_backup_id == environment_backup_id
        ][::-1]

    async def has_in_progress_environment_restore(
        self, environment_id: UUID
    ) -> EnvironmentRestore | None:
        constituents = self.constituent_source.models if self.constituent_source else []
        parents = self.parent_source.models if self.parent_source else []
        # ``EnvironmentRestore`` has no environment_id of its own; the real
        # query joins through the parent snapshot, so the fake does too.
        parent_ids = {p.id for p in parents if p.environment_id == environment_id}
        for environment_restore in self.models:
            if environment_restore.environment_backup_id not in parent_ids:
                continue
            if any(
                restore.environment_restore_id == environment_restore.id
                and restore.status in (RestoreStatus.PENDING, RestoreStatus.IN_PROGRESS)
                for restore in constituents
            ):
                return environment_restore
        return None


class FakePodStatusRepository(FakeRepository[PodStatus], PodStatusRepository):
    """Fake pod status repository for testing purposes."""

    async def find_by_deployment(self, deployment_id: UUID) -> list[PodStatus]:
        return [m for m in self.models if m.deployment_id == deployment_id]

    async def upsert(self, pod_status: PodStatus) -> PodStatus:
        # Mirror SQLModelPodStatusRepository.upsert: mutate the existing row's
        # mutable fields rather than replacing it wholesale. This is the only
        # way unit tests catch field-by-field omissions in the SQL upsert.
        for existing in self.models:
            if (
                existing.deployment_id == pod_status.deployment_id
                and existing.pod_name == pod_status.pod_name
            ):
                existing.phase = pod_status.phase
                existing.ready = pod_status.ready
                existing.restart_count = pod_status.restart_count
                existing.container_statuses = pod_status.container_statuses
                existing.node_name = pod_status.node_name
                existing.component_name = pod_status.component_name
                existing.started_at = pod_status.started_at
                existing.last_polled_at = pod_status.last_polled_at
                existing.namespace = pod_status.namespace
                return existing
        self.models.append(pod_status)
        return pod_status

    async def delete_stale(
        self, deployment_id: UUID, active_pod_names: set[str]
    ) -> int:
        before = len(self.models)
        self.models = [
            m
            for m in self.models
            if not (
                m.deployment_id == deployment_id and m.pod_name not in active_pod_names
            )
        ]
        return before - len(self.models)

    async def find_by_environment(self, environment_id: UUID) -> list[PodStatus]:
        return []

    async def find_by_cluster(self, cluster_id: UUID) -> list[PodStatus]:
        return []


class FakeDeploymentStatusRepository(
    FakeRepository[DeploymentStatus], DeploymentStatusRepository
):
    """Fake deployment CRD status repository for testing purposes."""

    async def find_by_deployment(self, deployment_id: UUID) -> DeploymentStatus | None:
        for m in self.models:
            if m.deployment_id == deployment_id:
                return m
        return None

    async def find_by_deployments(
        self, deployment_ids: Collection[UUID]
    ) -> list[DeploymentStatus]:
        return [m for m in self.models if m.deployment_id in deployment_ids]

    async def upsert(self, crd_status: DeploymentStatus) -> DeploymentStatus:
        for i, m in enumerate(self.models):
            if m.deployment_id == crd_status.deployment_id:
                self.models[i] = crd_status
                return crd_status
        self.models.append(crd_status)
        return crd_status


class FakeDeploymentRepository(DeploymentRepository):
    """Fake deployment repository for testing purposes."""

    def __init__(self, deployments: list[DeploymentEntity] | None = None) -> None:
        self._deployments: list[DeploymentEntity] = list(deployments or [])

    async def create(self, entity: Deployment) -> Deployment:
        return entity

    async def get(self, id: UUID) -> Deployment | None:
        return None

    async def get_all(self):  # type: ignore[override]
        return []

    async def delete(self, entity: Deployment) -> None:
        self._deployments = [d for d in self._deployments if d.id != entity.id]  # type: ignore[union-attr]

    async def save(self, deployment: DeploymentEntity) -> None:
        for i, d in enumerate(self._deployments):
            if d.id == deployment.id:
                self._deployments[i] = deployment
                return
        self._deployments.append(deployment)

    async def find(self, id: UUID) -> DeploymentEntity | None:
        for d in self._deployments:
            if d.id == id:
                return d
        return None

    async def get_by_name(
        self,
        name: str,
        environment_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> DeploymentEntity | None:
        for d in self._deployments:
            if d.name != name or d.environment_id != environment_id:
                continue
            if not include_deleted and d.deleted_at is not None:
                continue
            return d
        return None

    async def find_one_by_name_and_environment(
        self,
        name: str,
        environment_id: UUID,
    ) -> DeploymentEntity | None:
        return await self.get_by_name(name, environment_id, include_deleted=False)

    async def find_names_with_prefix(
        self,
        prefix: str,
        environment_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> list[str]:
        return [
            d.name
            for d in self._deployments
            if d.name.startswith(prefix)
            and d.environment_id == environment_id
            and (include_deleted or d.deleted_at is None)
        ]

    async def find_internal_by_environment(
        self, environment_id: UUID
    ) -> DeploymentEntity | None:
        for d in self._deployments:
            if (
                d.environment_id == environment_id
                and d.internal
                and d.deleted_at is None
            ):
                return d
        return None

    async def find_all_by_environment(
        self,
        environment_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> list[DeploymentEntity]:
        return [
            d
            for d in self._deployments
            if d.environment_id == environment_id
            and (include_deleted or d.deleted_at is None)
        ]

    async def delete_all_for_environment(self, environment_id: UUID) -> list[UUID]:
        """Drop every deployment of an environment, tombstones included.

        The SQL repository also cascades the deployments' dependent rows; the
        fakes hold each table independently, so there is nothing here to
        cascade into.
        """
        doomed = [d.id for d in self._deployments if d.environment_id == environment_id]
        self._deployments = [
            d for d in self._deployments if d.environment_id != environment_id
        ]
        return doomed


class FakeDeployedServiceRepository(
    FakeRepository[DeployedService], DeployedServiceRepository
):
    async def get_by_environment_id(
        self, environment_id: UUID
    ) -> list[DeployedService]:
        return [s for s in self.models if s.environment_id == environment_id]

    async def get_by_deployment_id(self, deployment_id: UUID) -> list[DeployedService]:
        return [s for s in self.models if s.deployment_id == deployment_id]

    async def get_by_resolved_name_and_environment_id(
        self, resolved_name: str, environment_id: UUID
    ) -> DeployedService | None:
        for s in self.models:
            if s.resolved_name == resolved_name and s.environment_id == environment_id:
                return s
        return None

    async def delete_by_deployment_id(self, deployment_id: UUID) -> None:
        self.models = [s for s in self.models if s.deployment_id != deployment_id]


class FakeBackupScheduleRepository(
    FakeRepository[BackupSchedule], BackupScheduleRepository
):
    async def get_by_deployment_id(self, deployment_id: UUID) -> list[BackupSchedule]:
        return [s for s in self.models if s.deployment_id == deployment_id]


class FakeUtilityRepository(FakeRepository[Utility], UtilityRepository):
    """Fake utility repository — returns an empty list by default.

    Tests that need specific utility rows can pre-populate ``self.models``
    directly after constructing ``FakeUnitOfWork``.
    """

    async def get_by_kind(self, kind: str) -> Utility | None:
        for u in self.models:
            if u.kind == kind:
                return u
        return None


class _FakeSession:
    async def refresh(self, obj: object) -> None:
        pass

    def begin_nested(self) -> contextlib.nullcontext[None]:
        # The services open savepoints on the real session; the fakes have none.
        return contextlib.nullcontext()


class FakeUnitOfWork(UnitOfWork):
    backup_storage_locations: FakeBackupStorageLocationRepository  # type: ignore[assignment]
    clusters: FakeClusterRepository
    environments: FakeEnvironmentRepository
    helm_repositories: FakeHelmRepositoryRepository
    helm_charts: FakeHelmChartRepository
    application_drivers: FakeApplicationDriverRepository  # type: ignore[assignment]
    application_driver_versions: FakeApplicationRepository  # type: ignore[assignment]
    instances: FakeApplicationInstanceRepository
    actions: FakeActionRepository  # type: ignore[assignment]
    tasks: FakeTaskRepository  # type: ignore[assignment]
    deployments: FakeDeploymentRepository  # type: ignore[assignment]
    deployed_services: FakeDeployedServiceRepository  # type: ignore[assignment]
    backups: FakeBackupRepository  # type: ignore[assignment]
    restores: FakeRestoreRepository  # type: ignore[assignment]
    environment_backups: FakeEnvironmentBackupRepository  # type: ignore[assignment]
    environment_restores: FakeEnvironmentRestoreRepository  # type: ignore[assignment]
    environment_clones: FakeEnvironmentCloneRepository  # type: ignore[assignment]
    backup_schedules: FakeBackupScheduleRepository  # type: ignore[assignment]
    pod_statuses: FakePodStatusRepository  # type: ignore[assignment]
    deployment_statuses: FakeDeploymentStatusRepository  # type: ignore[assignment]
    utilities: FakeUtilityRepository  # type: ignore[assignment]

    def __init__(
        self,
        clusters: FakeClusterRepository,
        environments: FakeEnvironmentRepository,
        helm_repositories: FakeHelmRepositoryRepository,
        helm_charts: FakeHelmChartRepository,
        application_driver_versions: FakeApplicationRepository,
        instances: FakeApplicationInstanceRepository,
        actions: FakeActionRepository,
        tasks: FakeTaskRepository,
        application_drivers: FakeApplicationDriverRepository | None = None,
        deployments: FakeDeploymentRepository | None = None,
        deployed_services: FakeDeployedServiceRepository | None = None,
        backups: FakeBackupRepository | None = None,
        restores: FakeRestoreRepository | None = None,
        environment_backups: FakeEnvironmentBackupRepository | None = None,
        environment_restores: FakeEnvironmentRestoreRepository | None = None,
        environment_clones: FakeEnvironmentCloneRepository | None = None,
        backup_schedules: FakeBackupScheduleRepository | None = None,
        backup_storage_locations: FakeBackupStorageLocationRepository | None = None,
        pod_statuses: FakePodStatusRepository | None = None,
        deployment_statuses: FakeDeploymentStatusRepository | None = None,
        utilities: FakeUtilityRepository | None = None,
    ):
        self.backup_storage_locations = (
            backup_storage_locations or FakeBackupStorageLocationRepository()
        )
        self.clusters = clusters
        self.environments = environments
        self.helm_repositories = helm_repositories
        self.helm_charts = helm_charts
        self.application_drivers = (
            application_drivers or FakeApplicationDriverRepository()
        )
        self.application_driver_versions = application_driver_versions
        self.instances = instances
        # Alias matching the real UoW's attribute name so service code can
        # use either accessor without divergence.
        self.application_instances = instances
        self.actions = actions
        self.tasks = tasks
        self.deployments = deployments or FakeDeploymentRepository()
        self.deployed_services = deployed_services or FakeDeployedServiceRepository()
        self.backups = backups or FakeBackupRepository()
        self.restores = restores or FakeRestoreRepository()
        self.restores.backup_source = self.backups
        self.restores.instance_source = self.instances
        # The two environment-level guards are EXISTS queries over the
        # constituent rows, so the fakes are handed the constituent repos
        # rather than tracking a status of their own (research.md D6).
        self.environment_backups = (
            environment_backups or FakeEnvironmentBackupRepository()
        )
        self.environment_backups.constituent_source = self.backups
        self.environment_restores = (
            environment_restores or FakeEnvironmentRestoreRepository()
        )
        self.environment_restores.constituent_source = self.restores
        self.environment_restores.parent_source = self.environment_backups
        self.environment_clones = environment_clones or FakeEnvironmentCloneRepository()
        self.environment_clones.restore_source = self.restores
        self.environment_clones.environment_backup_source = self.environment_backups
        self.environment_clones.backup_source = self.backups
        self.environment_clones.environment_source = self.environments
        self.backup_schedules = backup_schedules or FakeBackupScheduleRepository()
        self.pod_statuses = pod_statuses or FakePodStatusRepository()
        self.deployment_statuses = (
            deployment_statuses or FakeDeploymentStatusRepository()
        )
        self.utilities = utilities or FakeUtilityRepository()
        self.session = _FakeSession()  # type: ignore[assignment]

        self.committed = False
        # Total ``commit()`` invocations across the lifetime of this fake.
        # Used by regression tests that need to assert commit cadence
        # (e.g. "the env-config row was committed BEFORE the fanout loop
        # AND the Task rows were committed AFTER the loop"). The boolean
        # ``committed`` flag alone cannot distinguish "one commit total"
        # from "multiple commits"; counting closes that gap.
        self.commit_count = 0
        # Ordered log of commit invocations — append-only — so tests can
        # assert ordering relative to other observable side effects
        # (e.g. ``deployments.save`` calls). Each entry is a monotonically
        # increasing integer; the value is irrelevant beyond the order.
        self.commit_history: list[int] = []

    async def __aenter__(self):
        self.committed = False
        return self

    async def __aexit__(self, *args):
        pass

    async def commit(self):
        self.committed = True
        self.commit_count += 1
        self.commit_history.append(self.commit_count)

    async def rollback(self):
        pass
