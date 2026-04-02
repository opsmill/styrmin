"""Backup storage location resource operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.exceptions import ResourceNotFoundError
from styrmin_sdk.graphql._generated.create_backup_storage_location import (
    CreateBackupStorageLocation,
    CreateBackupStorageLocationCreateBackupStorageLocation,
)
from styrmin_sdk.graphql._generated.get_backup_storage_location import (
    GetBackupStorageLocation,
    GetBackupStorageLocationBackupStorageLocation,
)
from styrmin_sdk.graphql._generated.list_backup_storage_locations import (
    ListBackupStorageLocations,
    ListBackupStorageLocationsBackupStorageLocations,
)
from styrmin_sdk.graphql._generated.update_backup_storage_location import (
    UpdateBackupStorageLocation,
    UpdateBackupStorageLocationUpdateBackupStorageLocation,
)
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
    ) -> CreateBackupStorageLocationCreateBackupStorageLocation:
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
        return self._parse(
            CreateBackupStorageLocation,
            result["data"],
            "create_backup_storage_location",
            CreateBackupStorageLocationCreateBackupStorageLocation,
        )

    async def list(self) -> list[ListBackupStorageLocationsBackupStorageLocations]:
        result = await self._transport.execute(load_query("list_backup_storage_locations"))
        self._check_graphql_errors(result)
        data = ListBackupStorageLocations.model_validate(result["data"])
        return data.backup_storage_locations or []

    async def get(self, bsl_id: str | UUID) -> GetBackupStorageLocationBackupStorageLocation:
        result = await self._transport.execute(
            load_query("get_backup_storage_location"),
            {"backupStorageLocationId": str(bsl_id)},
        )
        self._check_graphql_errors(result)
        data = GetBackupStorageLocation.model_validate(result["data"])
        if data.backup_storage_location is None:
            raise ResourceNotFoundError(
                f"Backup storage location {bsl_id} not found",
                "NOT_FOUND",
            )
        return data.backup_storage_location

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
    ) -> UpdateBackupStorageLocationUpdateBackupStorageLocation:
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
        return self._parse(
            UpdateBackupStorageLocation,
            result["data"],
            "update_backup_storage_location",
            UpdateBackupStorageLocationUpdateBackupStorageLocation,
        )

    async def delete(self, bsl_id: str | UUID) -> bool:
        """Delete a BSL. Returns True on success.

        Raises OperationFailedError if the BSL is in use by environments.
        Raises ResourceNotFoundError if the BSL does not exist.
        """
        result = await self._transport.execute(
            load_query("delete_backup_storage_location"),
            {"backupStorageLocationId": str(bsl_id)},
        )
        self._check_graphql_errors(result)
        return True

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
