from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackup,
    VeleroBackupStorageLocation,
    VeleroRestore,
)


VELERO_API_GROUP = "velero.io"
VELERO_API_VERSION = "v1"
VELERO_BACKUP_PLURAL = "backups"
VELERO_RESTORE_PLURAL = "restores"
VELERO_BSL_PLURAL = "backupstoragelocations"
VELERO_PVB_PLURAL = "podvolumebackups"
#: Label Velero puts on the objects it creates for a backup.
VELERO_BACKUP_NAME_LABEL = "velero.io/backup-name"
#: Phases after which Velero no longer changes a backup or a restore.
TERMINAL_PHASES = frozenset(
    {"Completed", "PartiallyFailed", "Failed", "FailedValidation"}
)
_MAX_LABEL_LENGTH = 63


def velero_label_value(name: str) -> str:
    """The label value Velero writes for ``name``, which it cuts and hashes past 63 characters."""
    if len(name) <= _MAX_LABEL_LENGTH:
        return name
    digest = hashlib.sha256(name.encode()).hexdigest()
    return name[: _MAX_LABEL_LENGTH - 6] + digest[:6]


def failure_message(resource: str, status: dict[str, Any]) -> str:
    """Why Velero did not complete a backup or restore: its validation errors, failure reason or phase."""
    if errors := status.get("validationErrors"):
        return f"Velero {resource} failed validation: " + "; ".join(errors)
    if reason := status.get("failureReason"):
        return reason
    message = f"Velero {resource} phase: {status.get('phase', '')}"
    if count := status.get("errors"):
        message += f" ({count} errors)"
    return message


class VeleroClientError(Exception):
    """Base error for Velero client operations."""


