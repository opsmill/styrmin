"""Provides the models for the database tables.

This is where the different tables and their columns must be defined.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import JSON, Column, DateTime, Field, Relationship, SQLModel, func
from sqlmodel import Enum as SQLModelEnum


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


class DeploymentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"


class Deployment(StyrminModel, table=True):
    """The deployment represents the intention to deploy an application instance.
    Its attributes reflect the desired state of the service it is responsible for.
    """

    name: str = Field(unique=True)
    application_version: str
    config: dict | None = Field(default=None, sa_column=Column(JSON))
    parameters: dict | None = Field(default=None, sa_column=Column(JSON))
    internal: bool = Field(default=False)

    status: DeploymentStatus = Field(sa_column=Column(SQLModelEnum(DeploymentStatus)))

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


class TaskType(str, Enum):
    NOOP = "noop"

    CREATE_INSTANCE = "create_instance"
    DELETE_INSTANCE = "delete_instance"
    UPDATE_INSTANCE = "update_instance"
    UPGRADE_INSTANCE = "upgrade_instance"
    STOP_COMPONENTS = "stop_components"
    START_COMPONENTS = "start_components"
    RUN_JOB = "run_job"


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
