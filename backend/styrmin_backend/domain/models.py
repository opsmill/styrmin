from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.domain.utils import validate_deployment_name

# FIXME: Add domain model for application driver and application driver version


class InstanceStatus(str, Enum):
    """Instance status enum."""

    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"


class Instance(BaseModel):
    id: UUID
    name: str
    application_version: str
    status: InstanceStatus

    deployment_id: UUID
    application_driver_version_id: UUID

    context: GlobalContext

    # Position among the deployment's instances; the repository sets it on the first save.
    sequence: int | None = None

    @classmethod
    def create(
        cls,
        name: str,
        application_version: str,
        deployment_id: UUID,
        application_driver_version_id: UUID,
        context: GlobalContext,
    ) -> Instance:
        """Create a new Instance instance."""
        return cls(
            id=uuid4(),
            name=name,
            application_version=application_version,
            status=InstanceStatus.PENDING,
            deployment_id=deployment_id,
            application_driver_version_id=application_driver_version_id,
            context=context,
        )


class DeploymentState(str, Enum):
    """Deployment state enum."""

    PENDING = "pending"
    DEPLOYING = "deploying"
    RUNNING = "running"
    RESTORING = "restoring"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class Deployment(BaseModel):
    """The deployment represents the intention to deploy an application instance.
    Its attributes reflect the desired state of the service it is responsible for.
    """

    id: UUID
    name: str
    application_version: str
    config: dict | None
    parameters: dict = Field(default_factory=dict)
    internal: bool = Field(default=False)

    application_driver_version_id: UUID

    environment_id: UUID

    status: DeploymentState = Field(default=DeploymentState.PENDING)

    deleted_at: datetime | None = None

    created_by_user_id: UUID

    _components: Dict[str, Component] = PrivateAttr(default_factory=dict)

    # Application instance
    _application_instance: Instance | None = PrivateAttr(default=None)

    @property
    def components(self) -> list[Component]:
        """Get the components of the deployment."""
        return [component.model_copy() for component in self._components.values()]

    @property
    def active_instance(self) -> Instance | None:
        """Get the application instance of the deployment."""
        return (
            self._application_instance.model_copy()
            if self._application_instance
            else None
        )

    def get_components_names(self) -> list[str]:
        """Get the names of the components in the deployment."""
        return list(self._components.keys())

    def add_component(self, component: Component) -> None:
        """Add a component to the deployment."""
        if component.name in self._components:
            raise ValueError(f"Component with name {component.name} already exists.")
        self._components[component.name] = component

    def set_components(self, components: list[Component]) -> None:
        """Replace all components of the deployment.

        Used when rebinding the deployment to a different application driver
        version, whose component set supersedes the current one.
        """
        self._components = {}
        for component in components:
            self.add_component(component)

    def update_component(self, name: str, enabled: bool) -> None:
        """Update a component in the deployment."""
        if name not in self._components:
            raise ValueError(f"Component with name {name} does not exist.")
        self._components[name].enabled = enabled

    def set_active_instance(self, instance: Instance | None) -> None:
        """Set the active instance for the deployment."""
        self._application_instance = instance

    def set_status(self, status: DeploymentState) -> None:
        """Set the status of the deployment."""
        self.status = status

    @classmethod
    def create(
        cls,
        application_version: str,
        application_driver_version_id: UUID,
        environment_id: UUID,
        created_by_user_id: UUID,
        config: dict | None = None,
        parameters: dict | None = None,
        name: str | None = None,
        internal: bool = False,
        id: UUID | None = None,
    ) -> Deployment:
        """Create a new Deployment instance.

        Args:
            name: Optional deployment name. If provided, it is validated.
                  If None, the caller must have resolved the name beforehand
                  (e.g., via auto-generation in the service layer).
            created_by_user_id: The id of the user creating the deployment.
                  Used for attribution (Deployment.createdBy in the schema).
            id: The id to give the deployment, when the caller chose it in
                  advance (an environment clone's counterpart); a new id otherwise.
        """
        if not name or not name.strip():
            raise ValueError(
                "Deployment name must be provided. "
                "Use the service layer to auto-generate a name if needed."
            )
        resolved_name = validate_deployment_name(name)

        return cls(
            id=id or uuid4(),
            name=resolved_name,
            application_version=application_version,
            config=config or {},
            parameters=parameters or {},
            internal=internal,
            application_driver_version_id=application_driver_version_id,
            environment_id=environment_id,
            created_by_user_id=created_by_user_id,
        )


class DeployedService(BaseModel):
    """A runtime instance of a service definition, tied to a specific deployment."""

    id: UUID
    driver_service_name: str
    resolved_name: str
    kind: str
    scope: str
    port: int
    component: str
    deployment_id: UUID
    environment_id: UUID

    @classmethod
    def create(
        cls,
        driver_service_name: str,
        resolved_name: str,
        kind: str,
        scope: str,
        port: int,
        component: str,
        deployment_id: UUID,
        environment_id: UUID,
    ) -> DeployedService:
        """Create a new DeployedService instance."""
        return cls(
            id=uuid4(),
            driver_service_name=driver_service_name,
            resolved_name=resolved_name,
            kind=kind,
            scope=scope,
            port=port,
            component=component,
            deployment_id=deployment_id,
            environment_id=environment_id,
        )


class ComponentConfig(BaseModel):
    """ComponentConfig model."""

    id: UUID
    name: str
    config: dict

    @classmethod
    def create(cls, name: str, config: dict | None = None) -> ComponentConfig:
        """Create a new ComponentConfig instance."""
        return cls(id=uuid4(), name=name, config=config or {})


class Component(BaseModel):
    """Component model."""

    id: UUID
    name: str
    enabled: bool = True
    config: dict

    @classmethod
    def create(cls, name: str, config: dict, enabled: bool = True) -> Component:
        """Create a new Component instance."""
        return cls(id=uuid4(), name=name, config=config, enabled=enabled)


class TaskStatus(str, Enum):
    """Task status enum."""

    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    SUCCESS = "success"


class TaskType(str, Enum):
    """Task type enum."""

    NOOP = "noop"
    RUN_JOB = "run_job"
    DEPLOYMENT = "deployment"
    CREATE_INSTANCE = "create_instance"
    DELETE_INSTANCE = "delete_instance"
    UPDATE_INSTANCE = "update_instance"
    UPGRADE_INSTANCE = "upgrade_instance"
    STOP_COMPONENTS = "stop_components"
    START_COMPONENTS = "start_components"
    DELETE_DEPLOYMENT = "delete_deployment"


class Task(BaseModel):
    """Task model."""

    id: UUID
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    type: TaskType
    message: str | None = Field(default=None)

    prefect_flow_run_id: UUID | None = Field(default=None)

    deployment_id: UUID
    # The instance this task rolls out, and the hook step that started it.
    instance_id: UUID | None = Field(default=None)
    started_by_step_id: UUID | None = Field(default=None)

    created_on: datetime | None = Field(default=None)
    updated_on: datetime | None = Field(default=None)

    @classmethod
    def create(
        cls,
        type: TaskType,
        deployment_id: UUID,
        prefect_flow_run_id: UUID | None = None,
        status: TaskStatus = TaskStatus.PENDING,
        instance_id: UUID | None = None,
        started_by_step_id: UUID | None = None,
    ) -> Task:
        """Create a new Task instance."""
        return cls(
            id=uuid4(),
            type=type,
            status=status,
            deployment_id=deployment_id,
            prefect_flow_run_id=prefect_flow_run_id,
            instance_id=instance_id,
            started_by_step_id=started_by_step_id,
        )


class StepStatus(str, Enum):
    """Status of a step. ``succeeded`` and ``superseded`` are final."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class StepKind(str, Enum):
    """What a step does, and so which process writes it."""

    PLAN = "plan"
    HOOK = "hook"
    RESOURCE_WRITE = "resource_write"
    OPERATOR_PHASE = "operator_phase"
    COMMAND = "command"
    RESTORE = "restore"
    BACKUP_COMPONENT = "backup_component"

    @property
    def is_flow_kind(self) -> bool:
        """Written by a flow, so failed when the flow that owns it dies."""
        return self is not StepKind.OPERATOR_PHASE


class TaskResult(str, Enum):
    """Result of a task as users view it, calculated from its steps."""

    RUNNING = "running"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    SUPERSEDED = "superseded"


class StepEvent(str, Enum):
    """An event a writer records on a step through ``recordStep``."""

    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OUTPUT = "output"


class StepError(BaseModel):
    """The error of one failed attempt of a step."""

    attempt: int
    message: str
    occurred_at: datetime


class StepParent(BaseModel):
    """The task, backup or restore a step belongs to. Exactly one id is set."""

    model_config = ConfigDict(frozen=True)

    task_id: UUID | None = None
    backup_id: UUID | None = None
    restore_id: UUID | None = None

    @model_validator(mode="after")
    def _exactly_one_parent(self) -> StepParent:
        ids = (self.task_id, self.backup_id, self.restore_id)
        if sum(parent_id is not None for parent_id in ids) != 1:
            raise ValueError("A step has exactly one task, backup or restore")
        return self

    @classmethod
    def of_task(cls, task_id: UUID) -> StepParent:
        return cls(task_id=task_id)

    @classmethod
    def of_backup(cls, backup_id: UUID) -> StepParent:
        return cls(backup_id=backup_id)

    @classmethod
    def of_restore(cls, restore_id: UUID) -> StepParent:
        return cls(restore_id=restore_id)


class Step(BaseModel):
    """One unit of work inside a task, a backup or a restore."""

    id: UUID
    parent: StepParent
    key: str
    name: str
    kind: StepKind
    status: StepStatus = Field(default=StepStatus.PENDING)

    started_at: datetime | None = Field(default=None)
    ended_at: datetime | None = Field(default=None)
    attempt_count: int = Field(default=0)
    errors: list[StepError] = Field(default_factory=list)

    detail: str | None = Field(default=None)
    rolled_back_at: datetime | None = Field(default=None)
    rollback_message: str | None = Field(default=None)

    output: str | None = Field(default=None)
    output_truncated: bool = Field(default=False)

    superseded_by_task_id: UUID | None = Field(default=None)

    created_on: datetime | None = Field(default=None)
    updated_on: datetime | None = Field(default=None)

    @property
    def task_id(self) -> UUID | None:
        return self.parent.task_id

    @property
    def backup_id(self) -> UUID | None:
        return self.parent.backup_id

    @property
    def restore_id(self) -> UUID | None:
        return self.parent.restore_id

    @classmethod
    def create(
        cls,
        parent: StepParent,
        key: str,
        name: str,
        kind: StepKind,
        status: StepStatus = StepStatus.PENDING,
        started_at: datetime | None = None,
    ) -> Step:
        """Create a new step; a started step counts its first attempt."""
        return cls(
            id=uuid4(),
            parent=parent,
            key=key,
            name=name,
            kind=kind,
            status=status,
            started_at=started_at,
            attempt_count=0 if started_at is None else 1,
        )
