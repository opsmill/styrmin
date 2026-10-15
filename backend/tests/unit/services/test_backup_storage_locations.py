from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from styrmin_backend.db.models import BackupStorageLocation, Cluster, Environment
from styrmin_backend.services.backup_storage_locations import (
    assign_backup_storage_location,
    create_backup_storage_location,
    delete_backup_storage_location,
    get_backup_storage_location,
    get_backup_storage_locations,
    unassign_backup_storage_location,
    update_backup_storage_location,
)
from styrmin_backend.services.exceptions import (
    BackupStorageLocationAlreadyExistsError,
    BackupStorageLocationCleanupError,
    BackupStorageLocationInUseError,
    BackupStorageLocationNotFoundError,
    EnvironmentNotFoundError,
)
from styrmin_backend.workflows.models import PrefectAction
from tests.unit.services.fakes import (
    FakeBackupStorageLocationRepository,
    FakeUnitOfWork,
)


# --- US1: Create ---


async def test_create_backup_storage_location(
    uow: FakeUnitOfWork,
    fake_backup_storage_location_repository: FakeBackupStorageLocationRepository,
):
    bsl = await create_backup_storage_location(
        name="my-bsl",
        endpoint="https://s3.example.com",
        bucket="my-bucket",
        region="us-east-1",
        access_key_id="AKID",
        secret_access_key="SECRET",
        uow=uow,
    )

    assert len(fake_backup_storage_location_repository.models) == 1
    assert fake_backup_storage_location_repository.models[0] == bsl
    assert bsl.name == "my-bsl"
    assert bsl.endpoint == "https://s3.example.com"
    assert bsl.bucket == "my-bucket"
    assert bsl.region == "us-east-1"
    assert uow.committed


async def test_create_backup_storage_location_renamed_after_commit(
    uow: FakeUnitOfWork,
    fake_backup_storage_location_repository: FakeBackupStorageLocationRepository,
    monkeypatch: pytest.MonkeyPatch,
):
    """#510: a rename right after the commit does not lose the new location."""
    commit = uow.commit

    async def _commit_then_rename() -> None:
        await commit()
        for bsl in fake_backup_storage_location_repository.models:
            if bsl.name == "a":
                bsl.name = "b"
        fake_backup_storage_location_repository.models.append(
            BackupStorageLocation(
                name="a",
                endpoint="https://other.example.com",
                bucket="other",
                region="us-east-1",
                access_key_id="AKID",
                secret_access_key="SECRET",
            )
        )

    monkeypatch.setattr(uow, "commit", _commit_then_rename)

    bsl = await create_backup_storage_location(
        name="a",
        endpoint="https://s3.example.com",
        bucket="my-bucket",
        region="us-east-1",
        access_key_id="AKID",
        secret_access_key="SECRET",
        uow=uow,
    )

    assert bsl is fake_backup_storage_location_repository.models[0]
    assert bsl.name == "b"
    assert bsl.endpoint == "https://s3.example.com"


async def test_create_backup_storage_location_duplicate_name(
    uow: FakeUnitOfWork,
    fake_backup_storage_location: BackupStorageLocation,
):
    with pytest.raises(BackupStorageLocationAlreadyExistsError):
        await create_backup_storage_location(
            name=fake_backup_storage_location.name,
            endpoint="https://s3.example.com",
            bucket="bucket",
            region="us-east-1",
            access_key_id="AKID",
            secret_access_key="SECRET",
            uow=uow,
        )
    assert not uow.committed


# --- US1: List ---


async def test_get_backup_storage_locations(
    uow: FakeUnitOfWork,
    fake_backup_storage_location: BackupStorageLocation,
):
    bsls = await get_backup_storage_locations(uow=uow)

    assert len(bsls) == 1
    assert bsls[0].id == fake_backup_storage_location.id
    assert bsls[0].name == fake_backup_storage_location.name


async def test_get_backup_storage_locations_empty(uow: FakeUnitOfWork):
    bsls = await get_backup_storage_locations(uow=uow)
    assert len(bsls) == 0


# --- US3: Get single ---


async def test_get_backup_storage_location(
    uow: FakeUnitOfWork,
    fake_backup_storage_location: BackupStorageLocation,
):
    bsl = await get_backup_storage_location(
        backup_storage_location_id=fake_backup_storage_location.id, uow=uow
    )
    assert bsl.id == fake_backup_storage_location.id
    assert bsl.name == fake_backup_storage_location.name


async def test_get_backup_storage_location_not_found(uow: FakeUnitOfWork):
    with pytest.raises(BackupStorageLocationNotFoundError):
        await get_backup_storage_location(backup_storage_location_id=uuid4(), uow=uow)


# --- US3: Update ---


async def test_update_backup_storage_location(
    uow: FakeUnitOfWork,
    fake_backup_storage_location: BackupStorageLocation,
):
    updated = await update_backup_storage_location(
        backup_storage_location_id=fake_backup_storage_location.id,
        uow=uow,
        endpoint="https://new-s3.example.com",
        bucket="new-bucket",
    )

    assert updated.endpoint == "https://new-s3.example.com"
    assert updated.bucket == "new-bucket"
    # Unchanged fields remain the same
    assert updated.name == fake_backup_storage_location.name
    assert updated.region == fake_backup_storage_location.region
    assert uow.committed


