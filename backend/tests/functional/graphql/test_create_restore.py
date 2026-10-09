"""Propagation tests for the ``createRestore`` mutation.

Assertions read back through a second session bound to the same engine, so the
values must have been committed rather than served from the seeding session.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    Backup,
    BackupStatus,
    Deployment,
    DeploymentState,
    Restore,
    RestoreStatus,
)

from ._queries import load_query
from .conftest import gql
from .seeds import seed_application_instance


async def _read_back[T](session: AsyncSession, model: type[T], row_id: UUID) -> T:
    bind = session.get_bind()
    engine = bind if isinstance(bind, AsyncEngine) else AsyncEngine(bind)
    assert isinstance(engine.sync_engine, Engine)
    async with AsyncSession(engine, expire_on_commit=False) as fresh_session:
        row = await fresh_session.get(model, row_id)
    assert row is not None
    return row


@pytest.mark.asyncio
async def test_create_restore_fails_the_restore_when_its_dispatch_fails(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, mocker
) -> None:
    """A restore whose workflow could not be dispatched is failed, not left
    PENDING: a PENDING row would hold its deployment in RESTORING, because
    agent status reports skip a deployment with a restore in flight."""
    instance = await seed_application_instance(session)
    assert instance.deployment_id is not None
    backup = Backup(
        name="restore-dispatch-seed",
        status=BackupStatus.COMPLETED,
        instance_id=instance.id,
    )
    session.add(backup)
    await session.commit()
    # The resolver calls ``get_manager()`` directly, out of reach of the
    # fixture's dependency override.
    mocker.patch(
        "styrmin_backend.api.schema.mutation.get_manager",
        return_value=prefect_manager_mock,
    )
    prefect_manager_mock.run_action.side_effect = RuntimeError("prefect is down")

    data = await gql(
        client,
        "create_restore",
        {
            "backupId": str(backup.id),
            "targetNamespace": f"styrmin-{instance.deployment_id}",
        },
    )

    payload = data["createRestore"]
    prefect_manager_mock.run_action.assert_called_once()
    assert payload["status"] == RestoreStatus.FAILED.value
    assert "never dispatched" in payload["errorMessage"]
    assert "prefect is down" in payload["errorMessage"]
    assert payload["completedAt"] is not None

    restore = await _read_back(session, Restore, UUID(payload["id"]))
    assert restore.status == RestoreStatus.FAILED
    assert restore.error_message == payload["errorMessage"]
    deployment = await _read_back(session, Deployment, instance.deployment_id)
    assert deployment.status == DeploymentState.FAILED


@pytest.mark.asyncio
async def test_create_restore_into_a_deleted_deployment_is_refused(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, mocker
) -> None:
    """A deleted deployment lists its backups, but a restore into it is refused
    before any restore row is written or any workflow is dispatched."""
    instance = await seed_application_instance(session)
    deployment_id = instance.deployment_id
    assert deployment_id is not None
    deployment = await session.get(Deployment, deployment_id)
    assert deployment is not None
    deployment.status = DeploymentState.DELETED
    deployment.deleted_at = datetime(2026, 10, 8, tzinfo=UTC)
    backup = Backup(
        name="restore-deleted-seed",
        status=BackupStatus.COMPLETED,
        instance_id=instance.id,
    )
    session.add_all([deployment, backup])
    await session.commit()
    backup_id = backup.id
    mocker.patch(
        "styrmin_backend.api.schema.mutation.get_manager",
        return_value=prefect_manager_mock,
    )

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("create_restore"),
            "variables": {
                "backupId": str(backup_id),
                "targetNamespace": f"styrmin-{deployment_id}",
            },
        },
    )

    [error] = response.json()["errors"]
    assert error["extensions"]["code"] == "OPERATION_DENIED", error
    assert "was deleted" in error["message"], error
    prefect_manager_mock.run_action.assert_not_called()
    stored = await _read_back(session, Deployment, deployment_id)
    assert stored.status == DeploymentState.DELETED
    restores = await session.exec(select(Restore).where(Restore.backup_id == backup_id))
    assert restores.all() == []
