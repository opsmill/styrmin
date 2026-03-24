from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from styrmin_backend.agent.service.kubernetes.velero.resources import (
        VeleroBackupHook,
        VeleroRestoreHook,
    )


class BackupStrategy(ABC):
    """Abstract base class for backup strategies."""

    @abstractmethod
    def get_hooks(
        self,
        namespace: str,
        component_name: str,
        config: dict[str, Any],
    ) -> list[VeleroBackupHook]:
        """Return Velero backup hooks for this strategy."""

    @abstractmethod
    def get_restore_hooks(
        self,
        namespace: str,
        component_name: str,
        config: dict[str, Any],
    ) -> list[VeleroRestoreHook]:
        """Return Velero restore hooks for this strategy."""

    @abstractmethod
    def get_backup_volumes(
        self,
        component_name: str,
        config: dict[str, Any],
    ) -> list[str]:
        """Return the list of volume names to back up for this component."""