class VeleroClient:
    """Async client for interacting with Velero CRDs via kubernetes-asyncio."""

    def __init__(self, api_client: Any) -> None:
        from kubernetes_asyncio.client import CustomObjectsApi

        self._api_client = api_client
        self.custom_api = CustomObjectsApi(api_client)

    async def create_backup(self, backup: VeleroBackup) -> dict[str, Any]:
        """Create a Velero Backup CRD."""
        body = backup.render()
        return await self.create_backup_from_dict(body)

    async def create_backup_from_dict(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a Velero Backup CRD from a pre-rendered dict."""
        namespace = body["metadata"]["namespace"]
        name = body["metadata"]["name"]
        try:
            result = await self.custom_api.create_namespaced_custom_object(
                group=VELERO_API_GROUP,
                version=VELERO_API_VERSION,
                namespace=namespace,
                plural=VELERO_BACKUP_PLURAL,
                body=body,
            )
            logger.info(f"Created Velero Backup: {name}")
            return result
        except Exception as e:
            raise VeleroClientError(
                f"Failed to create Velero Backup {name}: {e}"
            ) from e

    async def get_backup(self, name: str, namespace: str) -> dict[str, Any]:
        """Get a Velero Backup CRD by name."""
        try:
            return await self.custom_api.get_namespaced_custom_object(
                group=VELERO_API_GROUP,
                version=VELERO_API_VERSION,
                namespace=namespace,
                plural=VELERO_BACKUP_PLURAL,
                name=name,
            )
        except Exception as e:
            raise VeleroClientError(f"Failed to get Velero Backup {name}: {e}") from e

    async def delete_backup(self, name: str, namespace: str) -> None:
        """Delete a Velero Backup CRD."""
        try:
            await self.custom_api.delete_namespaced_custom_object(
                group=VELERO_API_GROUP,
                version=VELERO_API_VERSION,
                namespace=namespace,
                plural=VELERO_BACKUP_PLURAL,
                name=name,
            )
            logger.info(f"Deleted Velero Backup: {name}")
        except Exception as e:
            raise VeleroClientError(
                f"Failed to delete Velero Backup {name}: {e}"
            ) from e

    async def create_restore(self, restore: VeleroRestore) -> dict[str, Any]:
        """Create a Velero Restore CRD."""
        body = restore.render()
        return await self.create_restore_from_dict(body)

    async def create_restore_from_dict(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a Velero Restore CRD from a pre-rendered dict."""
        namespace = body["metadata"]["namespace"]
        name = body["metadata"]["name"]
        try:
            result = await self.custom_api.create_namespaced_custom_object(
                group=VELERO_API_GROUP,
                version=VELERO_API_VERSION,
                namespace=namespace,
                plural=VELERO_RESTORE_PLURAL,
                body=body,
            )
            logger.info(f"Created Velero Restore: {name}")
            return result
        except Exception as e:
            raise VeleroClientError(
                f"Failed to create Velero Restore {name}: {e}"
            ) from e

    async def get_restore(self, name: str, namespace: str) -> dict[str, Any]:
        """Get a Velero Restore CRD by name."""
        try:
            return await self.custom_api.get_namespaced_custom_object(
                group=VELERO_API_GROUP,
                version=VELERO_API_VERSION,
                namespace=namespace,
                plural=VELERO_RESTORE_PLURAL,
                name=name,
            )
        except Exception as e:
            raise VeleroClientError(f"Failed to get Velero Restore {name}: {e}") from e

    async def delete_restore(self, name: str, namespace: str) -> None:
        """Delete a Velero Restore CRD."""
        try:
            await self.custom_api.delete_namespaced_custom_object(
                group=VELERO_API_GROUP,
                version=VELERO_API_VERSION,
                namespace=namespace,
                plural=VELERO_RESTORE_PLURAL,
                name=name,
            )
            logger.info(f"Deleted Velero Restore: {name}")
        except Exception as e:
            raise VeleroClientError(
                f"Failed to delete Velero Restore {name}: {e}"
            ) from e

    async def create_bsl(
        self,
        bsl: VeleroBackupStorageLocation,
        access_key_id: str,
        secret_access_key: str,
    ) -> dict[str, Any]:
        """Create a Velero BackupStorageLocation CRD and its credential Secret."""
        from kubernetes_asyncio.client import CoreV1Api

        core_api = CoreV1Api(self._api_client)

        # Create credential Secret first
        secret_body: Any = bsl.render_secret(access_key_id, secret_access_key)
        try:
            await core_api.create_namespaced_secret(
                namespace=bsl.namespace, body=secret_body
            )
            logger.info(f"Created BSL credential Secret: {bsl.credential_secret_name}")
        except Exception as e:
            raise VeleroClientError(
                f"Failed to create BSL credential Secret {bsl.credential_secret_name}: {e}"
            ) from e

        # Create BSL CRD
        bsl_body = bsl.render_bsl()
        try:
            result = await self.custom_api.create_namespaced_custom_object(
                group=VELERO_API_GROUP,
                version=VELERO_API_VERSION,
                namespace=bsl.namespace,
                plural=VELERO_BSL_PLURAL,
                body=bsl_body,
            )
            logger.info(f"Created Velero BSL: {bsl.name}")
            return result
        except Exception as e:
            raise VeleroClientError(
                f"Failed to create Velero BSL {bsl.name}: {e}"
            ) from e

    async def delete_bsl(self, name: str, secret_name: str, namespace: str) -> None:
        """Delete a Velero BackupStorageLocation CRD and its credential Secret."""
        from kubernetes_asyncio.client import CoreV1Api

        core_api = CoreV1Api(self._api_client)

        # Delete BSL CRD
        try:
            await self.custom_api.delete_namespaced_custom_object(
                group=VELERO_API_GROUP,
                version=VELERO_API_VERSION,
                namespace=namespace,
                plural=VELERO_BSL_PLURAL,
                name=name,
            )
            logger.info(f"Deleted Velero BSL: {name}")
        except Exception as e:
            raise VeleroClientError(f"Failed to delete Velero BSL {name}: {e}") from e

        # Delete credential Secret
        try:
            await core_api.delete_namespaced_secret(
                name=secret_name, namespace=namespace
            )
            logger.info(f"Deleted BSL credential Secret: {secret_name}")
        except Exception as e:
            raise VeleroClientError(
                f"Failed to delete BSL credential Secret {secret_name}: {e}"
            ) from e

    async def update_bsl_secret(
        self,
        secret_name: str,
        namespace: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        """Update the credential Secret for a BSL."""
        from kubernetes_asyncio.client import CoreV1Api

        core_api = CoreV1Api(self._api_client)

        cloud_credentials = (
            f"[default]\n"
            f"aws_access_key_id = {access_key_id}\n"
            f"aws_secret_access_key = {secret_access_key}\n"
        )
        body = {
            "stringData": {
                "cloud": cloud_credentials,
            },
        }
        try:
            await core_api.patch_namespaced_secret(
                name=secret_name, namespace=namespace, body=body
            )
            logger.info(f"Updated BSL credential Secret: {secret_name}")
        except Exception as e:
            raise VeleroClientError(
                f"Failed to update BSL credential Secret {secret_name}: {e}"
            ) from e

    async def list_pod_volume_backups(
        self, namespace: str, backup_name: str
    ) -> list[dict[str, Any]]:
        """List the PodVolumeBackups of a Velero Backup, one per backed-up pod volume."""
        try:
            result = await self.custom_api.list_namespaced_custom_object(
                group=VELERO_API_GROUP,
                version=VELERO_API_VERSION,
                namespace=namespace,
                plural=VELERO_PVB_PLURAL,
                label_selector=(
                    f"{VELERO_BACKUP_NAME_LABEL}={velero_label_value(backup_name)}"
                ),
            )
        except Exception as e:
            raise VeleroClientError(
                f"Failed to list PodVolumeBackups of Velero Backup {backup_name}: {e}"
            ) from e
        return result.get("items", [])

    async def poll_backup_status(
        self,
        name: str,
        namespace: str,
        timeout: int = 3600,
        interval: int = 10,
        on_poll: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Poll Velero Backup status until completion or timeout.

        ``on_poll`` receives the Backup after each poll, the last one included.
        """
        elapsed = 0
        while elapsed < timeout:
            backup = await self.get_backup(name, namespace)
            if on_poll is not None:
                await on_poll(backup)
            status = backup.get("status", {})
            phase = status.get("phase", "")

            if phase in TERMINAL_PHASES:
                return backup

            logger.debug(f"Backup {name} phase: {phase}, waiting...")
            await asyncio.sleep(interval)
            elapsed += interval

        raise VeleroClientError(f"Backup {name} timed out after {timeout}s")

    async def poll_restore_status(
        self, name: str, namespace: str, timeout: int = 7200, interval: int = 10
    ) -> dict[str, Any]:
        """Poll Velero Restore status until completion or timeout."""
        elapsed = 0
        while elapsed < timeout:
            restore = await self.get_restore(name, namespace)
            status = restore.get("status", {})
            phase = status.get("phase", "")

            if phase in TERMINAL_PHASES:
                return restore

            logger.debug(f"Restore {name} phase: {phase}, waiting...")
            await asyncio.sleep(interval)
            elapsed += interval

        raise VeleroClientError(f"Restore {name} timed out after {timeout}s")
