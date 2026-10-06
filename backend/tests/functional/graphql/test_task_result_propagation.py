"""``startedByStepId``, ``Task.result`` and the links between tasks reach the caller (spec 019, T072).

Writes: ``startedByStepId`` on ``stopComponents``, ``startComponents`` and
``updateDeploymentVersion`` reaches ``task.started_by_step_id``, and an unknown
step is rejected without creating a task. Reads: seeded tasks and steps reach a
``READ_ONLY`` user as ``Task.result`` (each of the four values, including a
family whose started tasks interrupt each other and a family interrupted by an
outside task), ``Task.startedBy``, ``Task.startedTasks``, ``Step.startedTasks``
and ``Step.supersededBy``, through ``Query.task`` (query fallback) and
``Query.deploymentTimeline`` (read model).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    Deployment as DeploymentRow,
    Role,
    Step as StepRow,
    StepKind,
    StepStatus,
    Task as TaskRow,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query
from .conftest import gql
from .seeds import seed_deployment, seed_task, seed_user

T0 = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
HOOK_KEY = "hook:upgrade:core"
READ_PATHS = ["task", "timeline"]


def _at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest.fixture
async def read_only_token(session: AsyncSession) -> str:
    user = await seed_user(session, role=Role.READ_ONLY)
    _row, token = await create_session(session, user.id)
    return token


@pytest.fixture
def dispatch(prefect_manager_mock: Any, mocker: Any) -> Any:
    async def _run(*_args: Any, **_kwargs: Any) -> Any:
        return type("FlowInfo", (), {"id": uuid4()})()

    prefect_manager_mock.run_action = AsyncMock(side_effect=_run)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    mocker.patch(
        "styrmin_backend.services.deployment.patch_custom_resource", autospec=True
    )
    return prefect_manager_mock


async def _read(
    client: AsyncClient, operation: str, variables: dict[str, Any], token: str
) -> dict[str, Any]:
    response = await client.post(
        "/graphql",
        json={"query": load_query(operation), "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    return payload["data"]


async def _read_tasks(
    client: AsyncClient,
    token: str,
    path: str,
    deployment_id: UUID,
    task_ids: list[UUID],
) -> dict[UUID, dict[str, Any]]:
    """The tasks as one ``Query.task`` each, or as entries of one timeline read."""
    if path == "task":
        return {
            task_id: (
                await _read(client, "get_task_family", {"taskId": str(task_id)}, token)
            )["task"]
            for task_id in task_ids
        }
    data = await _read(
        client,
        "get_deployment_timeline_family",
        {"deploymentId": str(deployment_id)},
        token,
    )
    entries = {
        UUID(entry["task"]["id"]): entry["task"] for entry in data["deploymentTimeline"]
    }
    return {task_id: entries[task_id] for task_id in task_ids}


def _link(task_id: UUID, task_type: TaskType, result: str) -> dict[str, str]:
    return {"id": str(task_id), "type": task_type.value, "result": result}


def _step(task: dict[str, Any], key: str) -> dict[str, Any]:
    (step,) = [step for step in task["steps"] if step["key"] == key]
    return step


# startedByStepId on the three mutations reaches task.started_by_step_id.


@dataclass(frozen=True)
class HookStep:
    deployment_id: UUID
    upgrade_task_id: UUID
    step_id: UUID


@pytest.fixture
async def hook_step(session: AsyncSession) -> HookStep:
    """A running upgrade task whose upgrade hook is running."""
    deployment = await seed_deployment(session)
    upgrade = await seed_task(
        session,
        deployment=deployment,
        task_type=TaskType.UPGRADE_INSTANCE,
        status=TaskStatus.RUNNING,
    )
    hook = StepRow(
        task_id=upgrade.id,
        key=HOOK_KEY,
        name="Run the upgrade hook",
        kind=StepKind.HOOK,
        status=StepStatus.RUNNING,
        started_at=T0,
        attempt_count=1,
    )
    session.add(hook)
    await session.commit()
    return HookStep(deployment.id, upgrade.id, hook.id)


@dataclass(frozen=True)
class StartingMutation:
    field: str
    operation: str
    arguments: dict[str, Any]
    task_type: TaskType


STARTING_MUTATIONS = [
    StartingMutation(
        "stopComponents",
        "stop_components_started_by",
        {"components": []},
        TaskType.STOP_COMPONENTS,
    ),
    StartingMutation(
        "startComponents",
        "start_components_started_by",
        {"components": []},
        TaskType.START_COMPONENTS,
    ),
    StartingMutation(
        "updateDeploymentVersion",
        "update_deployment_version_started_by",
        {"version": "1.0.1"},
        TaskType.UPGRADE_INSTANCE,
    ),
]
MUTATION_PARAMS = [
    pytest.param(mutation, id=mutation.field) for mutation in STARTING_MUTATIONS
]


def _variables(
    mutation: StartingMutation, deployment_id: UUID, step_id: UUID | None
) -> dict[str, Any]:
    return {
        "deploymentId": str(deployment_id),
        **mutation.arguments,
        "startedByStepId": str(step_id) if step_id is not None else None,
    }


@pytest.mark.asyncio
@pytest.mark.usefixtures("dispatch")
@pytest.mark.parametrize("path", READ_PATHS)
@pytest.mark.parametrize("mutation", MUTATION_PARAMS)
async def test_started_by_step_id_reaches_the_task_and_its_links(
    client: AsyncClient,
    unauth_client: AsyncClient,
    session: AsyncSession,
    read_only_token: str,
    hook_step: HookStep,
    mutation: StartingMutation,
    path: str,
) -> None:
    data = await gql(
        client,
        mutation.operation,
        _variables(mutation, hook_step.deployment_id, hook_step.step_id),
    )

    started_id = UUID(data[mutation.field]["id"])
    assert data[mutation.field]["startedByStepId"] == str(hook_step.step_id)
    session.expire_all()
    row = await session.get(TaskRow, started_id)
    assert row is not None
    assert row.started_by_step_id == hook_step.step_id
    assert row.type is mutation.task_type

    tasks = await _read_tasks(
        unauth_client,
        read_only_token,
        path,
        hook_step.deployment_id,
        [started_id, hook_step.upgrade_task_id],
    )
    started, upgrade = tasks[started_id], tasks[hook_step.upgrade_task_id]
    assert started["startedByStepId"] == str(hook_step.step_id)
    assert started["startedBy"] == _link(
        hook_step.upgrade_task_id, TaskType.UPGRADE_INSTANCE, "RUNNING"
    )
    assert upgrade["startedTasks"] == [_link(started_id, mutation.task_type, "RUNNING")]
    assert _step(upgrade, HOOK_KEY)["startedTasks"] == upgrade["startedTasks"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("dispatch")
@pytest.mark.parametrize("mutation", MUTATION_PARAMS)
async def test_omitted_started_by_step_id_leaves_the_task_unlinked(
    client: AsyncClient,
    session: AsyncSession,
    mutation: StartingMutation,
) -> None:
    deployment = await seed_deployment(session)

    data = await gql(
        client, mutation.operation, _variables(mutation, deployment.id, None)
    )

    session.expire_all()
    row = await session.get(TaskRow, UUID(data[mutation.field]["id"]))
    assert row is not None
    assert row.started_by_step_id is None
    assert data[mutation.field]["startedByStepId"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", MUTATION_PARAMS)
async def test_unknown_started_by_step_is_rejected_and_creates_no_task(
    client: AsyncClient,
    session: AsyncSession,
    dispatch: Any,
    mutation: StartingMutation,
) -> None:
    # The failed mutation rolls the shared session back, which expires the row.
    deployment_id = (await seed_deployment(session)).id
    unknown = uuid4()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query(mutation.operation),
            "variables": _variables(mutation, deployment_id, unknown),
        },
    )

    payload = response.json()
    (error,) = payload["errors"]
    assert error["extensions"]["code"] == "NOT_FOUND"
    assert error["message"] == f"Step with id {unknown} not found."
    session.expire_all()
    tasks = (
        await session.exec(
            select(TaskRow).where(TaskRow.deployment_id == deployment_id)
        )
    ).all()
    assert tasks == []
    row = await session.get(DeploymentRow, deployment_id)
    assert row is not None
    assert row.application_version == "1.0.0"
    dispatch.run_action.assert_not_awaited()


# Task.result, Task.startedBy, Task.startedTasks, Step.startedTasks and
# Step.supersededBy: seeded rows reach a READ_ONLY caller.


@dataclass
class Families:
    """Seeded tasks by name, with their expected task results."""

    deployment_id: UUID
    ids: dict[str, UUID]
    types: dict[str, TaskType]
    expected: dict[str, str]

    def link(self, name: str) -> dict[str, str]:
        return _link(self.ids[name], self.types[name], self.expected[name])


class _Seeder:
    def __init__(self, session: AsyncSession, deployment_id: UUID) -> None:
        self.session = session
        self.families = Families(deployment_id, {}, {}, {})
        self._created = 0

    async def task(
        self,
        name: str,
        task_type: TaskType,
        expected: str,
        *,
        status: TaskStatus = TaskStatus.SUCCESS,
        started_by: UUID | None = None,
    ) -> UUID:
        self._created += 1
        row = TaskRow(
            type=task_type,
            status=status,
            deployment_id=self.families.deployment_id,
            started_by_step_id=started_by,
            created_on=_at(self._created),  # Orders the started tasks.
        )
        self.session.add(row)
        await self.session.commit()
        self.families.ids[name] = row.id
        self.families.types[name] = task_type
        self.families.expected[name] = expected
        return row.id

    async def step(
        self,
        task: str,
        key: str,
        status: StepStatus,
        *,
        kind: StepKind = StepKind.OPERATOR_PHASE,
        superseded_by: str | None = None,
        started: int = 0,
    ) -> UUID:
        row = StepRow(
            task_id=self.families.ids[task],
            key=key,
            name=key,
            kind=kind,
            status=status,
            started_at=_at(started) if status is not StepStatus.PENDING else None,
            attempt_count=0 if status is StepStatus.PENDING else 1,
            superseded_by_task_id=(
                self.families.ids[superseded_by] if superseded_by else None
            ),
        )
        self.session.add(row)
        await self.session.commit()
        return row.id


@pytest.fixture
async def families(session: AsyncSession) -> Families:
    """Single tasks for each result, and three families started by upgrade hooks."""
    deployment = await seed_deployment(session)
    seed = _Seeder(session, deployment.id)
    succeeded = StepStatus.SUCCEEDED

    # Single tasks: the steps decide, and a running or failed Task.status also counts.
    await seed.task(
        "running", TaskType.UPDATE_INSTANCE, "RUNNING", status=TaskStatus.RUNNING
    )
    await seed.step("running", "operator:helmrelease", StepStatus.RUNNING)
    await seed.task("failed", TaskType.UPDATE_INSTANCE, "FAILED")
    await seed.step("failed", "operator:helmrelease", StepStatus.FAILED)
    await seed.task("succeeded", TaskType.UPDATE_INSTANCE, "SUCCEEDED")
    await seed.step("succeeded", "operator:ready", succeeded)
    await seed.task(
        "no-steps", TaskType.UPDATE_INSTANCE, "FAILED", status=TaskStatus.FAILED
    )
    # The flow failed, or still runs, after its only recorded step succeeded.
    for name, status, expected in (
        ("flow-failed", TaskStatus.FAILED, "FAILED"),
        ("flow-running", TaskStatus.RUNNING, "RUNNING"),
    ):
        await seed.task(name, TaskType.UPDATE_INSTANCE, expected, status=status)
        await seed.step(name, "plan", succeeded, kind=StepKind.PLAN)

    # Started tasks that interrupt each other: the upgrade counts it as its own work.
    await seed.task("upgrade", TaskType.UPGRADE_INSTANCE, "SUCCEEDED")
    hook = await seed.step("upgrade", HOOK_KEY, succeeded, kind=StepKind.HOOK)
    await seed.task("stop", TaskType.STOP_COMPONENTS, "SUPERSEDED", started_by=hook)
    await seed.task(
        "upgrade-version", TaskType.UPGRADE_INSTANCE, "SUPERSEDED", started_by=hook
    )
    await seed.task("start", TaskType.START_COMPONENTS, "SUCCEEDED", started_by=hook)
    for name, superseded_by in (
        ("stop", "upgrade-version"),
        ("upgrade-version", "start"),
    ):
        await seed.step(
            name,
            "operator:helmrelease",
            StepStatus.SUPERSEDED,
            superseded_by=superseded_by,
        )
    await seed.step("start", "operator:ready", succeeded)

    # A started task interrupted by a task outside the family.
    await seed.task("interrupted-upgrade", TaskType.UPGRADE_INSTANCE, "SUPERSEDED")
    hook = await seed.step(
        "interrupted-upgrade", HOOK_KEY, succeeded, kind=StepKind.HOOK
    )
    await seed.task(
        "interrupted-start", TaskType.START_COMPONENTS, "SUPERSEDED", started_by=hook
    )
    await seed.task("outside", TaskType.UPDATE_INSTANCE, "SUCCEEDED")
    await seed.step(
        "interrupted-start",
        "operator:helmrelease",
        StepStatus.SUPERSEDED,
        superseded_by="outside",
    )
    await seed.step("outside", "operator:ready", succeeded)

    # A started task that failed fails the upgrade.
    await seed.task("failing-upgrade", TaskType.UPGRADE_INSTANCE, "FAILED")
    hook = await seed.step("failing-upgrade", HOOK_KEY, succeeded, kind=StepKind.HOOK)
    await seed.task("failed-stop", TaskType.STOP_COMPONENTS, "FAILED", started_by=hook)
    await seed.step("failed-stop", "operator:prerequisites", StepStatus.FAILED)
    return seed.families


@pytest.mark.asyncio
@pytest.mark.parametrize("path", READ_PATHS)
async def test_task_result_reaches_read_only(
    unauth_client: AsyncClient, read_only_token: str, families: Families, path: str
) -> None:
    tasks = await _read_tasks(
        unauth_client,
        read_only_token,
        path,
        families.deployment_id,
        list(families.ids.values()),
    )

    results = {name: tasks[task_id]["result"] for name, task_id in families.ids.items()}
    assert results == families.expected
    assert set(results.values()) == {"RUNNING", "FAILED", "SUCCEEDED", "SUPERSEDED"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", READ_PATHS)
async def test_started_tasks_and_started_by_reach_read_only(
    unauth_client: AsyncClient, read_only_token: str, families: Families, path: str
) -> None:
    tasks = await _read_tasks(
        unauth_client,
        read_only_token,
        path,
        families.deployment_id,
        list(families.ids.values()),
    )

    upgrade = tasks[families.ids["upgrade"]]
    started = [families.link(name) for name in ("stop", "upgrade-version", "start")]
    assert upgrade["startedTasks"] == started
    assert _step(upgrade, HOOK_KEY)["startedTasks"] == started
    assert upgrade["startedBy"] is None
    for name in ("stop", "upgrade-version", "start"):
        task = tasks[families.ids[name]]
        assert task["startedBy"] == families.link("upgrade")
        assert task["startedTasks"] == []
        assert all(step["startedTasks"] == [] for step in task["steps"])


@pytest.mark.asyncio
@pytest.mark.parametrize("path", READ_PATHS)
async def test_superseded_by_reaches_read_only(
    unauth_client: AsyncClient, read_only_token: str, families: Families, path: str
) -> None:
    tasks = await _read_tasks(
        unauth_client,
        read_only_token,
        path,
        families.deployment_id,
        list(families.ids.values()),
    )

    def superseded_by(name: str) -> dict[str, str] | None:
        step = _step(tasks[families.ids[name]], "operator:helmrelease")
        assert step["status"] == "SUPERSEDED"
        return step["supersededBy"]

    assert superseded_by("stop") == families.link("upgrade-version")
    assert superseded_by("upgrade-version") == families.link("start")
    assert superseded_by("interrupted-start") == families.link("outside")
    assert _step(tasks[families.ids["start"]], "operator:ready")["supersededBy"] is None
