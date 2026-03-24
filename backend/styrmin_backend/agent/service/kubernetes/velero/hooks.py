from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackupHook,
    VeleroBackupHookExec,
    VeleroRestoreHook,
    VeleroRestoreHookExec,
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
                    f"PGPASSWORD=$(cat $POSTGRES_PASSWORD_FILE) pg_dump -U $POSTGRES_USER -d $POSTGRES_DATABASE -Fc -f {backup_mount_path}/pre-snapshot.dump && sync",
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
                timeout=timeout,
            ),
            VeleroRestoreHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"rm -f {backup_mount_path}/pre-snapshot.sql",
                ],
                on_error="Continue",
                timeout="30s",
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
                timeout=timeout,
            ),
            VeleroRestoreHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"rm -f {backup_mount_path}/pre-snapshot.archive",
                ],
                on_error="Continue",
                timeout="30s",
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
                # FIXME: sleep to workaround issues on restore due to the following error:
                # pg_restore: error: connection to server on socket \"/tmp/.s.PGSQL.5432\" failed: FATAL:  role \"simple-app\" does not exist
                #
                # It looks like its because the pg database is not yet initialized... although we set waitForReady=true...
                command=[
                    "/bin/sh",
                    "-c",
                    f"sleep 5 && PGPASSWORD=$(cat $POSTGRES_PASSWORD_FILE) pg_restore -U $POSTGRES_USER -d $POSTGRES_DATABASE --no-owner -c --if-exists {backup_mount_path}/pre-snapshot.dump",
                ],
                on_error="Fail",
                timeout=timeout,
            ),
            VeleroRestoreHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"rm -f {backup_mount_path}/pre-snapshot.dump",
                ],
                on_error="Continue",
                timeout="30s",
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
                timeout=timeout,
            ),
            VeleroRestoreHookExec(
                container=container,
                command=[
                    "/bin/sh",
                    "-c",
                    f"rm -rf {backup_mount_path}/*",
                ],
                on_error="Continue",
                timeout="30s",
            ),
        ],
    )
