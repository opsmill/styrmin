from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import TracebackType

from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.repository.action import ActionRepository, SQLModelActionRepository
from styrmin_backend.repository.backup_storage_location import (
    BackupStorageLocationRepository,
    SQLModelBackupStorageLocationRepository,
)
from styrmin_backend.repository.deployment_status import (
    DeploymentStatusRepository,
    SQLModelDeploymentStatusRepository,
)
from styrmin_backend.repository.application_driver import (
    ApplicationDriverRepository,
    SQLModelApplicationDriverRepository,
)
from styrmin_backend.repository.application_driver_version import (
    ApplicationDriverVersionRepository,
    SQLModelApplicationDriverVersionRepository,
)
from styrmin_backend.repository.backup import (
    BackupRepository,
    SQLModelBackupRepository,
)
from styrmin_backend.repository.backup_schedule import (
    BackupScheduleRepository,
    SQLModelBackupScheduleRepository,
)
from styrmin_backend.repository.cluster import (
    ClusterRepository,
    SQLModelClusterRepository,
)
from styrmin_backend.repository.deployed_service import (
    DeployedServiceRepository,
    SQLModelDeployedServiceRepository,
)
from styrmin_backend.repository.component_config import (
    ComponentConfigRepository,
    SQLModelComponentConfigRepository,
)
from styrmin_backend.repository.deployment import (
    DeploymentRepository,
    SQLModelDeploymentRepository,
)
from styrmin_backend.repository.environment import (
    EnvironmentRepository,
    SQLModelEnvironmentRepository,
)
from styrmin_backend.repository.environment_backup import (
    EnvironmentBackupRepository,
    EnvironmentRestoreRepository,
    SQLModelEnvironmentBackupRepository,
    SQLModelEnvironmentRestoreRepository,
)
from styrmin_backend.repository.environment_clone import (
    EnvironmentCloneRepository,
    SQLModelEnvironmentCloneRepository,
)
from styrmin_backend.repository.helm_chart import (
    HelmChartRepository,
    SQLModelHelmChartRepository,
)
from styrmin_backend.repository.helm_repository import (
    HelmRepositoryRepository,
    SQLModelHelmRepositoryRepository,
)
from styrmin_backend.repository.application_instance import (
    ApplicationInstanceRepository,
    SQLModelApplicationInstanceRepository,
)
from styrmin_backend.repository.restore import (
    RestoreRepository,
    SQLModelRestoreRepository,
)
from styrmin_backend.repository.pod_status import (
    PodStatusRepository,
    SQLModelPodStatusRepository,
)
from styrmin_backend.repository.steps import SQLModelStepRepository, StepRepository
from styrmin_backend.repository.tasks import SQLModelTaskRepository, TaskRepository
from styrmin_backend.repository.utility import (
    SQLModelUtilityRepository,
    UtilityRepository,
)


