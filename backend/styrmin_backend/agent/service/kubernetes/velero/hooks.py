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
#
# The fence stops the writes but not what the migration already wrote: it can
# stop in the middle, and a later migration may be the one that removes an
# object (Prefect drops the foreign key task_run.state_id that way). The dump
# comes from a fully migrated database, so --clean cannot drop such an object:
# it only drops what the dump holds, and pg_restore fails on a table that the
# leftover object depends on. Every retry then fails the same way. So each
# attempt first drops the tables of schema public that the hook's role owns, in
# one transaction, and --clean --if-exists drops the rest of what the dump holds.
# Limits of that drop:
# - It leaves a table that belongs to an extension, which PostgreSQL refuses to
#   drop on its own, and a table of another role or schema: --clean handles those
#   as before. A type, sequence or function that the migration left stays too.
# - It runs only after pg_restore has listed the dump, so a missing or unreadable
#   dump changes nothing. If pg_restore then fails, the database has no tables of
#   the application, like a database that no migration has run on yet.
# Dropping the schema instead would lose its privileges, and the role does not own
# schema public on PostgreSQL 14 and older images other than bitnami's.
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

wipe_sql='DO $do$ DECLARE r record; BEGIN FOR r IN SELECT n.nspname AS schemaname, c.relname AS tablename FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = $s$public$s$ AND c.relkind IN ($k$r$k$, $k$p$k$) AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user) AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = $c$pg_class$c$::regclass AND d.objid = c.oid AND d.deptype = $e$e$e$) LOOP EXECUTE format($f$DROP TABLE IF EXISTS %I.%I CASCADE$f$, r.schemaname, r.tablename); END LOOP; END $do$;'

attempt=0
while :; do
  attempt=$((attempt + 1))
  if pg_restore -l {backup_mount_path}/pre-snapshot.dump >/dev/null \\
    && psql -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -v ON_ERROR_STOP=1 --single-transaction -c "$wipe_sql" >/dev/null \\
    && pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" --no-owner --clean --if-exists --single-transaction {backup_mount_path}/pre-snapshot.dump; then
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


# Seconds the mariadb and mongodb restore hooks keep retrying the load before failing.
_DB_LOAD_DEADLINE_SECONDS = 120

# waitForReady only covers the readiness probe, which bitnami passes against the temporary server
# it stops and restarts after creating users. Reloading is safe: the dumps drop what they recreate.
_RETRIED_LOAD_SCRIPT = """\
deadline=$(($(date +%s) + {deadline}))
attempt=1
until {load}; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "{engine} restore failed after $attempt attempt(s)" >&2
    exit 1
  fi
  echo "{engine} restore attempt $attempt failed; retrying" >&2
  attempt=$((attempt + 1))
  sleep 2
done
"""


def _retried_load_command(engine: str, load: str) -> str:
    """Render a shell script that reruns ``load`` until it succeeds or the deadline passes."""
    return _RETRIED_LOAD_SCRIPT.format(
        engine=engine,
        load=load,
        deadline=_DB_LOAD_DEADLINE_SECONDS,
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
                    _retried_load_command(
                        "mariadb",
                        f"mariadb -u $MARIADB_USER -p$MARIADB_PASSWORD $MARIADB_DATABASE < {backup_mount_path}/pre-snapshot.sql",
                    ),
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
                    _retried_load_command(
                        "mongodb",
                        f"mongorestore --username=$MONGO_INITDB_ROOT_USERNAME --password=$MONGO_INITDB_ROOT_PASSWORD --authenticationDatabase=admin --nsExclude='admin.system.*' --archive={backup_mount_path}/pre-snapshot.archive --drop",
                    ),
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
