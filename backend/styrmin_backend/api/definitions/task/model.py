from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.deployment.model import Deployment
from styrmin_backend.api.definitions.step.model import NOT_LOADED, NotLoaded, Step
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.domain.models import StepParent
from styrmin_backend.domain.models import Task as TaskEntity
from styrmin_backend.services.exceptions import DeploymentNotFoundError
from styrmin_backend.services.steps.reads import list_steps

_NotLoaded = Literal[NotLoaded.NOT_LOADED]


@strawberry.type
class Task:
    id: UUID
    type: str
    status: str
    message: str | None = None
    deployment_id: UUID | None = None
    started_by_step_id: UUID | None = None
    created_on: datetime | None = None
    updated_on: datetime | None = None

    instance: strawberry.Private[TaskEntity]
    steps_view: strawberry.Private[list[Step] | _NotLoaded] = NOT_LOADED

    @strawberry.field
    async def deployment(self, info: strawberry.Info) -> Deployment | None:
        if self.deployment_id is None:
            return None
        return await resolve_related(
            info,
            "deployments",
            self.deployment_id,
            Deployment,
            DeploymentNotFoundError,
            method="find",
        )

    @strawberry.field(
        description="The steps of the task by start time, pending steps last."
    )
    async def steps(self, info: strawberry.Info) -> list[Step]:
        if self.steps_view is not NOT_LOADED:
            return self.steps_view
        steps = await list_steps(StepParent.of_task(self.id), uow=info.context["uow"])
        return [Step.from_instance(step) for step in steps]

    @classmethod
    def from_instance(
        cls,
        instance: TaskEntity,
        *,
        steps: list[Step] | _NotLoaded = NOT_LOADED,
    ) -> Task:
        """Build the type; a read model passes the steps it loaded for many tasks."""
        return cls(
            id=instance.id,
            type=instance.type,
            status=instance.status,
            instance=instance,
            deployment_id=instance.deployment_id,
            started_by_step_id=instance.started_by_step_id,
            message=instance.message,
            created_on=instance.created_on,
            updated_on=instance.updated_on,
            steps_view=steps,
        )
