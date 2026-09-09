from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackupHook,
    VeleroBackupHookExec,
    VeleroRestoreHook,
    VeleroRestoreHookExec,
)

# Tag on the hook's own libpq connections; the fence spares backends carrying it.
_PG_RESTORE_APPNAME = "styrmin-restore"
_PG_READY_TIMEOUT_SECONDS = 120
_PG_RESTORE_ATTEMPTS = 3

# The application is restored alongside its database and migrates the empty
# postgres while pg_restore replays the dump. The fence keeps pg_restore the only
# writer; --single-transaction makes each attempt all-or-nothing so retrying is safe.
_POSTGRES_RESTORE_SCRIPT = """\
set -e

PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE" 2>/dev/null || printf %s "$POSTGRES_PASSWORD")"
export PGPASSWORD
PGAPPNAME={appname}
export PGAPPNAME

# waitForReady only covers the readiness probe, which passes before initdb has created the role.
waited=0
while ! psql -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -tAc 'SELECT 1' >/dev/null 2>&1; do
  waited=$((waited + 1))
  if [ "$waited" -ge {ready_timeout} ]; then
    echo "postgres did not accept queries within {ready_timeout}s" >&2
    exit 1
  fi
  sleep 1
done

# Fence: terminate every rival backend this role may signal, for as long as the hook shell lives.
while kill -0 "$$" 2>/dev/null; do
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -tAc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() AND pg_has_role(usesysid, 'MEMBER') AND coalesce(application_name, '') <> '{appname}'" >/dev/null 2>&1 || true
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