async def test_update_backup_storage_location_not_found(uow: FakeUnitOfWork):
    with pytest.raises(BackupStorageLocationNotFoundError):
        await update_backup_storage_location(
            backup_storage_location_id=uuid4(),
            uow=uow,
            name="new-name",
        )


# --- US3: Delete ---


async def test_delete_backup_storage_location(
    uow: FakeUnitOfWork,
    fake_backup_storage_location: BackupStorageLocation,
    fake_backup_storage_location_repository: FakeBackupStorageLocationRepository,
    prefect_manager_mock,
):
    prefect_manager_mock.run_action = AsyncMock()

    await delete_backup_storage_location(
        backup_storage_location_id=fake_backup_storage_location.id, uow=uow
    )

    assert uow.committed
    assert len(fake_backup_storage_location_repository.models) == 0
    # Issue #475: the location is also removed from the cluster.
    prefect_manager_mock.run_action.assert_awaited_once_with(
        action=PrefectAction.SYNC_BSL_DELETE,
        parameters={"bsl_name": "test-bsl", "namespace": "styrmin"},
    )


async def test_delete_backup_storage_location_is_refused_when_cleanup_fails(
    uow: FakeUnitOfWork,
    fake_backup_storage_location: BackupStorageLocation,
    fake_backup_storage_location_repository: FakeBackupStorageLocationRepository,
    prefect_manager_mock,
):
    """Issue #475: a cleanup that cannot be submitted keeps the location.

    Once the row is gone nothing records that the Velero object and credentials
    Secret exist, so the delete is refused and can be retried.
    """
    prefect_manager_mock.run_action = AsyncMock(side_effect=RuntimeError("down"))

    with pytest.raises(BackupStorageLocationCleanupError) as exc_info:
        await delete_backup_storage_location(
            backup_storage_location_id=fake_backup_storage_location.id, uow=uow
        )

    assert exc_info.value.error_metadata == {"backup_storage_location_name": "test-bsl"}
    assert not uow.committed
    assert len(fake_backup_storage_location_repository.models) == 1


async def test_delete_backup_storage_location_not_found(uow: FakeUnitOfWork):
    with pytest.raises(BackupStorageLocationNotFoundError):
        await delete_backup_storage_location(
            backup_storage_location_id=uuid4(), uow=uow
        )
    assert not uow.committed


async def test_delete_backup_storage_location_in_use(
    uow: FakeUnitOfWork,
    fake_backup_storage_location: BackupStorageLocation,
    fake_backup_storage_location_repository: FakeBackupStorageLocationRepository,
):
    # Simulate an environment using this BSL
    env = Environment(
        name="env-using-bsl",
        cluster_id=uuid4(),
        backup_storage_location_id=fake_backup_storage_location.id,
    )
    fake_backup_storage_location.environments = [env]

    with pytest.raises(BackupStorageLocationInUseError):
        await delete_backup_storage_location(
            backup_storage_location_id=fake_backup_storage_location.id, uow=uow
        )
    assert not uow.committed
    # BSL should still exist
    assert len(fake_backup_storage_location_repository.models) == 1


# --- US2: Assign/Unassign ---


async def test_assign_backup_storage_location(
    uow: FakeUnitOfWork,
    fake_backup_storage_location: BackupStorageLocation,
    fake_cluster: Cluster,
    fake_environment: Environment,
):
    await assign_backup_storage_location(
        environment_id=fake_environment.id,
        backup_storage_location_id=fake_backup_storage_location.id,
        uow=uow,
    )
    assert (
        fake_environment.backup_storage_location_id == fake_backup_storage_location.id
    )
    assert uow.committed


async def test_assign_backup_storage_location_bsl_not_found(
    uow: FakeUnitOfWork,
    fake_environment: Environment,
    fake_cluster: Cluster,
):
    with pytest.raises(BackupStorageLocationNotFoundError):
        await assign_backup_storage_location(
            environment_id=fake_environment.id,
            backup_storage_location_id=uuid4(),
            uow=uow,
        )


async def test_assign_backup_storage_location_env_not_found(
    uow: FakeUnitOfWork,
    fake_backup_storage_location: BackupStorageLocation,
):
    with pytest.raises(EnvironmentNotFoundError):
        await assign_backup_storage_location(
            environment_id=uuid4(),
            backup_storage_location_id=fake_backup_storage_location.id,
            uow=uow,
        )


async def test_unassign_backup_storage_location(
    uow: FakeUnitOfWork,
    fake_backup_storage_location: BackupStorageLocation,
    fake_cluster: Cluster,
    fake_environment: Environment,
):
    # First assign
    fake_environment.backup_storage_location_id = fake_backup_storage_location.id

    await unassign_backup_storage_location(environment_id=fake_environment.id, uow=uow)
    assert fake_environment.backup_storage_location_id is None
    assert uow.committed


async def test_unassign_backup_storage_location_env_not_found(uow: FakeUnitOfWork):
    with pytest.raises(EnvironmentNotFoundError):
        await unassign_backup_storage_location(environment_id=uuid4(), uow=uow)
