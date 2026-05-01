"""Propagation tests for the Task GraphQL surface (read-only)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import TaskStatus, TaskType

from .conftest import gql
from .seeds import seed_deployment, seed_task


@pytest.mark.asyncio
async def test_task_projects_all_scalars(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session)
    task = await seed_task(
        session,
        deployment=deployment,
        task_type=TaskType.CREATE_INSTANCE,
        status=TaskStatus.RUNNING,
        message="working on it",
    )

    data = await gql(client, "get_task", {"taskId": str(task.id)})
    row = data["task"]
    assert row["id"] == str(task.id)
    assert row["type"] == TaskType.CREATE_INSTANCE.value
    assert row["status"] == TaskStatus.RUNNING.value
    assert row["message"] == "working on it"
    assert row["deploymentId"] == str(deployment.id)
    assert row["deployment"]["id"] == str(deployment.id)
    assert row["deployment"]["name"] == deployment.name


@pytest.mark.asyncio
async def test_tasks_projects_seeded(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session)
    await seed_task(session, deployment=deployment, task_type=TaskType.CREATE_INSTANCE)
    await seed_task(session, deployment=deployment, task_type=TaskType.UPDATE_INSTANCE)

    data = await gql(client, "list_tasks")
    types = {row["type"] for row in data["tasks"]}
    assert TaskType.CREATE_INSTANCE.value in types
    assert TaskType.UPDATE_INSTANCE.value in types
