import pytest
from fast_depends import dependency_provider

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    BackupStorageLocation,
    Cluster,
    Environment,
    HelmChart,
    HelmRepository,
)
from styrmin_backend.services.workflow import StyrminWorkflowExecutor
from styrmin_backend.services.workflow.dependency import get_workflow_executor
from styrmin_backend.services.workflow.local import WorkflowLocalExecutor
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeBackupStorageLocationRepository,
    FakeClusterRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


@pytest.fixture
def workflow_executor_mock(mocker):
    workflow_mock = mocker.Mock(spec=WorkflowLocalExecutor)

    def get_fake_workflow_executor() -> StyrminWorkflowExecutor:
        return workflow_mock

    dependency_provider.dependency_overrides[get_workflow_executor] = (
        get_fake_workflow_executor
    )
    yield workflow_mock
    dependency_provider.dependency_overrides.clear()


@pytest.fixture
def prefect_manager_mock(mocker):
    manager_mock = mocker.Mock(spec=PrefectManager)

    def get_fake_manager(catalogue=None, workflow_executor=None) -> PrefectManager:
        return manager_mock

    dependency_provider.dependency_overrides[get_manager] = get_fake_manager
    yield manager_mock
    dependency_provider.dependency_overrides.clear()


@pytest.fixture
def fake_cluster_repository():
    return FakeClusterRepository()


@pytest.fixture
def fake_environment_repository():
    return FakeEnvironmentRepository()


@pytest.fixture
def fake_helm_repository_repository():
    return FakeHelmRepositoryRepository()


@pytest.fixture
def fake_helm_chart_repository():
    return FakeHelmChartRepository()


@pytest.fixture
def fake_application_repository():
    return FakeApplicationRepository()


@pytest.fixture
def fake_application_instance_repository():
    return FakeApplicationInstanceRepository()


# Create all fixture for fake elements insertions in repositories


@pytest.fixture
async def fake_cluster(fake_cluster_repository: FakeClusterRepository):
    """Insert a fake cluster in the repository and return it."""
    return await fake_cluster_repository.create(Cluster(name="test_cluster"))


@pytest.fixture
async def fake_environment(
    fake_cluster: Cluster, fake_environment_repository: FakeEnvironmentRepository
):
    """Insert a fake environment bound to a previously inserted fake cluster in the repository and return it."""
    return await fake_environment_repository.create(
        Environment(name="test_environment", cluster_id=fake_cluster.id)
    )


@pytest.fixture
async def fake_helm_repository(
    fake_helm_repository_repository: FakeHelmRepositoryRepository,
):
    """Insert a fake helm repository in the repository and return it."""
    return await fake_helm_repository_repository.create(
        HelmRepository(url="test_repository")
    )


@pytest.fixture
async def fake_helm_chart(
    fake_helm_repository: HelmRepository,
    fake_helm_chart_repository: FakeHelmChartRepository,
):
    """Insert a fake helm chart bound to a previously inserted fake helm repository in the repository and return it."""
    return await fake_helm_chart_repository.create(
        HelmChart(
            repository_id=fake_helm_repository.id,
            version="1.0.0",
            name="test_chart",
            values_template="""
                name: {{ app.name }}
                version: {{ app.version }}
                fqdn_suffix: {{ instance.fqdn_suffix }}
                ingress_class: {{ instance.ingress_class }}
                db_size: {{ instance.db_size }}
                ip_whitelist: {{ instance.ip_whitelist }}
                runtime_class: {{ instance.runtime_class }}
                node_selector: {{ instance.node_selector }}
                dedicated_ingress: {{ instance.dedicated_ingress }}
            """,
        )
    )


@pytest.fixture
async def fake_application(
    fake_helm_chart: HelmChart, fake_application_repository: FakeApplicationRepository
):
    """Insert a fake application bound to a previously inserted fake helm chart in the repository and return it."""
    # Create an ApplicationDriver to set the relationship
    app_driver = ApplicationDriver(name="test_application")
    app_driver_version = ApplicationDriverVersion(
        version="1.0.0",
        application_supported_versions=">=1.0.0",
        helm_chart_id=fake_helm_chart.id,
        source_type="git",
        source_repository="https://github.com/test/repo",
        source_branch="main",
        source_path=None,
        application_driver_id=app_driver.id,
    )
    # Set the relationship manually for the fake
    app_driver_version.application_driver = app_driver
    # Add name property as expected by instantiate_application
    # (implementation accesses application.name directly with type: ignore)
    object.__setattr__(app_driver_version, "name", "test_application")
    return await fake_application_repository.create(app_driver_version)


@pytest.fixture
def fake_backup_storage_location_repository():
    return FakeBackupStorageLocationRepository()


@pytest.fixture
async def fake_backup_storage_location(
    fake_backup_storage_location_repository: FakeBackupStorageLocationRepository,
):
    """Insert a fake backup storage location in the repository and return it."""
    bsl = BackupStorageLocation(
        name="test-bsl",
        endpoint="https://s3.example.com",
        bucket="test-bucket",
        region="us-east-1",
        access_key_id="AKIAIOSFODNN7EXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        environments=[],
    )
    return await fake_backup_storage_location_repository.create(bsl)


@pytest.fixture
def fake_action_respository():
    """Return a fake action repository."""
    return FakeActionRepository()


@pytest.fixture
def fake_task_repository():
    """Return a fake task repository."""
    return FakeTaskRepository()


@pytest.fixture
def uow(
    fake_cluster_repository,
    fake_environment_repository,
    fake_helm_repository_repository,
    fake_helm_chart_repository,
    fake_application_repository,
    fake_application_instance_repository,
    fake_action_respository,
    fake_task_repository,
    fake_backup_storage_location_repository,
):
    return FakeUnitOfWork(
        clusters=fake_cluster_repository,
        environments=fake_environment_repository,
        helm_repositories=fake_helm_repository_repository,
        helm_charts=fake_helm_chart_repository,
        application_driver_versions=fake_application_repository,
        instances=fake_application_instance_repository,
        actions=fake_action_respository,
        tasks=fake_task_repository,
        backup_storage_locations=fake_backup_storage_location_repository,
    )
