"""Environment resource operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.create_environment import (
    CreateEnvironment,
    CreateEnvironmentCreateEnvironment,
)
from styrmin_sdk.graphql._generated.get_environment import GetEnvironment, GetEnvironmentEnvironment
from styrmin_sdk.graphql._generated.get_environment_services import GetEnvironmentServices
from styrmin_sdk.graphql._generated.get_pod_statuses import GetPodStatuses
from styrmin_sdk.graphql._generated.list_environments import ListEnvironments, ListEnvironmentsEnvironments
from styrmin_sdk.resources._base import BaseResource, JsonValue

if TYPE_CHECKING:
    from styrmin_sdk.graphql._generated.input_types import UpdateEnvironmentInput
    from styrmin_sdk.models import DeployedService, PodStatus


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
        return self._parse(CreateEnvironment, result["data"], "create_environment", CreateEnvironmentCreateEnvironment)

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
        return self._parse(GetEnvironment, result["data"], "environment", GetEnvironmentEnvironment)

    async def get_pod_statuses(
        self,
        environment_id: str | UUID | None = None,
        environment_name: str | None = None,
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
    ) -> list[PodStatus]:
        """Read the pod statuses of every deployment of an environment.

        Takes the same arguments as :meth:`get`: the environment's ID, or its name with
        the ID or name of its cluster. The method reads the environment first, so an
        unknown ID or name raises ``ResourceNotFoundError``.

        - Internal deployments, such as the ingress controller of a dedicated ingress,
          are included. ``deployments.list(environment_id, include_internal=True)``
          lists them.
        - Deleted deployments are left out.
        - The order of the list is not fixed.
        - The agent reports pods about every 5 seconds, so a pod can be up to one report
          old, and a pod that started since the last report is missing. A new
          environment, such as a clone right after its restore, can return an empty
          list. ``all(pod.ready for pod in pods)`` is also true for an empty list, and the pod
          of a finished job, in the ``SUCCEEDED`` phase, is never ready.
        """
        environment = await self.get(environment_id, environment_name, cluster_id, cluster_name)
        result = await self._transport.execute(
            load_query("get_pod_statuses"),
            {"environmentId": str(environment.id)},
        )
        self._check_graphql_errors(result)
        return GetPodStatuses.model_validate(result["data"]).pod_statuses

    async def get_services(
        self,
        environment_id: str | UUID | None = None,
        environment_name: str | None = None,
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
    ) -> list[DeployedService]:
        """Read the services of every deployment of an environment.

        Takes the same arguments as :meth:`get`: the environment's ID, or its name with
        the ID or name of its cluster. The method reads the environment first, so an
        unknown ID or name raises ``ResourceNotFoundError``.

        - ``resolved_name`` is the name by which the other deployments of the
          environment connect to the service: the service name that the driver
          declares, or the deployment's service name override.
        - Internal deployments, such as the ingress controller of a dedicated ingress,
          are included. ``deployments.list(environment_id, include_internal=True)``
          lists them.
        - Deleted deployments are left out.
        - The services have no URL or FQDN. ``deployments.get()`` returns them in
          ``deployed_services``.
        - The order of the list is not fixed.
        """
        environment = await self.get(environment_id, environment_name, cluster_id, cluster_name)
        result = await self._transport.execute(
            load_query("get_environment_services"),
            {"environmentId": str(environment.id)},
        )
        self._check_graphql_errors(result)
        return GetEnvironmentServices.model_validate(result["data"]).environment_services

    async def update(
        self,
        environment_id: str | UUID,
        input: UpdateEnvironmentInput,
    ) -> JsonValue:
        """Update an environment's config with a typed ``UpdateEnvironmentInput``.

        ``input`` is the regenerated Pydantic model that mirrors the
        GraphQL ``UpdateEnvironmentInput`` input type. Pass-through to
        ``Mutation.updateEnvironment`` (009-environment-update / US2);
        full-replacement semantics — any field omitted (``None``) is
        persisted as the unset state on the underlying ``EnvironmentConfig``.
        """
        variables: dict[str, Any] = {
            "environmentId": str(environment_id),
            "input": input.model_dump(by_alias=True, exclude_none=True),
        }
        result = await self._transport.execute(load_query("update_environment"), variables)
        self._check_graphql_errors(result)
        return (result.get("data") or {}).get("updateEnvironment")

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
