from __future__ import annotations

from typing import Any

from styrmin_backend.agent.service.kubernetes.velero.hooks import (
    mariadb_backup_hooks,
    mariadb_restore_hooks,
)
from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackupHook,
    VeleroRestoreHook,
)
from styrmin_backend.services.backup.strategies.base import BackupStrategy


class MariadbBackupStrategy(BackupStrategy):
    """MariaDB-aware backup: mariadb-dump to extra volume, Velero backs up extra volume."""

    def get_hooks(
        self,
        namespace: str,
        component_name: str,
        config: dict[str, Any],
    ) -> list[VeleroBackupHook]:
        container = config.get("container")
        backup_mount_path = config.get("backup_mount_path", "/backup")
        return [
            mariadb_backup_hooks(
                namespace=namespace,
                component_name=component_name,
                container=container,
                backup_mount_path=backup_mount_path,
            )
        ]

    def get_restore_hooks(
        self,
        namespace: str,
        component_name: str,
        config: dict[str, Any],
    ) -> list[VeleroRestoreHook]:
        container = config.get("container")
        backup_mount_path = config.get("backup_mount_path", "/backup")
        return [
            mariadb_restore_hooks(
                namespace=namespace,
                component_name=component_name,
                container=container,
                backup_mount_path=backup_mount_path,
            )
        ]

    def get_backup_volumes(
        self,
        component_name: str,
        config: dict[str, Any],
    ) -> list[str]:
        return [config.get("backup_volume", "backup")]
