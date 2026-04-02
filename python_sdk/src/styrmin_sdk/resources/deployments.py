"""Deployment resource operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.deploy import Deploy, DeployDeploy
from styrmin_sdk.graphql._generated.get_deployment import GetDeployment, GetDeploymentDeployment
from styrmin_sdk.graphql._generated.run_job import RunJob, RunJobRunJob
from styrmin_sdk.graphql._generated.start_components import StartComponents, StartComponentsStartComponents
from styrmin_sdk.graphql._generated.stop_components import StopComponents, StopComponentsStopComponents
from styrmin_sdk.graphql._generated.update_deployment import UpdateDeployment, UpdateDeploymentUpdateDeployment
from styrmin_sdk.graphql._generated.update_deployment_version import (
    UpdateDeploymentVersion,
    UpdateDeploymentVersionUpdateDeploymentVersion,
)
from styrmin_sdk.models.context import Context
from styrmin_sdk.resources._base import BaseResource, JsonValue


class DeploymentResource(BaseResource):
    async def create(
        self,
        driver: str,
        version: str,
        environment_id: str | UUID | None = None,
        *,
        environment_name: str | None = None,
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
        name: str | None = None,
        config: JsonValue | None = None,
        parameters: JsonValue | None = None,
        service_name_overrides: list[dict[str, str]] | None = None,
    ) -> DeployDeploy:
        variables: dict[str, Any] = {
            "driver": driver,
            "version": version,
        }
        if environment_id is not None:
            variables["environmentId"] = str(environment_id)
        if environment_name is not None:
            variables["environmentName"] = environment_name
        if cluster_id is not None:
            variables["clusterId"] = str(cluster_id)
        if cluster_name is not None:
            variables["clusterName"] = cluster_name
        if name is not None:
            variables["name"] = name
        if config is not None:
            variables["config"] = config
        if parameters is not None:
            variables["parameters"] = parameters
        if service_name_overrides is not None:
            variables["serviceNameOverrides"] = service_name_overrides

        result = await self._transport.execute(load_query("deploy"), variables)
        self._check_graphql_errors(result)
        return self._parse(Deploy, result["data"], "deploy", DeployDeploy)

    async def get(self, deployment_id: str | UUID) -> GetDeploymentDeployment:
        result = await self._transport.execute(load_query("get_deployment"), {"deploymentId": str(deployment_id)})
        self._check_graphql_errors(result)
        return self._parse(GetDeployment, result["data"], "deployment", GetDeploymentDeployment)

    async def update(
        self,
        deployment_id: str | UUID,
        *,
        name: str | None = None,
        config: JsonValue | None = None,
        parameters: JsonValue | None = None,
        service_name_overrides: list[dict[str, str]] | None = None,
    ) -> UpdateDeploymentUpdateDeployment:
        variables: dict[str, Any] = {"deploymentId": str(deployment_id)}
        if name is not None:
            variables["name"] = name
        if config is not None:
            variables["config"] = config
        if parameters is not None:
            variables["parameters"] = parameters
        if service_name_overrides is not None:
            variables["serviceNameOverrides"] = service_name_overrides
        result = await self._transport.execute(
            load_query("update_deployment"),
            variables,
        )
        self._check_graphql_errors(result)
        return self._parse(UpdateDeployment, result["data"], "update_deployment", UpdateDeploymentUpdateDeployment)

    async def update_version(
        self, deployment_id: str | UUID, version: str
    ) -> UpdateDeploymentVersionUpdateDeploymentVersion:
        result = await self._transport.execute(
            load_query("update_version"),
            {"deploymentId": str(deployment_id), "version": version},
        )
        self._check_graphql_errors(result)
        return self._parse(
            UpdateDeploymentVersion,
            result["data"],
            "update_deployment_version",
            UpdateDeploymentVersionUpdateDeploymentVersion,
        )

    async def start_components(
        self, deployment_id: str | UUID, components: list[str]
    ) -> StartComponentsStartComponents:
        result = await self._transport.execute(
            load_query("start_components"),
            {"deploymentId": str(deployment_id), "components": components},
        )
        self._check_graphql_errors(result)
        return self._parse(StartComponents, result["data"], "start_components", StartComponentsStartComponents)

    async def stop_components(self, deployment_id: str | UUID, components: list[str]) -> StopComponentsStopComponents:
        result = await self._transport.execute(
            load_query("stop_components"),
            {"deploymentId": str(deployment_id), "components": components},
        )
        self._check_graphql_errors(result)
        return self._parse(StopComponents, result["data"], "stop_components", StopComponentsStopComponents)

    async def run_job(
        self,
        deployment_id: str | UUID,
        image: str,
        commands: list[str],
        env: JsonValue,
    ) -> RunJobRunJob:
        result = await self._transport.execute(
            load_query("run_job"),
            {
                "deploymentId": str(deployment_id),
                "commands": commands,
                "image": image,
                "env": env,
            },
        )
        self._check_graphql_errors(result)
        return self._parse(RunJob, result["data"], "run_job", RunJobRunJob)

    async def get_context(self, deployment_id: str | UUID) -> Context:
        data = await self._transport.get(f"/deployments/{deployment_id}/context")
        return Context.model_validate({"context": data})
