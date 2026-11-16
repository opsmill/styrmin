"""The post-restore hook of a postgres component starts each attempt without the application's tables.

The application is restored alongside its database and migrates the empty
postgres while the hook replays the dump. The hook's fence stops those writes,
but a migration that stopped half way leaves objects the dump does not hold: the
dump comes from a fully migrated database. ``pg_restore --clean`` drops only what
the dump holds, so it fails on a table that such an object depends on (Prefect
drops the foreign key ``task_run.state_id`` in a late migration, and a database
that stopped before it still has the key), and every retry fails the same way.

These tests run the rendered script with ``sh`` and stand-ins for ``psql`` and
``pg_restore``. The stand-in ``pg_restore`` fails with the error of the real one
unless the tables were dropped first, so the test fails for the same reason as the
real restore did. The real behaviour was checked against the bitnami PostgreSQL 14.13 image and a
vanilla PostgreSQL 14.13, with the Prefect migrations: see the description of the
change.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from styrmin_backend.agent.service.kubernetes.velero.hooks import (
    _postgres_restore_command,
)

REAL_ERROR = (
    "pg_restore: error: could not execute query: ERROR:  cannot drop constraint "
    "pk_task_run_state on table public.task_run_state because other objects depend on it"
)

# Stand-in for psql. It records what it was asked, and a call that drops the
# tables marks the database clean. The fence and the readiness loop call it too.
FAKE_PSQL = """\
#!/bin/sh
echo "$*" >> "$STATE/psql.log"
case "$*" in
  *"DROP TABLE IF EXISTS %I.%I CASCADE"*)
    if [ -f "$STATE/fail-first-wipe" ] && [ ! -f "$STATE/wiped-once" ]; then
      touch "$STATE/wiped-once"
      exit 1
    fi
    touch "$STATE/clean"
    ;;
esac
exit 0
"""

# Stand-in for pg_restore. `-l` lists the dump, which the hook does first: it fails
# when the dump is missing. A restore fails on a database that a migration left half
# done, because --clean cannot drop what the dump does not hold, unless the tables
# were dropped first.
FAKE_PG_RESTORE = f"""\
#!/bin/sh
case " $* " in
  *" -l "*)
    if [ -f "$STATE/no-dump" ]; then
      echo "pg_restore: error: could not open input file" >&2
      exit 1
    fi
    exit 0
    ;;
esac
echo "$*" >> "$STATE/pg_restore.log"
if [ -f "$STATE/pg_restore-always-fails" ]; then
  echo "broken dump" >&2
  exit 1
fi
if [ -f "$STATE/clean" ]; then
  exit 0
fi
echo "{REAL_ERROR}" >&2
exit 1
"""

# Real sleep, shortened: the fence loop sleeps between its calls.
FAKE_SLEEP = """\
#!/bin/sh
exec /bin/sleep 0.02
"""


def _install(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_hook(
    tmp_path: Path,
    *,
    fail_first_wipe: bool = False,
    dump_missing: bool = False,
    pg_restore_always_fails: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
    """Run the rendered script; return the result, the pg_restore loads and the psql calls."""
    bin_dir = tmp_path / "bin"
    state = tmp_path / "state"
    bin_dir.mkdir()
    state.mkdir()
    _install(bin_dir, "psql", FAKE_PSQL)
    _install(bin_dir, "pg_restore", FAKE_PG_RESTORE)
    _install(bin_dir, "sleep", FAKE_SLEEP)
    for flag, name in (
        (fail_first_wipe, "fail-first-wipe"),
        (dump_missing, "no-dump"),
        (pg_restore_always_fails, "pg_restore-always-fails"),
    ):
        if flag:
            (state / name).touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STATE": str(state),
        "POSTGRES_USER": "prefect",
        "POSTGRES_DATABASE": "prefect",
        "POSTGRES_PASSWORD": "test",
    }
    result = subprocess.run(
        ["sh", "-c", _postgres_restore_command("/backup")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    pg_restore_log = state / "pg_restore.log"
    psql_log = state / "psql.log"
    return (
        result,
        pg_restore_log.read_text().splitlines() if pg_restore_log.exists() else [],
        psql_log.read_text().splitlines() if psql_log.exists() else [],
    )


def _wipes(psql_calls: list[str]) -> list[str]:
    return [call for call in psql_calls if "DROP TABLE IF EXISTS %I.%I CASCADE" in call]


def test_a_database_left_half_migrated_by_the_application_is_restored(
    tmp_path: Path,
) -> None:
    result, pg_restore_calls, _ = _run_hook(tmp_path)

    assert result.returncode == 0, result.stderr
    assert len(pg_restore_calls) == 1
    assert REAL_ERROR not in result.stderr


def test_every_attempt_drops_the_tables_before_pg_restore(tmp_path: Path) -> None:
    """A retry must not depend on what the failed attempt or the application left."""
    result, pg_restore_calls, psql_calls = _run_hook(tmp_path, fail_first_wipe=True)

    assert result.returncode == 0, result.stderr
    assert len(_wipes(psql_calls)) == 2, (
        "the first wipe failed, so the second attempt wipes again"
    )
    assert len(pg_restore_calls) == 1, (
        "pg_restore never runs on tables that were not dropped"
    )
    assert "pg_restore attempt 1 aborted; retrying" in result.stderr


def test_the_tables_are_dropped_in_one_transaction_without_dropping_the_schema(
    tmp_path: Path,
) -> None:
    """Dropping schema public would lose its privileges, and the role may not own it."""
    _, _, psql_calls = _run_hook(tmp_path)

    (wipe,) = _wipes(psql_calls)
    assert "--single-transaction" in wipe
    assert "ON_ERROR_STOP=1" in wipe
    assert "c.relowner" in wipe and "current_user" in wipe, (
        "only the tables the role may drop"
    )
    assert "pg_depend" in wipe and "deptype" in wipe, (
        "a table of an extension is left alone: PostgreSQL refuses to drop it on its own"
    )
    assert not any("DROP SCHEMA" in call for call in psql_calls)


def test_a_missing_dump_changes_nothing(tmp_path: Path) -> None:
    """The dump is listed before anything is dropped, so a failed restore leaves the tables."""
    result, pg_restore_calls, psql_calls = _run_hook(tmp_path, dump_missing=True)

    assert result.returncode == 1
    assert "pg_restore failed after 3 attempt(s)" in result.stderr
    assert _wipes(psql_calls) == [], "no table is dropped when the dump cannot be read"
    assert pg_restore_calls == []


def test_pg_restore_keeps_cleaning_what_the_dump_holds_in_other_schemas(
    tmp_path: Path,
) -> None:
    _, pg_restore_calls, _ = _run_hook(tmp_path)

    assert pg_restore_calls
    assert "--clean --if-exists" in pg_restore_calls[0]
    assert "--single-transaction" in pg_restore_calls[0]
    assert pg_restore_calls[0].endswith("/backup/pre-snapshot.dump")


def test_a_restore_that_keeps_failing_still_fails_after_the_attempts(
    tmp_path: Path,
) -> None:
    """The retries stay bounded: a dump that cannot be replayed fails the hook."""
    result, pg_restore_calls, _ = _run_hook(tmp_path, pg_restore_always_fails=True)

    assert result.returncode == 1
    assert len(pg_restore_calls) == 3
    assert "pg_restore failed after 3 attempt(s)" in result.stderr


@pytest.mark.parametrize("path", ["/backup", "/var/backups"])
def test_the_dump_is_read_from_the_backup_mount_path(path: str) -> None:
    assert f"{path}/pre-snapshot.dump" in _postgres_restore_command(path)
