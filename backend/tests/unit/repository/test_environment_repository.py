import pytest
from styrmin_backend.db.models import Cluster, Environment
from styrmin_backend.repository.cluster import SQLModelClusterRepository
from styrmin_backend.repository.environment import SQLModelEnvironmentRepository
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.fixture
async def test_cluster(session: AsyncSession):
    repository = SQLModelClusterRepository(session)
    cluster_name = "test_cluster"

    cluster = await repository.create(Cluster(name=cluster_name))

    return cluster


@pytest.mark.asyncio
async def test_get_environment_by_name(test_cluster: Cluster, session: AsyncSession):
    repository = SQLModelEnvironmentRepository(session)
    env_name = "test_env"

    environment = await repository.create(
        Environment(name=env_name, cluster_id=test_cluster.id)
    )

    result = await repository.get_by_name(env_name)
    assert result == environment


@pytest.mark.asyncio
async def test_get_environment_by_name_on_inexisting_name(session: AsyncSession):
    repository = SQLModelEnvironmentRepository(session)
    env_name = "test_env"

    result = await repository.get_by_name(env_name)
    assert result is None
