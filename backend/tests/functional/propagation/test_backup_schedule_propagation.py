"""Propagation tests for the BackupSchedule GraphQL surface."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import BackupSchedule

from .seeds import seed_deployment

create_schedule_mutation = """
    mutation CreateSchedule(
        $deploymentId: UUID!,
        $name: String!,
        $cronExpression: String!,
        $retentionCount: Int!,
        $enabled: Boolean!
    ) {
        createBackupSchedule(
            deploymentId: $deploymentId,
            name: $name,
            cronExpression: $cronExpression,
            retentionCount: $retentionCount,
            enabled: $enabled
        ) {
            id
            name
        }
    }
"""

update_schedule_mutation = """
    mutation UpdateSchedule(
        $scheduleId: UUID!,
        $name: String,
        $cronExpression: String,
        $retentionCount: Int,
        $enabled: Boolean
    ) {
        updateBackupSchedule(
            scheduleId: $scheduleId,
            name: $name,
            cronExpression: $cronExpression,
            retentionCount: $retentionCount,
            enabled: $enabled
        ) {
            id
        }
    }
"""

delete_schedule_mutation = """
    mutation DeleteSchedule($scheduleId: UUID!) {
        deleteBackupSchedule(scheduleId: $scheduleId)
    }
"""

get_schedule_query = """
    query GetSchedule($scheduleId: UUID!) {
        backupSchedule(scheduleId: $scheduleId) {
            id
            name
            enabled
            cronExpression
            retentionCount
            deploymentId
        }
    }
"""

list_schedules_query = """
    query ListSchedules($deploymentId: UUID!) {
        backupSchedules(deploymentId: $deploymentId) {
            id
            name
        }
    }
"""


@pytest.mark.asyncio
async def test_create_schedule_persists_all_fields(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session)
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": create_schedule_mutation,
            "variables": {
                "deploymentId": str(deployment_id),
                "name": "nightly",
                "cronExpression": "0 2 * * *",
                "retentionCount": 7,
                "enabled": True,
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    schedule_id = UUID(payload["data"]["createBackupSchedule"]["id"])

    db_row = await session.get(BackupSchedule, schedule_id)
    assert db_row is not None
    assert db_row.name == "nightly"
    assert db_row.cron_expression == "0 2 * * *"
    assert db_row.retention_count == 7
    assert db_row.enabled is True
    assert db_row.deployment_id == deployment_id


@pytest.mark.parametrize(
    "field, value, db_attr",
    [
        ("name", "renamed", "name"),
        ("cronExpression", "0 5 * * *", "cron_expression"),
        ("retentionCount", 30, "retention_count"),
        ("enabled", False, "enabled"),
    ],
)
@pytest.mark.asyncio
async def test_update_schedule_persists_field_changes(
    client: AsyncClient,
    session: AsyncSession,
    field: str,
    value: object,
    db_attr: str,
) -> None:
    deployment = await seed_deployment(session)
    schedule = BackupSchedule(
        name="seed-schedule",
        cron_expression="0 0 * * *",
        retention_count=10,
        enabled=True,
        deployment_id=deployment.id,
    )
    session.add(schedule)
    await session.commit()
    schedule_id = schedule.id

    response = await client.post(
        "/graphql",
        json={
            "query": update_schedule_mutation,
            "variables": {"scheduleId": str(schedule_id), field: value},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    refreshed = await session.get(BackupSchedule, schedule_id)
    assert refreshed is not None
    assert getattr(refreshed, db_attr) == value


@pytest.mark.asyncio
async def test_delete_schedule_removes_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session)
    schedule = BackupSchedule(
        name="to-delete",
        cron_expression="0 0 * * *",
        deployment_id=deployment.id,
    )
    session.add(schedule)
    await session.commit()
    schedule_id = schedule.id

    response = await client.post(
        "/graphql",
        json={
            "query": delete_schedule_mutation,
            "variables": {"scheduleId": str(schedule_id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    assert await session.get(BackupSchedule, schedule_id) is None


@pytest.mark.asyncio
async def test_schedule_projects_all_scalars(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session)
    schedule = BackupSchedule(
        name="seeded",
        cron_expression="0 4 * * *",
        retention_count=5,
        enabled=False,
        deployment_id=deployment.id,
    )
    session.add(schedule)
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": get_schedule_query,
            "variables": {"scheduleId": str(schedule.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    data = payload["data"]["backupSchedule"]
    assert data["name"] == "seeded"
    assert data["cronExpression"] == "0 4 * * *"
    assert data["retentionCount"] == 5
    assert data["enabled"] is False
    assert data["deploymentId"] == str(deployment.id)


@pytest.mark.asyncio
async def test_schedules_filters_by_deployment(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment_a = await seed_deployment(session, name="dep-a")
    deployment_b = await seed_deployment(session, name="dep-b")
    schedule_a = BackupSchedule(
        name="sched-a", cron_expression="0 0 * * *", deployment_id=deployment_a.id
    )
    schedule_b = BackupSchedule(
        name="sched-b", cron_expression="0 0 * * *", deployment_id=deployment_b.id
    )
    session.add_all([schedule_a, schedule_b])
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": list_schedules_query,
            "variables": {"deploymentId": str(deployment_a.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    rows = payload["data"]["backupSchedules"]
    names = {row["name"] for row in rows}
    assert names == {"sched-a"}
