"""Propagation tests for the ``deploymentId`` argument of the ``backups`` query (#304).

``backups(deploymentId:)`` lists the deployment's backup history: the backups of
every instance the deployment has had, so a backup stays listed after an
upgrade, a config edit, a refresh or an environment config change gives the
deployment a new instance. ``backups(instanceId:)`` keeps listing one
instance's backups, and the service rejects both or neither id.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
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
    ApplicationDriver,
    ApplicationInstance,
    Backup,
    BackupStatus,
    Deployment,
    DeploymentState,
)
from styrmin_backend.services.deployment import refresh_deployment
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_application_instance,
    seed_deployment,
    seed_environment,
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


# ---------------------------------------------------------------------------
# The four operations that give a deployment a new instance (research R2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeployedWithBackup:
    deployment_id: UUID
    name: str
    driver_name: str
    environment_id: UUID
    instance_id: UUID
    backup_id: UUID


def _arm_prefect(prefect_manager_mock: Any) -> None:
    """Return concrete flow ids so a dispatched reconcile binds real UUIDs."""
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())


async def _deploy_with_completed_backup(
    client: AsyncClient, session: AsyncSession
) -> DeployedWithBackup:
    """Deploy application version 1.0.0, then record a completed backup of its instance.

    A second driver version supports only 2.x, so the upgrade to 2.0.0 rebinds.
    """
    adv_v1 = await seed_application_driver_version(
        session, version="1", application_supported_versions=">=1.0,<2.0"
    )
    driver = await session.get(ApplicationDriver, adv_v1.application_driver_id)
    assert driver is not None
    driver_name = driver.name
    await seed_application_driver_version(
        session,
        driver=driver,
        version="2",
        application_supported_versions=">=2.0,<3.0",
    )
    environment = await seed_environment(session)
    environment_id = environment.id

    await gql(
        client,
        "deploy_with_driver_version",
        {
            "driver": driver_name,
            "environmentId": str(environment_id),
            "name": "history-app",
            "version": "1.0.0",
        },
    )
    session.expire_all()
    deployment = (
        await session.exec(select(Deployment).where(Deployment.name == "history-app"))
    ).one()
    deployment_id = deployment.id
    instance_id = deployment.active_application_instance_id
    assert instance_id is not None
    instance = await session.get(ApplicationInstance, instance_id)
    assert instance is not None
    assert instance.application_version == "1.0.0"

    backup = await _seed_backup(
        session, instance, status=BackupStatus.COMPLETED, created_on=BASE_TIME
    )
    return DeployedWithBackup(
        deployment_id=deployment_id,
        name="history-app",
        driver_name=driver_name,
        environment_id=environment_id,
        instance_id=instance_id,
        backup_id=backup.id,
    )


async def _upgrade(
    client: AsyncClient, session: AsyncSession, seeded: DeployedWithBackup
) -> None:
    await gql(
        client,
        "update_deployment_version",
        {"deploymentId": str(seeded.deployment_id), "version": "2.0.0"},
    )


async def _edit_config(
    client: AsyncClient, session: AsyncSession, seeded: DeployedWithBackup
) -> None:
    await gql(
        client,
        "update_deployment_config",
        {
            "deploymentId": str(seeded.deployment_id),
            "input": {"ipWhitelist": ["10.0.0.0/8"]},
        },
    )


async def _refresh(
    client: AsyncClient, session: AsyncSession, seeded: DeployedWithBackup
) -> None:
    # No GraphQL field, CLI command or flow calls refresh_deployment (research R2).
    await refresh_deployment(seeded.deployment_id, SqlModelUnitOfWork(session=session))


async def _change_environment_config(
    client: AsyncClient, session: AsyncSession, seeded: DeployedWithBackup
) -> None:
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(seeded.environment_id),
            "input": {"envVars": [{"name": "HISTORY_MARKER", "value": "1"}]},
        },
    )


Operation = Callable[[AsyncClient, AsyncSession, DeployedWithBackup], Awaitable[None]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [_upgrade, _edit_config, _refresh, _change_environment_config],
    ids=["upgrade", "config-edit", "refresh", "environment-config-change"],
)
async def test_backup_stays_in_history_after_operation_creates_new_instance(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    operation: Operation,
) -> None:
    _arm_prefect(prefect_manager_mock)
    seeded = await _deploy_with_completed_backup(client, session)

    await operation(client, session, seeded)

    session.expire_all()
    deployment = await session.get(Deployment, seeded.deployment_id)
    assert deployment is not None
    # Fails when the operation was a no-op, so the history check below proves something.
    assert deployment.active_application_instance_id not in (None, seeded.instance_id)

    data = await gql(
        client, "list_backup_history", {"deploymentId": str(seeded.deployment_id)}
    )
    [row] = data["backups"]
    assert row["id"] == str(seeded.backup_id)
    assert row["status"] == BackupStatus.COMPLETED.value
    assert row["instanceId"] == str(seeded.instance_id)
    assert row["instance"] == {
        "id": str(seeded.instance_id),
        "applicationVersion": "1.0.0",
    }


# ---------------------------------------------------------------------------
# A deleted deployment keeps its backup history (US4)
# ---------------------------------------------------------------------------


async def _mark_deleted(session: AsyncSession, deployment_id: UUID) -> None:
    """Tombstone the deployment as the deletion flow leaves it."""
    deployment = await session.get(Deployment, deployment_id)
    assert deployment is not None
    deployment.status = DeploymentState.DELETED
    deployment.deleted_at = datetime.now(tz=UTC)
    session.add(deployment)
    await session.commit()


@pytest.mark.asyncio
async def test_deleted_deployment_still_lists_its_backup_history(
    client: AsyncClient, session: AsyncSession, history: BackupHistory
) -> None:
    await _mark_deleted(session, UUID(history.deployment_id))

    data = await gql(
        client, "list_backup_history", {"deploymentId": history.deployment_id}
    )

    assert [row["id"] for row in data["backups"]] == [
        history.new_backup_id,
        history.old_backup_id,
    ]


@pytest.mark.asyncio
async def test_new_deployment_reusing_a_deleted_name_starts_with_empty_history(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    deleted = await _deploy_with_completed_backup(client, session)
    await _mark_deleted(session, deleted.deployment_id)

    # The name is free again only because the first deployment is tombstoned.
    await gql(
        client,
        "deploy_with_driver_version",
        {
            "driver": deleted.driver_name,
            "environmentId": str(deleted.environment_id),
            "name": deleted.name,
            "version": "1.0.0",
        },
    )
    session.expire_all()
    same_name = (
        await session.exec(
            select(Deployment)
            .where(Deployment.name == deleted.name)
            .where(Deployment.environment_id == deleted.environment_id)
        )
    ).all()
    [reused] = [row for row in same_name if row.id != deleted.deployment_id]
    assert reused.deleted_at is None
    assert reused.active_application_instance_id is not None
    reused_id = reused.id

    reused_history = await gql(
        client, "list_backup_history", {"deploymentId": str(reused_id)}
    )
    deleted_history = await gql(
        client, "list_backup_history", {"deploymentId": str(deleted.deployment_id)}
    )

    assert reused_history["backups"] == []
    assert [row["id"] for row in deleted_history["backups"]] == [str(deleted.backup_id)]
