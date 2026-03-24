from __future__ import annotations

from typing import Any

from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackupHook,
    VeleroRestoreHook,
)
from styrmin_backend.services.backup.strategies.base import BackupStrategy


class DiskSnapshotStrategy(BackupStrategy):
    """Direct volume snapshot via Velero - no hooks needed."""

    def get_hooks(
        self,
        namespace: str,
        component_name: str,
        config: dict[str, Any],
    ) -> list[VeleroBackupHook]:
        return []

    def get_restore_hooks(
        self,
        namespace: str,
        component_name: str,
        config: dict[str, Any],
    ) -> list[VeleroRestoreHook]:
        return []

    def get_backup_volumes(
        self,
        component_name: str,
        config: dict[str, Any],
    ) -> list[str]:
        volume = config.get("volume")
        volumes = config.get("volumes")
        if volumes:
            return list(volumes)
        if volume:
            return [volume]
        return []
