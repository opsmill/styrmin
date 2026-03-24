import pytest
from styrmin_backend.db.models import Cluster
from styrmin_backend.repository.cluster import SQLModelClusterRepository
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.mark.asyncio
async def test_get_cluster_by_name(session: AsyncSession):
    repository = SQLModelClusterRepository(session)
    cluster_name = "test_cluster"

    cluster = await repository.create(Cluster(name=cluster_name))

    result = await repository.get_by_name(cluster_name)
    assert result == cluster


@pytest.mark.asyncio
async def test_get_cluster_by_name_on_inexisting_name(session: AsyncSession):
    repository = SQLModelClusterRepository(session)
    cluster_name = "test_cluster"

    result = await repository.get_by_name(cluster_name)
    assert result is None
