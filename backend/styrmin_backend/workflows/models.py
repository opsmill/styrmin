import importlib
import sys
from abc import ABC, abstractmethod
from enum import Enum
from tempfile import TemporaryDirectory
from typing import Any, Awaitable, Callable, TypeVar
from uuid import UUID

from dulwich import porcelain
from prefect.client.orchestration import PrefectClient
from prefect.client.schemas.actions import DeploymentScheduleCreate
from prefect.client.schemas.objects import FlowRun
from prefect.client.schemas.schedules import CronSchedule
from prefect.runner.storage import GitRepository
from prefect_github import GitHubCredentials
from pydantic import BaseModel, Field
from typing_extensions import Self

from styrmin_backend import __version__
from styrmin_backend.workflows.utils import get_repository_name, set_directory_pull_step

from .constants import WorkflowType

WorkflowReturn = TypeVar("WorkflowReturn")


class KubernetesConnectivityResult(BaseModel):
    """Result of a Kubernetes connectivity check."""

    connected: bool
    cluster_info: str | None = None
    error: str | None = None


class PrefectWorkPool(Enum):
    """Enumeration of Prefect work pools."""

    STYRMIN_WORK_POOL = "styrmin-work-pool"
    USER_WORK_POOL = "user-work-pool"


class PrefectAction(Enum):
    """Enumeration of Prefect actions."""

    APPLY_STATE = "apply_state"

    CREATE_HELM_RELEASE = "create_instance"
    UPDATE_HELM_RELEASE = "update_instance"

    CREATE_INSTANCE = "orchestrate_instance_creation"
    UPDATE_INSTANCE = "orchestrate_instance_update"
    UPGRADE_INSTANCE = "orchestrate_instance_upgrade"
    RUN_JOB = "run_job"
    EXECUTE_BACKUP = "execute_backup"
    EXECUTE_RESTORE = "execute_restore"
    EXECUTE_ENVIRONMENT_CLONE = "execute_environment_clone"
    EXECUTE_VELERO_BACKUP = "execute_velero_backup"
    EXECUTE_VELERO_RESTORE = "execute_velero_restore"
    APPLY_UTILITY_RESOURCES = "apply_utility_resources"
    VALIDATE_CONNECTIVITY = "validate_connectivity"
    SYNC_BSL_CREATE = "sync_bsl_create"
    SYNC_BSL_DELETE = "sync_bsl_delete"
    SYNC_BSL_UPDATE_CREDENTIALS = "sync_bsl_update_credentials"
    CLEANUP_EXPIRED_SESSIONS = "cleanup_expired_sessions"

    def to_tag(self) -> str:
        """Convert the action to a tag for Prefect."""
        return f"action/{self.value}"


class WorkPoolDefinition(BaseModel):
    name: str
    worker_type: str | None = None
    description: str = ""
    base_job_template: dict[str, Any] | None = None


class DeploymentInfo(BaseModel):
    workflow_definition: "WorkflowDefinition"
    deployment_id: UUID
    flow_id: UUID


class WorkflowInfo(BaseModel):
    id: UUID
    info: FlowRun

    @classmethod
    def from_flow(cls, flow_run: FlowRun) -> Self:
        return cls(id=flow_run.id, info=flow_run)


class WorkflowDefinition(BaseModel, ABC):
    name: str
    module: str
    function: str
    type: WorkflowType = WorkflowType.INTERNAL
    cron: str | None = None
    tags: list[str] = Field(default_factory=list)
    image: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.name}/{self.name}"

    @property
    def entrypoint(self) -> str:
        return f"{self.module.replace('.', '/')}.py:{self.function}"

    async def to_deployment(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "entrypoint": self.entrypoint,
            "tags": self.get_tags(),
        }
        if self.image:
            payload["job_variables"] = {"image": self.image}
        if self.type == WorkflowType.INTERNAL:
            payload["version"] = __version__
        if self.cron:
            payload["schedules"] = [
                DeploymentScheduleCreate(schedule=CronSchedule(cron=self.cron))
            ]

        return payload

    def get_tags(self) -> list[str]:
        return self.tags

    async def save(
        self, client: PrefectClient, work_pool: WorkPoolDefinition
    ) -> DeploymentInfo:
        flow_id = await client.create_flow_from_name(self.name)
        data = await self.to_deployment()
        data["work_pool_name"] = work_pool.name
        deployment_id = await client.create_deployment(flow_id=flow_id, **data)
        return DeploymentInfo(
            deployment_id=deployment_id, flow_id=flow_id, workflow_definition=self
        )

    @abstractmethod
    def get_function(self) -> Callable[..., Awaitable[Any]]:
        raise NotImplementedError

    def validate_workflow(self) -> None:
        self.get_function()


class GitSourceWorkflowDefinition(WorkflowDefinition):
    repository: str
    branch: str
    token: str
    namespace: str
    set_directory: str | None = None

    async def to_deployment(self) -> dict[str, Any]:
        data = await super().to_deployment()
        # note: Looked up from prefect source code `Flow.from_source` method
        credentials = await GitHubCredentials.load(
            name=f"{self.namespace}-github-token"
        )
        storage = GitRepository(
            url=self.repository,
            branch=self.branch,
            credentials=credentials,
        )
        data["pull_steps"] = [storage.to_pull_step()]
        if self.set_directory:
            data["pull_steps"].append(
                set_directory_pull_step(
                    directory=self.set_directory,
                    repository_name=get_repository_name(self.repository),
                    branch=self.branch,
                )
            )

        return data

    @property
    def entrypoint(self) -> str:
        return f"{self.module}:{self.function}"

    def get_function(self) -> Callable[..., Awaitable[Any]]:
        with TemporaryDirectory() as tmpdir:
            porcelain.clone(
                self.repository, tmpdir, branch=self.branch, username=self.token
            )
            sys.path.append(tmpdir)
            module = importlib.import_module(f"{self.module}")
            return getattr(module, self.function)


class LocalSourceWorkflowDefinition(WorkflowDefinition):
    set_directory: str | None = None

    async def to_deployment(self) -> dict[str, Any]:
        data = await super().to_deployment()

        if self.set_directory:
            data.setdefault("pull_steps", []).append(
                {
                    "prefect.deployments.steps.set_working_directory": {
                        "directory": self.set_directory,
                    }
                }
            )

        return data

    def get_function(self) -> Callable[..., Awaitable[Any]]:
        module = importlib.import_module(self.module)
        return getattr(module, self.function)
