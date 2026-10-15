from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from styrmin_backend.context.models.components import ComponentsContext
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.db.utils import get_session
from styrmin_backend.server.app import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


def make_global_context(deployment_id: UUID | None = None) -> GlobalContext:
    deployment_id = deployment_id or uuid4()
    chart_id = uuid4()
    repo_id = uuid4()
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment_id,
            namespace="test-ns",
            release_reference="test-ref",
        ),
        app=ApplicationContext(
            name="test-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=chart_id,
                    name="test-chart",
                    version="1.0.0",
                    values_template="",
                ),
                repository=RepositoryInfo(id=repo_id, url="https://charts.example.com"),
            ),
        ),
        labels={},
        components=None,
        utilities=[],
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
async def client_fixture(session: AsyncSession):
    async def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_context_success(client: AsyncClient):
    deployment_id = uuid4()
    mock_context = make_global_context(deployment_id)

    with patch(
        "styrmin_backend.api.rest.deployments.generate_context_from_deployment_id",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = mock_context
        response = await client.get(f"/deployments/{deployment_id}/context")

    assert response.status_code == 200
    data = response.json()
    assert "cluster" in data
    assert "environment" in data
    assert "deployment" in data
    assert "instance" in data
    assert "app" in data
    assert data["instance"]["deployment_id"] == str(deployment_id)


@pytest.mark.asyncio
async def test_get_context_deployment_not_found(client: AsyncClient):
    deployment_id = uuid4()
    response = await client.get(f"/deployments/{deployment_id}/context")

    assert response.status_code == 404
    assert str(deployment_id) in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_context_invalid_uuid(client: AsyncClient):
    # FastAPI returns 422 for path parameter validation errors
    response = await client.get("/deployments/not-a-uuid/context")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_context_generation_fails(client: AsyncClient):
    deployment_id = uuid4()

    with patch(
        "styrmin_backend.api.rest.deployments.generate_context_from_deployment_id",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.side_effect = RuntimeError("database connection lost")
        response = await client.get(f"/deployments/{deployment_id}/context")

    assert response.status_code == 500
    assert "Context generation failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_context_omits_an_unset_replica_override(client: AsyncClient):
    """An agent of the release before 023 rejects any ``replica_override`` key (023)."""
    deployment_id = uuid4()
    context = make_global_context(deployment_id)
    context.components = ComponentsContext.model_validate(
        {
            name: {
                "config": {"identifier": {"label": {"app": name}}},
                "name": name,
                "enabled": True,
                "replica_override": override,
            }
            for name, override in (("server", None), ("worker", 3))
        }
    )

    with patch(
        "styrmin_backend.api.rest.deployments.generate_context_from_deployment_id",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = context
        response = await client.get(f"/deployments/{deployment_id}/context")

    assert response.status_code == 200
    components = response.json()["components"]
    assert "replica_override" not in components["server"]
    assert components["worker"]["replica_override"] == 3
