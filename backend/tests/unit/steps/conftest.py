"""Step storage fixtures: a real database on SQLite and on PostgreSQL."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    ApplicationInstance,
    Backup,
    BackupStatus,
    Cluster,
    Deployment,
    DeploymentState,
    Environment,
    HelmChart,
    HelmRepository,
    InstanceStatus,
    Restore,
    RestoreStatus,
    Role,
    User,
)
from styrmin_backend.db.models import Task as TaskModel
from styrmin_backend.domain.models import Task, TaskType
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork


@pytest.fixture(params=["sqlite", "postgresql"])
def database_url(request: pytest.FixtureRequest) -> str:
    # A sync fixture, so it can request the async ``postgres_url`` fixture.
    if request.param == "postgresql":
        return request.getfixturevalue("postgres_url")
    return "sqlite+aiosqlite://"


@pytest.fixture
async def session(database_url: str) -> AsyncGenerator[AsyncSession, None]:
    """A session on a schema built by ``create_all``, as the server builds it."""
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def uow(session: AsyncSession) -> AsyncGenerator[SqlModelUnitOfWork, None]:
    async with SqlModelUnitOfWork(session=session) as uow:
        yield uow


# Before the server's clock, so tasks that a test creates are newer.
TASK_CREATED_ON = datetime(2026, 1, 1, tzinfo=UTC)
OTHER_TASK_CREATED_ON = datetime(2026, 1, 2, tzinfo=UTC)


async def set_created_on(
    uow: SqlModelUnitOfWork, task_id: UUID, created_on: datetime
) -> None:
    """Set the creation time that orders tasks, which the database otherwise sets."""
    model = await uow.session.get(TaskModel, task_id)
    assert model is not None
    model.created_on = created_on
    await uow.session.flush()


@dataclass(frozen=True)
class Parents:
    """One deployment with an instance, a backup, a restore and two tasks.

    ``other_task`` is newer than ``task``.
    """

    deployment_id: UUID
    instance_id: UUID
    backup_id: UUID
    restore_id: UUID
    task: Task
    other_task: Task


@pytest.fixture
async def parents(uow: SqlModelUnitOfWork) -> Parents:
    session = uow.session
    cluster = Cluster(name="steps-cluster")
    helm_repository = HelmRepository(url="https://charts.example.com")
    driver = ApplicationDriver(name="steps-driver")
    session.add_all([cluster, helm_repository, driver])
    await session.flush()
    chart = HelmChart(
        name="app",
        version="1.0.0",
        values_template="",
        repository_id=helm_repository.id,
    )
    environment = Environment(name="steps-env", cluster_id=cluster.id)
    user = User(
        username="steps-user", password_hash="x", display_name="steps", role=Role.ADMIN
    )
    session.add_all([chart, environment, user])
    await session.flush()
    driver_version = ApplicationDriverVersion(
        application_driver_id=driver.id,
        version="1.0.0",
        application_supported_versions="*",
        source_repository="https://git.example.com/driver.git",
        helm_chart_id=chart.id,
    )
    session.add(driver_version)
    await session.flush()
    deployment = Deployment(
        name="steps-deployment",
        application_version="1.0.0",
        status=DeploymentState.RUNNING,
        application_driver_version_id=driver_version.id,
        environment_id=environment.id,
        created_by_user_id=user.id,
        last_instance_sequence=1,
    )
    session.add(deployment)
    await session.flush()
    instance = ApplicationInstance(
        name="steps-instance",
        application_version="1.0.0",
        status=InstanceStatus.RUNNING,
        deployment_id=deployment.id,
        application_driver_version_id=driver_version.id,
        sequence=1,
    )
    session.add(instance)
    await session.flush()
    backup = Backup(
        name="steps-backup", status=BackupStatus.COMPLETED, instance_id=instance.id
    )
    session.add(backup)
    await session.flush()
    restore = Restore(
        name="steps-restore",
        status=RestoreStatus.IN_PROGRESS,
        target_namespace="steps",
        backup_id=backup.id,
    )
    session.add(restore)

    task = Task.create(
        type=TaskType.UPGRADE_INSTANCE,
        deployment_id=deployment.id,
        instance_id=instance.id,
    )
    other_task = Task.create(type=TaskType.UPDATE_INSTANCE, deployment_id=deployment.id)
    await uow.tasks.save(task)
    await uow.tasks.save(other_task)
    await session.flush()
    # Tasks saved in one transaction share their creation time.
    await set_created_on(uow, task.id, TASK_CREATED_ON)
    await set_created_on(uow, other_task.id, OTHER_TASK_CREATED_ON)
    return Parents(
        deployment_id=deployment.id,
        instance_id=instance.id,
        backup_id=backup.id,
        restore_id=restore.id,
        task=task,
        other_task=other_task,
    )
