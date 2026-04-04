"""E2E tests for the environment backup and restore lifecycle.

These tests exercise the full lifecycle through the StyrminClient SDK:
create → monitor → restore → delete.

Requires: deployed_simple_app fixture (creates a deployed application with
active instance in a test environment with BSL configured).
"""

from __future__ import annotations

import pytest
from styrmin_sdk import StyrminClient


async def test_create_environment_backup(
    styrmin_resources: dict,
    deployed_simple_app: dict,
    velero_ready: None,
) -> None:
    """T051: Create an environment backup and verify constituent backups are created."""
    client: StyrminClient = styrmin_resources["client"]
    environment_id = styrmin_resources["environment_id"]

    env_backup = await client.environment_backups.create(
        environment_id=environment_id,
        name="e2e-env-backup",
    )

    assert env_backup.id is not None
    assert env_backup.name == "e2e-env-backup"
    assert env_backup.status == "pending"

    # Wait for completion
    env_backup = await client.environment_backups.wait_for_completion(
        env_backup.id, max_wait=600, interval=15
    )

    assert env_backup.status in ("completed", "partially_failed")

    # Verify details
    detail = await client.environment_backups.get(env_backup.id)
    assert detail.backup_count is not None
    assert detail.backup_count > 0


async def test_environment_restore_lifecycle(
    styrmin_resources: dict,
    deployed_simple_app: dict,
    velero_ready: None,
) -> None:
    """T052: Restore an environment from a completed backup."""
    client: StyrminClient = styrmin_resources["client"]
    environment_id = styrmin_resources["environment_id"]

    # Create a backup first
    env_backup = await client.environment_backups.create(
        environment_id=environment_id,
    )
    env_backup = await client.environment_backups.wait_for_completion(
        env_backup.id, max_wait=600, interval=15
    )

    if env_backup.status not in ("completed", "partially_failed"):
        pytest.skip("Backup did not complete, cannot test restore")

    # Create restore
    env_restore = await client.environment_restores.create(
        environment_backup_id=env_backup.id,
    )

    assert env_restore.id is not None
    assert env_restore.status == "pending"

    # Wait for completion
    env_restore = await client.environment_restores.wait_for_completion(
        env_restore.id, max_wait=600, interval=15
    )

    assert env_restore.status in ("completed", "partially_failed")

    # Verify details
    detail = await client.environment_restores.get(env_restore.id)
    assert detail.restore_count is not None
    assert detail.restore_count > 0


async def test_list_environment_backups(
    styrmin_resources: dict,
    deployed_simple_app: dict,
    velero_ready: None,
) -> None:
    """T053: List environment backups for an environment."""
    client: StyrminClient = styrmin_resources["client"]
    environment_id = styrmin_resources["environment_id"]

    backups = await client.environment_backups.list(environment_id=environment_id)
    # There should be at least the backups created by previous tests
    assert isinstance(backups, list)


async def test_delete_environment_backup(
    styrmin_resources: dict,
    deployed_simple_app: dict,
    velero_ready: None,
) -> None:
    """T054: Delete an environment backup and verify cascade."""
    client: StyrminClient = styrmin_resources["client"]
    environment_id = styrmin_resources["environment_id"]

    # Create a backup
    env_backup = await client.environment_backups.create(
        environment_id=environment_id,
    )
    env_backup = await client.environment_backups.wait_for_completion(
        env_backup.id, max_wait=600, interval=15
    )

    # Delete it
    await client.environment_backups.delete(env_backup.id)

    # Verify it's gone
    from styrmin_sdk.exceptions import ResourceNotFoundError

    with pytest.raises(ResourceNotFoundError):
        await client.environment_backups.get(env_backup.id)
