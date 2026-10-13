"""Strawberry result types of the ``updateCluster`` mutation (021-cluster-config-update)."""

from __future__ import annotations

from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.cluster.model import Cluster
from styrmin_backend.services.cluster_config_fanout import (
    ControllerAction,
    FanOutDeployment,
    FanOutEnvironment,
    FanOutIngressController,
)
from styrmin_backend.services.clusters import ClusterUpdateResult

IngressControllerAction = strawberry.enum(
    ControllerAction,
    name="IngressControllerAction",
    description=(
        "What a cluster update does to an environment's dedicated ingress controller. "
        "REMOVE is requested once no application of the environment uses the controller."
    ),
)


@strawberry.type(
    description="A deployment that a cluster update redeploys, leaves waiting, skips or could not start."
)
class UpdateClusterDeployment:
    deployment_id: UUID
    deployment_name: str
    environment_id: UUID
    environment_name: str
    task_id: UUID | None = strawberry.field(
        description="The update_instance task of the redeploy. Null in a dry run and when the redeploy did not start."
    )

    @classmethod
    def from_fan_out(cls, entry: FanOutDeployment) -> UpdateClusterDeployment:
        return cls(
            deployment_id=entry.deployment_id,
            deployment_name=entry.deployment_name,
            environment_id=entry.environment_id,
            environment_name=entry.environment_name,
            task_id=entry.task_id,
        )


@strawberry.type(
    description="An action of a cluster update on an environment's dedicated ingress controller."
)
class UpdateClusterIngressController:
    environment_id: UUID
    environment_name: str
    action: IngressControllerAction  # type: ignore[valid-type]
    failed: bool = strawberry.field(
        description="The controller could not be created or redeployed. Its applications wait."
    )

    @classmethod
    def from_fan_out(
        cls, entry: FanOutIngressController
    ) -> UpdateClusterIngressController:
        return cls(
            environment_id=entry.environment_id,
            environment_name=entry.environment_name,
            action=entry.action,
            failed=entry.failed,
        )


@strawberry.type(
    description="An environment whose evaluation failed; none of its deployments was redeployed."
)
class UpdateClusterEnvironment:
    environment_id: UUID
    environment_name: str

    @classmethod
    def from_fan_out(cls, entry: FanOutEnvironment) -> UpdateClusterEnvironment:
        return cls(
            environment_id=entry.environment_id,
            environment_name=entry.environment_name,
        )


@strawberry.type(
    description=(
        "The cluster after an update, and the deployments the update redeploys. In a dry "
        "run, the cluster is unchanged and the lists say what saving would do."
    )
)
class UpdateClusterResult:
    cluster: Cluster
    dry_run: bool
    redeployed: list[UpdateClusterDeployment] = strawberry.field(
        description="Deployments whose redeploy started, or would start in a dry run."
    )
    waiting_for_ingress: list[UpdateClusterDeployment] = strawberry.field(
        description=(
            "Deployments that move onto a dedicated ingress controller. They are "
            "redeployed when the controller is running with the new values."
        )
    )
    skipped_restoring: list[UpdateClusterDeployment] = strawberry.field(
        description="Deployments not redeployed because a restore is running. Save again after the restore."
    )
    failed_to_start: list[UpdateClusterDeployment] = strawberry.field(
        description="Deployments whose redeploy could not start. Save again to retry them."
    )
    unchanged_count: int = strawberry.field(
        description="Deployments already at their resolved configuration."
    )
    ingress_controllers: list[UpdateClusterIngressController]
    failed_environments: list[UpdateClusterEnvironment] = strawberry.field(
        description="Environments whose evaluation failed. Save again to retry them."
    )

    @classmethod
    def from_result(cls, result: ClusterUpdateResult) -> UpdateClusterResult:
        fan_out = result.fan_out
        return cls(
            cluster=Cluster.from_instance(result.cluster),
            dry_run=result.dry_run,
            redeployed=[
                UpdateClusterDeployment.from_fan_out(e) for e in fan_out.redeployed
            ],
            waiting_for_ingress=[
                UpdateClusterDeployment.from_fan_out(e)
                for e in fan_out.waiting_for_ingress
            ],
            skipped_restoring=[
                UpdateClusterDeployment.from_fan_out(e)
                for e in fan_out.skipped_for_restore
            ],
            failed_to_start=[
                UpdateClusterDeployment.from_fan_out(e) for e in fan_out.failed_to_start
            ],
            unchanged_count=fan_out.skipped_noop,
            ingress_controllers=[
                UpdateClusterIngressController.from_fan_out(e)
                for e in fan_out.ingress_controllers
            ],
            failed_environments=[
                UpdateClusterEnvironment.from_fan_out(e)
                for e in fan_out.failed_environments
            ],
        )
