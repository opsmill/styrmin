from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, NamedTuple

from loguru import logger

from styrmin_backend.agent.service.kubernetes.velero.resources import (
    BSL_ID_LABEL,
    VeleroBackup,
    VeleroBackupStorageLocation,
    VeleroRestore,
    velero_bsl_name,
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


def pod_volume_bytes(pod_volume_backups: list[dict[str, Any]]) -> int | None:
    """Sum ``status.progress.totalBytes`` over the completed PodVolumeBackups of one backup.

    This is the volume data the file-system backup read, before kopia deduplicates and
    compresses it; manifests are not counted. None when no PodVolumeBackup completed.
    """
    completed = [
        item.get("status") or {}
        for item in pod_volume_backups
        if (item.get("status") or {}).get("phase") == "Completed"
    ]
    if not completed:
        return None
    return sum(
        int((status.get("progress") or {}).get("totalBytes") or 0)
        for status in completed
    )


class VeleroClientError(Exception):
    """Base error for Velero client operations."""


class BslDeletion(NamedTuple):
    """How many objects of a backup storage location ``delete_bsl`` deleted."""

    locations: int
    secrets: int


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

    async def list_bsl_names(self, bsl_id: str, namespace: str) -> list[str]:
        """Names of the Velero BackupStorageLocations of the location ``bsl_id``, sorted.

        Found by label, so the list also holds objects that an earlier Styrmin
        version named after the location's name.
        """
        try:
            listed = await self.custom_api.list_namespaced_custom_object(
                group=VELERO_API_GROUP,
                version=VELERO_API_VERSION,
                namespace=namespace,
                plural=VELERO_BSL_PLURAL,
                label_selector=f"{BSL_ID_LABEL}={bsl_id}",
            )
        except Exception as e:
            raise VeleroClientError(
                f"Failed to list the Velero BSL of location {bsl_id}: {e}"
            ) from e
        return sorted(item["metadata"]["name"] for item in listed.get("items", []))

    async def get_bsl_name(self, bsl_id: str, namespace: str) -> str:
        """Name of the Velero BackupStorageLocation of the location ``bsl_id``.

        Prefers the object named after the id when there are several.
        """
        names = await self.list_bsl_names(bsl_id, namespace)
        if not names:
            raise VeleroClientError(
                f"No Velero BSL labelled {BSL_ID_LABEL}={bsl_id} in namespace {namespace}"
            )
        return velero_bsl_name(bsl_id) if velero_bsl_name(bsl_id) in names else names[0]

    async def delete_bsl(self, bsl_id: str, namespace: str) -> BslDeletion:
        """Delete the Velero BackupStorageLocations and credential Secrets of ``bsl_id``.

        Both are selected by label, which also covers objects that an earlier
        Styrmin version named after the location's name. Objects that are
        already gone count as removed. A failure on the Velero objects does not
        stop the Secrets, which hold the S3 keys, from being deleted.
        """
        from kubernetes_asyncio.client import ApiException, CoreV1Api

        core_api = CoreV1Api(self._api_client)
        selector = f"{BSL_ID_LABEL}={bsl_id}"
        failures: list[str] = []
        locations = secrets_deleted = 0

        async def _delete(
            kind: str, name: str, delete: Callable[[], Awaitable[Any]]
        ) -> int:
            """1 when this call deleted the object, else 0."""
            try:
                await delete()
            except ApiException as e:
                if e.status != 404:
                    failures.append(f"Failed to delete {kind} {name}: {e}")
                return 0
            except Exception as e:
                failures.append(f"Failed to delete {kind} {name}: {e}")
                return 0
            logger.info(f"Deleted {kind}: {name}")
            return 1

        try:
            listed = await self.custom_api.list_namespaced_custom_object(
                group=VELERO_API_GROUP,
                version=VELERO_API_VERSION,
                namespace=namespace,
                plural=VELERO_BSL_PLURAL,
                label_selector=selector,
            )
            for item in listed.get("items", []):
                name = item["metadata"]["name"]
                locations += await _delete(
                    "Velero BSL",
                    name,
                    partial(
                        self.custom_api.delete_namespaced_custom_object,
                        group=VELERO_API_GROUP,
                        version=VELERO_API_VERSION,
                        namespace=namespace,
                        plural=VELERO_BSL_PLURAL,
                        name=name,
                    ),
                )
        except Exception as e:
            failures.append(f"Failed to list the Velero BSL of location {bsl_id}: {e}")

        try:
            secrets = await core_api.list_namespaced_secret(
                namespace=namespace, label_selector=selector
            )
            for secret in secrets.items:
                name = secret.metadata.name
                secrets_deleted += await _delete(
                    "BSL credential Secret",
                    name,
                    partial(
                        core_api.delete_namespaced_secret,
                        name=name,
                        namespace=namespace,
                    ),
                )
        except Exception as e:
            failures.append(
                f"Failed to list the credential Secret of location {bsl_id}: {e}"
            )

        if failures:
            raise VeleroClientError("; ".join(failures))
        return BslDeletion(locations=locations, secrets=secrets_deleted)

    async def update_bsl_secret(
        self,
        bsl_id: str,
        namespace: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        """Update the credential Secrets of the location ``bsl_id``, found by label.

        A failed patch does not stop the other Secrets from being patched.
        """
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
            secrets = await core_api.list_namespaced_secret(
                namespace=namespace, label_selector=f"{BSL_ID_LABEL}={bsl_id}"
            )
        except Exception as e:
            raise VeleroClientError(
                f"Failed to list the credential Secret of location {bsl_id}: {e}"
            ) from e
        if not secrets.items:
            raise VeleroClientError(
                f"No credential Secret labelled {BSL_ID_LABEL}={bsl_id} "
                f"in namespace {namespace}"
            )
        failures: list[str] = []
        for secret in secrets.items:
            secret_name = secret.metadata.name
            try:
                await core_api.patch_namespaced_secret(
                    name=secret_name, namespace=namespace, body=body
                )
                logger.info(f"Updated BSL credential Secret: {secret_name}")
            except Exception as e:
                failures.append(
                    f"Failed to update BSL credential Secret {secret_name}: {e}"
                )
        if failures:
            raise VeleroClientError("; ".join(failures))

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
