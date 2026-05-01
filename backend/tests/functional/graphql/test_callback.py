"""Propagation tests for the Callback mutation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Task, TaskStatus, TaskType

from ._queries import load_query
from .seeds import seed_deployment, seed_task


@pytest.mark.asyncio
async def test_callback_running_state_persists_task_status(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session)
    task = await seed_task(
        session,
        deployment=deployment,
        task_type=TaskType.NOOP,
        status=TaskStatus.PENDING,
    )
    task_id = task.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("callback"),
            "variables": {
                "taskId": str(task_id),
                "stateName": "RUNNING",
                "stateMessage": "started running",
                "stateType": "RUNNING",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"]["callback"]["success"] is not False

    session.expire_all()
    refreshed = await session.get(Task, task_id)
    assert refreshed is not None
    assert refreshed.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_callback_completed_state_persists_task_success(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session)
    task = await seed_task(
        session,
        deployment=deployment,
        task_type=TaskType.NOOP,
        status=TaskStatus.RUNNING,
    )
    task_id = task.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("callback"),
            "variables": {
                "taskId": str(task_id),
                "stateName": "COMPLETED",
                "stateMessage": None,
                "stateType": "COMPLETED",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    refreshed = await session.get(Task, task_id)
    assert refreshed is not None
    assert refreshed.status == TaskStatus.SUCCESS


@pytest.mark.asyncio
async def test_callback_unknown_task_returns_error_response(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Negative path: an unknown task_id surfaces a TaskNotFoundError that the
    resolver converts to ``CallbackResponse(success=False)``. Asserts no
    Task row was fabricated."""
    bogus_id = uuid4()
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("callback"),
            "variables": {
                "taskId": str(bogus_id),
                "stateName": "RUNNING",
                "stateMessage": None,
                "stateType": "RUNNING",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    data = payload["data"]["callback"]
    assert data["success"] is False
    assert await session.get(Task, bogus_id) is None
