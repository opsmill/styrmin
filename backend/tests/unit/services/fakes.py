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
    HelmChart,
    HelmRepository,
    PodStatus,
    Restore,
    RestoreStatus,
    Task,
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
from styrmin_backend.repository.deployment_status import (
    DeploymentStatusRepository,
)
from styrmin_backend.repository.pod_status import PodStatusRepository
from styrmin_backend.repository.helm_chart import HelmChartRepository
from styrmin_backend.repository.helm_repository import HelmRepositoryRepository
from styrmin_backend.repository.restore import RestoreRepository
from styrmin_backend.repository.tasks import TaskRepository
from styrmin_backend.services.unit_of_work import UnitOfWork

ModelType = TypeVar("ModelType")


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

    async def get_by_source_path_and_version(
        self, application_driver_id: UUID, source_path: str, version: str
    ) -> ApplicationDriverVersion | None:
        for application in self.models:
            if (
                application.application_driver_id == application_driver_id
                and application.source_path == source_path
                and application.version == version
            ):
                return application
        return None


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
            if d.environment_id == environment_id and d.internal:
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


class _FakeSession:
    async def refresh(self, obj: object) -> None:
        pass


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
    backup_schedules: FakeBackupScheduleRepository  # type: ignore[assignment]
    pod_statuses: FakePodStatusRepository  # type: ignore[assignment]
    deployment_statuses: FakeDeploymentStatusRepository  # type: ignore[assignment]

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
        backup_schedules: FakeBackupScheduleRepository | None = None,
        backup_storage_locations: FakeBackupStorageLocationRepository | None = None,
        pod_statuses: FakePodStatusRepository | None = None,
        deployment_statuses: FakeDeploymentStatusRepository | None = None,
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
        self.backup_schedules = backup_schedules or FakeBackupScheduleRepository()
        self.pod_statuses = pod_statuses or FakePodStatusRepository()
        self.deployment_statuses = (
            deployment_statuses or FakeDeploymentStatusRepository()
        )
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
