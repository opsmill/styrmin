"""Propagation tests for the BackupSchedule GraphQL surface."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import BackupSchedule

from .conftest import gql
from .seeds import seed_deployment


@pytest.mark.asyncio
async def test_create_schedule_persists_all_fields(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session)
    deployment_id = deployment.id

    data = await gql(
        client,
        "create_backup_schedule",
        {
            "deploymentId": str(deployment_id),
            "name": "nightly",
            "cronExpression": "0 2 * * *",
            "retentionCount": 7,
            "enabled": True,
        },
    )
    schedule_id = UUID(data["createBackupSchedule"]["id"])

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

    await gql(
        client,
        "update_backup_schedule",
        {"scheduleId": str(schedule_id), field: value},
    )

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

    await gql(client, "delete_backup_schedule", {"scheduleId": str(schedule_id)})

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

    data = await gql(client, "get_backup_schedule", {"scheduleId": str(schedule.id)})
    row = data["backupSchedule"]
    assert row["name"] == "seeded"
    assert row["cronExpression"] == "0 4 * * *"
    assert row["retentionCount"] == 5
    assert row["enabled"] is False
    assert row["deploymentId"] == str(deployment.id)


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

    data = await gql(
        client,
        "list_backup_schedules",
        {"deploymentId": str(deployment_a.id)},
    )
    names = {row["name"] for row in data["backupSchedules"]}
    assert names == {"sched-a"}
