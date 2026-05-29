"""Deployment resource operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.delete_deployment import (
    DeleteDeployment,
    DeleteDeploymentDeleteDeployment,
)
from styrmin_sdk.graphql._generated.deploy import Deploy, DeployDeploy
from styrmin_sdk.graphql._generated.get_deployment import GetDeployment, GetDeploymentDeployment
from styrmin_sdk.graphql._generated.get_deployment_pod_statuses import (
    GetDeploymentPodStatuses,
    GetDeploymentPodStatusesDeploymentPodStatuses,
)
from styrmin_sdk.graphql._generated.get_deployment_timeline import (
    GetDeploymentTimeline,
    GetDeploymentTimelineDeploymentTimeline,
)
from styrmin_sdk.graphql._generated.list_deployments import (
    ListDeployments,
    ListDeploymentsEnvironmentDeployments,
)
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

if TYPE_CHECKING:
    from styrmin_sdk.graphql._generated.input_types import UpdateDeploymentInput


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

    async def list(
        self,
        environment_id: str | UUID,
        *,
        include_deleted: bool = False,
    ) -> list[ListDeploymentsEnvironmentDeployments]:
        """List the deployments belonging to an environment.

        Each entry carries the deployment's active application instance
        (``application_instance``), or ``None`` when the deployment has no
        active instance yet.
        """
        result = await self._transport.execute(
            load_query("list_deployments"),
            {"environmentId": str(environment_id), "includeDeleted": include_deleted},
        )
        self._check_graphql_errors(result)
        validated = ListDeployments.model_validate(result["data"])
        return validated.environment.deployments if validated.environment else []

    async def update(
        self,
        deployment_id: str | UUID,
        *,
        input: UpdateDeploymentInput,
    ) -> UpdateDeploymentUpdateDeployment:
        """Update a deployment with a typed ``UpdateDeploymentInput``.

        ``input`` is the regenerated Pydantic model that mirrors the GraphQL
        ``UpdateDeploymentInput`` input type. Top-level fields use
        full-replacement semantics: any field omitted (``None``) leaves the
        corresponding persisted state untouched; an empty list/dict explicitly
        clears it. The single exception is ``parameters``, which uses merge
        semantics — entries in the list merge on top of the persisted
        parameters dict.
        """
        variables: dict[str, Any] = {
            "deploymentId": str(deployment_id),
            "input": input.model_dump(by_alias=True, exclude_none=True),
        }
        result = await self._transport.execute(
            load_query("update_deployment"),
            variables,
        )
        self._check_graphql_errors(result)
        return self._parse(UpdateDeployment, result["data"], "update_deployment", UpdateDeploymentUpdateDeployment)

    async def delete(self, deployment_id: str | UUID) -> DeleteDeploymentDeleteDeployment:
        """Request deletion of a deployment.

        Patches the cluster-side StyrminDeployment CR to flip
        ``spec.deletionRequested`` to ``true``. Returns immediately
        with a born-complete ``DELETE_DEPLOYMENT`` task — poll
        ``Deployment.status`` to observe the lifecycle's
        ``DELETING -> DELETED`` progression.

        Idempotent: a second call against an already-DELETING
        deployment returns the existing in-flight task without
        duplicating side effects.

        Raises:
            ResourceNotFoundError: id is unknown OR the deployment is
                already DELETED (intentional conflation with unknown
                id; check ``error_code == "NOT_FOUND"`` to distinguish
                from a transport-level 404).
            DeploymentRestoringError: a restore is in progress on this
                deployment; deletion is refused for data-integrity
                reasons.
        """
        result = await self._transport.execute(
            load_query("delete_deployment"),
            {"deploymentId": str(deployment_id)},
        )
        self._check_graphql_errors(result)
        return self._parse(
            DeleteDeployment,
            result["data"],
            "delete_deployment",
            DeleteDeploymentDeleteDeployment,
        )

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

    async def get_timeline(self, deployment_id: str | UUID) -> list[GetDeploymentTimelineDeploymentTimeline]:
        result = await self._transport.execute(
            load_query("get_deployment_timeline"),
            {"deploymentId": str(deployment_id)},
        )
        self._check_graphql_errors(result)
        validated = GetDeploymentTimeline.model_validate(result["data"])
        return validated.deployment_timeline

    async def get_context(self, deployment_id: str | UUID) -> Context:
        data = await self._transport.get(f"/deployments/{deployment_id}/context")
        return Context.model_validate({"context": data})

    async def get_pod_statuses(self, deployment_id: str | UUID) -> list[GetDeploymentPodStatusesDeploymentPodStatuses]:
        result = await self._transport.execute(
            load_query("get_deployment_pod_statuses"),
            {"deploymentId": str(deployment_id)},
        )
        self._check_graphql_errors(result)
        validated = GetDeploymentPodStatuses.model_validate(result["data"])
        return validated.deployment.pod_statuses if validated.deployment else []
