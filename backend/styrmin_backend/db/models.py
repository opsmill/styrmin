"""Provides the models for the database tables.

This is where the different tables and their columns must be defined.
"""

from datetime import datetime
from enum import Enum, IntEnum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    LargeBinary,
    Text,
    UniqueConstraint,
    false,
    text,
    true,
)
from sqlmodel import JSON, Column, DateTime, Field, Relationship, SQLModel, func
from sqlmodel import Enum as SQLModelEnum


class Role(IntEnum):
    """Authorization role. See ADR-017.

    Stored as an ordered integer (10/20/30, gapped for future inserts).
    Comparisons (``>=``) work natively. The GraphQL representation is the
    string variant; the integer is an implementation detail.
    """

    READ_ONLY = 10
    READ_WRITE = 20
    ADMIN = 30


class StyrminModel(SQLModel):
    id: UUID = Field(primary_key=True, default_factory=uuid4)

    created_on: datetime | None = Field(  # type: ignore[call-overload]
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )

    updated_on: datetime | None = Field(  # type: ignore[call-overload]
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": func.now(), "server_default": func.now()},
    )


class UserGroup(SQLModel, table=True):
    """Many-to-many link between User and Group. See ADR-017."""

    __tablename__ = "user_group"

    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )
    group_id: UUID = Field(
        sa_column=Column(
            ForeignKey("group.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )


class User(StyrminModel, table=True):
    """User account. See ADR-016, ADR-017."""

    username: str = Field(unique=True)
    password_hash: str
    display_name: str
    # ``server_default`` mirrors revision ``a1b2c3d4e5f7`` so a fresh
    # ``create_all()`` database and a migrated one agree: an INSERT that omits
    # the column defaults to active in both.
    active: bool = Field(
        default=True,
        nullable=False,
        sa_column_kwargs={"server_default": true()},
    )
    # ``server_default`` mirrors revision ``c0d1e2f3a4b5``: least privilege at
    # the database level, so a row inserted outside the ORM is READ_ONLY.
    role: Role = Field(
        default=Role.READ_ONLY,
        sa_column=Column(
            SQLModelEnum(Role), nullable=False, server_default=Role.READ_ONLY.name
        ),
    )

    sessions: list["Session"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    groups: list["Group"] = Relationship(
        back_populates="users",
        link_model=UserGroup,
    )


class Group(StyrminModel, table=True):
    """Authorization group. See ADR-017.

    Membership monotonically elevates: a user's effective role is
    ``max(user.role, *(g.role for g in user.groups))``.
    """

    name: str = Field(unique=True)
    # ``server_default`` mirrors revision ``c0d1e2f3a4b5`` — see ``User.role``.
    role: Role = Field(
        default=Role.READ_ONLY,
        sa_column=Column(
            SQLModelEnum(Role), nullable=False, server_default=Role.READ_ONLY.name
        ),
    )

    users: list["User"] = Relationship(
        back_populates="groups",
        link_model=UserGroup,
    )


class Session(StyrminModel, table=True):
    """Server-side opaque session row. See ADR-016."""

    __table_args__ = (Index("ix_session_expires_at", "expires_at"),)

    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    token_hash: bytes = Field(
        sa_column=Column(LargeBinary, nullable=False, unique=True),
    )
    created_at: datetime = Field(sa_type=DateTime(timezone=True), nullable=False)  # type: ignore[call-overload]
    last_used_at: datetime = Field(sa_type=DateTime(timezone=True), nullable=False)  # type: ignore[call-overload]
    expires_at: datetime = Field(sa_type=DateTime(timezone=True), nullable=False)  # type: ignore[call-overload]

    user: User = Relationship(back_populates="sessions")


# Note: Requires repository
class Cluster(StyrminModel, table=True):
    name: str = Field(unique=True)
    config: dict | None = Field(default=None, sa_column=Column(JSON))
    capabilities: dict | None = Field(default=None, sa_column=Column(JSON))

    environments: list["Environment"] = Relationship(back_populates="cluster")


# Note: Requires repository
class BackupStorageLocation(StyrminModel, table=True):
    name: str = Field(unique=True)
    endpoint: str
    bucket: str
    region: str
    access_key_id: str
    secret_access_key: str

    environments: list["Environment"] = Relationship(
        back_populates="backup_storage_location"
    )


# Note: Requires repository
class Environment(StyrminModel, table=True):
    __table_args__ = (UniqueConstraint("name", "cluster_id"),)

    name: str
    config: dict | None = Field(default=None, sa_column=Column(JSON))
    capabilities: dict | None = Field(default=None, sa_column=Column(JSON))

    cluster_id: UUID = Field(foreign_key="cluster.id")
    cluster: Cluster = Relationship(back_populates="environments")

    backup_storage_location_id: UUID | None = Field(
        default=None, foreign_key="backupstoragelocation.id"
    )
    backup_storage_location: Optional["BackupStorageLocation"] = Relationship(
        back_populates="environments"
    )

    deployments: list["Deployment"] = Relationship(back_populates="environment")
    environment_backups: list["EnvironmentBackup"] = Relationship(
        back_populates="environment"
    )


# Note: Can be handled in application repository


class HelmRepository(StyrminModel, table=True):
    url: str = Field(unique=True)

    helm_charts: list["HelmChart"] = Relationship(back_populates="repository")


# Note: Can be handled in application repository


class HelmChart(StyrminModel, table=True):
    name: str
    version: str
    values_template: str

    repository_id: UUID = Field(foreign_key="helmrepository.id")
    repository: HelmRepository = Relationship(back_populates="helm_charts")

    application_driver_versions: list["ApplicationDriverVersion"] = Relationship(
        back_populates="helm_chart"
    )


# Note: Can be handled in application repository
class Action(StyrminModel, table=True):
    __table_args__ = (UniqueConstraint("name", "application_driver_version_id"),)

    name: str
    description: str
    location: str

    image: str | None = None

    hook: str | None = None
    mode: str | None = None

    application_driver_version_id: UUID = Field(
        foreign_key="applicationdriverversion.id"
    )
    application_driver_version: "ApplicationDriverVersion" = Relationship(
        back_populates="actions"
    )


class Utility(StyrminModel, table=True):
    kind: str


class ComponentConfig(StyrminModel, table=True):
    name: str
    config: dict = Field(sa_column=Column(JSON))

    application_driver_version_id: UUID = Field(
        foreign_key="applicationdriverversion.id"
    )
    application_driver_version: "ApplicationDriverVersion" = Relationship(
        back_populates="component_configs"
    )


class ApplicationDriver(StyrminModel, table=True):
    name: str = Field(unique=True)

    versions: list["ApplicationDriverVersion"] = Relationship(
        back_populates="application_driver"
    )


class ApplicationDriverVersion(StyrminModel, table=True):
    # 013 / R-X-1: UNIQUE composite index on the widened identity tuple.
    # ``postgresql_nulls_not_distinct=True`` gives ``IS NOT DISTINCT FROM``
    # semantics so that two rows whose fingerprint columns are both NULL
    # still collide (exactly one of ``content_hash`` / ``source_commit_sha``
    # is non-null per row, see data-model.md).
    __table_args__ = (
        Index(
            "uq_application_driver_version_identity",
            "application_driver_id",
            "source_type",
            "source_repository",
            "source_branch",
            "source_path",
            "version",
            "content_hash",
            "source_commit_sha",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    application_driver_id: UUID = Field(foreign_key="applicationdriver.id")
    application_driver: ApplicationDriver = Relationship(back_populates="versions")

    version: str
    # 013: SHA-256 hex of the canonical three-file byte concatenation
    # (driver.styrmin.yml + values template + actions.py when present).
    # Populated for ``source_type="local"`` rows.
    content_hash: str | None = None

    application_supported_versions: str
    default_version: str | None = None

    source_type: str = Field(default="git")
    source_repository: str
    source_branch: str | None = None
    source_path: str | None = None
    # 013: resolved git commit SHA at the loaded ref. Populated for
    # ``source_type="git"`` rows.
    source_commit_sha: str | None = None

    components: dict | None = Field(default=None, sa_column=Column(JSON))
    parameters: list | None = Field(default=None, sa_column=Column(JSON))
    services: list | None = Field(default=None, sa_column=Column(JSON))
    # 008 / US4: doc-only env var declarations parsed from ``spec.env_vars``.
    # Each entry shape matches :class:`DriverEnvVarDoc` (name, description,
    # level, components). Empty/None when the driver omits the block.
    env_vars: list | None = Field(default=None, sa_column=Column(JSON))
    # 014 / US6: doc-only container-override declarations parsed from
    # ``spec.container_overrides``. Each entry shape matches
    # :class:`DriverContainerOverrideDoc` (component, description, container,
    # command, args). Nullable JSON column added by revision ``a8b9c0d1e2f3``;
    # rows pre-dating it carry NULL and deserialize to ``None``.
    container_overrides: list | None = Field(default=None, sa_column=Column(JSON))
    # 020: logo URL from ``spec.info.icon`` (validated http/https URL).
    icon: str | None = None
    # 020: free text from ``spec.info.description``; an empty string is stored as NULL.
    description: str | None = None
    # 020: ``spec.info.links`` as ``[{"link", "url"}]`` in file order; empty is NULL.
    links: list | None = Field(default=None, sa_column=Column(JSON))
    component_configs: list[ComponentConfig] = Relationship(
        back_populates="application_driver_version",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    helm_chart_id: UUID = Field(foreign_key="helmchart.id")
    helm_chart: HelmChart = Relationship(back_populates="application_driver_versions")

    actions: list[Action] = Relationship(
        back_populates="application_driver_version",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    deployments: list["Deployment"] = Relationship(
        back_populates="application_driver_version"
    )


class DeployedService(StyrminModel, table=True):
    driver_service_name: str
    resolved_name: str
    kind: str
    scope: str
    port: int
    component: str

    deployment_id: UUID = Field(foreign_key="deployment.id")
    deployment: "Deployment" = Relationship(back_populates="deployed_services")

    environment_id: UUID = Field(foreign_key="environment.id")


class Component(StyrminModel, table=True):
    name: str
    enabled: bool = True
    config: dict = Field(sa_column=Column(JSON))

    deployment_id: UUID = Field(foreign_key="deployment.id")
    deployment: "Deployment" = Relationship(back_populates="components")


class DeploymentState(str, Enum):
    PENDING = "pending"
    DEPLOYING = "deploying"
    RUNNING = "running"
    RESTORING = "restoring"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class Deployment(StyrminModel, table=True):
    """The deployment represents the intention to deploy an application instance.
    Its attributes reflect the desired state of the service it is responsible for.

    Name uniqueness is scoped per ``(environment_id, name)`` and only
    applies to non-tombstoned rows (``deleted_at IS NULL``) — see the
    ``uq_deployment_env_name_active`` partial index in ``__table_args__``.
    Tombstoned (soft-deleted) deployments do not block name reuse, which
    is the user-visible behaviour an operator expects after retiring a
    deployment with ``deleteDeployment``.
    """

    __table_args__ = (
        Index(
            "uq_deployment_env_name_active",
            "environment_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    name: str  # unique scope: (environment_id, name) WHERE deleted_at IS NULL
    application_version: str
    config: dict | None = Field(default=None, sa_column=Column(JSON))
    parameters: dict | None = Field(default=None, sa_column=Column(JSON))
    internal: bool = Field(default=False)

    status: DeploymentState = Field(sa_column=Column(SQLModelEnum(DeploymentState)))

    deleted_at: datetime | None = Field(  # type: ignore[call-overload]
        sa_type=DateTime(timezone=True),
        default=None,
        index=True,
    )

    created_by_user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("user.id"),
            nullable=False,
        ),
    )

    # ==============
    # Relationships
    # ==============

    # Components. ``delete-orphan`` so that replacing the component set on a
    # driver-version rebind deletes the superseded rows on merge instead of
    # leaving them stranded.
    components: list[Component] = Relationship(
        back_populates="deployment",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    # Deployed services
    deployed_services: list["DeployedService"] = Relationship(
        back_populates="deployment",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    # Application driver version
    application_driver_version_id: UUID = Field(
        foreign_key="applicationdriverversion.id"
    )
    application_driver_version: ApplicationDriverVersion = Relationship(
        back_populates="deployments"
    )

    # Environment
    environment_id: UUID = Field(foreign_key="environment.id")
    environment: Environment = Relationship(back_populates="deployments")

    active_application_instance_id: UUID | None = Field(
        foreign_key="applicationinstance.id", default=None
    )

    # The sequence of the deployment's newest instance. Only the repository's
    # atomic increment writes it, so it has no default that a merge could copy.
    last_instance_sequence: int | None = Field(  # type: ignore[call-overload]
        sa_column_kwargs={"server_default": "0"},
        nullable=False,
    )

    active_application_instance: Optional["ApplicationInstance"] = Relationship(
        back_populates="is_active_for",
        sa_relationship_kwargs={
            "foreign_keys": "Deployment.active_application_instance_id",
            "post_update": True,
        },
    )

    # Application instance
    application_instances: list["ApplicationInstance"] = Relationship(
        back_populates="deployment",
        sa_relationship_kwargs={
            "foreign_keys": "ApplicationInstance.deployment_id",
        },
    )

    tasks: list["Task"] = Relationship(back_populates="deployment")

    pod_statuses: list["PodStatus"] = Relationship(
        back_populates="deployment",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    crd_status: Optional["DeploymentStatus"] = Relationship(
        back_populates="deployment",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "uselist": False},
    )


class InstanceStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"


class ApplicationInstance(StyrminModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "deployment_id",
            "sequence",
            name="uq_applicationinstance_deployment_sequence",
        ),
    )

    name: str = Field(unique=True)
    application_version: str
    status: InstanceStatus = Field(sa_column=Column(SQLModelEnum(InstanceStatus)))

    deployment_id: UUID = Field(foreign_key="deployment.id")
    deployment: Deployment = Relationship(
        back_populates="application_instances",
        sa_relationship_kwargs={
            "foreign_keys": "ApplicationInstance.deployment_id",
        },
    )

    is_active_for: Optional[Deployment] = Relationship(
        back_populates="active_application_instance",
        sa_relationship_kwargs={
            "foreign_keys": "Deployment.active_application_instance_id",
            "uselist": False,
            "post_update": True,
        },
    )

    application_driver_version_id: UUID = Field(
        foreign_key="applicationdriverversion.id"
    )

    context: dict | None = Field(default=None, sa_column=Column(JSON))

    # 1 for the deployment's first instance, then one more for each new one.
    sequence: int = Field(nullable=False)


class BackupStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class RestoreStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class EnvironmentBackup(StyrminModel, table=True):
    """A coordinated snapshot of an environment.

    Groups one constituent :class:`Backup` per eligible application instance
    together with the environment config and per-deployment declared state
    captured at backup time.

    There is deliberately **no status column**: the parent status is derived
    at read time from the constituent backups plus ``constituent_errors``, so
    a stored parent status can never contradict its children.
    """

    name: str = Field(unique=True)

    environment_id: UUID = Field(foreign_key="environment.id")
    environment: Environment = Relationship(back_populates="environment_backups")

    environment_config: dict | None = Field(default=None, sa_column=Column(JSON))
    deployment_snapshots: list | None = Field(default=None, sa_column=Column(JSON))
    constituent_errors: list | None = Field(default=None, sa_column=Column(JSON))

    backups: list["Backup"] = Relationship(back_populates="environment_backup")
    restores: list["EnvironmentRestore"] = Relationship(
        back_populates="environment_backup"
    )


class EnvironmentRestore(StyrminModel, table=True):
    """One coordinated in-place restore of an :class:`EnvironmentBackup`.

    Like its parent snapshot it carries **no status column** — the status is
    derived from the constituent restores plus ``skipped_constituents``.
    """

    environment_backup_id: UUID = Field(foreign_key="environmentbackup.id")
    environment_backup: EnvironmentBackup = Relationship(back_populates="restores")

    skipped_constituents: list | None = Field(default=None, sa_column=Column(JSON))

    restores: list["Restore"] = Relationship(back_populates="environment_restore")


class EnvironmentClone(StyrminModel, table=True):
    """One clone of an environment into a brand-new environment.

    Records the whole operation: the capture it is built from, the environment
    it created, the selection/override it was asked for, and one attribution
    entry per source deployment considered.

    There is deliberately **no status column** — like
    :class:`EnvironmentBackup` and :class:`EnvironmentRestore`, the status is
    derived at read time (``services/backup/clone.py``) from the backing
    capture's own derived status, the existence of ``created_environment_id``,
    the constituent ``Restore`` rows reachable through
    ``deployment_results[].restore_id``, and ``clone_errors``. A stored status
    could contradict any of them.

    ``name`` is **not** unique here: a failed clone must never block re-cloning
    under the same name. Uniqueness of the target environment name lives where
    it belongs, on ``Environment(name, cluster_id)``.

    Both environment foreign keys are nullable so provenance survives deletion:
    deleting the source nulls ``source_environment_id`` on terminal clones
    (``source_environment_name`` keeps the record readable), and deleting the
    created environment nulls ``created_environment_id``. Every such deletion
    also appends a ``clone_errors`` entry — ``{"step": str, "error": str,
    "fatal": bool}`` — because a bare NULL is not distinguishable from "not yet
    created". ``fatal: true`` drives the derivation to ``FAILED``; deletions
    that touch an already-terminal clone are recorded with ``fatal: false`` so
    history is kept without rewriting the outcome.
    """

    name: str

    source_environment_id: UUID | None = Field(
        default=None, foreign_key="environment.id"
    )
    source_environment: Optional["Environment"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[EnvironmentClone.source_environment_id]"
        },
    )

    #: The source's name at clone time, denormalised so provenance stays
    #: readable once the source environment is gone.
    source_environment_name: str

    environment_backup_id: UUID | None = Field(
        default=None, foreign_key="environmentbackup.id"
    )
    environment_backup: Optional["EnvironmentBackup"] = Relationship()

    created_environment_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("environment.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    created_environment: Optional["Environment"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[EnvironmentClone.created_environment_id]"
        },
    )

    #: The explicit deployment selection, verbatim; ``None`` means all eligible.
    requested_deployment_ids: list | None = Field(default=None, sa_column=Column(JSON))
    #: The environment config override as supplied, before merging.
    config_override: dict | None = Field(default=None, sa_column=Column(JSON))
    #: Config field names to drop from the captured config before the merge.
    cleared_config_fields: list | None = Field(default=None, sa_column=Column(JSON))
    #: One attribution entry per source deployment considered.
    deployment_results: list | None = Field(default=None, sa_column=Column(JSON))
    #: Operation-level events outside any single deployment; entries carry a
    #: ``fatal`` flag (see the class docstring).
    clone_errors: list | None = Field(default=None, sa_column=Column(JSON))

    created_by_user_id: UUID | None = Field(default=None, foreign_key="user.id")


class Backup(StyrminModel, table=True):
    name: str = Field(unique=True)
    status: BackupStatus = Field(sa_column=Column(SQLModelEnum(BackupStatus)))

    started_at: datetime | None = Field(sa_type=DateTime(timezone=True), default=None)  # type: ignore[call-overload]
    completed_at: datetime | None = Field(sa_type=DateTime(timezone=True), default=None)  # type: ignore[call-overload]
    # Volume bytes routinely exceed the 2 GiB a 32-bit INTEGER holds (#136).
    size_bytes: int | None = Field(sa_type=BigInteger, default=None)  # type: ignore[call-overload]
    error_message: str | None = Field(default=None)
    component_statuses: dict | None = Field(default=None, sa_column=Column(JSON))
    metadata_: dict | None = Field(default=None, sa_column=Column("metadata", JSON))

    instance_id: UUID = Field(foreign_key="applicationinstance.id")
    instance: ApplicationInstance = Relationship()

    schedule_id: UUID | None = Field(default=None, foreign_key="backupschedule.id")

    environment_backup_id: UUID | None = Field(
        default=None, foreign_key="environmentbackup.id"
    )
    environment_backup: Optional["EnvironmentBackup"] = Relationship(
        back_populates="backups"
    )

    restores: list["Restore"] = Relationship(back_populates="backup")


class Restore(StyrminModel, table=True):
    name: str = Field(unique=True)
    status: RestoreStatus = Field(sa_column=Column(SQLModelEnum(RestoreStatus)))

    started_at: datetime | None = Field(sa_type=DateTime(timezone=True), default=None)  # type: ignore[call-overload]
    completed_at: datetime | None = Field(sa_type=DateTime(timezone=True), default=None)  # type: ignore[call-overload]
    target_namespace: str
    error_message: str | None = Field(default=None)
    component_statuses: dict | None = Field(default=None, sa_column=Column(JSON))
    metadata_: dict | None = Field(default=None, sa_column=Column("metadata", JSON))

    backup_id: UUID = Field(foreign_key="backup.id")
    backup: Backup = Relationship(back_populates="restores")

    target_instance_id: UUID | None = Field(
        default=None, foreign_key="applicationinstance.id"
    )

    environment_restore_id: UUID | None = Field(
        default=None, foreign_key="environmentrestore.id"
    )
    environment_restore: Optional["EnvironmentRestore"] = Relationship(
        back_populates="restores"
    )


class BackupSchedule(StyrminModel, table=True):
    name: str = Field(unique=True)
    enabled: bool = Field(default=True)
    cron_expression: str

    last_backup_at: datetime | None = Field(  # type: ignore[call-overload]
        sa_type=DateTime(timezone=True), default=None
    )
    next_backup_at: datetime | None = Field(  # type: ignore[call-overload]
        sa_type=DateTime(timezone=True), default=None
    )
    retention_count: int = Field(default=10)
    prefect_deployment_id: UUID | None = Field(default=None)

    deployment_id: UUID = Field(foreign_key="deployment.id")
    deployment: Deployment = Relationship()


class PodPhase(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TaskType(str, Enum):
    NOOP = "noop"

    CREATE_INSTANCE = "create_instance"
    DELETE_INSTANCE = "delete_instance"
    UPDATE_INSTANCE = "update_instance"
    UPGRADE_INSTANCE = "upgrade_instance"
    STOP_COMPONENTS = "stop_components"
    START_COMPONENTS = "start_components"
    RUN_JOB = "run_job"
    DELETE_DEPLOYMENT = "delete_deployment"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Task(StyrminModel, table=True):
    status: TaskStatus = Field(sa_column=Column(SQLModelEnum(TaskStatus)))
    type: TaskType = Field(sa_column=Column(SQLModelEnum(TaskType)))
    message: str | None = Field(default=None)

    prefect_flow_run_id: UUID | None = Field(default=None)

    deployment_id: UUID = Field(foreign_key="deployment.id")
    deployment: Deployment = Relationship(back_populates="tasks")

    # The instance this task rolls out; links operator reports to the task.
    instance_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey(
                "applicationinstance.id",
                ondelete="SET NULL",
                name="task_instance_id_fkey",
            ),
            nullable=True,
            index=True,
        ),
    )
    # ``use_alter`` because ``step.task_id`` points back at ``task``.
    started_by_step_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey(
                "step.id",
                ondelete="SET NULL",
                use_alter=True,
                name="task_started_by_step_id_fkey",
            ),
            nullable=True,
            index=True,
        ),
    )


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class StepKind(str, Enum):
    PLAN = "plan"
    HOOK = "hook"
    RESOURCE_WRITE = "resource_write"
    OPERATOR_PHASE = "operator_phase"
    COMMAND = "command"
    RESTORE = "restore"
    BACKUP_COMPONENT = "backup_component"


#: Exactly one parent is set. Written without ``num_nonnulls`` so SQLite accepts it.
STEP_ONE_PARENT_CHECK = (
    "(CASE WHEN task_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN backup_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN restore_id IS NULL THEN 0 ELSE 1 END) = 1"
)


def _step_parent_key_index(parent_column: str) -> Index:
    """Unique (parent, key) over the rows of one parent type."""
    predicate = text(f"{parent_column} IS NOT NULL")
    return Index(
        f"uq_step_{parent_column}_key",
        parent_column,
        "key",
        unique=True,
        postgresql_where=predicate,
        sqlite_where=predicate,
    )


class Step(StyrminModel, table=True):
    """One unit of work inside a task, a backup or a restore. See spec 019."""

    __table_args__ = (
        CheckConstraint(STEP_ONE_PARENT_CHECK, name="ck_step_one_parent"),
        _step_parent_key_index("task_id"),
        _step_parent_key_index("backup_id"),
        _step_parent_key_index("restore_id"),
    )

    task_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("task.id", ondelete="CASCADE", name="step_task_id_fkey"),
            nullable=True,
        ),
    )
    backup_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("backup.id", ondelete="CASCADE", name="step_backup_id_fkey"),
            nullable=True,
        ),
    )
    restore_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("restore.id", ondelete="CASCADE", name="step_restore_id_fkey"),
            nullable=True,
        ),
    )

    key: str
    name: str
    kind: StepKind = Field(sa_column=Column(SQLModelEnum(StepKind), nullable=False))
    status: StepStatus = Field(
        sa_column=Column(SQLModelEnum(StepStatus), nullable=False)
    )

    started_at: datetime | None = Field(sa_type=DateTime(timezone=True), default=None)  # type: ignore[call-overload]
    ended_at: datetime | None = Field(sa_type=DateTime(timezone=True), default=None)  # type: ignore[call-overload]
    attempt_count: int = Field(default=0)
    # List of {"attempt": int, "message": str, "occurred_at": iso8601}.
    errors: list[dict] | None = Field(default=None, sa_column=Column(JSON))

    detail: str | None = Field(default=None)
    rolled_back_at: datetime | None = Field(  # type: ignore[call-overload]
        sa_type=DateTime(timezone=True), default=None
    )
    rollback_message: str | None = Field(default=None)

    output: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    # ``server_default`` mirrors the add-steps revision.
    output_truncated: bool = Field(
        default=False,
        nullable=False,
        sa_column_kwargs={"server_default": false()},
    )

    superseded_by_task_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey(
                "task.id",
                ondelete="SET NULL",
                name="step_superseded_by_task_id_fkey",
            ),
            nullable=True,
            index=True,
        ),
    )


