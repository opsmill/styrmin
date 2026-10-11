"""Backup volume annotation injection for Kubernetes pod templates.

Builds Kustomize post-rendering patches that add the ``backup.velero.io/backup-volumes``
annotation to pod templates of Deployments and StatefulSets for backup-enabled components.
This annotation tells Velero which volumes to include in a backup.
"""

from __future__ import annotations

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    Target,
    TargetPatch,
    TemplateAnnotationPatch,
)
from styrmin_backend.services.driver.models.resources.backup import (
    BackupKind,
    ComponentBackupConfig,
)

VELERO_BACKUP_VOLUMES_ANNOTATION = "backup.velero.io/backup-volumes"


def build_backup_volume_annotation_patches(
    backup_configs: dict[str, ComponentBackupConfig],
    component_label_selectors: dict[str, str],
) -> list[TargetPatch]:
    """Build Kustomize patches that inject Velero backup-volumes annotations.

    For each backup-enabled component, this creates TargetPatch entries that add the
    ``backup.velero.io/backup-volumes`` annotation to the pod template metadata of
    matching Deployments and StatefulSets.

    The annotation value is a comma-separated list of volume names to back up. For
    ``disk`` kind, this comes from the ``volume``/``volumes`` fields. For
    ``neo4j-community``, it is the ``volume`` field, defaulting to ``"data"``. For
    ``postgres`` and ``neo4j`` kinds, this defaults to ``"backup"`` (or the configured
    ``backup_volume`` field if set, but that is handled at a higher level).

    Args:
        backup_configs: Mapping of component name to its backup configuration.
        component_label_selectors: Mapping of component name to its label selector
            string (e.g. ``"app.kubernetes.io/name=my-app"``).

    Returns:
        A list of TargetPatch entries to be added to the HelmRelease post-renderers.
    """
    patches: list[TargetPatch] = []

    for component_name, config in backup_configs.items():
        if not config.enabled:
            continue

        volumes = _resolve_backup_volumes(config)
        if not volumes:
            continue

        label_selector = component_label_selectors.get(component_name)
        if label_selector is None:
            continue

        annotation_value = ",".join(volumes)
        annotations = {VELERO_BACKUP_VOLUMES_ANNOTATION: annotation_value}

        for kind in ("Deployment", "StatefulSet"):
            patches.append(
                TargetPatch(
                    target=Target(
                        label_selector=label_selector,
                        kind=kind,
                    ),
                    patch=TemplateAnnotationPatch(annotations=annotations, kind=kind),
                )
            )

    return patches


def _resolve_backup_volumes(config: ComponentBackupConfig) -> list[str]:
    """Resolve the list of volume names that should be annotated for backup.

    Args:
        config: The component's backup configuration.

    Returns:
        A list of volume names. May be empty if no volumes apply.
    """
    if config.kind == BackupKind.DISK:
        if config.volumes:
            return list(config.volumes)
        if config.volume:
            return [config.volume]
        return []

    if config.kind == BackupKind.NEO4J_COMMUNITY:
        # Velero copies the paused database's own data volume, not a dump.
        return [config.volume or "data"]

    if config.kind in (
        BackupKind.POSTGRES,
        BackupKind.NEO4J,
        BackupKind.MARIADB,
        BackupKind.MONGODB,
    ):
        # Database backups use a dedicated backup volume; default to "backup"
        return ["backup"]

    # Action kind does not require volume annotations (handled externally)
    return []
