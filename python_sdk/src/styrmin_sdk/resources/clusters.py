"""Cluster resource operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.models.cluster import Cluster
from styrmin_sdk.resources._base import BaseResource, JsonValue


class ClusterResource(BaseResource):
    async def create(self, name: str, config: JsonValue | None = None) -> Cluster:
        variables: dict[str, Any] = {"name": name}
        if config is not None:
            variables["config"] = config

        result = await self._transport.execute(load_query("create_cluster"), variables)
        self._check_graphql_errors(result)
        return Cluster.model_validate(result["data"]["createCluster"])

    async def list(self) -> list[Cluster]:
        result = await self._transport.execute(load_query("list_clusters"))
        self._check_graphql_errors(result)
        return [Cluster.model_validate(c) for c in result["data"].get("clusters", [])]

    async def get(
        self,
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
    ) -> Cluster:
        variables: dict[str, Any] = {}
        if cluster_id is not None:
            variables["clusterId"] = str(cluster_id)
        if cluster_name is not None:
            variables["clusterName"] = cluster_name
        result = await self._transport.execute(load_query("get_cluster"), variables)
        self._check_graphql_errors(result)
        return Cluster.model_validate(result["data"]["cluster"])

    async def delete(
        self,
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
    ) -> None:
        variables: dict[str, Any] = {}
        if cluster_id is not None:
            variables["clusterId"] = str(cluster_id)
        if cluster_name is not None:
            variables["clusterName"] = cluster_name
        result = await self._transport.execute(load_query("delete_cluster"), variables)
        self._check_graphql_errors(result)
