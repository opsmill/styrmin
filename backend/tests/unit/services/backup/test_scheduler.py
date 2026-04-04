"""Unit tests for BackupScheduler service."""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.db.models import BackupSchedule
from styrmin_backend.services.backup.scheduler import (
    create_backup_schedule,
    delete_backup_schedule,
    get_backup_schedule,
    get_backup_schedules,
    update_backup_schedule,
)
from styrmin_backend.services.exceptions import (
    BackupScheduleAlreadyExistsError,
    BackupScheduleNotFoundError,
)
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeBackupScheduleRepository,
    FakeClusterRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


def make_uow(
    backup_schedules: list[BackupSchedule] | None = None,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        backup_schedules=FakeBackupScheduleRepository(backup_schedules or []),
    )


class TestCreateBackupSchedule:
    async def test_create_backup_schedule_success(self) -> None:
        deployment_id = uuid4()
        uow = make_uow()

        schedule = await create_backup_schedule(
            deployment_id=deployment_id,
            name="daily-backup",
            cron_expression="0 0 * * *",
            uow=uow,
        )

        assert schedule.name == "daily-backup"
        assert schedule.cron_expression == "0 0 * * *"
        assert schedule.retention_count == 10
        assert schedule.enabled is True
        assert schedule.deployment_id == deployment_id
        assert uow.committed is True

    async def test_create_backup_schedule_custom_retention(self) -> None:
        deployment_id = uuid4()
        uow = make_uow()

        schedule = await create_backup_schedule(
            deployment_id=deployment_id,
            name="weekly-backup",
            cron_expression="0 0 * * 0",
            retention_count=5,
            uow=uow,
        )

        assert schedule.retention_count == 5

    async def test_create_backup_schedule_disabled(self) -> None:
        deployment_id = uuid4()
        uow = make_uow()

        schedule = await create_backup_schedule(
            deployment_id=deployment_id,
            name="disabled-schedule",
            cron_expression="0 0 * * *",
            enabled=False,
            uow=uow,
        )

        assert schedule.enabled is False

    async def test_create_backup_schedule_duplicate_deployment(self) -> None:
        deployment_id = uuid4()
        existing = BackupSchedule(
            name="existing-schedule",
            cron_expression="0 0 * * *",
            deployment_id=deployment_id,
        )
        uow = make_uow(backup_schedules=[existing])

        with pytest.raises(BackupScheduleAlreadyExistsError):
            await create_backup_schedule(
                deployment_id=deployment_id,
                name="new-schedule",
                cron_expression="0 12 * * *",
                uow=uow,
            )

    async def test_create_backup_schedule_different_deployment_ok(self) -> None:
        deployment_id_1 = uuid4()
        deployment_id_2 = uuid4()
        existing = BackupSchedule(
            name="existing-schedule",
            cron_expression="0 0 * * *",
            deployment_id=deployment_id_1,
        )
        uow = make_uow(backup_schedules=[existing])

        schedule = await create_backup_schedule(
            deployment_id=deployment_id_2,
            name="new-schedule",
            cron_expression="0 12 * * *",
            uow=uow,
        )

        assert schedule.deployment_id == deployment_id_2


class TestGetBackupSchedule:
    async def test_get_backup_schedule_found(self) -> None:
        deployment_id = uuid4()
        existing = BackupSchedule(
            name="test-schedule",
            cron_expression="0 0 * * *",
            deployment_id=deployment_id,
        )
        uow = make_uow(backup_schedules=[existing])

        result = await get_backup_schedule(schedule_id=existing.id, uow=uow)
        assert result.id == existing.id
        assert result.name == "test-schedule"

    async def test_get_backup_schedule_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupScheduleNotFoundError):
            await get_backup_schedule(schedule_id=uuid4(), uow=uow)


class TestGetBackupSchedules:
    async def test_get_backup_schedules_by_deployment(self) -> None:
        deployment_id = uuid4()
        other_deployment_id = uuid4()
        s1 = BackupSchedule(
            name="s1",
            cron_expression="0 0 * * *",
            deployment_id=deployment_id,
        )
        s2 = BackupSchedule(
            name="s2",
            cron_expression="0 12 * * *",
            deployment_id=deployment_id,
        )
        s3 = BackupSchedule(
            name="s3",
            cron_expression="0 6 * * *",
            deployment_id=other_deployment_id,
        )
        uow = make_uow(backup_schedules=[s1, s2, s3])

        results = await get_backup_schedules(deployment_id=deployment_id, uow=uow)
        assert len(results) == 2

    async def test_get_backup_schedules_empty(self) -> None:
        uow = make_uow()

        results = await get_backup_schedules(deployment_id=uuid4(), uow=uow)
        assert len(results) == 0


