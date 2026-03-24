"""Backup and restore resource operations."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.models.backup import Backup, Restore
from styrmin_sdk.resources._base import BaseResource


class BackupResource(BaseResource):
    async def create_backup(
        self,
        instance_id: str | UUID,
        name: str | None = None,
    ) -> Backup:
        variables: dict[str, Any] = {"instanceId": str(instance_id)}
        if name is not None:
            variables["name"] = name

        result = await self._transport.execute(load_query("create_backup"), variables)
        self._check_graphql_errors(result)
        return Backup.model_validate(result["data"]["createBackup"])

    async def get_backup(self, backup_id: str | UUID) -> Backup:
        result = await self._transport.execute(load_query("get_backup"), {"backupId": str(backup_id)})
        self._check_graphql_errors(result)
        return Backup.model_validate(result["data"]["backup"])

    async def list_backups(
        self,
        instance_id: str | UUID,
        status: str | None = None,
    ) -> list[Backup]:
        variables: dict[str, Any] = {"instanceId": str(instance_id)}
        if status is not None:
            variables["status"] = status

        result = await self._transport.execute(load_query("list_backups"), variables)
        self._check_graphql_errors(result)
        return [Backup.model_validate(b) for b in result["data"].get("backups", [])]

    async def delete_backup(self, backup_id: str | UUID) -> None:
        result = await self._transport.execute(load_query("delete_backup"), {"backupId": str(backup_id)})
        self._check_graphql_errors(result)

    async def create_restore(
        self,
        backup_id: str | UUID,
        target_namespace: str,
        target_instance_id: str | UUID | None = None,
    ) -> Restore:
        variables: dict[str, Any] = {
            "backupId": str(backup_id),
            "targetNamespace": target_namespace,
        }
        if target_instance_id is not None:
            variables["targetInstanceId"] = str(target_instance_id)

        result = await self._transport.execute(load_query("create_restore"), variables)
        self._check_graphql_errors(result)
        return Restore.model_validate(result["data"]["createRestore"])

    async def get_restore(self, restore_id: str | UUID) -> Restore:
        result = await self._transport.execute(load_query("get_restore"), {"restoreId": str(restore_id)})
        self._check_graphql_errors(result)
        return Restore.model_validate(result["data"]["restore"])

    async def list_restores(
        self,
        backup_id: str | UUID,
        status: str | None = None,
    ) -> list[Restore]:
        variables: dict[str, Any] = {"backupId": str(backup_id)}
        if status is not None:
            variables["status"] = status

        result = await self._transport.execute(load_query("list_restores"), variables)
        self._check_graphql_errors(result)
        return [Restore.model_validate(r) for r in result["data"].get("restores", [])]

    async def wait_for_backup(
        self,
        backup_id: str | UUID,
        max_wait: float = 300,
        interval: float = 5,
    ) -> Backup:
        """Poll get_backup() until the backup reaches a terminal status."""
        elapsed = 0.0
        while elapsed < max_wait:
            backup = await self.get_backup(backup_id)
            if backup.status in {"completed", "failed"}:
                return backup
            await asyncio.sleep(interval)
            elapsed += interval
        return await self.get_backup(backup_id)

    async def wait_for_restore(
        self,
        restore_id: str | UUID,
        max_wait: float = 300,
        interval: float = 5,
    ) -> Restore:
        """Poll get_restore() until the restore reaches a terminal status."""
        elapsed = 0.0
        while elapsed < max_wait:
            restore = await self.get_restore(restore_id)
            if restore.status in {"completed", "failed"}:
                return restore
            await asyncio.sleep(interval)
            elapsed += interval
        return await self.get_restore(restore_id)
