from __future__ import annotations

from typing import Any

from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackupHook,
    VeleroRestoreHook,
)
from styrmin_backend.services.backup.strategies.base import BackupStrategy


class ActionBackupStrategy(BackupStrategy):
    """Custom backup via driver's action system (Prefect flows), not Velero hooks."""

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
        return []
