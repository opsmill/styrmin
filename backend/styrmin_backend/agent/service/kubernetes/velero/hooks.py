from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackupHook,
    VeleroBackupHookExec,
    VeleroRestoreHook,
    VeleroRestoreHookExec,
)

# Marker put on every libpq connection the postgres restore hook opens, via
# PGAPPNAME. The fence below terminates every backend on the target database
# that is *not* tagged with it, which is how pg_restore stays the only writer
# without needing a superuser or a connection limit.
_PG_RESTORE_APPNAME = "styrmin-restore"

# Seconds to wait for postgres to answer a trivial query before giving up.
_PG_READY_TIMEOUT_SECONDS = 120

# How many times to re-run pg_restore if an attempt aborts. Each attempt is a
# single transaction, so a failed one leaves the database untouched and a
# retry starts from the same state.
_PG_RESTORE_ATTEMPTS = 3

# Restoring a deployment deletes and recreates its namespace, so postgres comes
# up on an empty data volume and the application pods -- restored alongside it
# -- boot against an empty database and start running their own schema
# migrations. Those migrations interleave with pg_restore's drop/create pass
# and leave a database that is neither the backup's schema nor the
# application's: tables recreated at an older migration revision, COPY failing
# on columns that no longer exist, foreign keys missing. The window is small,
# so this surfaces as a rare PartiallyFailed restore rather than a consistent
# one.
#
# Two things close it:
#
#   * a background loop that terminates every rival backend for the duration
#     of the restore, so nothing else can write while pg_restore runs;
#   * --single-transaction, which makes each attempt all-or-nothing. Losing a
#     race now rolls back cleanly instead of corrupting the schema, which in
#     turn makes retrying safe.
#
# --clean --if-exists stays: DROP SCHEMA public CASCADE would be tidier but
# schema `public` is owned by `postgres`, and the role the hook runs as is the
# database owner, not a superuser.
_POSTGRES_RESTORE_SCRIPT = """\
set -e

# See the matching backup hook for the rationale on resolving
# $POSTGRES_PASSWORD_FILE with a $POSTGRES_PASSWORD fallback.
PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE" 2>/dev/null || printf %s "$POSTGRES_PASSWORD")"
export PGPASSWORD
PGAPPNAME={appname}
export PGAPPNAME

# velero's waitForReady only waits for the container's readiness probe, which
# bitnami satisfies while initdb is still creating the role and the database.
# Poll for a query the restore actually needs to succeed instead -- this is
# what the old `sleep 5` was reaching for, and why restores used to fail with
# `FATAL: role "..." does not exist`.
waited=0
while ! psql -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -tAc 'SELECT 1' >/dev/null 2>&1; do
  waited=$((waited + 1))
  if [ "$waited" -ge {ready_timeout} ]; then
    echo "postgres did not accept queries within {ready_timeout}s" >&2
    exit 1
  fi
  sleep 1
done

# Fence: keep pg_restore the only writer. coalesce() treats a NULL
# application_name as a rival -- pg_stat_activity hides that column for
# backends owned by another role, and a rival we cannot identify is still a
# rival. Our own backends are tagged via PGAPPNAME.
while :; do
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -tAc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() AND coalesce(application_name, '') <> '{appname}'" >/dev/null 2>&1 || true
  sleep 1
done &
fence_pid=$!
trap 'kill "$fence_pid" 2>/dev/null || true' EXIT INT TERM

attempt=0
while :; do
  attempt=$((attempt + 1))
  if pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" --no-owner --clean --if-exists --single-transaction {backup_mount_path}/pre-snapshot.dump; then
    break
  fi
  if [ "$attempt" -ge {attempts} ]; then
    echo "pg_restore failed after $attempt attempt(s)" >&2
    exit 1
  fi
  echo "pg_restore attempt $attempt aborted; retrying" >&2
  sleep 3
done
"""


def _postgres_restore_command(backup_mount_path: str) -> str:
    """Render the postgres post-restore shell script."""
    return _POSTGRES_RESTORE_SCRIPT.format(
        appname=_PG_RESTORE_APPNAME,
        ready_timeout=_PG_READY_TIMEOUT_SECONDS,
        attempts=_PG_RESTORE_ATTEMPTS,
        backup_mount_path=backup_mount_path,
    )


