"""The telemetry report data (spec 020, FR-002, FR-006, research D6, D9)."""

import json
import tomllib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
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
from styrmin_backend.services.telemetry import payload
from styrmin_backend.services.telemetry.payload import (
    build_report_data,
    styrmin_version,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

FR_006_KEYS = [
    "install_id",
    "styrmin_version",
    "python_version",
    "os_family",
    "arch",
    "cluster_count",
    "environment_count",
    "deployment_count",
    "drivers",
]
DRIVER_KEYS = ["name", "version", "source_type", "deployment_count"]

REPOSITORY_URL = "https://git.example.com/secret-org/secret-drivers.git"
BRANCH_MAIN = "secret-branch-main"
BRANCH_HOTFIX = "secret-branch-hotfix"
SOURCE_PATH = "secret/driver/path"
CLUSTER_NAME = "secret-cluster-name"
ENVIRONMENT_NAMES = ["secret-environment-one", "secret-environment-two"]
DEPLOYMENT_NAMES = ["secret-deployment-a", "secret-deployment-b", "secret-deployment-c"]
FORBIDDEN = [
    REPOSITORY_URL,
    BRANCH_MAIN,
    BRANCH_HOTFIX,
    SOURCE_PATH,
    CLUSTER_NAME,
    *ENVIRONMENT_NAMES,
    *DEPLOYMENT_NAMES,
    "tombstoned-deployment",
]


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'telemetry.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


async def _build(engine: AsyncEngine) -> dict:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        async with SqlModelUnitOfWork(session) as uow:
            data = await build_report_data(uow)
            await uow.commit()
    return data


def _version(
    driver: ApplicationDriver,
    chart: HelmChart,
    version: str,
    source_type: str,
    branch: str,
) -> ApplicationDriverVersion:
    return ApplicationDriverVersion(
        id=uuid4(),
        application_driver_id=driver.id,
        version=version,
        application_supported_versions=">=1.0.0",
        source_type=source_type,
        source_repository=REPOSITORY_URL,
        source_branch=branch,
        source_path=SOURCE_PATH,
        helm_chart_id=chart.id,
    )


@pytest.fixture
async def seeded(engine: AsyncEngine) -> AsyncEngine:
    """Two ``zeta`` rows that differ only in branch, and two ``alpha`` versions, one unused."""
    helm_repo = HelmRepository(id=uuid4(), url="https://charts.example.com")
    chart = HelmChart(
        id=uuid4(),
        name="chart",
        version="0.1.0",
        values_template="",
        repository_id=helm_repo.id,
    )
    zeta = ApplicationDriver(id=uuid4(), name="zeta")
    alpha = ApplicationDriver(id=uuid4(), name="alpha")
    zeta_main = _version(zeta, chart, "1.0.0", "git", BRANCH_MAIN)
    zeta_hotfix = _version(zeta, chart, "1.0.0", "git", BRANCH_HOTFIX)
    alpha_new = _version(alpha, chart, "2.0.0", "local", BRANCH_MAIN)
    alpha_old = _version(alpha, chart, "1.5.0", "local", BRANCH_MAIN)
    cluster = Cluster(id=uuid4(), name=CLUSTER_NAME)
    env_one, env_two = (
        Environment(id=uuid4(), name=name, cluster_id=cluster.id)
        for name in ENVIRONMENT_NAMES
    )
    creator = User(
        id=uuid4(),
        username="telemetry",
        password_hash="x",
        display_name="telemetry",
        role=Role.ADMIN,
    )

    def deployment(
        name: str,
        env: Environment,
        version: ApplicationDriverVersion,
        deleted: bool = False,
    ) -> Deployment:
        return Deployment(
            id=uuid4(),
            name=name,
            application_version="1.0.0",
            status=DeploymentState.DELETED if deleted else DeploymentState.RUNNING,
            deleted_at=datetime.now(UTC) if deleted else None,
            created_by_user_id=creator.id,
            application_driver_version_id=version.id,
            environment_id=env.id,
        )

    async with AsyncSession(engine) as session:
        session.add_all(
            [
                helm_repo,
                chart,
                zeta,
                alpha,
                zeta_main,
                zeta_hotfix,
                alpha_new,
                alpha_old,
            ]
            + [cluster, env_one, env_two, creator]
        )
        await session.flush()
        session.add_all(
            [
                deployment(DEPLOYMENT_NAMES[0], env_one, zeta_main),
                deployment(DEPLOYMENT_NAMES[1], env_two, zeta_main),
                deployment(DEPLOYMENT_NAMES[2], env_one, zeta_hotfix),
                deployment("tombstoned-deployment", env_two, zeta_hotfix, deleted=True),
                deployment("alpha-user", env_two, alpha_old),
            ]
        )
        await session.commit()
    return engine


async def test_data_has_exactly_the_fr_006_keys_in_order(seeded: AsyncEngine) -> None:
    data = await _build(seeded)

    assert list(data) == FR_006_KEYS
    for entry in data["drivers"]:
        assert list(entry) == DRIVER_KEYS


async def test_data_holds_no_source_location_or_names(seeded: AsyncEngine) -> None:
    serialized = json.dumps(await _build(seeded))

    for value in FORBIDDEN:
        assert value not in serialized
    # Every seeded source and name contains "secret", so no fragment of them leaks either.
    assert "secret" not in serialized


async def test_rows_that_differ_only_in_source_are_merged_and_sorted(
    seeded: AsyncEngine,
) -> None:
    data = await _build(seeded)

    assert data["drivers"] == [
        {
            "name": "alpha",
            "version": "1.5.0",
            "source_type": "local",
            "deployment_count": 1,
        },
        {
            "name": "alpha",
            "version": "2.0.0",
            "source_type": "local",
            "deployment_count": 0,
        },
        {
            "name": "zeta",
            "version": "1.0.0",
            "source_type": "git",
            "deployment_count": 3,
        },
    ]


async def test_counts(seeded: AsyncEngine) -> None:
    data = await _build(seeded)

    assert data["cluster_count"] == 1
    assert data["environment_count"] == 2
    assert data["deployment_count"] == 4
    assert data["deployment_count"] == sum(
        d["deployment_count"] for d in data["drivers"]
    )


async def test_install_id_is_stable_across_calls(seeded: AsyncEngine) -> None:
    first = await _build(seeded)
    second = await _build(seeded)

    assert first["install_id"] == second["install_id"]
    assert str(UUID(first["install_id"])) == first["install_id"]


async def test_empty_database(engine: AsyncEngine) -> None:
    data = await _build(engine)

    assert list(data) == FR_006_KEYS
    assert (
        data["cluster_count"],
        data["environment_count"],
        data["deployment_count"],
    ) == (0, 0, 0)
    assert data["drivers"] == []


def test_styrmin_version_reads_the_root_pyproject() -> None:
    root_pyproject = Path(__file__).resolve().parents[5] / "pyproject.toml"
    project = tomllib.loads(root_pyproject.read_text(encoding="utf-8"))["project"]

    assert project["name"] == "styrmin-mvp"
    assert styrmin_version() == project["version"]


def test_styrmin_version_is_unknown_when_the_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(payload, "ROOT_PYPROJECT_PATH", tmp_path / "missing.toml")
    messages: list[str] = []
    handler_id = logger.add(
        lambda message: messages.append(message.record["level"].name), level="DEBUG"
    )
    try:
        assert styrmin_version() == "unknown"
    finally:
        logger.remove(handler_id)

    assert messages == ["DEBUG"]


def test_styrmin_version_is_unknown_for_another_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "pyproject.toml"
    other.write_text(
        '[project]\nname = "styrmin-backend"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    monkeypatch.setattr(payload, "ROOT_PYPROJECT_PATH", other)

    assert styrmin_version() == "unknown"
