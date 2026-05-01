"""Propagation tests for the Task GraphQL surface (read-only)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import TaskStatus, TaskType

from .seeds import seed_deployment, seed_task

get_task_query = """
    query GetTask($taskId: UUID!) {
        task(taskId: $taskId) {
            id
            type
            status
            message
            deploymentId
            deployment {
                id
                name
            }
        }
    }
"""

list_tasks_query = """
    query ListTasks {
        tasks {
            id
            type
            status
        }
    }
"""


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

    response = await client.post(
        "/graphql",
        json={"query": get_task_query, "variables": {"taskId": str(task.id)}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    data = payload["data"]["task"]
    assert data["id"] == str(task.id)
    assert data["type"] == TaskType.CREATE_INSTANCE.value
    assert data["status"] == TaskStatus.RUNNING.value
    assert data["message"] == "working on it"
    assert data["deploymentId"] == str(deployment.id)
    assert data["deployment"]["id"] == str(deployment.id)
    assert data["deployment"]["name"] == deployment.name


@pytest.mark.asyncio
async def test_tasks_projects_seeded(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session)
    await seed_task(session, deployment=deployment, task_type=TaskType.CREATE_INSTANCE)
    await seed_task(session, deployment=deployment, task_type=TaskType.UPDATE_INSTANCE)

    response = await client.post("/graphql", json={"query": list_tasks_query})
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    types = {row["type"] for row in payload["data"]["tasks"]}
    assert TaskType.CREATE_INSTANCE.value in types
    assert TaskType.UPDATE_INSTANCE.value in types
