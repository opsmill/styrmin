"""Propagation tests for the ``deploymentId`` argument of the ``backups`` query (#304).

``backups(deploymentId:)`` lists the deployment's backup history: the backups of
every instance the deployment has had, so a backup stays listed after an
upgrade gives the deployment a new instance. ``backups(instanceId:)`` keeps
listing one instance's backups, and the service rejects both or neither id.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationInstance,
    Backup,
    BackupStatus,
)

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_application_instance,
    seed_deployment,
)

BASE_TIME = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class BackupHistory:
    deployment_id: str
    old_instance_id: str
    new_instance_id: str
    old_backup_id: str
    new_backup_id: str
    other_deployment_backup_id: str


async def _seed_backup(
    session: AsyncSession,
    instance: ApplicationInstance,
    *,
    status: BackupStatus,
    created_on: datetime,
) -> Backup:
    backup = Backup(
        name=f"backup-{uuid4().hex[:8]}",
        status=status,
        instance_id=instance.id,
        created_on=created_on,
    )
    session.add(backup)
    await session.commit()
    return backup


@pytest.fixture
async def history(session: AsyncSession) -> BackupHistory:
    """A deployment upgraded from 1.0.0 to 2.0.0 with a backup of each instance.

    A second deployment's backup sits between the two in time, so a missing
    deployment filter would show up in the middle of the list.
    """
    adv_v1 = await seed_application_driver_version(session, version="1.0.0")
    driver = await session.get(ApplicationDriver, adv_v1.application_driver_id)
    adv_v2 = await seed_application_driver_version(
        session, driver=driver, version="2.0.0"
    )
    deployment = await seed_deployment(session, adv=adv_v2)
    old_instance = await seed_application_instance(
        session, deployment=deployment, adv=adv_v1
    )
    new_instance = await seed_application_instance(
        session, deployment=deployment, adv=adv_v2
    )
    deployment.active_application_instance_id = new_instance.id
    session.add(deployment)
    await session.commit()

    other_instance = await seed_application_instance(session)

    old_backup = await _seed_backup(
        session, old_instance, status=BackupStatus.COMPLETED, created_on=BASE_TIME
    )
    other_backup = await _seed_backup(
        session,
        other_instance,
        status=BackupStatus.COMPLETED,
        created_on=BASE_TIME + timedelta(minutes=30),
    )
    new_backup = await _seed_backup(
        session,
        new_instance,
        status=BackupStatus.FAILED,
        created_on=BASE_TIME + timedelta(hours=1),
    )

    return BackupHistory(
        deployment_id=str(deployment.id),
        old_instance_id=str(old_instance.id),
        new_instance_id=str(new_instance.id),
        old_backup_id=str(old_backup.id),
        new_backup_id=str(new_backup.id),
        other_deployment_backup_id=str(other_backup.id),
    )


@pytest.mark.asyncio
async def test_backups_by_deployment_id_lists_every_instance_newest_first(
    client: AsyncClient, history: BackupHistory
) -> None:
    data = await gql(
        client, "list_backup_history", {"deploymentId": history.deployment_id}
    )
    rows = data["backups"]

    assert [row["id"] for row in rows] == [
        history.new_backup_id,
        history.old_backup_id,
    ]
    new_row, old_row = rows
    assert new_row["instanceId"] == history.new_instance_id
    assert new_row["instance"] == {
        "id": history.new_instance_id,
        "applicationVersion": "2.0.0",
    }
    assert old_row["instanceId"] == history.old_instance_id
    assert old_row["instance"] == {
        "id": history.old_instance_id,
        "applicationVersion": "1.0.0",
    }
    assert history.other_deployment_backup_id not in {row["id"] for row in rows}


@pytest.mark.asyncio
async def test_backups_by_deployment_id_filters_by_status(
    client: AsyncClient, history: BackupHistory
) -> None:
    data = await gql(
        client,
        "list_backup_history",
        {"deploymentId": history.deployment_id, "status": "COMPLETED"},
    )

    assert [(row["id"], row["status"]) for row in data["backups"]] == [
        (history.old_backup_id, BackupStatus.COMPLETED.value)
    ]


@pytest.mark.asyncio
async def test_backups_by_unknown_deployment_id_returns_empty_list(
    client: AsyncClient, history: BackupHistory
) -> None:
    data = await gql(client, "list_backup_history", {"deploymentId": str(uuid4())})

    assert data["backups"] == []


@pytest.mark.asyncio
async def test_backups_by_inactive_instance_id_returns_only_its_backups(
    client: AsyncClient, history: BackupHistory
) -> None:
    data = await gql(
        client, "list_backup_history", {"instanceId": history.old_instance_id}
    )

    assert [row["id"] for row in data["backups"]] == [history.old_backup_id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("use_deployment_id", "use_instance_id", "message"),
    [
        (True, True, "Provide either deployment_id or instance_id, not both"),
        (False, False, "Either deployment_id or instance_id is required"),
    ],
    ids=["both", "neither"],
)
async def test_backups_with_both_or_neither_id_is_a_validation_error(
    client: AsyncClient,
    history: BackupHistory,
    use_deployment_id: bool,
    use_instance_id: bool,
    message: str,
) -> None:
    variables: dict[str, Any] = {}
    if use_deployment_id:
        variables["deploymentId"] = history.deployment_id
    if use_instance_id:
        variables["instanceId"] = history.old_instance_id

    response = await client.post(
        "/graphql",
        json={"query": load_query("list_backup_history"), "variables": variables},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] is None, payload
    [error] = payload["errors"]
    # The service message proves AmbiguousIdentifierError raised it, not graphql-core.
    assert error["message"] == message, payload
    assert error["path"] == ["backups"], payload
    assert error["extensions"]["code"] == "VALIDATION_ERROR", payload
