"""The deployment timeline reads the steps of its tasks with a fixed number of queries.

Spec 019, T039 (research D14). ``deploymentTimeline`` runs through the real
schema against a real database; the operation lists every field the timeline
read model must serve, so a field that falls back to a query per task or per
step makes the count grow with the number of tasks.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import strawberry
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.api.schema.mutation import Mutation
from styrmin_backend.api.schema.query import Query
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
from styrmin_backend.domain.models import (
    Step,
    StepError,
    StepKind,
    StepParent,
    StepStatus,
    Task,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

OPERATION = (
    Path(__file__).parent / "graphql" / "get_deployment_timeline_read_model.graphql"
).read_text()

STEPS_PER_TASK = 10
T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
SCHEMA = strawberry.Schema(query=Query, mutation=Mutation)


@pytest.fixture(params=["sqlite", "postgresql"])
def database_url(request: pytest.FixtureRequest) -> str:
    if request.param == "postgresql":
        return request.getfixturevalue("postgres_url")
    return "sqlite+aiosqlite://"


@pytest.fixture
async def engine(database_url: str) -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def uow(engine: AsyncEngine) -> AsyncGenerator[SqlModelUnitOfWork, None]:
    async with (
        AsyncSession(engine, expire_on_commit=False) as session,
        SqlModelUnitOfWork(session=session) as uow,
    ):
        yield uow


async def _seed_deployment(session: AsyncSession, name: str) -> UUID:
    cluster = Cluster(name=f"{name}-cluster")
    helm_repository = HelmRepository(url=f"https://charts.example.com/{name}")
    driver = ApplicationDriver(name=f"{name}-driver")
    session.add_all([cluster, helm_repository, driver])
    await session.flush()
    chart = HelmChart(
        name="app",
        version="1.0.0",
        values_template="",
        repository_id=helm_repository.id,
    )
    environment = Environment(name=f"{name}-env", cluster_id=cluster.id)
    user = User(
        username=f"{name}-user", password_hash="x", display_name=name, role=Role.ADMIN
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
        name=name,
        application_version="1.0.0",
        status=DeploymentState.RUNNING,
        application_driver_version_id=driver_version.id,
        environment_id=environment.id,
        created_by_user_id=user.id,
    )
    session.add(deployment)
    await session.flush()
    return deployment.id


def _steps_of(task: Task) -> list[Step]:
    """Nine started steps, the last one failed twice, and one pending step."""
    steps: list[Step] = []
    for index in range(STEPS_PER_TASK - 1):
        started = T0 + timedelta(minutes=index)
        step = Step.create(
            StepParent.of_task(task.id),
            f"step:{index}",
            f"Step {index}",
            StepKind.OPERATOR_PHASE if index else StepKind.PLAN,
            StepStatus.SUCCEEDED,
            started,
        )
        step.ended_at = started + timedelta(seconds=30)
        steps.append(step)
    failed = steps[-1]
    failed.status = StepStatus.FAILED
    failed.attempt_count = 2
    failed.errors = [
        StepError(attempt=1, message="first", occurred_at=T0),
        StepError(attempt=2, message="second", occurred_at=T0),
    ]
    failed.output = "tail\n"
    steps.append(
        Step.create(
            StepParent.of_task(task.id),
            "operator:ready",
            "Wait until the deployment is ready",
            StepKind.OPERATOR_PHASE,
        )
    )
    return steps


async def _seed_timeline(uow: SqlModelUnitOfWork, name: str, tasks: int) -> UUID:
    deployment_id = await _seed_deployment(uow.session, name)
    for _ in range(tasks):
        task = Task.create(
            type=TaskType.UPGRADE_INSTANCE,
            deployment_id=deployment_id,
            status=TaskStatus.SUCCESS,
        )
        await uow.tasks.save(task)
        await uow.session.flush()
        for step in _steps_of(task):
            await uow.steps.save(step)
    await uow.session.commit()
    return deployment_id


@contextmanager
def _count_selects(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record(
        conn: Any,  # noqa: ARG001
        cursor: Any,  # noqa: ARG001
        statement: str,
        parameters: Any,  # noqa: ARG001
        context: Any,  # noqa: ARG001
        executemany: bool,  # noqa: ARG001
    ) -> None:
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)


@dataclass(frozen=True)
class TimelineRead:
    entries: list[dict[str, Any]]
    queries: list[str]


async def _read_timeline(
    engine: AsyncEngine, uow: SqlModelUnitOfWork, deployment_id: UUID
) -> TimelineRead:
    uow.session.expire_all()
    with _count_selects(engine) as queries:
        result = await SCHEMA.execute(
            OPERATION,
            variable_values={"deploymentId": str(deployment_id)},
            context_value={"uow": uow},
        )
    assert result.errors is None, result.errors
    assert result.data is not None
    return TimelineRead(entries=result.data["deploymentTimeline"], queries=queries)


async def test_timeline_query_count_does_not_grow_with_tasks(
    engine: AsyncEngine, uow: SqlModelUnitOfWork
) -> None:
    one_task = await _seed_timeline(uow, "one-task", tasks=1)
    twenty_tasks = await _seed_timeline(uow, "twenty-tasks", tasks=20)

    small = await _read_timeline(engine, uow, one_task)
    large = await _read_timeline(engine, uow, twenty_tasks)

    assert len(large.entries) == 20
    assert all(len(e["task"]["steps"]) == STEPS_PER_TASK for e in large.entries)
    assert len(large.queries) == len(small.queries), large.queries
    # Tasks, instances and the steps of all tasks.
    assert len(large.queries) <= 3, large.queries


async def test_timeline_steps_are_grouped_by_task_in_start_order(
    engine: AsyncEngine, uow: SqlModelUnitOfWork
) -> None:
    deployment_id = await _seed_timeline(uow, "ordered", tasks=3)

    read = await _read_timeline(engine, uow, deployment_id)

    for entry in read.entries:
        steps = entry["task"]["steps"]
        assert {step["taskId"] for step in steps} == {entry["task"]["id"]}
        assert [step["key"] for step in steps] == [
            *(f"step:{index}" for index in range(STEPS_PER_TASK - 1)),
            "operator:ready",
        ]
        failed = steps[STEPS_PER_TASK - 2]
        assert failed["status"] == "FAILED"
        assert failed["error"] == "second"
        assert failed["attemptCount"] == 2
        assert failed["hasOutput"] is True
        assert failed["durationSeconds"] == 30.0
        assert steps[-1]["status"] == "PENDING"
        assert steps[-1]["startedAt"] is None
