"""Unit tests for backup strategies."""

from __future__ import annotations

import pytest

from styrmin_backend.services.backup.strategies.action import ActionBackupStrategy
from styrmin_backend.services.backup.strategies.disk import DiskSnapshotStrategy
from styrmin_backend.services.backup.strategies.mariadb import MariadbBackupStrategy
from styrmin_backend.services.backup.strategies.mongodb import MongodbBackupStrategy
from styrmin_backend.services.backup.strategies.neo4j import Neo4jBackupStrategy
from styrmin_backend.services.backup.strategies.postgres import PostgresBackupStrategy


class TestDiskSnapshotStrategy:
    def test_get_hooks_returns_empty(self) -> None:
        strategy = DiskSnapshotStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="web",
            config={"kind": "disk", "volume": "data"},
        )
        assert hooks == []

    def test_get_restore_hooks_returns_empty(self) -> None:
        strategy = DiskSnapshotStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="web",
            config={"kind": "disk", "volume": "data"},
        )
        assert hooks == []

    def test_get_backup_volumes_single_volume(self) -> None:
        strategy = DiskSnapshotStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="web",
            config={"kind": "disk", "volume": "data"},
        )
        assert volumes == ["data"]

    def test_get_backup_volumes_multiple_volumes(self) -> None:
        strategy = DiskSnapshotStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="web",
            config={"kind": "disk", "volumes": ["data", "logs"]},
        )
        assert volumes == ["data", "logs"]

    def test_get_backup_volumes_prefers_volumes_over_volume(self) -> None:
        strategy = DiskSnapshotStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="web",
            config={"kind": "disk", "volume": "data", "volumes": ["v1", "v2"]},
        )
        assert volumes == ["v1", "v2"]

    def test_get_backup_volumes_empty_when_no_volume(self) -> None:
        strategy = DiskSnapshotStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="web",
            config={"kind": "disk"},
        )
        assert volumes == []


