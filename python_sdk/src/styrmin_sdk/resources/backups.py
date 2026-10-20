"""Backup and restore resource operations."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.exceptions import IncompatibleServerError
from styrmin_sdk.graphql._generated.create_backup import CreateBackup, CreateBackupCreateBackup
from styrmin_sdk.graphql._generated.create_restore import CreateRestore, CreateRestoreCreateRestore
from styrmin_sdk.graphql._generated.enums import BackupStatus, RestoreStatus
from styrmin_sdk.graphql._generated.get_backup import GetBackup, GetBackupBackup
from styrmin_sdk.graphql._generated.get_restore import GetRestore, GetRestoreRestore
from styrmin_sdk.graphql._generated.list_backups import ListBackups, ListBackupsBackups
from styrmin_sdk.graphql._generated.list_restores import ListRestores, ListRestoresRestores
from styrmin_sdk.resources._base import BaseResource

#: How a server from before #532 refuses a restore that names only the backup.
_TARGET_NAMESPACE_REQUIRED = "Field 'createRestore' argument 'targetNamespace' of type 'String!' is required"


def _raise_if_server_requires_target_namespace(result: dict[str, Any]) -> None:
    """Raise :class:`IncompatibleServerError` when the server predates #532 and requires ``targetNamespace``."""
    for error in result.get("errors") or []:
        if str(error.get("message", "")).startswith(_TARGET_NAMESPACE_REQUIRED):
            raise IncompatibleServerError(
                "the Styrmin server is older than this styrminctl or SDK: before #532, createRestore requires "
                "a 'targetNamespace' argument, and this styrminctl or SDK sends only the backup id. Upgrade the "
                "Styrmin server, or restore with the styrminctl or SDK of the server's version.",
                "",
            )


def _coerce_backup_status(value: BackupStatus | str | None) -> str | None:
    if value is None or isinstance(value, BackupStatus):
        return value.value if isinstance(value, BackupStatus) else None
    return BackupStatus(value.upper()).value


def _coerce_restore_status(value: RestoreStatus | str | None) -> str | None:
    if value is None or isinstance(value, RestoreStatus):
        return value.value if isinstance(value, RestoreStatus) else None
    return RestoreStatus(value.upper()).value


class BackupResource(BaseResource):
    async def create_backup(
        self,
        instance_id: str | UUID,
        name: str | None = None,
    ) -> CreateBackupCreateBackup:
        variables: dict[str, Any] = {"instanceId": str(instance_id)}
        if name is not None:
            variables["name"] = name

        result = await self._transport.execute(load_query("create_backup"), variables)
        self._check_graphql_errors(result)
        return self._parse(CreateBackup, result["data"], "create_backup", CreateBackupCreateBackup)

    async def get_backup(self, backup_id: str | UUID) -> GetBackupBackup:
        result = await self._transport.execute(load_query("get_backup"), {"backupId": str(backup_id)})
        self._check_graphql_errors(result)
        return self._parse(GetBackup, result["data"], "backup", GetBackupBackup)

    async def list_backups(
        self,
        instance_id: str | UUID | None = None,
        status: BackupStatus | str | None = None,
        *,
        deployment_id: str | UUID | None = None,
    ) -> list[ListBackupsBackups]:
        """List backups, newest first, by deployment or by instance.

        ``deployment_id`` lists the deployment's backup history: the backups of
        every instance the deployment has had, including instances replaced by
        an upgrade, a config edit or an environment config change.
        ``instance_id`` lists the backups of that one instance. Each backup
        carries ``instance.application_version``, the application version of
        the instance it was taken of, and ``instance.deployment_id``, the
        deployment that instance belongs to. ``status`` filters either list.

        Pass exactly one of ``deployment_id`` and ``instance_id``, or the call
        raises :class:`ValueError` without sending a request.

        Examples::

            history = await client.backups.list_backups(deployment_id=deployment_id)
            completed = await client.backups.list_backups(instance_id, "completed")
        """
        if (deployment_id is None) == (instance_id is None):
            raise ValueError("Provide exactly one of deployment_id or instance_id")
        variables: dict[str, Any] = {}
        if deployment_id is not None:
            variables["deploymentId"] = str(deployment_id)
        if instance_id is not None:
            variables["instanceId"] = str(instance_id)
        coerced = _coerce_backup_status(status)
        if coerced is not None:
            variables["status"] = coerced

        result = await self._transport.execute(load_query("list_backups"), variables)
        self._check_graphql_errors(result)
        data = ListBackups.model_validate(result["data"])
        return data.backups or []

    async def delete_backup(self, backup_id: str | UUID) -> None:
        result = await self._transport.execute(load_query("delete_backup"), {"backupId": str(backup_id)})
        self._check_graphql_errors(result)

    async def create_restore(self, backup_id: str | UUID) -> CreateRestoreCreateRestore:
        """Restore a backup into the deployment it was taken of.

        The server records that deployment's namespace and active instance on
        the restore; the caller names neither.

        Raises:
            IncompatibleServerError: The server predates #532 and requires a
                target namespace.
        """
        result = await self._transport.execute(load_query("create_restore"), {"backupId": str(backup_id)})
        _raise_if_server_requires_target_namespace(result)
        self._check_graphql_errors(result)
        return self._parse(CreateRestore, result["data"], "create_restore", CreateRestoreCreateRestore)

    async def get_restore(self, restore_id: str | UUID) -> GetRestoreRestore:
        result = await self._transport.execute(load_query("get_restore"), {"restoreId": str(restore_id)})
        self._check_graphql_errors(result)
        return self._parse(GetRestore, result["data"], "restore", GetRestoreRestore)

    async def list_restores(
        self,
        backup_id: str | UUID,
        status: RestoreStatus | str | None = None,
    ) -> list[ListRestoresRestores]:
        variables: dict[str, Any] = {"backupId": str(backup_id)}
        coerced = _coerce_restore_status(status)
        if coerced is not None:
            variables["status"] = coerced

        result = await self._transport.execute(load_query("list_restores"), variables)
        self._check_graphql_errors(result)
        data = ListRestores.model_validate(result["data"])
        return data.restores or []

    async def wait_for_backup(
        self,
        backup_id: str | UUID,
        max_wait: float = 300,
        interval: float = 5,
    ) -> GetBackupBackup:
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
    ) -> GetRestoreRestore:
        """Poll get_restore() until the restore reaches a terminal status."""
        elapsed = 0.0
        while elapsed < max_wait:
            restore = await self.get_restore(restore_id)
            if restore.status in {"completed", "failed"}:
                return restore
            await asyncio.sleep(interval)
            elapsed += interval
        return await self.get_restore(restore_id)