class UnitOfWork(ABC):
    session: AsyncSession
    backup_storage_locations: BackupStorageLocationRepository
    clusters: ClusterRepository
    environments: EnvironmentRepository
    helm_repositories: HelmRepositoryRepository
    helm_charts: HelmChartRepository
    component_configs: ComponentConfigRepository
    application_drivers: ApplicationDriverRepository
    application_driver_versions: ApplicationDriverVersionRepository
    application_instances: ApplicationInstanceRepository
    actions: ActionRepository
    utilities: UtilityRepository
    tasks: TaskRepository
    steps: StepRepository
    deployments: DeploymentRepository
    deployed_services: DeployedServiceRepository
    backups: BackupRepository
    restores: RestoreRepository
    environment_backups: EnvironmentBackupRepository
    environment_restores: EnvironmentRestoreRepository
    environment_clones: EnvironmentCloneRepository
    backup_schedules: BackupScheduleRepository
    pod_statuses: PodStatusRepository
    deployment_statuses: DeploymentStatusRepository

    async def __aenter__(self) -> "UnitOfWork":
        return self

    @abstractmethod
    async def rollback(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def commit(self) -> None:
        raise NotImplementedError

    async def __aexit__(
        self,
        type_: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if type_ is not None:
            await self.rollback()
        return None


class SqlModelUnitOfWork(UnitOfWork):
    backup_storage_locations: SQLModelBackupStorageLocationRepository
    clusters: SQLModelClusterRepository
    environments: SQLModelEnvironmentRepository
    helm_repositories: SQLModelHelmRepositoryRepository
    helm_charts: SQLModelHelmChartRepository
    component_configs: SQLModelComponentConfigRepository
    application_drivers: SQLModelApplicationDriverRepository
    application_driver_versions: SQLModelApplicationDriverVersionRepository
    application_instances: SQLModelApplicationInstanceRepository
    actions: SQLModelActionRepository
    utilities: SQLModelUtilityRepository
    tasks: SQLModelTaskRepository
    steps: SQLModelStepRepository
    deployments: SQLModelDeploymentRepository
    deployed_services: SQLModelDeployedServiceRepository
    backups: SQLModelBackupRepository
    restores: SQLModelRestoreRepository
    environment_backups: SQLModelEnvironmentBackupRepository
    environment_restores: SQLModelEnvironmentRestoreRepository
    environment_clones: SQLModelEnvironmentCloneRepository
    backup_schedules: SQLModelBackupScheduleRepository
    pod_statuses: SQLModelPodStatusRepository
    deployment_statuses: SQLModelDeploymentStatusRepository

    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def __aenter__(self) -> "SqlModelUnitOfWork":
        self.backup_storage_locations = SQLModelBackupStorageLocationRepository(
            session=self.session
        )
        self.clusters = SQLModelClusterRepository(session=self.session)
        self.environments = SQLModelEnvironmentRepository(session=self.session)
        self.helm_repositories = SQLModelHelmRepositoryRepository(session=self.session)
        self.helm_charts = SQLModelHelmChartRepository(session=self.session)
        self.component_configs = SQLModelComponentConfigRepository(session=self.session)
        self.application_drivers = SQLModelApplicationDriverRepository(
            session=self.session
        )
        self.application_driver_versions = SQLModelApplicationDriverVersionRepository(
            session=self.session
        )
        self.application_instances = SQLModelApplicationInstanceRepository(
            session=self.session
        )
        self.actions = SQLModelActionRepository(session=self.session)
        self.utilities = SQLModelUtilityRepository(session=self.session)
        self.tasks = SQLModelTaskRepository(session=self.session)
        self.steps = SQLModelStepRepository(session=self.session)
        self.deployments = SQLModelDeploymentRepository(session=self.session)
        self.deployed_services = SQLModelDeployedServiceRepository(session=self.session)
        self.backups = SQLModelBackupRepository(session=self.session)
        self.restores = SQLModelRestoreRepository(session=self.session)
        self.environment_backups = SQLModelEnvironmentBackupRepository(
            session=self.session
        )
        self.environment_restores = SQLModelEnvironmentRestoreRepository(
            session=self.session
        )
        self.environment_clones = SQLModelEnvironmentCloneRepository(
            session=self.session
        )
        self.backup_schedules = SQLModelBackupScheduleRepository(session=self.session)
        self.pod_statuses = SQLModelPodStatusRepository(session=self.session)
        self.deployment_statuses = SQLModelDeploymentStatusRepository(
            session=self.session
        )
        return self

    async def rollback(self) -> None:
        await self.session.rollback()

    async def commit(self) -> None:
        await self.session.commit()


@asynccontextmanager
async def get_unit_of_work() -> AsyncGenerator[SqlModelUnitOfWork, None]:
    """Yield a UnitOfWork on a fresh session for standalone use (outside FastAPI DI).

    Mirrors ``get_unit_of_work_dependency``: the session is closed on exit, while
    ``async with uow`` blocks inside stay transaction boundaries only.
    """
    from styrmin_backend.db.utils import get_async_engine

    async with AsyncSession(get_async_engine(), expire_on_commit=False) as session:
        uow = SqlModelUnitOfWork(session=session)
        async with uow:
            yield uow
