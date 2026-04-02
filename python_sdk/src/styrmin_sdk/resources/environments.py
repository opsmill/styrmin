"""Environment resource operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.create_environment import (
    CreateEnvironment,
    CreateEnvironmentCreateEnvironment,
)
from styrmin_sdk.graphql._generated.get_environment import GetEnvironment, GetEnvironmentEnvironment
from styrmin_sdk.graphql._generated.list_environments import ListEnvironments, ListEnvironmentsEnvironments
from styrmin_sdk.resources._base import BaseResource, JsonValue


class EnvironmentResource(BaseResource):
    async def create(
        self,
        name: str,
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
        config: JsonValue | None = None,
    ) -> CreateEnvironmentCreateEnvironment:
        variables: dict[str, Any] = {"name": name}
        if cluster_id is not None:
            variables["clusterId"] = str(cluster_id)
        if cluster_name is not None:
            variables["clusterName"] = cluster_name
        if config is not None:
            variables["config"] = config

        result = await self._transport.execute(load_query("create_environment"), variables)
        self._check_graphql_errors(result)
        return self._parse(CreateEnvironment, result["data"], "create_environment")

    async def list(self) -> list[ListEnvironmentsEnvironments]:
        result = await self._transport.execute(load_query("list_environments"))
        self._check_graphql_errors(result)
        data = ListEnvironments.model_validate(result["data"])
        return data.environments or []

    async def get(
        self,
        environment_id: str | UUID | None = None,
        environment_name: str | None = None,
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
    ) -> GetEnvironmentEnvironment:
        variables: dict[str, Any] = {}
        if environment_id is not None:
            variables["environmentId"] = str(environment_id)
        if environment_name is not None:
            variables["environmentName"] = environment_name
        if cluster_id is not None:
            variables["clusterId"] = str(cluster_id)
        if cluster_name is not None:
            variables["clusterName"] = cluster_name
        result = await self._transport.execute(load_query("get_environment"), variables)
        self._check_graphql_errors(result)
        return self._parse(GetEnvironment, result["data"], "environment")

    async def delete(
        self,
        environment_id: str | UUID | None = None,
        environment_name: str | None = None,
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
    ) -> None:
        variables: dict[str, Any] = {}
        if environment_id is not None:
            variables["environmentId"] = str(environment_id)
        if environment_name is not None:
            variables["environmentName"] = environment_name
        if cluster_id is not None:
            variables["clusterId"] = str(cluster_id)
        if cluster_name is not None:
            variables["clusterName"] = cluster_name
        result = await self._transport.execute(load_query("delete_environment"), variables)
        self._check_graphql_errors(result)
