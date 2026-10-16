"""Cluster resource operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from styrmin_sdk._input_checks import to_graphql_enum_names, validate_input_strict
from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.create_cluster import CreateCluster, CreateClusterCreateCluster
from styrmin_sdk.graphql._generated.get_cluster import GetCluster, GetClusterCluster
from styrmin_sdk.graphql._generated.input_types import UpdateClusterInput
from styrmin_sdk.graphql._generated.list_clusters import ListClusters, ListClustersClusters
from styrmin_sdk.graphql._generated.update_cluster import UpdateCluster, UpdateClusterUpdateCluster
from styrmin_sdk.resources._base import BaseResource, JsonValue

#: The server starts one redeploy per changed deployment before it answers.
UPDATE_CLUSTER_TIMEOUT_SECONDS = 600.0


def cluster_update_input(config: Mapping[str, Any]) -> dict[str, Any]:
    """Check a cluster config and return it as the ``UpdateClusterInput`` variables.

    Accepts snake_case or camelCase keys, and the stored enum values that ``get()``
    returns (``http``, ``NodeExternalIP``) as well as the GraphQL names.

    Raises:
        ValueError: If a key, at any depth, is not a field of ``UpdateClusterInput``.
        pydantic.ValidationError: If a value has the wrong type.
    """
    if not isinstance(config, Mapping):
        raise TypeError(f"config must be a mapping, got {type(config).__name__}")
    data = dict(config)
    validate_input_strict(UpdateClusterInput, data)
    update_input = UpdateClusterInput.model_validate(to_graphql_enum_names(UpdateClusterInput, data))
    return update_input.model_dump(by_alias=True, exclude_none=True, mode="json")


class ClusterResource(BaseResource):
    async def create(self, name: str, config: JsonValue | None = None) -> CreateClusterCreateCluster:
        variables: dict[str, Any] = {"name": name}
        if config is not None:
            variables["config"] = config

        result = await self._transport.execute(load_query("create_cluster"), variables)
        self._check_graphql_errors(result)
        return self._parse(CreateCluster, result["data"], "create_cluster", CreateClusterCreateCluster)

    async def list(self) -> list[ListClustersClusters]:
        result = await self._transport.execute(load_query("list_clusters"))
        self._check_graphql_errors(result)
        data = ListClusters.model_validate(result["data"])
        return data.clusters or []

    async def get(
        self,
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
    ) -> GetClusterCluster:
        variables: dict[str, Any] = {}
        if cluster_id is not None:
            variables["clusterId"] = str(cluster_id)
        if cluster_name is not None:
            variables["clusterName"] = cluster_name
        result = await self._transport.execute(load_query("get_cluster"), variables)
        self._check_graphql_errors(result)
        return self._parse(GetCluster, result["data"], "cluster", GetClusterCluster)

    async def update(
        self,
        config: Mapping[str, Any],
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
        *,
        dry_run: bool = False,
    ) -> UpdateClusterUpdateCluster:
        """Replace a cluster's config and return the deployments the update redeploys.

        Full replacement: a key left out, or set to ``None``, is removed from the
        stored config. The config is checked by :func:`cluster_update_input` before
        any request, so a misspelled key is refused instead of being dropped. With
        ``dry_run``, nothing is saved and the result lists what saving would do.
        Pass exactly one of ``cluster_id`` and ``cluster_name``.
        """
        variables: dict[str, Any] = {"input": cluster_update_input(config), "dryRun": dry_run}
        if cluster_id is not None:
            variables["clusterId"] = str(cluster_id)
        if cluster_name is not None:
            variables["clusterName"] = cluster_name
        result = await self._transport.execute(
            load_query("update_cluster"), variables, request_timeout=UPDATE_CLUSTER_TIMEOUT_SECONDS
        )
        self._check_graphql_errors(result)
        return self._parse(UpdateCluster, result["data"], "update_cluster", UpdateClusterUpdateCluster)

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
