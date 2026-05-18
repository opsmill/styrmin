from uuid import uuid4

import pytest
from styrmin_backend.db.models import Role, User
from styrmin_backend.db.utils import get_session
from styrmin_backend.server.app import app
from styrmin_backend.services.auth.password import hash_password
from styrmin_backend.services.auth.session import create_session
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.pool import StaticPool

from .helpers import (
    get_cluster_query,
    get_clusters_query,
    create_cluster_query,
    delete_cluster_query,
    get_environment_query,
    create_environment_query,
    delete_environment_query,
    ok_query,
    callback_mutation,
    get_deployment_with_environment_query,
    get_deployment_with_adv_query,
    get_deployment_backward_compat_query,
    get_deployment_with_adv_and_driver_query,
    get_backup_with_instance_adv_query,
    get_task_with_deployment_query,
    get_backup_schedule_with_deployment_query,
    get_backup_with_instance_query,
    get_restore_with_backup_query,
)


@pytest.fixture(name="session")
async def session_fixture():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest.fixture(name="client")
async def graphql_fixture(session: AsyncSession):
    """Authenticated-as-admin ASGI client.

    Default-deny is on (ADR-025); this seeds an admin user and a session
    token and pre-attaches the bearer header so existing tests keep
    exercising the production auth path without each having to log in.
    """
    user = User(
        username="test-admin",
        password_hash=hash_password("test-admin-password"),
        display_name="Test Admin",
        active=True,
        role=Role.ADMIN,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    _row, raw_token = await create_session(session, user.id)

    async def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {raw_token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_inexistant_cluster(client: AsyncClient):
    response = await client.post(
        "/graphql",
        json={
            "query": get_cluster_query,
            "variables": {"clusterId": str(uuid4())},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["cluster"] is None
    assert len(data["errors"]) == 1
    assert data["errors"][0]["extensions"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_create_cluster_and_try_to_create_it_again(client: AsyncClient):
    response = await client.post(
        "/graphql",
        json={
            "query": create_cluster_query,
            "variables": {"name": "test_cluster"},
        },
    )

    data = response.json()

    assert response.status_code == 200
    assert data["data"]["createCluster"]["name"] == "test_cluster"
    assert data["data"]["createCluster"]["id"] is not None

    response = await client.post(
        "/graphql",
        json={
            "query": create_cluster_query,
            "variables": {"name": "test_cluster"},
        },
    )

    data = response.json()
    assert response.status_code == 200
    assert data["data"]["createCluster"] is None
    assert len(data["errors"]) == 1
    assert data["errors"][0]["extensions"]["code"] == "CLUSTER_LIMIT_REACHED"


@pytest.mark.asyncio
async def test_try_to_delete_inexistant_cluster(client: AsyncClient):
    response = await client.post(
        "/graphql",
        json={
            "query": delete_cluster_query,
            "variables": {"clusterId": str(uuid4())},
        },
    )

    data = response.json()
    assert response.status_code == 200
    assert data["data"]["deleteCluster"] is None
    assert len(data["errors"]) == 1
    assert data["errors"][0]["extensions"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_create_and_delete_cluster_with_error_support(client: AsyncClient):
    # Create a cluster
    variable = {
        "name": "test_cluster",
        "config": {"runtime_class": "example_runtime_class"},
    }
    response = await client.post(
        "/graphql",
        json={"query": create_cluster_query, "variables": variable},
    )

    data = response.json()

    assert response.status_code == 200
    assert data["data"]["createCluster"]["name"] == "test_cluster"
    assert data["data"]["createCluster"]["id"] is not None
    assert data["data"]["createCluster"]["config"] == {
        "runtime_class": "example_runtime_class",
        "dedicated_ingress": {},
        "ingress_class": "traefik",
    }

    cluster_id = data["data"]["createCluster"]["id"]

    # Get the cluster
    variable = {"clusterId": cluster_id}

    response = await client.post(
        "/graphql",
        json={"query": get_cluster_query, "variables": variable},
    )

    assert response.status_code == 200
    cluster_data = response.json()["data"]["cluster"]
    assert cluster_data["id"] == cluster_id
    assert cluster_data["name"] == "test_cluster"
    assert cluster_data["config"] == {
        "runtime_class": "example_runtime_class",
        "dedicated_ingress": {},
        "ingress_class": "traefik",
    }
    assert cluster_data["createdOn"] is not None
    assert cluster_data["environments"] == []

    # Delete the cluster
    response = await client.post(
        "/graphql",
        json={"query": delete_cluster_query, "variables": variable},
    )

    assert response.status_code == 200
    assert response.json() == {"data": {"deleteCluster": "Cluster deleted"}}


@pytest.mark.asyncio
async def test_create_cluster_with_invalid_config(client: AsyncClient):
    response = await client.post(
        "/graphql",
        json={
            "query": create_cluster_query,
            "variables": {"name": "test_cluster", "config": {"invalid_key": "value"}},
        },
    )

    data = response.json()
    assert response.status_code == 200
    assert data["data"]["createCluster"] is None
    assert len(data["errors"]) == 1
    assert data["errors"][0]["extensions"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_get_an_environment_that_does_not_exist(client: AsyncClient):
    response = await client.post(
        "/graphql",
        json={
            "query": get_environment_query,
            "variables": {"environmentId": str(uuid4())},
        },
    )

    data = response.json()
    assert response.status_code == 200
    assert data["data"]["environment"] is None
    assert len(data["errors"]) == 1
    assert data["errors"][0]["extensions"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_create_an_environment_and_try_to_create_it_again(client: AsyncClient):
    # Create a cluster
    variable = {"name": "test_cluster"}
    response = await client.post(
        "/graphql",
        json={"query": create_cluster_query, "variables": variable},
    )

    data = response.json()

    assert response.status_code == 200
    assert data["data"]["createCluster"]["name"] == "test_cluster"
    assert data["data"]["createCluster"]["id"] is not None

    cluster_id = data["data"]["createCluster"]["id"]

    # Create an environment
    variable = {"name": "test_environment", "clusterId": cluster_id}
    response = await client.post(
        "/graphql",
        json={"query": create_environment_query, "variables": variable},
    )

    data = response.json()

    assert response.status_code == 200
    assert data["data"]["createEnvironment"]["name"] == "test_environment"
    assert data["data"]["createEnvironment"]["id"] is not None
    assert data["data"]["createEnvironment"]["cluster"]["id"] == cluster_id
    assert data["data"]["createEnvironment"]["cluster"]["name"] == "test_cluster"

    # Try to create the same environment again
    variable = {"name": "test_environment", "clusterId": cluster_id}
    response = await client.post(
        "/graphql",
        json={"query": create_environment_query, "variables": variable},
    )

    data = response.json()
    assert response.status_code == 200
    assert data["data"]["createEnvironment"] is None
    assert len(data["errors"]) == 1
    assert data["errors"][0]["extensions"]["code"] == "ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_create_environment_with_invalid_config(client: AsyncClient):
    # Create a cluster
    variable = {"name": "test_cluster"}
    response = await client.post(
        "/graphql",
        json={"query": create_cluster_query, "variables": variable},
    )

    data = response.json()

    assert response.status_code == 200
    assert data["data"]["createCluster"]["name"] == "test_cluster"
    assert data["data"]["createCluster"]["id"] is not None

    cluster_id = data["data"]["createCluster"]["id"]

    # Try to create an environment with an invalid config
    variable = {
        "name": "test_environment",
        "clusterId": cluster_id,
        "config": {"invalid_key": "value"},  # type: ignore[dict-item]
    }
    response = await client.post(
        "/graphql",
        json={"query": create_environment_query, "variables": variable},
    )

    data = response.json()
    assert response.status_code == 200
    assert data["data"]["createEnvironment"] is None
    assert len(data["errors"]) == 1
    assert data["errors"][0]["extensions"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_create_and_delete_environment_with_error_support(client: AsyncClient):
    # Create a cluster
    variable = {"name": "test_cluster"}
    response = await client.post(
        "/graphql",
        json={"query": create_cluster_query, "variables": variable},
    )

    data = response.json()

    assert response.status_code == 200
    assert data["data"]["createCluster"]["name"] == "test_cluster"
    assert data["data"]["createCluster"]["id"] is not None

    cluster_id = data["data"]["createCluster"]["id"]

    # Create an environment
    variable = {
        "name": "test_environment",
        "clusterId": cluster_id,
        "config": {"ingress_class": "example_ingress_class"},  # type: ignore[dict-item]
    }
    response = await client.post(
        "/graphql",
        json={"query": create_environment_query, "variables": variable},
    )

    data = response.json()

    assert response.status_code == 200
    assert data["data"]["createEnvironment"]["name"] == "test_environment"
    assert data["data"]["createEnvironment"]["id"] is not None
    assert data["data"]["createEnvironment"]["cluster"]["id"] == cluster_id
    assert data["data"]["createEnvironment"]["cluster"]["name"] == "test_cluster"
    assert data["data"]["createEnvironment"]["config"] == {
        "ingress_class": "example_ingress_class"
    }

    environment_id = data["data"]["createEnvironment"]["id"]

    # Get the environment
    variable = {"environmentId": environment_id}

    response = await client.post(
        "/graphql",
        json={"query": get_environment_query, "variables": variable},
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "environment": {
                "id": environment_id,
                "name": "test_environment",
                "cluster": {"id": cluster_id, "name": "test_cluster"},
            }
        }
    }

    # Delete the environment
    variable = {"environmentId": environment_id}
    response = await client.post(
        "/graphql",
        json={"query": delete_environment_query, "variables": variable},
    )

    assert response.status_code == 200
    assert response.json() == {"data": {"deleteEnvironment": "Environment deleted"}}


@pytest.mark.asyncio
async def test_delete_inexistant_environment(client: AsyncClient):
    response = await client.post(
        "/graphql",
        json={
            "query": delete_environment_query,
            "variables": {"environmentId": str(uuid4())},
        },
    )

    data = response.json()
    assert response.status_code == 200
    assert data["data"]["deleteEnvironment"] is None
    assert len(data["errors"]) == 1
    assert data["errors"][0]["extensions"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_get_cluster_returns_timestamps(client: AsyncClient):
    # Create a cluster
    response = await client.post(
        "/graphql",
        json={"query": create_cluster_query, "variables": {"name": "ts_cluster"}},
    )
    cluster_id = response.json()["data"]["createCluster"]["id"]

    # Get the cluster and verify timestamps
    response = await client.post(
        "/graphql",
        json={"query": get_cluster_query, "variables": {"clusterId": cluster_id}},
    )

    data = response.json()["data"]["cluster"]
    assert data["createdOn"] is not None
    assert isinstance(data["createdOn"], str)
    assert len(data["createdOn"]) > 0


@pytest.mark.asyncio
async def test_get_cluster_returns_empty_environments(client: AsyncClient):
    # Create a cluster with no environments
    response = await client.post(
        "/graphql",
        json={"query": create_cluster_query, "variables": {"name": "empty_cluster"}},
    )
    cluster_id = response.json()["data"]["createCluster"]["id"]

    # Get the cluster
    response = await client.post(
        "/graphql",
        json={"query": get_cluster_query, "variables": {"clusterId": cluster_id}},
    )

    data = response.json()["data"]["cluster"]
    assert data["environments"] == []


@pytest.mark.asyncio
async def test_get_cluster_returns_environments(client: AsyncClient):
    # Create a cluster
    response = await client.post(
        "/graphql",
        json={"query": create_cluster_query, "variables": {"name": "parent_cluster"}},
    )
    cluster_id = response.json()["data"]["createCluster"]["id"]

    # Create two environments in that cluster
    response = await client.post(
        "/graphql",
        json={
            "query": create_environment_query,
            "variables": {"name": "env_alpha", "clusterId": cluster_id},
        },
    )
    env_alpha_id = response.json()["data"]["createEnvironment"]["id"]

    response = await client.post(
        "/graphql",
        json={
            "query": create_environment_query,
            "variables": {"name": "env_beta", "clusterId": cluster_id},
        },
    )
    env_beta_id = response.json()["data"]["createEnvironment"]["id"]

    # Get the cluster and verify environments are returned
    response = await client.post(
        "/graphql",
        json={"query": get_cluster_query, "variables": {"clusterId": cluster_id}},
    )

    data = response.json()["data"]["cluster"]
    env_ids = {env["id"] for env in data["environments"]}
    env_names = {env["name"] for env in data["environments"]}
    assert len(data["environments"]) == 2
    assert env_ids == {env_alpha_id, env_beta_id}
    assert env_names == {"env_alpha", "env_beta"}


@pytest.mark.asyncio
async def test_list_clusters_returns_environments(client: AsyncClient):
    # Create a cluster with an environment
    response = await client.post(
        "/graphql",
        json={"query": create_cluster_query, "variables": {"name": "list_cluster"}},
    )
    cluster_id = response.json()["data"]["createCluster"]["id"]

    response = await client.post(
        "/graphql",
        json={
            "query": create_environment_query,
            "variables": {"name": "list_env", "clusterId": cluster_id},
        },
    )
    env_id = response.json()["data"]["createEnvironment"]["id"]

    # List all clusters
    response = await client.post(
        "/graphql",
        json={"query": get_clusters_query},
    )

    data = response.json()["data"]["clusters"]
    assert len(data) == 1
    assert data[0]["id"] == cluster_id
    assert data[0]["environments"] == [{"id": env_id, "name": "list_env"}]
    assert data[0]["createdOn"] is not None


@pytest.mark.asyncio
async def test_ok_health_check_on_unified_endpoint(client: AsyncClient):
    """Verify the previously-internal 'ok' query works on /graphql."""
    response = await client.post(
        "/graphql",
        json={"query": ok_query},
    )

    assert response.status_code == 200
    assert response.json() == {"data": {"ok": True}}


@pytest.mark.asyncio
async def test_callback_mutation_on_unified_endpoint(client: AsyncClient):
    """Verify the previously-internal 'callback' mutation works on /graphql."""
    response = await client.post(
        "/graphql",
        json={
            "query": callback_mutation,
            "variables": {
                "taskId": str(uuid4()),
                "stateName": "Running",
                "stateMessage": "test message",
                "stateType": "RUNNING",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    # Task won't exist, so callback should report failure
    assert data["data"]["callback"]["success"] is False
    assert "Task not found" in data["data"]["callback"]["message"]


@pytest.mark.asyncio
async def test_internal_graphql_endpoint_returns_404(client: AsyncClient):
    """Verify the old /internal/graphql endpoint no longer exists."""
    response = await client.post(
        "/internal/graphql",
        json={"query": ok_query},
    )

    # 404 when no frontend dist exists, 405 when SPA static files are mounted
    # (StaticFiles only handles GET/HEAD, so POST returns Method Not Allowed)
    assert response.status_code in (404, 405)


# --- Shared fixture for nested resolver tests ---


@pytest.fixture(name="resolver_data")
async def resolver_data_fixture(session: AsyncSession) -> dict:
    """Insert all entities needed for nested resolver tests, return their IDs."""
    from styrmin_backend.db.models import (
        ApplicationDriver as ApplicationDriverModel,
        ApplicationDriverVersion as ApplicationDriverVersionModel,
        ApplicationInstance as ApplicationInstanceModel,
        Backup as BackupModel,
        BackupSchedule as BackupScheduleModel,
        BackupStatus,
        Cluster as ClusterModel,
        Deployment as DeploymentModel,
        DeploymentState,
        Environment as EnvironmentModel,
        HelmChart as HelmChartModel,
        HelmRepository as HelmRepositoryModel,
        InstanceStatus,
        Restore as RestoreModel,
        RestoreStatus,
        Role,
        Task as TaskModel,
        TaskStatus,
        TaskType,
        User as UserModel,
    )
    from styrmin_backend.services.auth.password import hash_password as _hash_password

    cluster = ClusterModel(name="resolver-test-cluster")
    session.add(cluster)
    await session.flush()

    env = EnvironmentModel(name="resolver-test-env", cluster_id=cluster.id)
    session.add(env)
    await session.flush()

    helm_repo = HelmRepositoryModel(url="https://charts.example.com")
    session.add(helm_repo)
    await session.flush()

    helm_chart = HelmChartModel(
        name="test-chart",
        version="1.0.0",
        values_template="",
        repository_id=helm_repo.id,
    )
    session.add(helm_chart)
    await session.flush()

    app_driver = ApplicationDriverModel(name="resolver-test-driver")
    session.add(app_driver)
    await session.flush()

    adv = ApplicationDriverVersionModel(
        application_driver_id=app_driver.id,
        version="2.0.0",
        application_supported_versions=">=1.0.0",
        source_repository="https://github.com/example/repo",
        helm_chart_id=helm_chart.id,
    )
    session.add(adv)
    await session.flush()

    creator = UserModel(
        username="resolver-test-creator",
        password_hash=_hash_password("seed-password-not-used"),
        display_name="Resolver Test Creator",
        active=True,
        role=Role.ADMIN,
    )
    session.add(creator)
    await session.flush()

    deployment = DeploymentModel(
        name="resolver-test-deployment",
        application_version="1.0.0",
        status=DeploymentState.RUNNING,
        application_driver_version_id=adv.id,
        environment_id=env.id,
        created_by_user_id=creator.id,
    )
    session.add(deployment)
    await session.flush()

    app_instance = ApplicationInstanceModel(
        name="resolver-test-instance",
        application_version="1.0.0",
        status=InstanceStatus.RUNNING,
        deployment_id=deployment.id,
        application_driver_version_id=adv.id,
        context=None,
    )
    session.add(app_instance)
    await session.flush()

    task = TaskModel(
        status=TaskStatus.PENDING,
        type=TaskType.CREATE_INSTANCE,
        deployment_id=deployment.id,
    )
    session.add(task)
    await session.flush()

    schedule = BackupScheduleModel(
        name="resolver-test-schedule",
        cron_expression="0 0 * * *",
        deployment_id=deployment.id,
    )
    session.add(schedule)
    await session.flush()

    backup = BackupModel(
        name="resolver-test-backup",
        status=BackupStatus.COMPLETED,
        instance_id=app_instance.id,
    )
    session.add(backup)
    await session.flush()

    restore = RestoreModel(
        name="resolver-test-restore",
        status=RestoreStatus.COMPLETED,
        target_namespace="default",
        backup_id=backup.id,
    )
    session.add(restore)
    await session.flush()

    await session.commit()

    return {
        "cluster_id": str(cluster.id),
        "environment_id": str(env.id),
        "environment_name": env.name,
        "app_driver_id": str(app_driver.id),
        "app_driver_name": app_driver.name,
        "adv_id": str(adv.id),
        "adv_version": adv.version,
        "deployment_id": str(deployment.id),
        "deployment_name": deployment.name,
        "instance_id": str(app_instance.id),
        "instance_name": app_instance.name,
        "task_id": str(task.id),
        "schedule_id": str(schedule.id),
        "schedule_name": schedule.name,
        "backup_id": str(backup.id),
        "backup_name": backup.name,
        "restore_id": str(restore.id),
        "restore_name": restore.name,
    }


# --- Nested resolver tests ---


@pytest.mark.asyncio
async def test_deployment_environment_resolver(
    client: AsyncClient, resolver_data: dict
):
    """Verify Deployment.environment returns the related environment object."""
    response = await client.post(
        "/graphql",
        json={
            "query": get_deployment_with_environment_query,
            "variables": {"deploymentId": resolver_data["deployment_id"]},
        },
    )

    assert response.status_code == 200
    assert "errors" not in response.json()
    result = response.json()["data"]["deployment"]
    assert result["environmentId"] == resolver_data["environment_id"]
    assert result["environment"]["id"] == resolver_data["environment_id"]
    assert result["environment"]["name"] == resolver_data["environment_name"]


@pytest.mark.asyncio
async def test_deployment_adv_resolver(client: AsyncClient, resolver_data: dict):
    """Verify Deployment.applicationDriverVersion returns the related ADV object."""
    response = await client.post(
        "/graphql",
        json={
            "query": get_deployment_with_adv_query,
            "variables": {"deploymentId": resolver_data["deployment_id"]},
        },
    )

    assert response.status_code == 200
    assert "errors" not in response.json()
    result = response.json()["data"]["deployment"]
    assert result["applicationDriverVersionId"] == resolver_data["adv_id"]
    assert result["applicationDriverVersion"]["id"] == resolver_data["adv_id"]
    assert result["applicationDriverVersion"]["version"] == resolver_data["adv_version"]


@pytest.mark.asyncio
async def test_deployment_backward_compat(client: AsyncClient, resolver_data: dict):
    """Verify existing *Id fields still work unchanged."""
    response = await client.post(
        "/graphql",
        json={
            "query": get_deployment_backward_compat_query,
            "variables": {"deploymentId": resolver_data["deployment_id"]},
        },
    )

    assert response.status_code == 200
    assert "errors" not in response.json()
    result = response.json()["data"]["deployment"]
    assert result["environmentId"] == resolver_data["environment_id"]
    assert result["applicationDriverVersionId"] == resolver_data["adv_id"]


@pytest.mark.asyncio
async def test_adv_application_driver_resolver(
    client: AsyncClient, resolver_data: dict
):
    """Verify ApplicationDriverVersion.applicationDriver returns the parent driver."""
    response = await client.post(
        "/graphql",
        json={
            "query": get_deployment_with_adv_and_driver_query,
            "variables": {"deploymentId": resolver_data["deployment_id"]},
        },
    )

    assert response.status_code == 200
    assert "errors" not in response.json()
    adv = response.json()["data"]["deployment"]["applicationDriverVersion"]
    assert adv["applicationDriver"]["id"] == resolver_data["app_driver_id"]
    assert adv["applicationDriver"]["name"] == resolver_data["app_driver_name"]


@pytest.mark.asyncio
async def test_app_instance_adv_resolver(client: AsyncClient, resolver_data: dict):
    """Verify ApplicationInstance.applicationDriverVersion returns the ADV object."""
    response = await client.post(
        "/graphql",
        json={
            "query": get_backup_with_instance_adv_query,
            "variables": {"backupId": resolver_data["backup_id"]},
        },
    )

    assert response.status_code == 200
    assert "errors" not in response.json()
    instance = response.json()["data"]["backup"]["instance"]
    assert instance is not None
    assert instance["id"] == resolver_data["instance_id"]
    assert instance["applicationDriverVersion"]["id"] == resolver_data["adv_id"]
    assert (
        instance["applicationDriverVersion"]["version"] == resolver_data["adv_version"]
    )


@pytest.mark.asyncio
async def test_task_deployment_resolver(client: AsyncClient, resolver_data: dict):
    """Verify Task.deployment returns the related deployment object."""
    response = await client.post(
        "/graphql",
        json={
            "query": get_task_with_deployment_query,
            "variables": {"taskId": resolver_data["task_id"]},
        },
    )

    assert response.status_code == 200
    assert "errors" not in response.json()
    result = response.json()["data"]["task"]
    assert result["deploymentId"] == resolver_data["deployment_id"]
    assert result["deployment"]["id"] == resolver_data["deployment_id"]
    assert result["deployment"]["name"] == resolver_data["deployment_name"]


@pytest.mark.asyncio
async def test_backup_schedule_deployment_resolver(
    client: AsyncClient, resolver_data: dict
):
    """Verify BackupSchedule.deployment returns the related deployment object."""
    response = await client.post(
        "/graphql",
        json={
            "query": get_backup_schedule_with_deployment_query,
            "variables": {"scheduleId": resolver_data["schedule_id"]},
        },
    )

    assert response.status_code == 200
    assert "errors" not in response.json()
    result = response.json()["data"]["backupSchedule"]
    assert result["deploymentId"] == resolver_data["deployment_id"]
    assert result["deployment"]["id"] == resolver_data["deployment_id"]
    assert result["deployment"]["name"] == resolver_data["deployment_name"]


@pytest.mark.asyncio
async def test_backup_instance_resolver(client: AsyncClient, resolver_data: dict):
    """Verify Backup.instance returns the related ApplicationInstance object."""
    response = await client.post(
        "/graphql",
        json={
            "query": get_backup_with_instance_query,
            "variables": {"backupId": resolver_data["backup_id"]},
        },
    )

    assert response.status_code == 200
    assert "errors" not in response.json()
    result = response.json()["data"]["backup"]
    assert result["instanceId"] == resolver_data["instance_id"]
    assert result["instance"]["id"] == resolver_data["instance_id"]
    assert result["instance"]["name"] == resolver_data["instance_name"]


@pytest.mark.asyncio
async def test_restore_backup_resolver(client: AsyncClient, resolver_data: dict):
    """Verify Restore.backup returns the related Backup object."""
    response = await client.post(
        "/graphql",
        json={
            "query": get_restore_with_backup_query,
            "variables": {"restoreId": resolver_data["restore_id"]},
        },
    )

    assert response.status_code == 200
    assert "errors" not in response.json()
    result = response.json()["data"]["restore"]
    assert result["backupId"] == resolver_data["backup_id"]
    assert result["backup"]["id"] == resolver_data["backup_id"]
    assert result["backup"]["name"] == resolver_data["backup_name"]


# --- Status filter validation ---


_LIST_BACKUPS_QUERY = """
    query ListBackups($instanceId: UUID!, $status: BackupStatus) {
        backups(instanceId: $instanceId, status: $status) {
            id
            status
        }
    }
"""

_LIST_RESTORES_QUERY = """
    query ListRestores($backupId: UUID!, $status: RestoreStatus) {
        restores(backupId: $backupId, status: $status) {
            id
            status
        }
    }
"""


@pytest.mark.asyncio
async def test_list_backups_rejects_invalid_status(
    client: AsyncClient, resolver_data: dict
):
    """Invalid backup status filter values are rejected at the schema boundary."""
    response = await client.post(
        "/graphql",
        json={
            "query": _LIST_BACKUPS_QUERY,
            "variables": {
                "instanceId": resolver_data["instance_id"],
                "status": "NOT_A_REAL_STATUS",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("data") is None
    assert len(payload["errors"]) >= 1
    assert any(
        "BackupStatus" in err["message"] or "NOT_A_REAL_STATUS" in err["message"]
        for err in payload["errors"]
    )


@pytest.mark.asyncio
async def test_list_backups_accepts_valid_status(
    client: AsyncClient, resolver_data: dict
):
    """A valid enum value is accepted and returns matching backups."""
    response = await client.post(
        "/graphql",
        json={
            "query": _LIST_BACKUPS_QUERY,
            "variables": {
                "instanceId": resolver_data["instance_id"],
                "status": "COMPLETED",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload
    assert payload["data"]["backups"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_list_restores_rejects_invalid_status(
    client: AsyncClient, resolver_data: dict
):
    """Invalid restore status filter values are rejected at the schema boundary."""
    response = await client.post(
        "/graphql",
        json={
            "query": _LIST_RESTORES_QUERY,
            "variables": {
                "backupId": resolver_data["backup_id"],
                "status": "NOT_A_REAL_STATUS",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("data") is None
    assert len(payload["errors"]) >= 1
    assert any(
        "RestoreStatus" in err["message"] or "NOT_A_REAL_STATUS" in err["message"]
        for err in payload["errors"]
    )


@pytest.mark.asyncio
async def test_list_restores_accepts_valid_status(
    client: AsyncClient, resolver_data: dict
):
    """A valid enum value is accepted and returns matching restores."""
    response = await client.post(
        "/graphql",
        json={
            "query": _LIST_RESTORES_QUERY,
            "variables": {
                "backupId": resolver_data["backup_id"],
                "status": "COMPLETED",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload
    assert payload["data"]["restores"][0]["status"] == "completed"
