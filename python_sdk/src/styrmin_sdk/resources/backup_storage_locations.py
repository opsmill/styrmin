"""Backup storage location resource operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.exceptions import (
    BackupStorageLocationAlreadyExistsError,
    BackupStorageLocationInUseError,
    BackupStorageLocationNotFoundError,
)
from styrmin_sdk.models.backup_storage_location import BackupStorageLocation
from styrmin_sdk.resources._base import BaseResource


class BackupStorageLocationResource(BaseResource):
    async def create(
        self,
        name: str,
        endpoint: str,
        bucket: str,
        *,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> BackupStorageLocation:
        variables: dict[str, Any] = {
            "name": name,
            "endpoint": endpoint,
            "bucket": bucket,
            "region": region,
            "accessKeyId": access_key_id,
            "secretAccessKey": secret_access_key,
        }
        result = await self._transport.execute(load_query("create_backup_storage_location"), variables)
        self._check_graphql_errors(result)
        data = result["data"]["createBackupStorageLocation"]
        typename = data.get("__typename", "")
        if typename == "BackupStorageLocationAlreadyExists":
            raise BackupStorageLocationAlreadyExistsError(data["message"], typename, existing_id=data["existingId"])
        return BackupStorageLocation.model_validate(data)

    async def list(self) -> list[BackupStorageLocation]:
        result = await self._transport.execute(load_query("list_backup_storage_locations"))
        self._check_graphql_errors(result)
        return [BackupStorageLocation.model_validate(b) for b in result["data"].get("backupStorageLocations", [])]

    async def get(self, bsl_id: str | UUID) -> BackupStorageLocation:
        result = await self._transport.execute(
            load_query("get_backup_storage_location"),
            {"backupStorageLocationId": str(bsl_id)},
        )
        self._check_graphql_errors(result)
        data = result["data"]["backupStorageLocation"]
        if data is None:
            raise BackupStorageLocationNotFoundError(
                f"Backup storage location {bsl_id} not found",
                "BackupStorageLocationNotFound",
            )
        return BackupStorageLocation.model_validate(data)

    async def update(
        self,
        bsl_id: str | UUID,
        *,
        name: str | None = None,
        endpoint: str | None = None,
        bucket: str | None = None,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> BackupStorageLocation:
        variables: dict[str, Any] = {
            "backupStorageLocationId": str(bsl_id),
        }
        if name is not None:
            variables["name"] = name
        if endpoint is not None:
            variables["endpoint"] = endpoint
        if bucket is not None:
            variables["bucket"] = bucket
        if region is not None:
            variables["region"] = region
        if access_key_id is not None:
            variables["accessKeyId"] = access_key_id
        if secret_access_key is not None:
            variables["secretAccessKey"] = secret_access_key

        result = await self._transport.execute(load_query("update_backup_storage_location"), variables)
        self._check_graphql_errors(result)
        data = result["data"]["updateBackupStorageLocation"]
        typename = data.get("__typename", "")
        if typename == "BackupStorageLocationNotFound":
            raise BackupStorageLocationNotFoundError(data["message"], typename)
        return BackupStorageLocation.model_validate(data)

    async def delete(self, bsl_id: str | UUID) -> bool:
        """Delete a BSL. Returns True on success.

        Raises BackupStorageLocationInUseError if environments reference it.
        """
        result = await self._transport.execute(
            load_query("delete_backup_storage_location"),
            {"backupStorageLocationId": str(bsl_id)},
        )
        self._check_graphql_errors(result)
        data = result["data"]["deleteBackupStorageLocation"]
        typename = data.get("__typename", "")
        if typename == "BackupStorageLocationInUse":
            raise BackupStorageLocationInUseError(
                data["message"],
                typename,
                environment_names=data["environmentNames"],
            )
        return data.get("success", False)

    async def assign(
        self,
        environment_id: str | UUID,
        bsl_id: str | UUID,
    ) -> None:
        """Assign a BSL to an environment."""
        result = await self._transport.execute(
            load_query("assign_backup_storage_location"),
            {
                "environmentId": str(environment_id),
                "backupStorageLocationId": str(bsl_id),
            },
        )
        self._check_graphql_errors(result)

    async def unassign(self, environment_id: str | UUID) -> None:
        """Remove the BSL assignment from an environment."""
        result = await self._transport.execute(
            load_query("unassign_backup_storage_location"),
            {"environmentId": str(environment_id)},
        )
        self._check_graphql_errors(result)
