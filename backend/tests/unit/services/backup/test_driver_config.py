"""Unit tests for driver backup config validation (T036) and annotation injection (T037)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    TargetPatch,
    TemplateAnnotationPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.builders.backup_annotations import (
    VELERO_BACKUP_VOLUMES_ANNOTATION,
    build_backup_volume_annotation_patches,
)
from styrmin_backend.services.driver.exceptions import ValidationError
from styrmin_backend.services.driver.models.resources.backup import (
    BackupKind,
    ComponentBackupConfig,
)
from styrmin_backend.services.driver.validators import (
    BackupConfigValidator,
    validate_driver_backup_configs,
)

# Repo root: .../backend/tests/unit/services/backup/test_driver_config.py
_REPO_ROOT = Path(__file__).resolve().parents[5]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**kwargs) -> ComponentBackupConfig:
    """Create a ComponentBackupConfig with sensible defaults."""
    return ComponentBackupConfig(**kwargs)


def _make_actions_list(hook_names: list[str]) -> list:
    """Build a list of ActionDefinition objects with the given action names."""
    from styrmin_backend.services.driver.models.resources.actions import (
        ActionDefinition,
        HookKind,
    )

    return [
        ActionDefinition(
            name=name,
            location=f"actions.py::{name}",
            description=f"The {name} action",
            hook=HookKind.SETUP,
            mode="core",
        )
        for name in hook_names
    ]


# ===========================================================================
# T036 - BackupConfigValidator / validate_driver_backup_configs
# ===========================================================================


class TestValidConfigs:
    """Valid configurations for all backup kinds should pass validation."""

    def test_disk_single_volume(self) -> None:
        configs = {
            "web": _make_config(enabled=True, kind="disk", volume="data"),
        }
        validator = BackupConfigValidator(
            component_volumes={"web": ["data", "logs"]},
        )
        validator.validate(configs)

    def test_disk_multiple_volumes(self) -> None:
        configs = {
            "web": _make_config(enabled=True, kind="disk", volumes=["data", "logs"]),
        }
        validator = BackupConfigValidator(
            component_volumes={"web": ["data", "logs"]},
        )
        validator.validate(configs)

    def test_disk_without_known_volumes(self) -> None:
        """When component_volumes is not provided, skip volume existence checks."""
        configs = {
            "web": _make_config(enabled=True, kind="disk", volume="any-vol"),
        }
        validator = BackupConfigValidator()
        validator.validate(configs)

    def test_postgres_kind(self) -> None:
        configs = {
            "db": _make_config(enabled=True, kind="postgres", database_name="mydb"),
        }
        validator = BackupConfigValidator()
        validator.validate(configs)

    def test_neo4j_kind(self) -> None:
        configs = {
            "graph": _make_config(enabled=True, kind="neo4j"),
        }
        validator = BackupConfigValidator()
        validator.validate(configs)

    def test_mariadb_kind(self) -> None:
        configs = {
            "db": _make_config(enabled=True, kind="mariadb"),
        }
        validator = BackupConfigValidator()
        validator.validate(configs)

    def test_mongodb_kind(self) -> None:
        configs = {
            "db": _make_config(enabled=True, kind="mongodb"),
        }
        validator = BackupConfigValidator()
        validator.validate(configs)

    def test_action_kind_with_hooks(self) -> None:
        configs = {
            "custom": _make_config(enabled=True, kind="action"),
        }
        validator = BackupConfigValidator(
            action_hooks={"backup", "restore"},
        )
        validator.validate(configs)

    def test_disabled_config_skipped(self) -> None:
        """Disabled backup configs should never raise, even if incomplete."""
        configs = {
            "web": _make_config(enabled=False),
        }
        validator = BackupConfigValidator()
        validator.validate(configs)

    def test_valid_credentials_secret(self) -> None:
        configs = {
            "db": _make_config(
                enabled=True,
                kind="postgres",
                credentials_secret="my-pg-secret",
            ),
        }
        validator = BackupConfigValidator()
        validator.validate(configs)

    def test_multiple_components_all_valid(self) -> None:
        configs = {
            "web": _make_config(enabled=True, kind="disk", volume="data"),
            "db": _make_config(enabled=True, kind="postgres"),
            "graph": _make_config(enabled=True, kind="neo4j"),
        }
        validator = BackupConfigValidator(
            component_volumes={"web": ["data"]},
        )
        validator.validate(configs)

    def test_empty_configs(self) -> None:
        validator = BackupConfigValidator()
        validator.validate({})


class TestMissingKind:
    """When enabled=true, kind must be present."""

    def test_model_level_validation_rejects_missing_kind(self) -> None:
        """The Pydantic model itself should reject missing kind when enabled."""
        with pytest.raises(ValueError, match="kind is required when backup is enabled"):
            _make_config(enabled=True, kind=None)

    def test_validator_rejects_enabled_without_kind(self) -> None:
        """BackupConfigValidator also catches it if config is constructed without model validation."""
        config = ComponentBackupConfig.model_construct(enabled=True, kind=None)
        configs = {"web": config}
        validator = BackupConfigValidator()
        with pytest.raises(ValidationError, match="kind is required"):
            validator.validate(configs)


class TestInvalidVolumeReferences:
    """Disk kind requires volume references that match known volumes."""

    def test_disk_no_volume_specified(self) -> None:
        configs = {
            "web": _make_config(enabled=True, kind="disk"),
        }
        validator = BackupConfigValidator()
        with pytest.raises(
            ValidationError, match="disk backup requires at least one volume"
        ):
            validator.validate(configs)

    def test_disk_volume_not_in_known_volumes(self) -> None:
        configs = {
            "web": _make_config(enabled=True, kind="disk", volume="missing-vol"),
        }
        validator = BackupConfigValidator(
            component_volumes={"web": ["data", "logs"]},
        )
        with pytest.raises(
            ValidationError, match="volume 'missing-vol' is not defined"
        ):
            validator.validate(configs)

    def test_disk_volumes_one_not_in_known_volumes(self) -> None:
        configs = {
            "web": _make_config(
                enabled=True, kind="disk", volumes=["data", "missing-vol"]
            ),
        }
        validator = BackupConfigValidator(
            component_volumes={"web": ["data", "logs"]},
        )
        with pytest.raises(
            ValidationError, match="volume 'missing-vol' is not defined"
        ):
            validator.validate(configs)


class TestMissingActionHooks:
    """Action kind requires 'backup' and 'restore' hooks in the actions spec."""

    def test_action_missing_both_hooks(self) -> None:
        configs = {
            "custom": _make_config(enabled=True, kind="action"),
        }
        validator = BackupConfigValidator(action_hooks=set())
        with pytest.raises(
            ValidationError, match="action backup requires action hooks"
        ):
            validator.validate(configs)

    def test_action_missing_restore_hook(self) -> None:
        configs = {
            "custom": _make_config(enabled=True, kind="action"),
        }
        validator = BackupConfigValidator(action_hooks={"backup"})
        with pytest.raises(ValidationError, match="'restore'"):
            validator.validate(configs)

    def test_action_missing_backup_hook(self) -> None:
        configs = {
            "custom": _make_config(enabled=True, kind="action"),
        }
        validator = BackupConfigValidator(action_hooks={"restore"})
        with pytest.raises(ValidationError, match="'backup'"):
            validator.validate(configs)


class TestInvalidCredentialsSecret:
    """credentials_secret must match Kubernetes naming conventions."""

    def test_uppercase_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="credentials_secret must match Kubernetes"
        ):
            _make_config(enabled=True, kind="postgres", credentials_secret="MySecret")

    def test_leading_dot_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="credentials_secret must match Kubernetes"
        ):
            _make_config(enabled=True, kind="postgres", credentials_secret=".bad-name")

    def test_trailing_dot_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="credentials_secret must match Kubernetes"
        ):
            _make_config(enabled=True, kind="postgres", credentials_secret="bad-name.")

    def test_special_chars_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="credentials_secret must match Kubernetes"
        ):
            _make_config(enabled=True, kind="postgres", credentials_secret="bad_name!")

    def test_single_char_rejected(self) -> None:
        """The regex requires at least 2 chars (start + end anchors without middle)."""
        with pytest.raises(
            ValueError, match="credentials_secret must match Kubernetes"
        ):
            _make_config(enabled=True, kind="postgres", credentials_secret="a")

    def test_valid_name_accepted(self) -> None:
        config = _make_config(
            enabled=True, kind="postgres", credentials_secret="my-pg-secret.v2"
        )
        assert config.credentials_secret == "my-pg-secret.v2"


class TestValidateDriverBackupConfigs:
    """Test the top-level validate_driver_backup_configs convenience function."""

    def test_passes_action_hooks_from_actions(self) -> None:
        actions = _make_actions_list(["backup", "restore"])
        configs = {
            "custom": _make_config(enabled=True, kind="action"),
        }
        # Should not raise
        validate_driver_backup_configs(
            backup_configs=configs,
            actions=actions,
        )

    def test_fails_when_actions_missing_hooks(self) -> None:
        actions = _make_actions_list(["setup"])
        configs = {
            "custom": _make_config(enabled=True, kind="action"),
        }
        with pytest.raises(
            ValidationError, match="action backup requires action hooks"
        ):
            validate_driver_backup_configs(
                backup_configs=configs,
                actions=actions,
            )

    def test_passes_component_volumes(self) -> None:
        configs = {
            "web": _make_config(enabled=True, kind="disk", volume="data"),
        }
        validate_driver_backup_configs(
            backup_configs=configs,
            component_volumes={"web": ["data", "logs"]},
        )

    def test_fails_with_invalid_volume(self) -> None:
        configs = {
            "web": _make_config(enabled=True, kind="disk", volume="nope"),
        }
        with pytest.raises(ValidationError, match="volume 'nope' is not defined"):
            validate_driver_backup_configs(
                backup_configs=configs,
                component_volumes={"web": ["data"]},
            )


class TestNonDictDataRejected:
    """The validator expects a dict; anything else should raise."""

    def test_list_rejected(self) -> None:
        validator = BackupConfigValidator()
        with pytest.raises(ValidationError, match="must be a dict"):
            validator.validate([_make_config(enabled=True, kind="disk", volume="x")])

    def test_string_rejected(self) -> None:
        validator = BackupConfigValidator()
        with pytest.raises(ValidationError, match="must be a dict"):
            validator.validate("not a dict")


# ===========================================================================
# T037 - Backup volume annotation injection
# ===========================================================================


class TestBuildBackupVolumeAnnotationPatches:
    """Tests for build_backup_volume_annotation_patches."""

    def test_disk_single_volume(self) -> None:
        configs = {
            "web": _make_config(enabled=True, kind="disk", volume="data"),
        }
        label_selectors = {"web": "app=web"}

        patches = build_backup_volume_annotation_patches(configs, label_selectors)

        # Should produce 2 patches: one for Deployment, one for StatefulSet
        assert len(patches) == 2
        for patch in patches:
            assert isinstance(patch, TargetPatch)
            assert isinstance(patch.patch, TemplateAnnotationPatch)
            assert patch.patch.annotations[VELERO_BACKUP_VOLUMES_ANNOTATION] == "data"  # type: ignore[attr-defined]

    def test_disk_multiple_volumes(self) -> None:
        configs = {
            "web": _make_config(enabled=True, kind="disk", volumes=["data", "logs"]),
        }
        label_selectors = {"web": "app=web"}

        patches = build_backup_volume_annotation_patches(configs, label_selectors)

        assert len(patches) == 2
        for patch in patches:
            assert (
                patch.patch.annotations[VELERO_BACKUP_VOLUMES_ANNOTATION] == "data,logs"  # type: ignore[attr-defined]
            )

    def test_postgres_default_volume(self) -> None:
        configs = {
            "db": _make_config(enabled=True, kind="postgres"),
        }
        label_selectors = {"db": "app=db"}

        patches = build_backup_volume_annotation_patches(configs, label_selectors)

        assert len(patches) == 2
        for patch in patches:
            assert patch.patch.annotations[VELERO_BACKUP_VOLUMES_ANNOTATION] == "backup"  # type: ignore[attr-defined]

    def test_neo4j_default_volume(self) -> None:
        configs = {
            "graph": _make_config(enabled=True, kind="neo4j"),
        }
        label_selectors = {"graph": "app=graph"}

        patches = build_backup_volume_annotation_patches(configs, label_selectors)

        assert len(patches) == 2
        for patch in patches:
            assert patch.patch.annotations[VELERO_BACKUP_VOLUMES_ANNOTATION] == "backup"  # type: ignore[attr-defined]

    def test_action_kind_no_patches(self) -> None:
        """Action backups do not need volume annotations."""
        configs = {
            "custom": _make_config(enabled=True, kind="action"),
        }
        label_selectors = {"custom": "app=custom"}

        patches = build_backup_volume_annotation_patches(configs, label_selectors)

        assert patches == []

    def test_disabled_config_no_patches(self) -> None:
        configs = {
            "web": _make_config(enabled=False, kind="disk", volume="data"),
        }
        label_selectors = {"web": "app=web"}

        patches = build_backup_volume_annotation_patches(configs, label_selectors)

        assert patches == []

    def test_missing_label_selector_skipped(self) -> None:
        """If no label selector exists for a component, skip it."""
        configs = {
            "web": _make_config(enabled=True, kind="disk", volume="data"),
        }

        patches = build_backup_volume_annotation_patches(configs, {})

        assert patches == []

    def test_multiple_components(self) -> None:
        configs = {
            "web": _make_config(enabled=True, kind="disk", volume="data"),
            "db": _make_config(enabled=True, kind="postgres"),
            "graph": _make_config(enabled=False, kind="neo4j"),
        }
        label_selectors = {
            "web": "app=web",
            "db": "app=db",
            "graph": "app=graph",
        }

        patches = build_backup_volume_annotation_patches(configs, label_selectors)

        # web: 2 patches (Deployment + StatefulSet), db: 2 patches, graph: disabled
        assert len(patches) == 4

    def test_patch_targets_deployment_and_statefulset(self) -> None:
        configs = {
            "web": _make_config(enabled=True, kind="disk", volume="data"),
        }
        label_selectors = {"web": "app=web"}

        patches = build_backup_volume_annotation_patches(configs, label_selectors)

        kinds = {p.target.kind for p in patches}
        assert kinds == {"Deployment", "StatefulSet"}

    def test_patch_target_label_selector(self) -> None:
        configs = {
            "web": _make_config(enabled=True, kind="disk", volume="data"),
        }
        label_selectors = {"web": "my-label=my-value"}

        patches = build_backup_volume_annotation_patches(configs, label_selectors)

        for patch in patches:
            assert patch.target.label_selector == "my-label=my-value"

    def test_empty_configs(self) -> None:
        patches = build_backup_volume_annotation_patches({}, {})
        assert patches == []

    def test_disk_no_volume_produces_no_patches(self) -> None:
        """Disk kind with no volume/volumes configured should not produce annotations."""
        config = ComponentBackupConfig.model_construct(
            enabled=True, kind=BackupKind.DISK, volume=None, volumes=None
        )
        configs = {"web": config}
        label_selectors = {"web": "app=web"}

        patches = build_backup_volume_annotation_patches(configs, label_selectors)

        assert patches == []


class TestInfrahubExampleDriverDiskBackup:
    """Guard the infrahub example drivers' disk backup against silent no-ops.

    Commit af6fc28 enabled ``kind: disk`` on the infrahub ``server`` component
    but omitted the ``volume`` name. Because the disk-volume validator is not
    wired into the driver-load path, that misconfiguration produced no Velero
    ``backup-volumes`` annotation and the server PVC (object-store / artifact
    content at ``/opt/infrahub/storage``) was silently never backed up. These
    tests pin the fix: the server's disk backup must name the
    ``infrahub-server-storage-data`` volume so it is actually captured.
    """

    # Pod-template volume name the infrahub chart mounts at
    # ``/opt/infrahub/storage`` (verified against the rendered chart).
    _SERVER_STORAGE_VOLUME = "infrahub-server-storage-data"

    @pytest.mark.parametrize("driver_dir", ["infrahub", "infrahub-enterprise"])
    def test_server_disk_backup_names_storage_volume(self, driver_dir: str) -> None:
        spec_path = (
            _REPO_ROOT / "driver" / "examples" / driver_dir / "driver.styrmin.yml"
        )
        spec = yaml.safe_load(spec_path.read_text())

        server = spec["spec"]["components"]["server"]
        backup_raw = server.get("backup")
        assert backup_raw is not None, (
            f"{driver_dir}: server component is missing a 'backup' block"
        )

        config = ComponentBackupConfig.model_validate(backup_raw)
        assert config.enabled is True
        assert config.kind == BackupKind.DISK

        # A disk backup with no volume name is a silent no-op; the volume must
        # be named for Velero's opt-in file-system backup to capture the PVC.
        patches = build_backup_volume_annotation_patches(
            {"server": config},
            {"server": "service=infrahub-server"},
        )
        assert patches, (
            f"{driver_dir}: server disk backup produced no backup-volumes "
            "annotation — the storage PVC would not be captured"
        )
        for patch in patches:
            assert (
                patch.patch.annotations[VELERO_BACKUP_VOLUMES_ANNOTATION]  # type: ignore[attr-defined]
                == self._SERVER_STORAGE_VOLUME
            )


class TestTemplateAnnotationPatchRendering:
    """Verify the TemplateAnnotationPatch renders correctly."""

    def test_render_value(self) -> None:
        patch = TemplateAnnotationPatch(
            annotations={"backup.velero.io/backup-volumes": "data,logs"}
        )
        rendered = patch.render_value()
        assert "backup.velero.io/backup-volumes" in rendered
        assert "data,logs" in rendered
        # Should be a strategic merge patch, not a JSON Patch
        assert "op:" not in rendered
        assert "apiVersion: apps/v1" in rendered
        assert "kind: Deployment" in rendered
        assert "name:" in rendered
        assert "spec:" in rendered
        assert "template:" in rendered
        assert "annotations:" in rendered

    def test_render_value_custom_kind(self) -> None:
        patch = TemplateAnnotationPatch(
            annotations={"backup.velero.io/backup-volumes": "data"},
            kind="StatefulSet",
        )
        rendered = patch.render_value()
        assert "kind: StatefulSet" in rendered
        assert "apiVersion: apps/v1" in rendered
