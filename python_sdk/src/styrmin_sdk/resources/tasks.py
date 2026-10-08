"""Task resource operations."""

from __future__ import annotations

from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.enums import StepStatus
from styrmin_sdk.graphql._generated.get_step_output import GetStepOutput, GetStepOutputStep
from styrmin_sdk.graphql._generated.get_task import GetTask, GetTaskTask
from styrmin_sdk.graphql._generated.list_tasks import ListTasks, ListTasksTasks
from styrmin_sdk.models.task import FailedStep
from styrmin_sdk.resources._base import BaseResource


class TaskResource(BaseResource):
    async def list(self) -> list[ListTasksTasks]:
        result = await self._transport.execute(load_query("list_tasks"))
        self._check_graphql_errors(result)
        data = ListTasks.model_validate(result["data"])
        return data.tasks or []

    async def get(self, task_id: str | UUID) -> GetTaskTask:
        """Read a task with its result, its steps and the tasks its hook steps started."""
        result = await self._transport.execute(load_query("get_task"), {"taskId": str(task_id)})
        self._check_graphql_errors(result)
        return self._parse(GetTask, result["data"], "task", GetTaskTask)

    async def step_output(self, step_id: str | UUID) -> GetStepOutputStep:
        """Read the end of a failed command's output for one step.

        ``get()`` returns only ``has_output`` for each step; the output is read one step at a time.
        """
        result = await self._transport.execute(load_query("get_step_output"), {"stepId": str(step_id)})
        self._check_graphql_errors(result)
        return self._parse(GetStepOutput, result["data"], "step", GetStepOutputStep)

    async def failed_step(self, task_id: str | UUID) -> FailedStep | None:
        """Return the first failed step of the task, else of the tasks it started, nearest first.

        Reads the task, then each started task breadth-first; returns ``None``
        when no step of these tasks has failed.
        """
        queue = [str(task_id)]
        while queue:
            task = await self.get(queue.pop(0))
            step = next((step for step in task.steps if step.status == StepStatus.FAILED), None)
            if step is not None:
                return FailedStep(name=step.name, task_id=task.id, error=step.error)
            queue.extend(str(started.id) for started in task.started_tasks)
        return None
