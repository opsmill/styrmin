"""Environment backup and restore resource operations."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from styrmin_sdk._queries import load_query
from styrmin_sdk.resources._base import BaseResource


class _EnvironmentBackupData(BaseModel):
    id: str
    name: str
    status: str
    created_on: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    metadata: Any = None
    max_concurrency: int | None = None
    timeout: int | None = None
    backup_count: int | None = None
    completed_count: int | None = None
    failed_count: int | None = None
    environment: Any = None
    backups: list[Any] | None = None
    restores: list[Any] | None = None


class _EnvironmentRestoreData(BaseModel):
    id: str
    name: str
    status: str
    created_on: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    metadata: Any = None
    restore_count: int | None = None
    completed_count: int | None = None
    failed_count: int | None = None
    environment_backup: Any = None
    restores: list[Any] | None = None


class EnvironmentBackupResource(BaseResource):
    async def create(
        self,
        environment_id: str | UUID,
        name: str | None = None,
        max_concurrency: int | None = None,
        backup_timeout: int | None = None,
    ) -> _EnvironmentBackupData:
        variables: dict[str, Any] = {"environmentId": str(environment_id)}
        if name is not None:
            variables["name"] = name
        if max_concurrency is not None:
            variables["maxConcurrency"] = max_concurrency
        if backup_timeout is not None:
            variables["timeout"] = backup_timeout

        result = await self._transport.execute(load_query("create_environment_backup"), variables)
        self._check_graphql_errors(result)
        data = result["data"]["createEnvironmentBackup"]
        return _EnvironmentBackupData.model_validate(data)

    async def get(self, environment_backup_id: str | UUID) -> _EnvironmentBackupData:
        result = await self._transport.execute(
            load_query("get_environment_backup"),
            {"environmentBackupId": str(environment_backup_id)},
        )
        self._check_graphql_errors(result)
        data = result["data"]["environmentBackup"]
        return _EnvironmentBackupData.model_validate(data)

    async def list(
        self,
        environment_id: str | UUID,
        status: str | None = None,
    ) -> list[_EnvironmentBackupData]:
        variables: dict[str, Any] = {"environmentId": str(environment_id)}
        if status is not None:
            variables["status"] = status

        result = await self._transport.execute(load_query("list_environment_backups"), variables)
        self._check_graphql_errors(result)
        items = result["data"]["environmentBackups"] or []
        return [_EnvironmentBackupData.model_validate(item) for item in items]

    async def delete(self, environment_backup_id: str | UUID) -> None:
        result = await self._transport.execute(
            load_query("delete_environment_backup"),
            {"environmentBackupId": str(environment_backup_id)},
        )
        self._check_graphql_errors(result)

    async def wait_for_completion(
        self,
        environment_backup_id: str | UUID,
        max_wait: float = 600,
        interval: float = 10,
    ) -> _EnvironmentBackupData:
        """Poll until the environment backup reaches a terminal status."""
        elapsed = 0.0
        while elapsed < max_wait:
            env_backup = await self.get(environment_backup_id)
            if env_backup.status in {"completed", "partially_failed", "failed"}:
                return env_backup
            await asyncio.sleep(interval)
            elapsed += interval
        return await self.get(environment_backup_id)


class EnvironmentRestoreResource(BaseResource):
    async def create(
        self,
        environment_backup_id: str | UUID,
    ) -> _EnvironmentRestoreData:
        result = await self._transport.execute(
            load_query("create_environment_restore"),
            {"environmentBackupId": str(environment_backup_id)},
        )
        self._check_graphql_errors(result)
        data = result["data"]["createEnvironmentRestore"]
        return _EnvironmentRestoreData.model_validate(data)

    async def get(self, environment_restore_id: str | UUID) -> _EnvironmentRestoreData:
        result = await self._transport.execute(
            load_query("get_environment_restore"),
            {"environmentRestoreId": str(environment_restore_id)},
        )
        self._check_graphql_errors(result)
        data = result["data"]["environmentRestore"]
        return _EnvironmentRestoreData.model_validate(data)

    async def list(
        self,
        environment_backup_id: str | UUID,
        status: str | None = None,
    ) -> list[_EnvironmentRestoreData]:
        variables: dict[str, Any] = {"environmentBackupId": str(environment_backup_id)}
        if status is not None:
            variables["status"] = status

        result = await self._transport.execute(load_query("list_environment_restores"), variables)
        self._check_graphql_errors(result)
        items = result["data"]["environmentRestores"] or []
        return [_EnvironmentRestoreData.model_validate(item) for item in items]

    async def wait_for_completion(
        self,
        environment_restore_id: str | UUID,
        max_wait: float = 600,
        interval: float = 10,
    ) -> _EnvironmentRestoreData:
        """Poll until the environment restore reaches a terminal status."""
        elapsed = 0.0
        while elapsed < max_wait:
            env_restore = await self.get(environment_restore_id)
            if env_restore.status in {"completed", "partially_failed", "failed"}:
                return env_restore
            await asyncio.sleep(interval)
            elapsed += interval
        return await self.get(environment_restore_id)
