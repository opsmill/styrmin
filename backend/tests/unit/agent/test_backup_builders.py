"""Unit tests for backup builder functions."""

from __future__ import annotations

from styrmin_backend.agent.service.kubernetes.resources.builders.backup import (
    build_velero_backup,
    build_velero_restore,
)


class TestBuildVeleroBackup:
    def test_basic_backup(self) -> None:
        backup = build_velero_backup(
            name="test-backup",
            velero_namespace="velero",
            target_namespace="app-ns",
            instance_id="inst-123",
            driver_name="mydriver",
            ttl="2160h",
        )
        rendered = backup.render()
        assert rendered["metadata"]["name"] == "test-backup"
        assert rendered["metadata"]["namespace"] == "velero"
        assert rendered["spec"]["includedNamespaces"] == ["app-ns"]
        assert rendered["spec"]["includeClusterResources"] is False
        assert "labelSelector" not in rendered["spec"]
        assert rendered["metadata"]["labels"]["styrmin.io/driver"] == "mydriver"
        # ``ttl`` is a required argument with no default (016): the builder
        # passes the caller's resolved retention straight through.
        assert rendered["spec"]["ttl"] == "2160h"

    def test_backup_with_hooks(self) -> None:
        from styrmin_backend.agent.service.kubernetes.velero.resources import (
            VeleroBackupHook,
            VeleroBackupHookExec,
        )

        hook = VeleroBackupHook(
            name="pg-hook",
            included_namespaces=["app-ns"],
            label_selector={"matchLabels": {"component": "db"}},
            pre=[VeleroBackupHookExec(container="pg", command=["pg_dump"])],
        )
        backup = build_velero_backup(
            name="test-backup",
            velero_namespace="velero",
            target_namespace="app-ns",
            instance_id="inst-123",
            driver_name="mydriver",
            ttl="720h",
            hooks=[hook],
        )
        rendered = backup.render()
        assert "hooks" in rendered["spec"]
        assert len(rendered["spec"]["hooks"]["resources"]) == 1


