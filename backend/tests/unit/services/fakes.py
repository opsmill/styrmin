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
    Environment,
    HelmChart,
    HelmRepository,
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


class FakeDeploymentRepository(DeploymentRepository):
    """Fake deployment repository for testing purposes."""

    def __init__(self) -> None:
        self._deployments: list[DeploymentEntity] = []

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

    async def get_by_name(self, name: str) -> DeploymentEntity | None:
        for d in self._deployments:
            if d.name == name:
                return d
        return None

    async def find_names_with_prefix(self, prefix: str) -> list[str]:
        return [d.name for d in self._deployments if d.name.startswith(prefix)]

    async def find_internal_by_environment(
        self, environment_id: UUID
    ) -> DeploymentEntity | None:
        for d in self._deployments:
            if d.environment_id == environment_id and d.internal:
                return d
        return None


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
        self.actions = actions
        self.tasks = tasks
        self.deployments = deployments or FakeDeploymentRepository()
        self.deployed_services = deployed_services or FakeDeployedServiceRepository()
        self.backups = backups or FakeBackupRepository()
        self.restores = restores or FakeRestoreRepository()
        self.backup_schedules = backup_schedules or FakeBackupScheduleRepository()
        self.session = _FakeSession()  # type: ignore[assignment]

        self.committed = False

    async def __aenter__(self):
        self.committed = False
        return self

    async def __aexit__(self, *args):
        pass

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass
