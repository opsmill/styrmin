"""Unit tests for backup strategies."""

from __future__ import annotations

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
