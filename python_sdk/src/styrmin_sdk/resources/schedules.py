"""Backup schedule resource operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.create_backup_schedule import (
    CreateBackupSchedule,
    CreateBackupScheduleCreateBackupSchedule,
)
from styrmin_sdk.graphql._generated.get_backup_schedule import GetBackupSchedule, GetBackupScheduleBackupSchedule
from styrmin_sdk.graphql._generated.list_backup_schedules import ListBackupSchedules, ListBackupSchedulesBackupSchedules
from styrmin_sdk.graphql._generated.update_backup_schedule import (
    UpdateBackupSchedule,
    UpdateBackupScheduleUpdateBackupSchedule,
)
from styrmin_sdk.resources._base import BaseResource


class ScheduleResource(BaseResource):
    async def create(
        self,
        deployment_id: str | UUID,
        name: str,
        cron_expression: str,
        retention_count: int = 10,
        enabled: bool = True,
    ) -> CreateBackupScheduleCreateBackupSchedule:
        variables: dict[str, Any] = {
            "deploymentId": str(deployment_id),
            "name": name,
            "cronExpression": cron_expression,
            "retentionCount": retention_count,
            "enabled": enabled,
        }

        result = await self._transport.execute(load_query("create_schedule"), variables)
        self._check_graphql_errors(result)
        return self._parse(CreateBackupSchedule, result["data"], "create_backup_schedule")

    async def get(self, schedule_id: str | UUID) -> GetBackupScheduleBackupSchedule:
        result = await self._transport.execute(load_query("get_schedule"), {"scheduleId": str(schedule_id)})
        self._check_graphql_errors(result)
        return self._parse(GetBackupSchedule, result["data"], "backup_schedule")

    async def list(self, deployment_id: str | UUID) -> list[ListBackupSchedulesBackupSchedules]:
        result = await self._transport.execute(load_query("list_schedules"), {"deploymentId": str(deployment_id)})
        self._check_graphql_errors(result)
        data = ListBackupSchedules.model_validate(result["data"])
        return data.backup_schedules or []

    async def update(
        self,
        schedule_id: str | UUID,
        name: str | None = None,
        cron_expression: str | None = None,
        retention_count: int | None = None,
        enabled: bool | None = None,
    ) -> UpdateBackupScheduleUpdateBackupSchedule:
        variables: dict[str, Any] = {"scheduleId": str(schedule_id)}
        if name is not None:
            variables["name"] = name
        if cron_expression is not None:
            variables["cronExpression"] = cron_expression
        if retention_count is not None:
            variables["retentionCount"] = retention_count
        if enabled is not None:
            variables["enabled"] = enabled

        result = await self._transport.execute(load_query("update_schedule"), variables)
        self._check_graphql_errors(result)
        return self._parse(UpdateBackupSchedule, result["data"], "update_backup_schedule")

    async def delete(self, schedule_id: str | UUID) -> None:
        result = await self._transport.execute(load_query("delete_schedule"), {"scheduleId": str(schedule_id)})
        self._check_graphql_errors(result)
