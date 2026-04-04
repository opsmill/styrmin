"""Environment backup and restore resource operations."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.create_environment_backup import (
    CreateEnvironmentBackup,
    CreateEnvironmentBackupCreateEnvironmentBackup,
)
from styrmin_sdk.graphql._generated.create_environment_restore import (
    CreateEnvironmentRestore,
    CreateEnvironmentRestoreCreateEnvironmentRestore,
)
from styrmin_sdk.graphql._generated.get_environment_backup import (
    GetEnvironmentBackup,
    GetEnvironmentBackupEnvironmentBackup,
)
from styrmin_sdk.graphql._generated.get_environment_restore import (
    GetEnvironmentRestore,
    GetEnvironmentRestoreEnvironmentRestore,
)
from styrmin_sdk.graphql._generated.list_environment_backups import (
    ListEnvironmentBackups,
    ListEnvironmentBackupsEnvironmentBackups,
)
from styrmin_sdk.graphql._generated.list_environment_restores import (
    ListEnvironmentRestores,
    ListEnvironmentRestoresEnvironmentRestores,
)
from styrmin_sdk.resources._base import BaseResource


class EnvironmentBackupResource(BaseResource):
    async def create(
        self,
        environment_id: str | UUID,
        name: str | None = None,
        max_concurrency: int | None = None,
        backup_timeout: int | None = None,
    ) -> CreateEnvironmentBackupCreateEnvironmentBackup:
        variables: dict[str, Any] = {"environmentId": str(environment_id)}
        if name is not None:
            variables["name"] = name
        if max_concurrency is not None:
            variables["maxConcurrency"] = max_concurrency
        if backup_timeout is not None:
            variables["timeout"] = backup_timeout

        result = await self._transport.execute(load_query("create_environment_backup"), variables)
        self._check_graphql_errors(result)
        return self._parse(
            CreateEnvironmentBackup,
            result["data"],
            "create_environment_backup",
            CreateEnvironmentBackupCreateEnvironmentBackup,
        )

    async def get(self, environment_backup_id: str | UUID) -> GetEnvironmentBackupEnvironmentBackup:
        result = await self._transport.execute(
            load_query("get_environment_backup"),
            {"environmentBackupId": str(environment_backup_id)},
        )
        self._check_graphql_errors(result)
        return self._parse(
            GetEnvironmentBackup,
            result["data"],
            "environment_backup",
            GetEnvironmentBackupEnvironmentBackup,
        )

    async def list(
        self,
        environment_id: str | UUID,
        status: str | None = None,
    ) -> list[ListEnvironmentBackupsEnvironmentBackups]:
        variables: dict[str, Any] = {"environmentId": str(environment_id)}
        if status is not None:
            variables["status"] = status

        result = await self._transport.execute(load_query("list_environment_backups"), variables)
        self._check_graphql_errors(result)
        data = ListEnvironmentBackups.model_validate(result["data"])
        return data.environment_backups or []

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
    ) -> GetEnvironmentBackupEnvironmentBackup:
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
    ) -> CreateEnvironmentRestoreCreateEnvironmentRestore:
        result = await self._transport.execute(
            load_query("create_environment_restore"),
            {"environmentBackupId": str(environment_backup_id)},
        )
        self._check_graphql_errors(result)
        return self._parse(
            CreateEnvironmentRestore,
            result["data"],
            "create_environment_restore",
            CreateEnvironmentRestoreCreateEnvironmentRestore,
        )

    async def get(self, environment_restore_id: str | UUID) -> GetEnvironmentRestoreEnvironmentRestore:
        result = await self._transport.execute(
            load_query("get_environment_restore"),
            {"environmentRestoreId": str(environment_restore_id)},
        )
        self._check_graphql_errors(result)
        return self._parse(
            GetEnvironmentRestore,
            result["data"],
            "environment_restore",
            GetEnvironmentRestoreEnvironmentRestore,
        )

    async def list(
        self,
        environment_backup_id: str | UUID,
        status: str | None = None,
    ) -> list[ListEnvironmentRestoresEnvironmentRestores]:
        variables: dict[str, Any] = {"environmentBackupId": str(environment_backup_id)}
        if status is not None:
            variables["status"] = status

        result = await self._transport.execute(load_query("list_environment_restores"), variables)
        self._check_graphql_errors(result)
        data = ListEnvironmentRestores.model_validate(result["data"])
        return data.environment_restores or []

    async def wait_for_completion(
        self,
        environment_restore_id: str | UUID,
        max_wait: float = 600,
        interval: float = 10,
    ) -> GetEnvironmentRestoreEnvironmentRestore:
        """Poll until the environment restore reaches a terminal status."""
        elapsed = 0.0
        while elapsed < max_wait:
            env_restore = await self.get(environment_restore_id)
            if env_restore.status in {"completed", "partially_failed", "failed"}:
                return env_restore
            await asyncio.sleep(interval)
            elapsed += interval
        return await self.get(environment_restore_id)