class PodStatus(StyrminModel, table=True):
    __table_args__ = (UniqueConstraint("deployment_id", "pod_name"),)

    pod_name: str
    namespace: str
    # Non-optional in Python, so the column must be NOT NULL. The bare
    # ``Column(SQLModelEnum(PodPhase))`` used to default to nullable, which
    # contradicted the annotation and diverged from revision ``a1b2c3d4e5f6``.
    phase: PodPhase = Field(sa_column=Column(SQLModelEnum(PodPhase), nullable=False))
    ready: bool = Field(default=False)
    restart_count: int = Field(default=0)
    container_statuses: list[dict] | None = Field(default=None, sa_column=Column(JSON))
    node_name: str | None = Field(default=None)
    component_name: str | None = Field(default=None)
    started_at: datetime | None = Field(sa_type=DateTime(timezone=True), default=None)  # type: ignore[call-overload]
    last_polled_at: datetime = Field(  # type: ignore[call-overload]
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )

    deployment_id: UUID = Field(foreign_key="deployment.id")
    deployment: Deployment = Relationship(back_populates="pod_statuses")


class DeploymentStatus(StyrminModel, table=True):
    """Latest StyrminDeployment CRD status snapshot per deployment."""

    deployment_id: UUID = Field(foreign_key="deployment.id", unique=True)
    phase: str
    message: str | None = Field(default=None)
    conditions: list[dict] | None = Field(default=None, sa_column=Column(JSON))
    managed_resource_counts: dict | None = Field(default=None, sa_column=Column(JSON))
    last_polled_at: datetime = Field(  # type: ignore[call-overload]
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )

    deployment: Deployment = Relationship(back_populates="crd_status")


class Installation(SQLModel, table=True):
    """The install ID that telemetry reports (spec 020). Always one row, ``id = 1``."""

    __table_args__ = (CheckConstraint("id = 1", name="ck_installation_single_row"),)

    id: int = Field(
        default=1, primary_key=True, sa_column_kwargs={"autoincrement": False}
    )
    install_id: UUID = Field(nullable=False)
    created_on: datetime | None = Field(  # type: ignore[call-overload]
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )
