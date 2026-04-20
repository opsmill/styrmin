from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, PrivateAttr

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.domain.utils import generate_unique_name, validate_deployment_name

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

    @classmethod
    def create(
        cls,
        application_version: str,
        deployment_id: UUID,
        application_driver_version_id: UUID,
        context: GlobalContext,
    ) -> Instance:
        """Create a new Instance instance."""
        return cls(
            id=uuid4(),
            name=generate_unique_name(),
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
    FAILED = "failed"
    DELETION_REQUESTED = "deletion_requested"
    DELETION_IN_PROGRESS = "deletion_in_progress"
    DELETED = "deleted"


class BackupDisposition(str, Enum):
    """Operator's choice for what happens to backups when a deployment is deleted."""

    RETAIN = "retain"
    REMOVE = "remove"


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
    deleted_at: datetime | None = Field(default=None)

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
        config: dict | None = None,
        parameters: dict | None = None,
        name: str | None = None,
        internal: bool = False,
    ) -> Deployment:
        """Create a new Deployment instance.

        Args:
            name: Optional deployment name. If provided, it is validated.
                  If None, the caller must have resolved the name beforehand
                  (e.g., via auto-generation in the service layer).
        """
        if not name or not name.strip():
            raise ValueError(
                "Deployment name must be provided. "
                "Use the service layer to auto-generate a name if needed."
            )
        resolved_name = validate_deployment_name(name)

        return cls(
            id=uuid4(),
            name=resolved_name,
            application_version=application_version,
            config=config or {},
            parameters=parameters or {},
            internal=internal,
            application_driver_version_id=application_driver_version_id,
            environment_id=environment_id,
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


class Task(BaseModel):
    """Task model."""

    id: UUID
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    type: TaskType
    message: str | None = Field(default=None)

    prefect_flow_run_id: UUID | None = Field(default=None)

    deployment_id: UUID

    created_on: datetime | None = Field(default=None)
    updated_on: datetime | None = Field(default=None)

    @classmethod
    def create(
        cls,
        type: TaskType,
        deployment_id: UUID,
        prefect_flow_run_id: UUID | None = None,
        status: TaskStatus = TaskStatus.PENDING,
    ) -> Task:
        """Create a new Task instance."""
        return cls(
            id=uuid4(),
            type=type,
            deployment_id=deployment_id,
            prefect_flow_run_id=prefect_flow_run_id,
        )
