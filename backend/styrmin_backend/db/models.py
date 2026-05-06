"""Provides the models for the database tables.

This is where the different tables and their columns must be defined.
"""

from datetime import datetime
from enum import Enum, IntEnum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, LargeBinary, UniqueConstraint, text
from sqlmodel import JSON, Column, DateTime, Field, Relationship, SQLModel, func
from sqlmodel import Enum as SQLModelEnum


class Role(IntEnum):
    """Authorization role. See ADR-020.

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
    """Many-to-many link between User and Group. See ADR-020."""

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
    """User account. See ADR-019, ADR-020."""

    username: str = Field(unique=True)
    password_hash: str
    display_name: str
    active: bool = Field(default=True, nullable=False)
    role: Role = Field(
        default=Role.READ_ONLY,
        sa_column=Column(SQLModelEnum(Role), nullable=False),
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
    """Authorization group. See ADR-020.

    Membership monotonically elevates: a user's effective role is
    ``max(user.role, *(g.role for g in user.groups))``.
    """

    name: str = Field(unique=True)
    role: Role = Field(
        default=Role.READ_ONLY,
        sa_column=Column(SQLModelEnum(Role), nullable=False),
    )

    users: list["User"] = Relationship(
        back_populates="groups",
        link_model=UserGroup,
    )


class Session(StyrminModel, table=True):
    """Server-side opaque session row. See ADR-019."""

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
    resource_template: str = Field(default="")


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
    application_driver_id: UUID = Field(foreign_key="applicationdriver.id")
    application_driver: ApplicationDriver = Relationship(back_populates="versions")

    version: str

    application_supported_versions: str
    default_version: str | None = None

    source_type: str = Field(default="git")
    source_repository: str
    source_branch: str | None = None
    source_path: str | None = None

    components: dict | None = Field(default=None, sa_column=Column(JSON))
    parameters: list | None = Field(default=None, sa_column=Column(JSON))
    services: list | None = Field(default=None, sa_column=Column(JSON))
    # 008 / US4: doc-only env var declarations parsed from ``spec.env_vars``.
    # Each entry shape matches :class:`DriverEnvVarDoc` (name, description,
    # level, components). Empty/None when the driver omits the block.
    env_vars: list | None = Field(default=None, sa_column=Column(JSON))
    component_configs: list[ComponentConfig] = Relationship(
        back_populates="application_driver_version"
    )

    helm_chart_id: UUID = Field(foreign_key="helmchart.id")
    helm_chart: HelmChart = Relationship(back_populates="application_driver_versions")

    actions: list[Action] = Relationship(back_populates="application_driver_version")

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

    # ==============
    # Relationships
    # ==============

    # Components
    components: list[Component] = Relationship(back_populates="deployment")

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


class Backup(StyrminModel, table=True):
    name: str = Field(unique=True)
    status: BackupStatus = Field(sa_column=Column(SQLModelEnum(BackupStatus)))

    started_at: datetime | None = Field(sa_type=DateTime(timezone=True), default=None)  # type: ignore[call-overload]
    completed_at: datetime | None = Field(sa_type=DateTime(timezone=True), default=None)  # type: ignore[call-overload]
    size_bytes: int | None = Field(default=None)
    error_message: str | None = Field(default=None)
    component_statuses: dict | None = Field(default=None, sa_column=Column(JSON))
    metadata_: dict | None = Field(default=None, sa_column=Column("metadata", JSON))

    instance_id: UUID = Field(foreign_key="applicationinstance.id")
    instance: ApplicationInstance = Relationship()

    schedule_id: UUID | None = Field(default=None, foreign_key="backupschedule.id")

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


class PodStatus(StyrminModel, table=True):
    __table_args__ = (UniqueConstraint("deployment_id", "pod_name"),)

    pod_name: str
    namespace: str
    phase: PodPhase = Field(sa_column=Column(SQLModelEnum(PodPhase)))
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
