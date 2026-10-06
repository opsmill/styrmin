from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.deployment.model import Deployment
from styrmin_backend.api.definitions.step.model import (
    NOT_LOADED,
    NotLoaded,
    Step,
    TaskResult,
)
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.domain.models import StepParent
from styrmin_backend.domain.models import Task as TaskEntity
from styrmin_backend.domain.models import TaskResult as TaskResultEntity
from styrmin_backend.services.exceptions import DeploymentNotFoundError
from styrmin_backend.services.steps.reads import (
    get_starting_task,
    get_tasks_started_by_task,
    list_steps,
)
from styrmin_backend.services.steps.results import get_task_result

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
    result_view: strawberry.Private[TaskResultEntity | _NotLoaded] = NOT_LOADED
    started_by_view: strawberry.Private[TaskEntity | None | _NotLoaded] = NOT_LOADED
    started_tasks_view: strawberry.Private[list[TaskEntity] | _NotLoaded] = NOT_LOADED
    #: Results a read model calculated, so the linked tasks need no query for theirs.
    task_results_view: strawberry.Private[Mapping[UUID, TaskResultEntity] | None] = None

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

    @strawberry.field(
        description=(
            "The task result, calculated from the steps of the task and of the "
            "tasks its hook steps started."
        )
    )
    async def result(self, info: strawberry.Info) -> TaskResult:
        if self.result_view is not NOT_LOADED:
            return self.result_view
        return await get_task_result(self.instance, uow=info.context["uow"])

    @strawberry.field(description="The task whose hook step started this task.")
    async def started_by(self, info: strawberry.Info) -> Task | None:
        if self.started_by_step_id is None:
            return None
        task = self.started_by_view
        if task is NOT_LOADED:
            task = await get_starting_task(self.instance, uow=info.context["uow"])
        return Task.linked(task, self.task_results_view) if task is not None else None

    @strawberry.field(description="Tasks started by this task's hook steps.")
    async def started_tasks(self, info: strawberry.Info) -> list[Task]:
        tasks = self.started_tasks_view
        if tasks is NOT_LOADED:
            tasks = await get_tasks_started_by_task(self.id, uow=info.context["uow"])
        return [Task.linked(task, self.task_results_view) for task in tasks]

    @classmethod
    def from_instance(
        cls,
        instance: TaskEntity,
        *,
        steps: list[Step] | _NotLoaded = NOT_LOADED,
        result: TaskResultEntity | _NotLoaded = NOT_LOADED,
        started_by: TaskEntity | None | _NotLoaded = NOT_LOADED,
        started_tasks: list[TaskEntity] | _NotLoaded = NOT_LOADED,
        task_results: Mapping[UUID, TaskResultEntity] | None = None,
    ) -> Task:
        """Build the type; a read model passes the views it loaded for many tasks."""
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
            result_view=result,
            started_by_view=started_by,
            started_tasks_view=started_tasks,
            task_results_view=task_results,
        )

    @classmethod
    def linked(
        cls,
        instance: TaskEntity,
        task_results: Mapping[UUID, TaskResultEntity] | None,
    ) -> Task:
        """A task that another task or a step links to, with its known result."""
        result = (
            task_results.get(instance.id, NOT_LOADED) if task_results else NOT_LOADED
        )
        return cls.from_instance(instance, result=result, task_results=task_results)
