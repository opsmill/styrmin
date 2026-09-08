"""Unit tests for Velero resource dataclasses."""

from __future__ import annotations

from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackup,
    VeleroBackupHook,
    VeleroBackupHookExec,
    VeleroRestore,
    VeleroRestoreHook,
    VeleroRestoreHookExec,
)


class TestVeleroRestore:
    def test_render_basic(self) -> None:
        restore = VeleroRestore(
            name="my-restore",
            namespace="velero",
            backup_name="my-backup",
        )
        result = restore.render()
        assert result["apiVersion"] == "velero.io/v1"
        assert result["kind"] == "Restore"
        assert result["metadata"]["name"] == "my-restore"
        assert result["metadata"]["namespace"] == "velero"
        assert result["spec"]["backupName"] == "my-backup"
        assert result["spec"]["restorePVs"] is True
        assert result["spec"]["preserveNodePorts"] is True
        assert "existingResourcePolicy" not in result["spec"]
        assert "namespaceMapping" not in result["spec"]
        assert "resourceModifier" not in result["spec"]

    def test_render_with_existing_resource_policy(self) -> None:
        restore = VeleroRestore(
            name="my-restore",
            namespace="velero",
            backup_name="my-backup",
            existing_resource_policy="update",
        )
        result = restore.render()
        assert result["spec"]["existingResourcePolicy"] == "update"

    def test_render_with_namespace_mapping(self) -> None:
        restore = VeleroRestore(
            name="my-restore",
            namespace="velero",
            backup_name="my-backup",
            namespace_mapping={"ns-a": "ns-b"},
        )
        result = restore.render()
        assert result["spec"]["namespaceMapping"] == {"ns-a": "ns-b"}

    def test_render_with_labels(self) -> None:
        restore = VeleroRestore(
            name="my-restore",
            namespace="velero",
            backup_name="my-backup",
            labels={"styrmin.io/instance": "abc"},
        )
        result = restore.render()
        assert result["metadata"]["labels"] == {"styrmin.io/instance": "abc"}

    def test_render_with_resource_modifier_ref(self) -> None:
        restore = VeleroRestore(
            name="my-restore",
            namespace="velero",
            backup_name="my-backup",
            resource_modifier_ref="my-configmap",
        )
        result = restore.render()
        assert result["spec"]["resourceModifier"] == {
            "kind": "ConfigMap",
            "name": "my-configmap",
        }

    def test_render_with_all_options(self) -> None:
        restore = VeleroRestore(
            name="my-restore",
            namespace="velero",
            backup_name="my-backup",
            namespace_mapping={"src": "dst"},
            labels={"key": "val"},
            existing_resource_policy="update",
            restore_pvs=False,
            preserve_node_ports=False,
            resource_modifier_ref="pvc-patch",
        )
        result = restore.render()
        assert result["spec"]["existingResourcePolicy"] == "update"
        assert result["spec"]["namespaceMapping"] == {"src": "dst"}
        assert result["spec"]["restorePVs"] is False
        assert result["spec"]["preserveNodePorts"] is False
        assert result["spec"]["resourceModifier"] == {
            "kind": "ConfigMap",
            "name": "pvc-patch",
        }
        assert result["metadata"]["labels"] == {"key": "val"}

    def test_render_without_hooks(self) -> None:
        restore = VeleroRestore(
            name="my-restore",
            namespace="velero",
            backup_name="my-backup",
        )
        result = restore.render()
        assert "hooks" not in result["spec"]

    def test_render_with_hooks(self) -> None:
        hook = VeleroRestoreHook(
            name="pg-restore",
            included_namespaces=["ns1"],
            label_selector={"matchLabels": {"styrmin/component": "db"}},
            post=[
                VeleroRestoreHookExec(
                    container="postgresql",
                    command=["/bin/sh", "-c", "pg_restore ..."],
                    on_error="Fail",
                    exec_timeout="600s",
                )
            ],
        )
        restore = VeleroRestore(
            name="my-restore",
            namespace="velero",
            backup_name="my-backup",
            hooks=[hook],
        )
        result = restore.render()
        assert "hooks" in result["spec"]
        assert len(result["spec"]["hooks"]["resources"]) == 1
        rendered_hook = result["spec"]["hooks"]["resources"][0]
        assert rendered_hook["name"] == "pg-restore"
        assert len(rendered_hook["postHooks"]) == 1
        assert rendered_hook["postHooks"][0]["exec"]["container"] == "postgresql"
        assert rendered_hook["postHooks"][0]["exec"]["waitForReady"] is True


