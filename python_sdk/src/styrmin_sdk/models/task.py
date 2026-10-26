"""Models built from task reads."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from styrmin_sdk.graphql._generated.enums import TaskResult  # noqa: TC001 — Pydantic reads the field type at runtime


class FailedStep(BaseModel):
    """A failed step: its name, the task that holds it, and its newest error."""

    model_config = ConfigDict(frozen=True)

    name: str
    task_id: UUID
    error: str | None = None


class TaskWait(BaseModel):
    """What :meth:`~styrmin_sdk.resources.deployments.DeploymentResource.wait_for_task` read when it stopped.

    ``failure_reason`` is ``None`` only when the change finished as requested. ``timed_out`` is
    true when ``max_wait`` elapsed first; the change can still finish after that.
    """

    model_config = ConfigDict(frozen=True)

    task_id: UUID
    deployment_id: UUID | None
    task_result: TaskResult
    deployment_status: str | None = None
    failure_reason: str | None = None
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        """True when the change finished as requested."""
        return self.failure_reason is None