def postgres_backup_hooks(
    namespace: str,
    component_name: str,
    container: str | None = None,
    backup_mount_path: str = "/backup",
    timeout: str = "600s",
) -> VeleroBackupHook:
    """Create Velero pre/post backup hooks for PostgreSQL."""
    return VeleroBackupHook(
        name=f"{component_name}-postgres-backup",
        included_namespaces=[namespace],
        label_selector={"matchLabels": {"styrmin/component": component_name}},
        pre=[
            VeleroBackupHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    # Read the password from $POSTGRES_PASSWORD_FILE when the chart
                    # exposes one (older bitnami postgres releases, vault/sealed-secret
                    # mounts); otherwise fall back to $POSTGRES_PASSWORD (current
                    # bitnami releases set this directly). The `cat "$VAR" 2>/dev/null`
                    # construct returns empty and exits non-zero when the var is unset,
                    # empty, or points at a nonexistent path, which triggers the `||`
                    # fallback to the plain env var.
                    f'PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE" 2>/dev/null || printf %s "$POSTGRES_PASSWORD")" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -Fc -f {backup_mount_path}/pre-snapshot.dump && sync',
                ],
                on_error="Fail",
                timeout=timeout,
            )
        ],
        post=[
            VeleroBackupHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"rm -f {backup_mount_path}/pre-snapshot.dump",
                ],
                on_error="Continue",
                timeout="30s",
            )
        ],
    )


def neo4j_backup_hooks(
    namespace: str,
    component_name: str,
    container: str | None = None,
    backup_mount_path: str = "/backup",
    timeout: str = "600s",
) -> VeleroBackupHook:
    """Create Velero pre/post backup hooks for Neo4j."""
    return VeleroBackupHook(
        name=f"{component_name}-neo4j-backup",
        included_namespaces=[namespace],
        label_selector={"matchLabels": {"styrmin/component": component_name}},
        pre=[
            VeleroBackupHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"neo4j-admin database backup --to-path={backup_mount_path} neo4j && sync",
                ],
                on_error="Fail",
                timeout=timeout,
            )
        ],
        post=[
            VeleroBackupHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"rm -rf {backup_mount_path}/*",
                ],
                on_error="Continue",
                timeout="30s",
            )
        ],
    )


def mariadb_backup_hooks(
    namespace: str,
    component_name: str,
    container: str | None = None,
    backup_mount_path: str = "/backup",
    timeout: str = "600s",
) -> VeleroBackupHook:
    """Create Velero pre/post backup hooks for MariaDB."""
    return VeleroBackupHook(
        name=f"{component_name}-mariadb-backup",
        included_namespaces=[namespace],
        label_selector={"matchLabels": {"styrmin/component": component_name}},
        pre=[
            VeleroBackupHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"mariadb-dump -u $MARIADB_USER -p$MARIADB_PASSWORD $MARIADB_DATABASE --single-transaction --quick --routines --triggers > {backup_mount_path}/pre-snapshot.sql && sync",
                ],
                on_error="Fail",
                timeout=timeout,
            )
        ],
        post=[
            VeleroBackupHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"rm -f {backup_mount_path}/pre-snapshot.sql",
                ],
                on_error="Continue",
                timeout="30s",
            )
        ],
    )


def mariadb_restore_hooks(
    namespace: str,
    component_name: str,
    container: str | None = None,
    backup_mount_path: str = "/backup",
    timeout: str = "600s",
) -> VeleroRestoreHook:
    """Create Velero post-restore hooks for MariaDB."""
    return VeleroRestoreHook(
        name=f"{component_name}-mariadb-restore",
        included_namespaces=[namespace],
        label_selector={"matchLabels": {"styrmin/component": component_name}},
        post=[
            VeleroRestoreHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"sleep 5 && mariadb -u $MARIADB_USER -p$MARIADB_PASSWORD $MARIADB_DATABASE < {backup_mount_path}/pre-snapshot.sql",
                ],
                on_error="Fail",
                exec_timeout=timeout,
            ),
            VeleroRestoreHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"rm -f {backup_mount_path}/pre-snapshot.sql",
                ],
                on_error="Continue",
                exec_timeout="30s",
            ),
        ],
    )


