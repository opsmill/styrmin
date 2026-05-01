"""Propagation tests for the Callback mutation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Task, TaskStatus, TaskType

from .conftest import gql
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

    data = await gql(
        client,
        "callback",
        {
            "taskId": str(task_id),
            "stateName": "RUNNING",
            "stateMessage": "started running",
            "stateType": "RUNNING",
        },
    )
    assert data["callback"]["success"] is True

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

    await gql(
        client,
        "callback",
        {
            "taskId": str(task_id),
            "stateName": "COMPLETED",
            "stateMessage": None,
            "stateType": "COMPLETED",
        },
    )

    session.expire_all()
    refreshed = await session.get(Task, task_id)
    assert refreshed is not None
    assert refreshed.status == TaskStatus.SUCCESS


@pytest.mark.asyncio
async def test_callback_unknown_task_returns_error_response(
    client: AsyncClient, session: AsyncSession
) -> None:
    """An unknown task_id surfaces a TaskNotFoundError that the resolver converts
    to ``CallbackResponse(success=False)`` — the resolver itself does not raise,
    so this stays inside the success-payload contract that ``gql`` enforces."""
    bogus_id = uuid4()
    data = await gql(
        client,
        "callback",
        {
            "taskId": str(bogus_id),
            "stateName": "RUNNING",
            "stateMessage": None,
            "stateType": "RUNNING",
        },
    )
    assert data["callback"]["success"] is False
    assert await session.get(Task, bogus_id) is None
