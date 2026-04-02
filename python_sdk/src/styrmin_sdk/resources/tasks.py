"""Task resource operations."""

from __future__ import annotations

from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.get_task import GetTask, GetTaskTask
from styrmin_sdk.graphql._generated.list_tasks import ListTasks, ListTasksTasks
from styrmin_sdk.resources._base import BaseResource


class TaskResource(BaseResource):
    async def list(self) -> list[ListTasksTasks]:
        result = await self._transport.execute(load_query("list_tasks"))
        self._check_graphql_errors(result)
        data = ListTasks.model_validate(result["data"])
        return data.tasks or []

    async def get(self, task_id: str | UUID) -> GetTaskTask:
        result = await self._transport.execute(load_query("get_task"), {"taskId": str(task_id)})
        self._check_graphql_errors(result)
        return self._parse(GetTask, result["data"], "task")