def mongodb_backup_hooks(
    namespace: str,
    component_name: str,
    container: str | None = None,
    backup_mount_path: str = "/backup",
    timeout: str = "600s",
) -> VeleroBackupHook:
    """Create Velero pre/post backup hooks for MongoDB."""
    return VeleroBackupHook(
        name=f"{component_name}-mongodb-backup",
        included_namespaces=[namespace],
        label_selector={"matchLabels": {"styrmin/component": component_name}},
        pre=[
            VeleroBackupHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"mongodump --username=$MONGO_INITDB_ROOT_USERNAME --password=$MONGO_INITDB_ROOT_PASSWORD --authenticationDatabase=admin --archive={backup_mount_path}/pre-snapshot.archive && sync",
                ],
                on_error="Fail",
                timeout=timeout,
            )
        ],
        post=[
            VeleroBackupHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"rm -f {backup_mount_path}/pre-snapshot.archive",
                ],
                on_error="Continue",
                timeout="30s",
            )
        ],
    )


def mongodb_restore_hooks(
    namespace: str,
    component_name: str,
    container: str | None = None,
    backup_mount_path: str = "/backup",
    timeout: str = "600s",
) -> VeleroRestoreHook:
    """Create Velero post-restore hooks for MongoDB."""
    return VeleroRestoreHook(
        name=f"{component_name}-mongodb-restore",
        included_namespaces=[namespace],
        label_selector={"matchLabels": {"styrmin/component": component_name}},
        post=[
            VeleroRestoreHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"sleep 5 && mongorestore --username=$MONGO_INITDB_ROOT_USERNAME --password=$MONGO_INITDB_ROOT_PASSWORD --authenticationDatabase=admin --nsExclude='admin.system.*' --archive={backup_mount_path}/pre-snapshot.archive --drop",
                ],
                on_error="Fail",
                exec_timeout=timeout,
            ),
            VeleroRestoreHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"rm -f {backup_mount_path}/pre-snapshot.archive",
                ],
                on_error="Continue",
                exec_timeout="30s",
            ),
        ],
    )


def postgres_restore_hooks(
    namespace: str,
    component_name: str,
    container: str | None = None,
    backup_mount_path: str = "/backup",
    timeout: str = "600s",
) -> VeleroRestoreHook:
    """Create Velero post-restore hooks for PostgreSQL."""
    return VeleroRestoreHook(
        name=f"{component_name}-postgres-restore",
        included_namespaces=[namespace],
        label_selector={"matchLabels": {"styrmin/component": component_name}},
        post=[
            VeleroRestoreHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    _postgres_restore_command(backup_mount_path),
                ],
                on_error="Fail",
                exec_timeout=timeout,
            ),
            VeleroRestoreHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"rm -f {backup_mount_path}/pre-snapshot.dump",
                ],
                on_error="Continue",
                exec_timeout="30s",
            ),
        ],
    )


def neo4j_restore_hooks(
    namespace: str,
    component_name: str,
    container: str | None = None,
    backup_mount_path: str = "/backup",
    timeout: str = "600s",
) -> VeleroRestoreHook:
    """Create Velero post-restore hooks for Neo4j."""
    return VeleroRestoreHook(
        name=f"{component_name}-neo4j-restore",
        included_namespaces=[namespace],
        label_selector={"matchLabels": {"styrmin/component": component_name}},
        post=[
            VeleroRestoreHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"NEO4J_USER=$(cut -d'/' -f1 $NEO4J_AUTH_PATH) && "
                    f"NEO4J_PASS=$(cut -d'/' -f2 $NEO4J_AUTH_PATH) && "
                    f'cypher-shell -u $NEO4J_USER -p $NEO4J_PASS "STOP DATABASE neo4j" && '
                    f"neo4j-admin database restore --from-path=$(ls {backup_mount_path}/*.backup) neo4j --overwrite-destination=true && "
                    f'cypher-shell -u $NEO4J_USER -p $NEO4J_PASS -d system "START DATABASE neo4j"',
                ],
                on_error="Fail",
                exec_timeout=timeout,
            ),
            VeleroRestoreHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"rm -rf {backup_mount_path}/*",
                ],
                on_error="Continue",
                exec_timeout="30s",
            ),
        ],
    )