class TestUpdateBackupSchedule:
    async def test_update_name(self) -> None:
        deployment_id = uuid4()
        schedule = BackupSchedule(
            name="old-name",
            cron_expression="0 0 * * *",
            deployment_id=deployment_id,
        )
        uow = make_uow(backup_schedules=[schedule])

        result = await update_backup_schedule(
            schedule_id=schedule.id,
            uow=uow,
            name="new-name",
        )

        assert result.name == "new-name"
        assert result.cron_expression == "0 0 * * *"
        assert uow.committed is True

    async def test_update_cron_expression(self) -> None:
        deployment_id = uuid4()
        schedule = BackupSchedule(
            name="test-schedule",
            cron_expression="0 0 * * *",
            deployment_id=deployment_id,
        )
        uow = make_uow(backup_schedules=[schedule])

        result = await update_backup_schedule(
            schedule_id=schedule.id,
            uow=uow,
            cron_expression="0 12 * * *",
        )

        assert result.cron_expression == "0 12 * * *"
        assert result.name == "test-schedule"

    async def test_update_retention_count(self) -> None:
        deployment_id = uuid4()
        schedule = BackupSchedule(
            name="test-schedule",
            cron_expression="0 0 * * *",
            deployment_id=deployment_id,
            retention_count=10,
        )
        uow = make_uow(backup_schedules=[schedule])

        result = await update_backup_schedule(
            schedule_id=schedule.id,
            uow=uow,
            retention_count=5,
        )

        assert result.retention_count == 5

    async def test_update_enabled(self) -> None:
        deployment_id = uuid4()
        schedule = BackupSchedule(
            name="test-schedule",
            cron_expression="0 0 * * *",
            deployment_id=deployment_id,
            enabled=True,
        )
        uow = make_uow(backup_schedules=[schedule])

        result = await update_backup_schedule(
            schedule_id=schedule.id,
            uow=uow,
            enabled=False,
        )

        assert result.enabled is False

    async def test_update_multiple_fields(self) -> None:
        deployment_id = uuid4()
        schedule = BackupSchedule(
            name="old-name",
            cron_expression="0 0 * * *",
            deployment_id=deployment_id,
            retention_count=10,
            enabled=True,
        )
        uow = make_uow(backup_schedules=[schedule])

        result = await update_backup_schedule(
            schedule_id=schedule.id,
            uow=uow,
            name="new-name",
            cron_expression="0 6 * * *",
            retention_count=3,
            enabled=False,
        )

        assert result.name == "new-name"
        assert result.cron_expression == "0 6 * * *"
        assert result.retention_count == 3
        assert result.enabled is False

    async def test_update_no_fields_keeps_existing(self) -> None:
        deployment_id = uuid4()
        schedule = BackupSchedule(
            name="test-schedule",
            cron_expression="0 0 * * *",
            deployment_id=deployment_id,
            retention_count=10,
            enabled=True,
        )
        uow = make_uow(backup_schedules=[schedule])

        result = await update_backup_schedule(
            schedule_id=schedule.id,
            uow=uow,
        )

        assert result.name == "test-schedule"
        assert result.cron_expression == "0 0 * * *"
        assert result.retention_count == 10
        assert result.enabled is True

    async def test_update_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupScheduleNotFoundError):
            await update_backup_schedule(
                schedule_id=uuid4(),
                uow=uow,
                name="new-name",
            )


class TestDeleteBackupSchedule:
    async def test_delete_backup_schedule_success(self) -> None:
        deployment_id = uuid4()
        schedule = BackupSchedule(
            name="to-delete",
            cron_expression="0 0 * * *",
            deployment_id=deployment_id,
        )
        uow = make_uow(backup_schedules=[schedule])

        await delete_backup_schedule(schedule_id=schedule.id, uow=uow)

        assert uow.committed is True
        assert len(uow.backup_schedules.models) == 0

    async def test_delete_backup_schedule_not_found(self) -> None:
        uow = make_uow()

        with pytest.raises(BackupScheduleNotFoundError):
            await delete_backup_schedule(schedule_id=uuid4(), uow=uow)