class TestBuildVeleroRestore:
    def test_basic_restore_same_namespace(self) -> None:
        restore = build_velero_restore(
            name="test-restore",
            velero_namespace="velero",
            backup_name="test-backup",
            source_namespace="app-ns",
            target_namespace="app-ns",
            instance_id="inst-123",
            driver_name="mydriver",
        )
        rendered = restore.render()
        assert rendered["metadata"]["name"] == "test-restore"
        assert rendered["spec"]["backupName"] == "test-backup"
        assert rendered["spec"]["restorePVs"] is False
        assert rendered["spec"]["preserveNodePorts"] is False
        assert rendered["spec"]["resourceModifier"] == {
            "kind": "ConfigMap",
            "name": "velero-restore-pvc-patch",
        }
        assert "namespaceMapping" not in rendered["spec"]
        assert "existingResourcePolicy" not in rendered["spec"]

    def test_restore_different_namespace(self) -> None:
        restore = build_velero_restore(
            name="test-restore",
            velero_namespace="velero",
            backup_name="test-backup",
            source_namespace="ns-a",
            target_namespace="ns-b",
            instance_id="inst-123",
            driver_name="mydriver",
        )
        rendered = restore.render()
        assert rendered["spec"]["namespaceMapping"] == {"ns-a": "ns-b"}

    def test_restore_with_existing_resource_policy(self) -> None:
        restore = build_velero_restore(
            name="test-restore",
            velero_namespace="velero",
            backup_name="test-backup",
            source_namespace="app-ns",
            target_namespace="app-ns",
            instance_id="inst-123",
            driver_name="mydriver",
            existing_resource_policy="update",
        )
        rendered = restore.render()
        assert rendered["spec"]["existingResourcePolicy"] == "update"

    def test_restore_labels(self) -> None:
        restore = build_velero_restore(
            name="test-restore",
            velero_namespace="velero",
            backup_name="test-backup",
            source_namespace="app-ns",
            target_namespace="app-ns",
            instance_id="inst-123",
            driver_name="mydriver",
        )
        rendered = restore.render()
        assert rendered["metadata"]["labels"]["styrmin.io/instance"] == "inst-123"
        assert rendered["metadata"]["labels"]["styrmin.io/driver"] == "mydriver"

    def test_restore_with_hooks(self) -> None:
        from styrmin_backend.agent.service.kubernetes.velero.resources import (
            VeleroRestoreHook,
            VeleroRestoreHookExec,
        )

        hook = VeleroRestoreHook(
            name="pg-restore",
            included_namespaces=["app-ns"],
            label_selector={"matchLabels": {"styrmin/component": "db"}},
            post=[
                VeleroRestoreHookExec(
                    container="postgresql",
                    command=["/bin/sh", "-c", "pg_restore ..."],
                )
            ],
        )
        restore = build_velero_restore(
            name="test-restore",
            velero_namespace="velero",
            backup_name="test-backup",
            source_namespace="app-ns",
            target_namespace="app-ns",
            instance_id="inst-123",
            driver_name="mydriver",
            hooks=[hook],
        )
        rendered = restore.render()
        assert "hooks" in rendered["spec"]
        assert len(rendered["spec"]["hooks"]["resources"]) == 1
        assert rendered["spec"]["hooks"]["resources"][0]["name"] == "pg-restore"

    def test_restore_without_hooks(self) -> None:
        restore = build_velero_restore(
            name="test-restore",
            velero_namespace="velero",
            backup_name="test-backup",
            source_namespace="app-ns",
            target_namespace="app-ns",
            instance_id="inst-123",
            driver_name="mydriver",
        )
        rendered = restore.render()
        assert "hooks" not in rendered["spec"]

    def test_cross_target_restore_labels_the_counterpart_instance(self) -> None:
        """research D2.6: a cross-target Restore CR is attributed to the target.

        ``instance_id`` names the instance the *backup* was taken from. For an
        environment clone the restore lands in a different (counterpart)
        instance, and labelling the CR with the source would misattribute it.
        """
        restore = build_velero_restore(
            name="test-restore",
            velero_namespace="velero",
            backup_name="test-backup",
            source_namespace="styrmin-source",
            target_namespace="styrmin-counterpart",
            instance_id="source-inst",
            driver_name="mydriver",
            target_instance_id="counterpart-inst",
        )
        rendered = restore.render()
        labels = rendered["metadata"]["labels"]
        assert labels["styrmin.io/instance"] == "counterpart-inst"
        # Provenance is preserved rather than dropped.
        assert labels["styrmin.io/source-instance"] == "source-inst"
        assert labels["styrmin.io/driver"] == "mydriver"
        assert rendered["spec"]["namespaceMapping"] == {
            "styrmin-source": "styrmin-counterpart"
        }

    def test_in_place_restore_labels_are_unchanged_without_target_instance(
        self,
    ) -> None:
        """Omitting ``target_instance_id`` renders exactly the shipped labels."""
        restore = build_velero_restore(
            name="test-restore",
            velero_namespace="velero",
            backup_name="test-backup",
            source_namespace="app-ns",
            target_namespace="app-ns",
            instance_id="inst-123",
            driver_name="mydriver",
        )
        rendered = restore.render()
        assert rendered["metadata"]["labels"] == {
            "styrmin.io/instance": "inst-123",
            "styrmin.io/driver": "mydriver",
        }

    def test_target_instance_equal_to_source_adds_no_provenance_label(self) -> None:
        """A "cross-target" restore that is really in-place stays clean."""
        restore = build_velero_restore(
            name="test-restore",
            velero_namespace="velero",
            backup_name="test-backup",
            source_namespace="app-ns",
            target_namespace="app-ns",
            instance_id="inst-123",
            driver_name="mydriver",
            target_instance_id="inst-123",
        )
        rendered = restore.render()
        assert rendered["metadata"]["labels"] == {
            "styrmin.io/instance": "inst-123",
            "styrmin.io/driver": "mydriver",
        }
