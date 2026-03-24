import pytest
from styrmin_backend.db.models import BackupStorageLocation
from styrmin_backend.repository.backup_storage_location import (
    SQLModelBackupStorageLocationRepository,
)
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.mark.asyncio
async def test_create_and_get_by_name(session: AsyncSession):
    repository = SQLModelBackupStorageLocationRepository(session)

    bsl = await repository.create(
        BackupStorageLocation(
            name="test-bsl",
            endpoint="https://s3.example.com",
            bucket="test-bucket",
            region="us-east-1",
            access_key_id="AKID",
            secret_access_key="SECRET",
        )
    )

    result = await repository.get_by_name("test-bsl")
    assert result is not None
    assert result.id == bsl.id
    assert result.name == "test-bsl"
    assert result.endpoint == "https://s3.example.com"
    assert result.bucket == "test-bucket"
    assert result.region == "us-east-1"


@pytest.mark.asyncio
async def test_get_by_name_not_found(session: AsyncSession):
    repository = SQLModelBackupStorageLocationRepository(session)

    result = await repository.get_by_name("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_all(session: AsyncSession):
    repository = SQLModelBackupStorageLocationRepository(session)

    await repository.create(
        BackupStorageLocation(
            name="bsl-1",
            endpoint="https://s3.example.com",
            bucket="bucket-1",
            region="us-east-1",
            access_key_id="AKID1",
            secret_access_key="SECRET1",
        )
    )
    await repository.create(
        BackupStorageLocation(
            name="bsl-2",
            endpoint="https://s3.example.com",
            bucket="bucket-2",
            region="eu-west-1",
            access_key_id="AKID2",
            secret_access_key="SECRET2",
        )
    )

    results = await repository.get_all()
    assert len(results) == 2


@pytest.mark.asyncio
async def test_get_by_id(session: AsyncSession):
    repository = SQLModelBackupStorageLocationRepository(session)

    bsl = await repository.create(
        BackupStorageLocation(
            name="test-bsl",
            endpoint="https://s3.example.com",
            bucket="test-bucket",
            region="us-east-1",
            access_key_id="AKID",
            secret_access_key="SECRET",
        )
    )

    result = await repository.get(bsl.id)
    assert result is not None
    assert result.name == "test-bsl"


@pytest.mark.asyncio
async def test_delete(session: AsyncSession):
    repository = SQLModelBackupStorageLocationRepository(session)

    bsl = await repository.create(
        BackupStorageLocation(
            name="test-bsl",
            endpoint="https://s3.example.com",
            bucket="test-bucket",
            region="us-east-1",
            access_key_id="AKID",
            secret_access_key="SECRET",
        )
    )

    await repository.delete(bsl)
    result = await repository.get_by_name("test-bsl")
    assert result is None