class TestPostgresBackupStrategy:
    def test_get_hooks_returns_postgres_hooks(self) -> None:
        strategy = PostgresBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "postgres"},
        )
        assert len(hooks) == 1
        hook = hooks[0]
        assert hook.name == "db-postgres-backup"
        assert hook.included_namespaces == ["test-ns"]
        assert len(hook.pre) == 1  # type: ignore[arg-type]
        assert len(hook.post) == 1  # type: ignore[arg-type]

    def test_get_hooks_custom_container(self) -> None:
        strategy = PostgresBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "postgres", "container": "my-pg"},
        )
        assert hooks[0].pre[0].container == "my-pg"  # type: ignore[index]

    def test_get_hooks_custom_mount_path(self) -> None:
        strategy = PostgresBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "postgres", "backup_mount_path": "/custom/backup"},
        )
        pre_cmd = hooks[0].pre[0].command  # type: ignore[index]
        assert "/custom/backup" in " ".join(pre_cmd)

    def test_get_restore_hooks_returns_postgres_hooks(self) -> None:
        strategy = PostgresBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "postgres"},
        )
        assert len(hooks) == 1
        hook = hooks[0]
        assert hook.name == "db-postgres-restore"
        assert hook.included_namespaces == ["test-ns"]
        assert len(hook.post) == 2

    def test_get_restore_hooks_custom_container(self) -> None:
        strategy = PostgresBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "postgres", "container": "my-pg"},
        )
        assert hooks[0].post[0].container == "my-pg"

    def test_get_restore_hooks_custom_mount_path(self) -> None:
        strategy = PostgresBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "postgres", "backup_mount_path": "/custom/backup"},
        )
        for hook_exec in hooks[0].post:
            assert "/custom/backup/pre-snapshot.dump" in " ".join(hook_exec.command)

    def test_restore_fences_concurrent_writers(self) -> None:
        """pg_restore must be the only writer while it rewrites the schema.

        A restore recreates the namespace, so the application pods boot
        against an empty database and run their own schema migrations
        concurrently with the restore. Interleaving the two leaves tables at
        an older migration revision and COPY failing on columns that no
        longer exist. The hook terminates rival backends on a loop for the
        duration; its own connections are tagged via PGAPPNAME so the loop
        cannot kill them.
        """
        strategy = PostgresBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "postgres"},
        )
        script = hooks[0].post[0].command[2]
        assert "PGAPPNAME=styrmin-restore" in script
        assert "pg_terminate_backend(pid)" in script
        assert "pid <> pg_backend_pid()" in script
        # A backend owned by another role has its application_name hidden;
        # treating that NULL as "one of ours" would silently disable the fence.
        assert "coalesce(application_name, '') <> 'styrmin-restore'" in script
        # The fence must be torn down however the hook exits.
        assert "trap 'kill \"$fence_pid\" 2>/dev/null || true' EXIT INT TERM" in script

    def test_restore_is_atomic_and_retried(self) -> None:
        """Each attempt is all-or-nothing, which is what makes retrying safe.

        Without --single-transaction a lost race leaves a half-dropped,
        half-recreated schema behind and a retry compounds it.
        """
        strategy = PostgresBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "postgres"},
        )
        script = hooks[0].post[0].command[2]
        assert "--single-transaction" in script
        assert "--clean --if-exists" in script
        assert "pg_restore attempt $attempt aborted; retrying" in script

    def test_restore_waits_for_the_database_rather_than_sleeping(self) -> None:
        """velero's waitForReady only covers the container's readiness probe.

        bitnami satisfies that probe while initdb is still creating the role
        and database, which is what produced ``FATAL: role "..." does not
        exist``. Poll for a query that has to succeed instead of guessing at
        a sleep.
        """
        strategy = PostgresBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "postgres"},
        )
        script = hooks[0].post[0].command[2]
        assert "sleep 5 &&" not in script
        assert "while ! psql" in script
        assert "-tAc 'SELECT 1'" in script

    def test_restore_hooks_declare_exec_timeout(self) -> None:
        """Restore hooks carry ``execTimeout``; a bare ``timeout`` is pruned.

        The Restore CRD's structural schema drops unknown keys without
        complaint, so a mis-named timeout silently became velero's 30s
        default and killed any longer restore.
        """
        strategy = PostgresBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "postgres"},
        )
        rendered = hooks[0].render()["postHooks"]
        assert rendered[0]["exec"]["execTimeout"] == "600s"
        assert all("timeout" not in post["exec"] for post in rendered)

    def test_get_backup_volumes_default(self) -> None:
        strategy = PostgresBackupStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="db",
            config={"kind": "postgres"},
        )
        assert volumes == ["backup"]

    def test_get_backup_volumes_custom(self) -> None:
        strategy = PostgresBackupStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="db",
            config={"kind": "postgres", "backup_volume": "pg-backup"},
        )
        assert volumes == ["pg-backup"]


class TestNeo4jBackupStrategy:
    def test_get_hooks_returns_neo4j_hooks(self) -> None:
        strategy = Neo4jBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="graph",
            config={"kind": "neo4j"},
        )
        assert len(hooks) == 1
        hook = hooks[0]
        assert hook.name == "graph-neo4j-backup"
        assert hook.included_namespaces == ["test-ns"]
        assert len(hook.pre) == 1  # type: ignore[arg-type]
        assert len(hook.post) == 1  # type: ignore[arg-type]

    def test_get_hooks_pre_command_contains_neo4j_admin(self) -> None:
        strategy = Neo4jBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="graph",
            config={"kind": "neo4j"},
        )
        pre_cmd = " ".join(hooks[0].pre[0].command)  # type: ignore[index]
        assert "neo4j-admin" in pre_cmd

    def test_get_hooks_custom_container(self) -> None:
        strategy = Neo4jBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="graph",
            config={"kind": "neo4j", "container": "my-neo4j"},
        )
        assert hooks[0].pre[0].container == "my-neo4j"  # type: ignore[index]

    def test_get_restore_hooks_returns_neo4j_hooks(self) -> None:
        strategy = Neo4jBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="graph",
            config={"kind": "neo4j"},
        )
        assert len(hooks) == 1
        hook = hooks[0]
        assert hook.name == "graph-neo4j-restore"
        assert hook.included_namespaces == ["test-ns"]
        assert len(hook.post) == 2

    def test_get_restore_hooks_post_command_contains_neo4j_admin(self) -> None:
        strategy = Neo4jBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="graph",
            config={"kind": "neo4j"},
        )
        post_cmd = " ".join(hooks[0].post[0].command)
        assert "neo4j-admin" in post_cmd

    def test_get_restore_hooks_custom_container(self) -> None:
        strategy = Neo4jBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="graph",
            config={"kind": "neo4j", "container": "my-neo4j"},
        )
        assert hooks[0].post[0].container == "my-neo4j"

    def test_get_backup_volumes_default(self) -> None:
        strategy = Neo4jBackupStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="graph",
            config={"kind": "neo4j"},
        )
        assert volumes == ["backup"]

    def test_get_backup_volumes_custom(self) -> None:
        strategy = Neo4jBackupStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="graph",
            config={"kind": "neo4j", "backup_volume": "neo4j-dump"},
        )
        assert volumes == ["neo4j-dump"]


