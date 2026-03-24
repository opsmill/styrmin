"""Task resource operations."""

from __future__ import annotations

from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.models.task import Task
from styrmin_sdk.resources._base import BaseResource


class TaskResource(BaseResource):
    async def list(self) -> list[Task]:
        result = await self._transport.execute(load_query("list_tasks"))
        self._check_graphql_errors(result)
        return [Task.model_validate(t) for t in result["data"].get("tasks", [])]

    async def get(self, task_id: str | UUID) -> Task:
        result = await self._transport.execute(load_query("get_task"), {"taskId": str(task_id)})
        self._check_graphql_errors(result)
        return Task.model_validate(result["data"]["task"])
