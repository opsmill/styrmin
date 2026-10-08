"""Count and driver-usage queries that the telemetry report reads (spec 020, D1, D9)."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    Cluster,
    Deployment,
    DeploymentState,
    Environment,
    HelmChart,
    HelmRepository,
    Role,
    User,
)
from styrmin_backend.repository.application_driver_version import (
    DriverVersionUsage,
    SQLModelApplicationDriverVersionRepository,
)
from styrmin_backend.repository.cluster import SQLModelClusterRepository
from styrmin_backend.repository.deployment import SQLModelDeploymentRepository
from styrmin_backend.repository.environment import SQLModelEnvironmentRepository


def _driver_version(
    driver: ApplicationDriver, chart: HelmChart, version: str, source_type: str
) -> ApplicationDriverVersion:
    return ApplicationDriverVersion(
        id=uuid4(),
        application_driver_id=driver.id,
        version=version,
        application_supported_versions=">=1.0.0",
        source_type=source_type,
        source_repository="https://example.com/drivers.git",
        source_branch="main",
        helm_chart_id=chart.id,
    )


def _deployment(
    name: str,
    *,
    environment: Environment,
    driver_version: ApplicationDriverVersion,
    creator: User,
    internal: bool = False,
    deleted: bool = False,
) -> Deployment:
    return Deployment(
        id=uuid4(),
        name=name,
        application_version="1.0.0",
        internal=internal,
        status=DeploymentState.DELETED if deleted else DeploymentState.RUNNING,
        deleted_at=datetime.now(UTC) if deleted else None,
        created_by_user_id=creator.id,
        application_driver_version_id=driver_version.id,
        environment_id=environment.id,
    )


async def _seed(session: AsyncSession) -> None:
    """One cluster, two environments; version A has 3 deployments (1 tombstoned, 1 internal), B has none."""
    helm_repo = HelmRepository(id=uuid4(), url="https://example.com/charts")
    chart = HelmChart(
        id=uuid4(),
        name="chart",
        version="0.1.0",
        values_template="",
        repository_id=helm_repo.id,
    )
    alpha = ApplicationDriver(id=uuid4(), name="alpha")
    beta = ApplicationDriver(id=uuid4(), name="beta")
    version_a = _driver_version(alpha, chart, "1.0.0", "git")
    version_b = _driver_version(beta, chart, "2.0.0", "local")
    cluster = Cluster(id=uuid4(), name="cluster-one")
    env_one = Environment(id=uuid4(), name="env-one", cluster_id=cluster.id)
    env_two = Environment(id=uuid4(), name="env-two", cluster_id=cluster.id)
    creator = User(
        id=uuid4(),
        username="telemetry-counts",
        password_hash="x",
        display_name="telemetry-counts",
        role=Role.ADMIN,
    )
    deployments = [
        _deployment(
            "app", environment=env_one, driver_version=version_a, creator=creator
        ),
        _deployment(
            "ingress",
            environment=env_two,
            driver_version=version_a,
            creator=creator,
            internal=True,
        ),
        _deployment(
            "retired",
            environment=env_two,
            driver_version=version_a,
            creator=creator,
            deleted=True,
        ),
    ]
    session.add_all(
        [
            helm_repo,
            chart,
            alpha,
            beta,
            version_a,
            version_b,
            cluster,
            env_one,
            env_two,
            creator,
        ]
    )
    await session.flush()
    session.add_all(deployments)
    await session.flush()


async def test_empty_database_gives_zeros_and_no_driver_versions(
    session: AsyncSession,
) -> None:
    assert await SQLModelClusterRepository(session).count() == 0
    assert await SQLModelEnvironmentRepository(session).count() == 0
    assert await SQLModelDeploymentRepository(session).count_live() == 0
    assert await SQLModelApplicationDriverVersionRepository(session).list_usage() == []


async def test_counts_exclude_tombstoned_deployments(session: AsyncSession) -> None:
    await _seed(session)

    assert await SQLModelClusterRepository(session).count() == 1
    assert await SQLModelEnvironmentRepository(session).count() == 2
    assert await SQLModelDeploymentRepository(session).count_live() == 2


async def test_usage_lists_every_driver_version_with_live_deployments(
    session: AsyncSession,
) -> None:
    await _seed(session)

    usage = await SQLModelApplicationDriverVersionRepository(session).list_usage()

    assert sorted(usage, key=lambda row: row.name) == [
        DriverVersionUsage(
            name="alpha", version="1.0.0", source_type="git", deployment_count=2
        ),
        DriverVersionUsage(
            name="beta", version="2.0.0", source_type="local", deployment_count=0
        ),
    ]


async def test_usage_query_runs_on_postgresql(postgres_url: str) -> None:
    """PostgreSQL rejects a GROUP BY that SQLite accepts, so the query runs on both."""
    engine = create_async_engine(postgres_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await _seed(session)
            usage = await SQLModelApplicationDriverVersionRepository(
                session
            ).list_usage()
            live = await SQLModelDeploymentRepository(session).count_live()
    finally:
        await engine.dispose()

    assert live == 2
    assert sorted(usage, key=lambda row: row.name) == [
        DriverVersionUsage(
            name="alpha", version="1.0.0", source_type="git", deployment_count=2
        ),
        DriverVersionUsage(
            name="beta", version="2.0.0", source_type="local", deployment_count=0
        ),
    ]


async def test_internal_deployment_is_counted(session: AsyncSession) -> None:
    """Only the internal deployment is live in the seed when ``app`` is tombstoned."""
    await _seed(session)
    app = (await session.exec(select(Deployment).where(Deployment.name == "app"))).one()
    app.deleted_at = datetime.now(UTC)
    await session.flush()

    usage = await SQLModelApplicationDriverVersionRepository(session).list_usage()

    assert await SQLModelDeploymentRepository(session).count_live() == 1
    assert next(row for row in usage if row.name == "alpha").deployment_count == 1


async def test_usage_query_does_not_read_the_driver_source(
    session: AsyncSession,
) -> None:
    await _seed(session)
    statements: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _many) -> None:  # noqa: ANN001
        statements.append(statement)

    engine = session.bind.sync_engine  # type: ignore[union-attr]
    event.listen(engine, "before_cursor_execute", record)
    try:
        await SQLModelApplicationDriverVersionRepository(session).list_usage()
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(statements) == 1
    for column in (
        "source_repository",
        "source_branch",
        "source_path",
        "content_hash",
        "source_commit_sha",
    ):
        assert column not in statements[0]