class TestMariadbBackupStrategy:
    def test_get_hooks_returns_mariadb_hooks(self) -> None:
        strategy = MariadbBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mariadb"},
        )
        assert len(hooks) == 1
        hook = hooks[0]
        assert hook.name == "db-mariadb-backup"
        assert hook.included_namespaces == ["test-ns"]
        assert len(hook.pre) == 1  # type: ignore[arg-type]
        assert len(hook.post) == 1  # type: ignore[arg-type]

    def test_get_hooks_pre_command_contains_mariadb_dump(self) -> None:
        strategy = MariadbBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mariadb"},
        )
        pre_cmd = " ".join(hooks[0].pre[0].command)  # type: ignore[index]
        assert "mariadb-dump" in pre_cmd

    def test_get_hooks_uses_user_password_env_vars(self) -> None:
        strategy = MariadbBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mariadb"},
        )
        pre_cmd = " ".join(hooks[0].pre[0].command)  # type: ignore[index]
        assert "$MARIADB_USER" in pre_cmd
        assert "$MARIADB_PASSWORD" in pre_cmd
        assert "$MARIADB_DATABASE" in pre_cmd

    def test_get_hooks_custom_container(self) -> None:
        strategy = MariadbBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mariadb", "container": "my-mariadb"},
        )
        assert hooks[0].pre[0].container == "my-mariadb"  # type: ignore[index]

    def test_get_hooks_custom_mount_path(self) -> None:
        strategy = MariadbBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mariadb", "backup_mount_path": "/custom/backup"},
        )
        pre_cmd = hooks[0].pre[0].command  # type: ignore[index]
        assert "/custom/backup" in " ".join(pre_cmd)

    def test_get_restore_hooks_returns_mariadb_hooks(self) -> None:
        strategy = MariadbBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mariadb"},
        )
        assert len(hooks) == 1
        hook = hooks[0]
        assert hook.name == "db-mariadb-restore"
        assert hook.included_namespaces == ["test-ns"]
        assert len(hook.post) == 2

    def test_get_restore_hooks_uses_user_password_env_vars(self) -> None:
        strategy = MariadbBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mariadb"},
        )
        restore_cmd = " ".join(hooks[0].post[0].command)
        assert "$MARIADB_USER" in restore_cmd
        assert "$MARIADB_PASSWORD" in restore_cmd
        assert "$MARIADB_DATABASE" in restore_cmd

    def test_get_restore_hooks_custom_container(self) -> None:
        strategy = MariadbBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mariadb", "container": "my-mariadb"},
        )
        assert hooks[0].post[0].container == "my-mariadb"

    def test_get_backup_volumes_default(self) -> None:
        strategy = MariadbBackupStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="db",
            config={"kind": "mariadb"},
        )
        assert volumes == ["backup"]

    def test_get_backup_volumes_custom(self) -> None:
        strategy = MariadbBackupStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="db",
            config={"kind": "mariadb", "backup_volume": "maria-backup"},
        )
        assert volumes == ["maria-backup"]


