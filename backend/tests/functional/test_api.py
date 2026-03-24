from uuid import uuid4

import pytest
from styrmin_backend.db.utils import get_session
from styrmin_backend.server.app import app
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
    async def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
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
    assert data["errors"][0]["extensions"]["code"] == "ALREADY_EXISTS"


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
    assert cluster_data["config"] == {"runtime_class": "example_runtime_class"}
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
