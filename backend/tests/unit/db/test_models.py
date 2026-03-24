import pytest
from styrmin_backend.db.models import Cluster, Environment
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.fixture
async def session():
    """Create a new database for testing."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=True)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def cluster(session: AsyncSession):
    cluster = Cluster(name="test_cluster")
    session.add(cluster)

    await session.commit()
    await session.refresh(cluster)

    return cluster


@pytest.mark.asyncio
async def test_create_cluster(session: AsyncSession):
    cluster = Cluster(name="test_cluster")
    session.add(cluster)

    await session.commit()
    await session.refresh(cluster, ["environments"])

    assert cluster.id is not None
    assert cluster.name == "test_cluster"
    assert cluster.environments == []


@pytest.mark.asyncio
async def test_create_environment(session: AsyncSession, cluster: Cluster):
    environment = Environment(name="test_environment", cluster_id=cluster.id)
    session.add(environment)

    await session.commit()
    await session.refresh(environment, ["cluster"])

    assert environment.id is not None
    assert environment.name == "test_environment"
    assert environment.cluster_id == cluster.id
    assert environment.config is None
    assert environment.cluster == cluster
