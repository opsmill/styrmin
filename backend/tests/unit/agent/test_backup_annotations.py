"""Unit tests for backup annotation injection in ApplicationHelmReleaseBuilder."""

from __future__ import annotations

from styrmin_backend.agent.service.kubernetes.resources.builders.backup_annotations import (
    VELERO_BACKUP_VOLUMES_ANNOTATION,
    build_backup_volume_annotation_patches,
)
from styrmin_backend.services.driver.models.resources.backup import (
    BackupKind,
    ComponentBackupConfig,
)


class TestBuildBackupVolumeAnnotationPatches:
    def test_empty_configs(self) -> None:
        patches = build_backup_volume_annotation_patches({}, {})
        assert patches == []

    def test_disabled_config(self) -> None:
        configs = {
            "db": ComponentBackupConfig(enabled=False, kind=BackupKind.POSTGRES),
        }
        selectors = {"db": "app.kubernetes.io/name=postgresql"}
        patches = build_backup_volume_annotation_patches(configs, selectors)
        assert patches == []

    def test_postgres_kind_produces_backup_volume(self) -> None:
        configs = {
            "database": ComponentBackupConfig(enabled=True, kind=BackupKind.POSTGRES),
        }
        selectors = {"database": "app.kubernetes.io/name=postgresql"}
        patches = build_backup_volume_annotation_patches(configs, selectors)

        # Should produce 2 patches (Deployment + StatefulSet)
        assert len(patches) == 2

        for patch in patches:
            rendered = patch.patch.render_value()
            assert VELERO_BACKUP_VOLUMES_ANNOTATION in rendered
            assert "backup" in rendered  # default volume name for postgres
            assert "apiVersion: apps/v1" in rendered
            assert "name:" in rendered

    def test_disk_kind_with_volumes(self) -> None:
        configs = {
            "data": ComponentBackupConfig(
                enabled=True, kind=BackupKind.DISK, volumes=["vol1", "vol2"]
            ),
        }
        selectors = {"data": "app.kubernetes.io/name=data"}
        patches = build_backup_volume_annotation_patches(configs, selectors)

        assert len(patches) == 2

        for patch in patches:
            rendered = patch.patch.render_value()
            assert "vol1,vol2" in rendered
            assert "apiVersion: apps/v1" in rendered

    def test_disk_kind_with_single_volume(self) -> None:
        configs = {
            "data": ComponentBackupConfig(
                enabled=True, kind=BackupKind.DISK, volume="my-vol"
            ),
        }
        selectors = {"data": "app.kubernetes.io/name=data"}
        patches = build_backup_volume_annotation_patches(configs, selectors)

        assert len(patches) == 2

        for patch in patches:
            rendered = patch.patch.render_value()
            assert "my-vol" in rendered
            assert "apiVersion: apps/v1" in rendered

    def test_missing_label_selector(self) -> None:
        configs = {
            "db": ComponentBackupConfig(enabled=True, kind=BackupKind.POSTGRES),
        }
        selectors: dict[str, str] = {}  # No selector for "db"
        patches = build_backup_volume_annotation_patches(configs, selectors)
        assert patches == []

    def test_action_kind_no_volumes(self) -> None:
        configs = {
            "worker": ComponentBackupConfig(enabled=True, kind=BackupKind.ACTION),
        }
        selectors = {"worker": "app.kubernetes.io/name=worker"}
        patches = build_backup_volume_annotation_patches(configs, selectors)
        assert patches == []

    def test_neo4j_kind_produces_backup_volume(self) -> None:
        configs = {
            "graph": ComponentBackupConfig(enabled=True, kind=BackupKind.NEO4J),
        }
        selectors = {"graph": "app.kubernetes.io/name=neo4j"}
        patches = build_backup_volume_annotation_patches(configs, selectors)

        assert len(patches) == 2

        for patch in patches:
            rendered = patch.patch.render_value()
            assert "backup" in rendered
            assert "apiVersion: apps/v1" in rendered

    def test_mariadb_kind_produces_backup_volume(self) -> None:
        configs = {
            "db": ComponentBackupConfig(enabled=True, kind=BackupKind.MARIADB),
        }
        selectors = {"db": "app.kubernetes.io/component=mariadb"}
        patches = build_backup_volume_annotation_patches(configs, selectors)

        assert len(patches) == 2

        for patch in patches:
            rendered = patch.patch.render_value()
            assert "backup" in rendered
            assert "apiVersion: apps/v1" in rendered

    def test_mongodb_kind_produces_backup_volume(self) -> None:
        configs = {
            "db": ComponentBackupConfig(enabled=True, kind=BackupKind.MONGODB),
        }
        selectors = {"db": "app.kubernetes.io/component=mongodb"}
        patches = build_backup_volume_annotation_patches(configs, selectors)

        assert len(patches) == 2

        for patch in patches:
            rendered = patch.patch.render_value()
            assert "backup" in rendered
            assert "apiVersion: apps/v1" in rendered

    def test_patch_kind_matches_target_kind(self) -> None:
        """The patch kind should match its target kind for correct schema merging."""
        configs = {
            "db": ComponentBackupConfig(enabled=True, kind=BackupKind.POSTGRES),
        }
        selectors = {"db": "app.kubernetes.io/name=db"}
        patches = build_backup_volume_annotation_patches(configs, selectors)

        assert len(patches) == 2
        for patch in patches:
            rendered = patch.patch.render_value()
            assert f"kind: {patch.target.kind}" in rendered
