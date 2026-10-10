"""Unit tests for backup strategies."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from styrmin_backend.agent.service.kubernetes.velero.hooks import (
    neo4j_community_backup_hooks,
)

from styrmin_backend.services.backup.strategies.action import ActionBackupStrategy
from styrmin_backend.services.backup.strategies.base import BackupStrategy
from styrmin_backend.services.backup.strategies.disk import DiskSnapshotStrategy
from styrmin_backend.services.backup.strategies.mariadb import MariadbBackupStrategy
from styrmin_backend.services.backup.strategies.mongodb import MongodbBackupStrategy
from styrmin_backend.services.backup.strategies.neo4j import Neo4jBackupStrategy
from styrmin_backend.services.backup.strategies.neo4j_community import (
    Neo4jCommunityBackupStrategy,
)
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
        # Only backends this role may signal: one foreign-role row would abort
        # the whole statement and silently disable the fence.
        assert "pg_has_role(usesysid, 'MEMBER')" in script
        # Torn down however the hook exits, including a signal that skips the trap.
        assert "trap 'kill \"$fence_pid\" 2>/dev/null || true' EXIT INT TERM" in script
        assert 'while kill -0 "$$" 2>/dev/null; do' in script

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


class TestNeo4jCommunityBackupStrategy:
    def test_get_hooks_pause_before_and_resume_after(self) -> None:
        hooks = Neo4jCommunityBackupStrategy().get_hooks(
            namespace="test-ns",
            component_name="graph",
            config={"kind": "neo4j-community"},
        )
        assert len(hooks) == 1
        hook = hooks[0]
        assert hook.name == "graph-neo4j-community-backup"
        assert hook.included_namespaces == ["test-ns"]
        pre_cmd = hook.pre[0].command[-1]  # type: ignore[index]
        post_cmd = hook.post[0].command[-1]  # type: ignore[index]
        assert 'kill -STOP "$pid"' in pre_cmd
        assert 'kill -CONT "$pid"' in post_cmd
        assert "neo4j-admin" not in pre_cmd

    def test_both_hooks_fail_the_backup_on_error(self) -> None:
        """A failed pause must skip the volume; a late resume must flag the backup."""
        hook = Neo4jCommunityBackupStrategy().get_hooks(
            namespace="test-ns",
            component_name="graph",
            config={"kind": "neo4j-community"},
        )[0]
        assert hook.pre[0].on_error == "Fail"  # type: ignore[index]
        assert hook.post[0].on_error == "Fail"  # type: ignore[index]

    def test_get_hooks_custom_container(self) -> None:
        hooks = Neo4jCommunityBackupStrategy().get_hooks(
            namespace="test-ns",
            component_name="graph",
            config={"kind": "neo4j-community", "container": "my-neo4j"},
        )
        assert hooks[0].pre[0].container == "my-neo4j"  # type: ignore[index]
        assert hooks[0].post[0].container == "my-neo4j"  # type: ignore[index]

    def test_get_restore_hooks_returns_empty(self) -> None:
        """Velero restores the data volume before Neo4j starts; no hook is needed."""
        hooks = Neo4jCommunityBackupStrategy().get_restore_hooks(
            namespace="test-ns",
            component_name="graph",
            config={"kind": "neo4j-community"},
        )
        assert hooks == []

    def test_get_backup_volumes_default(self) -> None:
        volumes = Neo4jCommunityBackupStrategy().get_backup_volumes(
            component_name="graph",
            config={"kind": "neo4j-community"},
        )
        assert volumes == ["data"]

    def test_get_backup_volumes_custom(self) -> None:
        volumes = Neo4jCommunityBackupStrategy().get_backup_volumes(
            component_name="graph",
            config={"kind": "neo4j-community", "volume": "neo4j-data"},
        )
        assert volumes == ["neo4j-data"]


def _process_state(pid: int) -> str:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("State:"):
            return line.split()[1]
    raise AssertionError(f"no State line for pid {pid}")


def _wait_for_state(pid: int, expected: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while _process_state(pid) != expected:
        assert time.monotonic() < deadline, f"pid {pid} never reached state {expected}"
        time.sleep(0.05)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="reads process state from /proc"
)
class TestNeo4jCommunityPauseScripts:
    """Run the rendered hook scripts against a stand-in for the Neo4j JVM."""

    @pytest.fixture
    def neo4j_process(self, tmp_path: Path) -> Iterator[tuple[int, Path]]:
        proc = subprocess.Popen(["sleep", "300"])
        pid_file = tmp_path / "neo4j.pid"
        pid_file.write_text(f"{proc.pid}\n")
        try:
            yield proc.pid, pid_file
        finally:
            proc.kill()
            proc.wait()

    def _scripts(
        self, pid_file: Path, watchdog_dir: Path, max_pause_seconds: int
    ) -> tuple[str, str]:
        hook = neo4j_community_backup_hooks(
            namespace="test-ns",
            component_name="graph",
            pid_file=str(pid_file),
            watchdog_dir=str(watchdog_dir),
            max_pause_seconds=max_pause_seconds,
        )
        return hook.pre[0].command[-1], hook.post[0].command[-1]  # type: ignore[index]

    def test_pause_then_resume(
        self, neo4j_process: tuple[int, Path], tmp_path: Path
    ) -> None:
        pid, pid_file = neo4j_process
        pause, resume = self._scripts(pid_file, tmp_path, max_pause_seconds=300)

        subprocess.run(["/bin/sh", "-c", pause], check=True, timeout=10)
        _wait_for_state(pid, "T")

        result = subprocess.run(
            ["/bin/sh", "-c", resume], capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, result.stderr
        _wait_for_state(pid, "S")
        assert not (tmp_path / "styrmin-neo4j-watchdog.pid").exists()

    def test_watchdog_resumes_and_resume_flags_the_backup(
        self, neo4j_process: tuple[int, Path], tmp_path: Path
    ) -> None:
        """Neo4j never stays paused, and a backup it outlived is reported as failed."""
        pid, pid_file = neo4j_process
        pause, resume = self._scripts(pid_file, tmp_path, max_pause_seconds=1)

        subprocess.run(["/bin/sh", "-c", pause], check=True, timeout=10)
        _wait_for_state(pid, "T")
        _wait_for_state(pid, "S")

        result = subprocess.run(
            ["/bin/sh", "-c", resume], capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 1
        assert "not consistent" in result.stderr

    def test_next_pause_disarms_an_earlier_watchdog(
        self, neo4j_process: tuple[int, Path], tmp_path: Path
    ) -> None:
        """A watchdog left by an earlier backup must not resume Neo4j mid-backup."""
        pid, pid_file = neo4j_process
        stale_pause, _ = self._scripts(pid_file, tmp_path, max_pause_seconds=2)
        pause, resume = self._scripts(pid_file, tmp_path, max_pause_seconds=300)

        subprocess.run(["/bin/sh", "-c", stale_pause], check=True, timeout=10)
        subprocess.run(["/bin/sh", "-c", pause], check=True, timeout=10)
        time.sleep(3)
        assert _process_state(pid) == "T"

        result = subprocess.run(
            ["/bin/sh", "-c", resume], capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, result.stderr
        _wait_for_state(pid, "S")


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

    def test_restore_retries_the_load_rather_than_sleeping(self) -> None:
        """bitnami passes the readiness probe on a temporary server it then restarts.

        A load that ran 5s after readiness hit the restart and failed with
        ``ERROR 2002 ... Can't connect to local server through socket`` (#412).
        """
        strategy = MariadbBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mariadb"},
        )
        script = hooks[0].post[0].command[2]
        assert "sleep 5 &&" not in script
        assert "until mariadb -u $MARIADB_USER" in script
        assert "< /backup/pre-snapshot.sql; do" in script

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

    def test_restore_retries_the_load_rather_than_sleeping(self) -> None:
        """bitnami passes the readiness probe before it has created the root user.

        A load that ran 5s after readiness could still reach that server and
        failed with ``(AuthenticationFailed)`` (#412). ``--drop`` makes a rerun safe.
        """
        strategy = MongodbBackupStrategy()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"kind": "mongodb"},
        )
        script = hooks[0].post[0].command[2]
        assert "sleep 5 &&" not in script
        assert "until mongorestore --username=$MONGO_INITDB_ROOT_USERNAME" in script
        assert "--drop; do" in script

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


# Fails the first $FAILURES calls, then succeeds; counts calls in $CALLS.
_FAKE_CLIENT = """\
#!/bin/sh
n=$(($(cat "$CALLS" 2>/dev/null || echo 0) + 1))
echo "$n" > "$CALLS"
[ "$n" -gt "$FAILURES" ]
"""

# Advances 100s per call, so the 120s deadline has passed by the second check.
_FAKE_DATE = """\
#!/bin/sh
now=$(cat "$CLOCK" 2>/dev/null || echo 0)
echo $((now + 100)) > "$CLOCK"
echo "$now"
"""


@pytest.mark.parametrize(
    ("strategy", "engine", "client", "dump"),
    [
        (MariadbBackupStrategy(), "mariadb", "mariadb", "pre-snapshot.sql"),
        (MongodbBackupStrategy(), "mongodb", "mongorestore", "pre-snapshot.archive"),
    ],
)
class TestRetriedDatabaseLoad:
    """Run the rendered restore script with fake clients in place of the database."""

    @staticmethod
    def _run(
        tmp_path: Path,
        strategy: BackupStrategy,
        client: str,
        dump: str,
        *,
        failures: int,
        fake_date: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], int]:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        shims = {client: _FAKE_CLIENT, "sleep": "#!/bin/sh\n"}
        if fake_date:
            shims["date"] = _FAKE_DATE
        for name, body in shims.items():
            shim = bin_dir / name
            shim.write_text(body)
            shim.chmod(0o755)
        (tmp_path / dump).touch()
        hooks = strategy.get_restore_hooks(
            namespace="test-ns",
            component_name="db",
            config={"backup_mount_path": str(tmp_path)},
        )
        result = subprocess.run(
            hooks[0].post[0].command,
            env={
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                "CALLS": str(tmp_path / "calls"),
                "CLOCK": str(tmp_path / "clock"),
                "FAILURES": str(failures),
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result, int((tmp_path / "calls").read_text())

    def test_load_is_retried_until_it_succeeds(
        self,
        tmp_path: Path,
        strategy: BackupStrategy,
        engine: str,
        client: str,
        dump: str,
    ) -> None:
        result, calls = self._run(tmp_path, strategy, client, dump, failures=2)
        assert result.returncode == 0, result.stderr
        assert calls == 3
        assert f"{engine} restore attempt 2 failed; retrying" in result.stderr

    def test_load_fails_once_the_deadline_passes(
        self,
        tmp_path: Path,
        strategy: BackupStrategy,
        engine: str,
        client: str,
        dump: str,
    ) -> None:
        result, calls = self._run(
            tmp_path, strategy, client, dump, failures=1000, fake_date=True
        )
        assert result.returncode == 1
        assert calls == 2
        assert f"{engine} restore failed after 2 attempt(s)" in result.stderr


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
