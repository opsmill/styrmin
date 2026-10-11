from __future__ import annotations

from typing import Any

from styrmin_backend.agent.service.kubernetes.velero.hooks import (
    neo4j_community_backup_hooks,
)
from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackupHook,
    VeleroRestoreHook,
)
from styrmin_backend.services.backup.strategies.base import BackupStrategy


class Neo4jCommunityBackupStrategy(BackupStrategy):
    """Neo4j Community backup: pause Neo4j while Velero backs up its data volume.

    The restore needs no hook: Velero lays the volume down before Neo4j starts,
    and Neo4j replays its transaction logs on startup.
    """

    post_hook_failure = (
        "The post-backup hook of this component fails when Neo4j was not paused for "
        "the whole copy of its data volume, so this copy may not be consistent"
    )

    def get_hooks(
        self,
        namespace: str,
        component_name: str,
        config: dict[str, Any],
    ) -> list[VeleroBackupHook]:
        return [
            neo4j_community_backup_hooks(
                namespace=namespace,
                component_name=component_name,
                container=config.get("container"),
            )
        ]

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
        return [config.get("volume") or "data"]
