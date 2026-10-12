"""Provides the cluster config fan-out (021-cluster-config-update, research D1 and D7).

After a cluster's config is saved, every live, non-internal deployment of every
environment of the cluster whose resolved config differs from the resolved
config of its active instance is redeployed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, ValidationError

from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.resolvers import resolve_instance_config
from styrmin_backend.services.deployment import redeploy_for_environment_update
from styrmin_backend.services.exceptions import ServiceError

if TYPE_CHECKING:
    from uuid import UUID

    from styrmin_backend.db.models import Cluster, Environment
    from styrmin_backend.domain.models import Deployment
    from styrmin_backend.services.unit_of_work import UnitOfWork


@dataclass
class FanOutCounts:
    """What one fan-out did, logged once per run (data-model §6)."""

    environments: int = 0
    evaluated: int = 0
    dispatched: int = 0
    skipped_noop: int = 0
    skipped_restoring: int = 0
    skipped_waiting_for_ingress: int = 0
    dispatch_failed: int = 0
    ingress_controllers_created: int = 0
    ingress_controllers_redeployed: int = 0
    ingress_controllers_removed: int = 0


def _canonical(config: Any) -> dict[str, Any]:
    """Normalize a resolved config so that ``None`` and missing keys compare equal."""
    if isinstance(config, BaseModel):
        config = config.model_dump(mode="json")
    return ResolvedConfig.model_validate(config).model_dump(
        exclude_none=True, mode="json"
    )


def _deployment_at_resolved_config(
    deployment: Deployment,
    cluster_config: ClusterConfig,
    environment_config: EnvironmentConfig,
) -> bool:
    """Return True when the active instance was rendered with the config the deployment resolves to now.

    A deployment without an active instance, or whose stored resolved config no
    longer validates, is not at config and gets redeployed.
    """
    active = deployment.active_instance
    if active is None:
        return False
    try:
        stored = _canonical(active.context.instance.config)
    except ValidationError, ServiceError:
        return False
    desired = resolve_instance_config(
        cluster=cluster_config,
        environment=environment_config,
        deployment=DeploymentConfig.model_validate(deployment.config or {}),
    )
    return _canonical(desired) == stored


def _waits_for_ingress_controller(
    deployment: Deployment,  # noqa: ARG001
    cluster_config: ClusterConfig,  # noqa: ARG001
    environment_config: EnvironmentConfig,  # noqa: ARG001
) -> bool:
    """Return True when the application must wait until its dedicated ingress controller is ready.

    Seam for the dedicated ingress ordering (research D4). It is not applied yet, so no application waits.
    """
    return False


async def _redeploy_application(
    deployment: Deployment,
    cluster_config: ClusterConfig,
    environment_config: EnvironmentConfig,
    uow: UnitOfWork,
    counts: FanOutCounts,
) -> None:
    """Redeploy one application unless it is already at config, and count the outcome."""
    try:
        if _deployment_at_resolved_config(
            deployment, cluster_config, environment_config
        ):
            counts.skipped_noop += 1
            return
        if _waits_for_ingress_controller(
            deployment, cluster_config, environment_config
        ):
            counts.skipped_waiting_for_ingress += 1
            return
        task = await redeploy_for_environment_update(deployment, uow)
    except Exception:  # noqa: BLE001 — one deployment must not stop the others (FR-002)
        counts.dispatch_failed += 1
        logger.exception(
            "cluster_config_fanout_dispatch_error environment_id={} deployment_id={}",
            deployment.environment_id,
            deployment.id,
        )
        return
    if task is None:
        # Only a RESTORING deployment returns None; the restore owns its namespace.
        counts.skipped_restoring += 1
        return
    counts.dispatched += 1


async def _fan_out_environment(
    environment: Environment,
    cluster_config: ClusterConfig,
    uow: UnitOfWork,
    counts: FanOutCounts,
) -> None:
    """Redeploy the applications of one environment that are not at their resolved config."""
    environment_config = EnvironmentConfig.model_validate(environment.config or {})
    counts.environments += 1
    for deployment in await uow.deployments.find_all_by_environment(environment.id):
        if deployment.deleted_at is not None:
            continue
        counts.evaluated += 1
        if deployment.internal:
            continue
        await _redeploy_application(
            deployment, cluster_config, environment_config, uow, counts
        )


async def fan_out_cluster_config(
    cluster: Cluster,
    uow: UnitOfWork,
    acting_user_id: UUID,  # noqa: ARG001
) -> FanOutCounts:
    """Redeploy every deployment of the cluster whose resolved config changed (research D1, D7).

    The caller commits the cluster row first (FR-001). ``acting_user_id`` is the
    administrator who submitted the config; it is reserved for attributing the
    dedicated ingress controllers that the fan-out creates (research D4).
    """
    counts = FanOutCounts()
    async with uow:
        cluster_config = ClusterConfig.model_validate(cluster.config or {})
        environments = [
            env
            for env in await uow.environments.get_all()
            if env.cluster_id == cluster.id
        ]
        for environment in environments:
            await _fan_out_environment(environment, cluster_config, uow, counts)
        await uow.commit()

    logger.info(
        "cluster_config_fanout cluster_id={} environments={} evaluated={} dispatched={} "
        "skipped_noop={} skipped_restoring={} skipped_waiting_for_ingress={} dispatch_failed={} "
        "ingress_controllers_created={} ingress_controllers_redeployed={} ingress_controllers_removed={}",
        cluster.id,
        counts.environments,
        counts.evaluated,
        counts.dispatched,
        counts.skipped_noop,
        counts.skipped_restoring,
        counts.skipped_waiting_for_ingress,
        counts.dispatch_failed,
        counts.ingress_controllers_created,
        counts.ingress_controllers_redeployed,
        counts.ingress_controllers_removed,
    )
    return counts