class TestMongodbBackupStrategy:
    def test_get_hooks_returns_mongodb_hooks(self) -> None:
        strategy = MongodbBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mongodb"},
        )
        assert len(hooks) == 1
        hook = hooks[0]
        assert hook.name == "db-mongodb-backup"
        assert hook.included_namespaces == ["test-ns"]
        assert len(hook.pre) == 1  # type: ignore[arg-type]
        assert len(hook.post) == 1  # type: ignore[arg-type]

    def test_get_hooks_pre_command_contains_mongodump(self) -> None:
        strategy = MongodbBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mongodb"},
        )
        pre_cmd = " ".join(hooks[0].pre[0].command)  # type: ignore[index]
        assert "mongodump" in pre_cmd

    def test_get_hooks_uses_root_password_env_var(self) -> None:
        strategy = MongodbBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mongodb"},
        )
        pre_cmd = " ".join(hooks[0].pre[0].command)  # type: ignore[index]
        assert "$MONGO_INITDB_ROOT_PASSWORD" in pre_cmd

    def test_get_hooks_custom_container(self) -> None:
        strategy = MongodbBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mongodb", "container": "my-mongo"},
        )
        assert hooks[0].pre[0].container == "my-mongo"  # type: ignore[index]

    def test_get_hooks_custom_mount_path(self) -> None:
        strategy = MongodbBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mongodb", "backup_mount_path": "/custom/backup"},
        )
        pre_cmd = hooks[0].pre[0].command  # type: ignore[index]
        assert "/custom/backup" in " ".join(pre_cmd)

    def test_get_restore_hooks_returns_mongodb_hooks(self) -> None:
        strategy = MongodbBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mongodb"},
        )
        assert len(hooks) == 1
        hook = hooks[0]
        assert hook.name == "db-mongodb-restore"
        assert hook.included_namespaces == ["test-ns"]
        assert len(hook.post) == 2

    def test_get_restore_hooks_post_command_contains_mongorestore(self) -> None:
        strategy = MongodbBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mongodb"},
        )
        post_cmd = " ".join(hooks[0].post[0].command)
        assert "mongorestore" in post_cmd

    def test_get_restore_hooks_excludes_admin_system(self) -> None:
        strategy = MongodbBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mongodb"},
        )
        restore_cmd = " ".join(hooks[0].post[0].command)
        assert "--nsExclude='admin.system.*'" in restore_cmd
        assert len(hooks[0].post) == 2  # restore + cleanup

    def test_get_restore_hooks_custom_container(self) -> None:
        strategy = MongodbBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mongodb", "container": "my-mongo"},
        )
        assert hooks[0].post[0].container == "my-mongo"

    def test_get_backup_volumes_default(self) -> None:
        strategy = MongodbBackupStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="db",
            config={"kind": "mongodb"},
        )
        assert volumes == ["backup"]

    def test_get_backup_volumes_custom(self) -> None:
        strategy = MongodbBackupStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="db",
            config={"kind": "mongodb", "backup_volume": "mongo-dump"},
        )
        assert volumes == ["mongo-dump"]


class TestActionBackupStrategy:
    def test_get_hooks_returns_empty(self) -> None:
        strategy = ActionBackupStrategy()
        hooks = strategy.get_hooks(
            namespace="test-ns",
            component_name="custom",
            config={"kind": "action"},
        )
        assert hooks == []

    def test_get_restore_hooks_returns_empty(self) -> None:
        strategy = ActionBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="custom",
            config={"kind": "action"},
        )
        assert hooks == []

    def test_get_backup_volumes_returns_empty(self) -> None:
        strategy = ActionBackupStrategy()
        volumes = strategy.get_backup_volumes(
            component_name="custom",
            config={"kind": "action"},
        )
        assert volumes == []


@pytest.mark.parametrize(
    ("strategy", "kind"),
    [
        (PostgresBackupStrategy(), "postgres"),
        (MariadbBackupStrategy(), "mariadb"),
        (MongodbBackupStrategy(), "mongodb"),
        (Neo4jBackupStrategy(), "neo4j"),
    ],
)
def test_restore_hooks_never_render_a_bare_timeout(strategy: object, kind: str) -> None:
    """Regression: every restore hook must use ``execTimeout``.

    ``timeout`` is the *backup* hook field. On a Restore it is not part of
    velero's ExecRestoreHook, so the CRD's structural schema prunes it and
    velero applies its own 30s default -- silently capping every database
    restore, whatever the strategy declared.
    """
    hooks = strategy.get_restore_hooks(  # type: ignore[attr-defined]
        namespace="test-ns",
        component_name="db",
        config={"kind": kind},
    )
    rendered = [post for hook in hooks for post in hook.render()["postHooks"]]
    assert rendered, f"{kind} declares no restore hooks"
    for post in rendered:
        assert "timeout" not in post["exec"]
        assert post["exec"]["execTimeout"]
