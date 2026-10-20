import importlib
import sys
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Awaitable, Callable, TypeVar
from uuid import UUID

from dulwich import porcelain
from prefect.client.orchestration import PrefectClient
from prefect.client.schemas.actions import DeploymentScheduleCreate
from prefect.client.schemas.objects import FlowRun
from prefect.client.schemas.schedules import CronSchedule
from prefect.runner.storage import GitRepository
from prefect.utilities.importtools import import_object
from prefect_github import GitHubCredentials
from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self

from styrmin_backend import __version__
from styrmin_backend.workflows.local_driver import (
    CHECK_LOCAL_DRIVER_STEP,
    check_local_driver_files,
)
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
    RUN_JOB_COMMAND = "run_job_command"
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
    SEND_TELEMETRY_REPORT = "send_telemetry_report"

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
    # Prefect upserts deployments on ``(flow, name)``: workflows that must
    # coexist under one flow name (user actions, one per driver version) set
    # a distinct deployment name; the rest reuse ``name``.
    deployment_name: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.name}/{self.deployment_name or self.name}"

    @property
    def entrypoint(self) -> str:
        return f"{self.module.replace('.', '/')}.py:{self.function}"

    async def to_deployment(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.deployment_name or self.name,
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
    # Commit to pull instead of the branch tip (ADR-053, #375).
    commit_sha: str | None = None

    @property
    def clone_directory_name(self) -> str:
        """Directory the pull step clones into.

        Mirrors Prefect's ``<repo>-<branch>`` default. A pinned commit gets
        its own ``<repo>-<sha>`` directory, so a reused worker directory can
        never serve another commit's checkout.
        """
        repository_name = get_repository_name(self.repository)
        if self.commit_sha:
            return f"{repository_name}-{self.commit_sha[:7]}"
        return f"{repository_name}-{self.branch.replace('/', '-')}"

    async def to_deployment(self) -> dict[str, Any]:
        data = await super().to_deployment()
        # note: Looked up from prefect source code `Flow.from_source` method
        credentials = await GitHubCredentials.load(
            name=f"{self.namespace}-github-token"
        )
        # Prefect refuses ``branch`` alongside ``commit_sha``.
        storage = GitRepository(
            url=self.repository,
            branch=None if self.commit_sha else self.branch,
            commit_sha=self.commit_sha,
            name=self.clone_directory_name,
            credentials=credentials,
        )
        data["pull_steps"] = [storage.to_pull_step()]
        if self.set_directory:
            data["pull_steps"].append(
                set_directory_pull_step(
                    directory=self.set_directory,
                    clone_directory_name=self.clone_directory_name,
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


class LocalDriverActionWorkflowDefinition(WorkflowDefinition):
    """An action of a driver version loaded from a local directory (spec 029).

    The action runs from ``directory`` in the agent pod, through the agent's
    Prefect process worker: the deployment's only pull step,
    :func:`~styrmin_backend.workflows.local_driver.check_local_driver`, checks
    the provenance fingerprint of the driver files at ``directory`` and returns
    the directory. Prefect then changes into it and imports the
    entrypoint ``<module>:<function>`` (research R-001).

    The definition refuses a ``directory`` that contains ``{`` or ``}`` or is
    relative, an empty ``content_hash``, and a ``module`` other than
    ``actions_file``. ``ensure_action_registrations`` refuses such a path and
    such an action first, with the message for the user.
    """

    # The path that the driver version was loaded from (``source_path``).
    directory: str
    # The full provenance fingerprint of the driver version (``content_hash``).
    content_hash: str
    # The driver file names of the server settings when the driver was loaded.
    spec_file: str
    values_template: str
    actions_file: str

    @field_validator("directory")
    @classmethod
    def _refuse_template_braces(cls, directory: str) -> str:
        """Refuse ``{`` and ``}``: Prefect fills in templates in pull-step inputs (research R-005).

        A template in the path would be filled in before the check reads it,
        so the check could write a value of the action's environment, such as
        the action token, into its error.
        """
        if "{" in directory or "}" in directory:
            raise ValueError(
                f"The driver path {directory!r} contains '{{' or '}}'. Prefect fills "
                "in '{{ ... }}' templates in the inputs of the pull step that checks "
                "the driver files, so the path cannot be an input of that step."
            )
        return directory

    @field_validator("content_hash")
    @classmethod
    def _refuse_empty_content_hash(cls, content_hash: str) -> str:
        """Refuse an empty provenance fingerprint, which no driver files can match."""
        if not content_hash:
            raise ValueError(
                "The provenance fingerprint (content_hash) is empty. The check before "
                "each action compares the driver files with it, so it must be set."
            )
        return content_hash

    @model_validator(mode="after")
    def _refuse_what_the_check_does_not_cover(self) -> Self:
        """Refuse a relative ``directory`` and a ``module`` other than ``actions_file``.

        The agent runs the action from a temporary working folder, where a
        relative path does not lead to the driver, and the check hashes only
        ``actions_file`` of the driver's code.
        """
        if not self.directory.startswith("/"):
            raise ValueError(
                f"The driver path {self.directory!r} is relative. The action runs "
                "from a temporary working folder, so the path must be absolute."
            )
        if self.module != self.actions_file:
            raise ValueError(
                f"The action's module {self.module!r} is not the actions file "
                f"{self.actions_file!r}, the only code file that the check before "
                "the action covers."
            )
        return self

    @property
    def entrypoint(self) -> str:
        return f"{self.module}:{self.function}"

    async def to_deployment(self) -> dict[str, Any]:
        data = await super().to_deployment()
        data["pull_steps"] = [
            {
                CHECK_LOCAL_DRIVER_STEP: {
                    "directory": self.directory,
                    "content_hash": self.content_hash,
                    "spec_file": self.spec_file,
                    "values_template": self.values_template,
                    "actions_file": self.actions_file,
                }
            }
        ]
        return data

    def get_function(self) -> Callable[..., Awaitable[Any]]:
        # The same check as the pull step, so the files are never imported unchecked.
        check_local_driver_files(
            directory=self.directory,
            content_hash=self.content_hash,
            spec_file=self.spec_file,
            values_template=self.values_template,
            actions_file=self.actions_file,
        )
        # Prefect's script loader, as in the action's flow run: the directory is on ``sys.path``.
        return import_object(f"{Path(self.directory) / self.module}:{self.function}")


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
