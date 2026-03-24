"""Environment resource operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.models.environment import Environment
from styrmin_sdk.resources._base import BaseResource, JsonValue


class EnvironmentResource(BaseResource):
    async def create(self, name: str, cluster_id: str | UUID, config: JsonValue | None = None) -> Environment:
        variables: dict[str, Any] = {"name": name, "clusterId": str(cluster_id)}
        if config is not None:
            variables["config"] = config

        result = await self._transport.execute(load_query("create_environment"), variables)
        self._check_graphql_errors(result)
        return Environment.model_validate(result["data"]["createEnvironment"])

    async def list(self) -> list[Environment]:
        result = await self._transport.execute(load_query("list_environments"))
        self._check_graphql_errors(result)
        return [Environment.model_validate(e) for e in result["data"].get("environments", [])]

    async def get(self, environment_id: str | UUID) -> Environment:
        result = await self._transport.execute(load_query("get_environment"), {"environmentId": str(environment_id)})
        self._check_graphql_errors(result)
        return Environment.model_validate(result["data"]["environment"])

    async def delete(self, environment_id: str | UUID) -> None:
        result = await self._transport.execute(load_query("delete_environment"), {"environmentId": str(environment_id)})
        self._check_graphql_errors(result)