class TestVeleroRestoreHook:
    def test_render(self) -> None:
        hook = VeleroRestoreHook(
            name="db-postgres-restore",
            included_namespaces=["app-ns"],
            label_selector={"matchLabels": {"styrmin/component": "db"}},
            post=[
                VeleroRestoreHookExec(
                    container="postgresql",
                    command=["/bin/sh", "-c", "pg_restore ..."],
                    on_error="Fail",
                    exec_timeout="600s",
                ),
                VeleroRestoreHookExec(
                    container="postgresql",
                    command=["/bin/sh", "-c", "rm -f /backup/pre-snapshot.dump"],
                    on_error="Continue",
                    exec_timeout="30s",
                ),
            ],
        )
        result = hook.render()
        assert result["name"] == "db-postgres-restore"
        assert result["includedNamespaces"] == ["app-ns"]
        assert result["labelSelector"] == {"matchLabels": {"styrmin/component": "db"}}
        assert len(result["postHooks"]) == 2
        assert result["postHooks"][0]["exec"]["container"] == "postgresql"
        assert result["postHooks"][0]["exec"]["onError"] == "Fail"
        assert result["postHooks"][0]["exec"]["waitForReady"] is True
        assert result["postHooks"][0]["exec"]["execTimeout"] == "600s"
        assert result["postHooks"][1]["exec"]["onError"] == "Continue"
        assert result["postHooks"][1]["exec"]["execTimeout"] == "30s"
        assert result["postHooks"][1]["exec"]["waitForReady"] is True

    def test_render_uses_exec_timeout_not_timeout(self) -> None:
        """Restore hooks name the field ``execTimeout``; ``timeout`` is backup-only.

        The Restore CRD's structural schema prunes unknown keys silently, so
        rendering ``timeout`` did not fail -- velero just fell back to its 30s
        default and killed any longer-running restore command.
        """
        hook = VeleroRestoreHook(
            name="db-postgres-restore",
            included_namespaces=["app-ns"],
            label_selector={"matchLabels": {"styrmin/component": "db"}},
            post=[
                VeleroRestoreHookExec(
                    command=["/bin/sh", "-c", "pg_restore ..."],
                    exec_timeout="600s",
                )
            ],
        )
        exec_spec = hook.render()["postHooks"][0]["exec"]
        assert exec_spec["execTimeout"] == "600s"
        assert "timeout" not in exec_spec

    def test_render_omits_wait_timeout_by_default(self) -> None:
        """Unset ``waitTimeout`` means velero waits indefinitely for readiness.

        A finite value would reintroduce the failure the hook's own readiness
        polling exists to avoid, so it is only emitted when explicitly set.
        """
        post = [VeleroRestoreHookExec(command=["true"])]
        hook = VeleroRestoreHook(
            name="db-restore",
            included_namespaces=["ns1"],
            label_selector={"matchLabels": {"styrmin/component": "db"}},
            post=post,
        )
        assert "waitTimeout" not in hook.render()["postHooks"][0]["exec"]

        post[0].wait_timeout = "300s"
        assert hook.render()["postHooks"][0]["exec"]["waitTimeout"] == "300s"

    def test_render_omits_container_when_none(self) -> None:
        hook = VeleroRestoreHook(
            name="db-restore",
            included_namespaces=["ns1"],
            label_selector={"matchLabels": {"styrmin/component": "db"}},
            post=[
                VeleroRestoreHookExec(
                    command=["/bin/sh", "-c", "pg_restore ..."],
                )
            ],
        )
        result = hook.render()
        assert "container" not in result["postHooks"][0]["exec"]

    def test_render_single_post_hook(self) -> None:
        hook = VeleroRestoreHook(
            name="test-hook",
            included_namespaces=["ns1"],
            label_selector={"matchLabels": {"app": "test"}},
            post=[
                VeleroRestoreHookExec(
                    container="main",
                    command=["echo", "done"],
                )
            ],
        )
        result = hook.render()
        assert len(result["postHooks"]) == 1
        assert result["postHooks"][0]["exec"]["command"] == ["echo", "done"]
        assert result["postHooks"][0]["exec"]["waitForReady"] is True


class TestVeleroBackupHook:
    def test_render_omits_container_when_none(self) -> None:
        hook = VeleroBackupHook(
            name="db-backup",
            included_namespaces=["ns1"],
            label_selector={"matchLabels": {"styrmin/component": "db"}},
            pre=[
                VeleroBackupHookExec(
                    command=["/bin/sh", "-c", "pg_dump"],
                )
            ],
        )
        result = hook.render()
        assert "container" not in result["pre"][0]["exec"]

    def test_render_includes_container_when_set(self) -> None:
        hook = VeleroBackupHook(
            name="db-backup",
            included_namespaces=["ns1"],
            label_selector={"matchLabels": {"styrmin/component": "db"}},
            pre=[
                VeleroBackupHookExec(
                    command=["/bin/sh", "-c", "pg_dump"],
                    container="postgresql",
                )
            ],
        )
        result = hook.render()
        assert result["pre"][0]["exec"]["container"] == "postgresql"


class TestVeleroBackup:
    def test_render_basic(self) -> None:
        backup = VeleroBackup(
            name="my-backup",
            namespace="velero",
            included_namespaces=["app-ns"],
            ttl="2160h",
        )
        result = backup.render()
        assert result["apiVersion"] == "velero.io/v1"
        assert result["kind"] == "Backup"
        assert result["spec"]["includedNamespaces"] == ["app-ns"]
        assert result["spec"]["includeClusterResources"] is False
        # ``ttl`` is a required input with no default (016): the renderer
        # passes through whatever retention the caller resolved.
        assert result["spec"]["ttl"] == "2160h"
        assert "labelSelector" not in result["spec"]

    def test_render_with_hooks(self) -> None:
        hook = VeleroBackupHook(
            name="pg-hook",
            included_namespaces=["ns1"],
            label_selector={"matchLabels": {"component": "db"}},
            pre=[
                VeleroBackupHookExec(
                    container="postgresql",
                    command=["/bin/sh", "-c", "pg_dump"],
                )
            ],
        )
        backup = VeleroBackup(
            name="my-backup",
            namespace="velero",
            included_namespaces=["ns1"],
            ttl="720h",
            hooks=[hook],
        )
        result = backup.render()
        assert "hooks" in result["spec"]
        assert len(result["spec"]["hooks"]["resources"]) == 1
        assert result["spec"]["hooks"]["resources"][0]["name"] == "pg-hook"
