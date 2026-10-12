"""Provides the cluster config fan-out (021-cluster-config-update, research D1, D4, D5 and D7).

After a cluster's config is saved, every live, non-internal deployment of every
environment of the cluster whose resolved config differs from the resolved
config of its active instance is redeployed. The redeploys are ordered around
each environment's dedicated ingress controller, and the status reporter
continues the fan-out of an environment once its controller is ready.

Each environment, each redeploy and each controller action runs in its own
savepoint, so a failure rolls back and counts only that unit (FR-002).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, ValidationError

from styrmin_backend.context.models.config import (
    ClusterConfig,
    DedicatedIngressConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.resolvers import resolve_instance_config
from styrmin_backend.domain.models import DeploymentState
from styrmin_backend.services.deployment import (
    _create_ingress_controller,
    _rendered_dedicated_ingress,
    redeploy_for_environment_update,
    tear_down_unused_ingress_controller,
)
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
    environments_failed: int = 0
    evaluated: int = 0
    dispatched: int = 0
    skipped_noop: int = 0
    skipped_restoring: int = 0
    skipped_waiting_for_ingress: int = 0
    dispatch_failed: int = 0
    ingress_controllers_created: int = 0
    ingress_controllers_redeployed: int = 0
    ingress_controllers_removed: int = 0

    def add(self, other: FanOutCounts) -> None:
        for name, value in asdict(other).items():
            setattr(self, name, getattr(self, name) + value)


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


def _effective_dedicated_ingress(
    environment_config: EnvironmentConfig, cluster_config: ClusterConfig
) -> DedicatedIngressConfig | None:
    """The environment's own ``dedicated_ingress``, else the cluster's (data-model §3)."""
    if environment_config.dedicated_ingress is not None:
        return environment_config.dedicated_ingress
    return cluster_config.dedicated_ingress


def _ingress_values(value: DedicatedIngressConfig | None) -> dict[str, Any] | None:
    return None if value is None else value.model_dump(exclude_none=True, mode="json")


def _rendered_ingress_values(deployment: Deployment) -> dict[str, Any] | None:
    return _ingress_values(_rendered_dedicated_ingress(deployment))


async def _apply_controller_action(
    environment_id: UUID,
    controller: Deployment | None,
    target: dict[str, Any] | None,
    *,
    has_applications: bool,
    has_waiting_applications: bool,
    acting_user_id: UUID | None,
    uow: UnitOfWork,
    counts: FanOutCounts,
) -> Deployment | None:
    """Create or redeploy the environment's dedicated ingress controller (research D4).

    Without an acting user (the status reporter continuation) no controller is
    created. Turning the value off leaves the removal to the removal check (D5).
    """
    if target is None:
        return controller
    if controller is None:
        if not has_applications or acting_user_id is None:
            return None
        try:
            async with uow.session.begin_nested():
                created = await _create_ingress_controller(
                    environment_id, uow, acting_user_id
                )
        except Exception:  # noqa: BLE001 — the applications wait for a controller that failed to start
            _count_controller_failure(environment_id, counts)
            return None
        counts.ingress_controllers_created += 1
        return created
    if controller.status == DeploymentState.DELETING:
        return controller
    values_changed = _rendered_ingress_values(controller) != target
    retry_failed = (
        controller.status == DeploymentState.FAILED and has_waiting_applications
    )
    if not (values_changed or retry_failed):
        return controller
    try:
        async with uow.session.begin_nested():
            task = await redeploy_for_environment_update(controller, uow)
    except Exception:  # noqa: BLE001 — the applications wait for a controller that failed to start
        _count_controller_failure(environment_id, counts)
        return controller
    if task is not None:
        counts.ingress_controllers_redeployed += 1
    return controller


def _count_controller_failure(environment_id: UUID, counts: FanOutCounts) -> None:
    counts.dispatch_failed += 1
    logger.exception(
        "cluster_config_fanout_ingress_controller_error environment_id={}",
        environment_id,
    )


async def _redeploy_application(
    deployment: Deployment, uow: UnitOfWork, counts: FanOutCounts
) -> None:
    """Redeploy one application in a savepoint and count the outcome."""
    try:
        async with uow.session.begin_nested():
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


def _applications_to_redeploy(
    applications: list[Deployment],
    cluster_config: ClusterConfig,
    environment_config: EnvironmentConfig,
    counts: FanOutCounts,
) -> list[Deployment]:
    """The applications whose resolved config differs from their active instance's."""
    changed = []
    for application in applications:
        try:
            at_config = _deployment_at_resolved_config(
                application, cluster_config, environment_config
            )
        except Exception:  # noqa: BLE001 — one deployment must not stop the others (FR-002)
            counts.dispatch_failed += 1
            logger.exception(
                "cluster_config_fanout_dispatch_error environment_id={} deployment_id={}",
                application.environment_id,
                application.id,
            )
            continue
        if at_config:
            counts.skipped_noop += 1
        else:
            changed.append(application)
    return changed


async def _remove_unused_controller(
    environment_id: UUID, uow: UnitOfWork, counts: FanOutCounts
) -> None:
    try:
        async with uow.session.begin_nested():
            removed = await tear_down_unused_ingress_controller(environment_id, uow)
    except Exception:  # noqa: BLE001 — the redeploys already started must still commit
        logger.exception(
            "cluster_config_fanout_ingress_removal_error environment_id={}",
            environment_id,
        )
        return
    counts.ingress_controllers_removed += removed


async def _fan_out_environment(
    environment: Environment,
    cluster_config: ClusterConfig,
    uow: UnitOfWork,
    counts: FanOutCounts,
    acting_user_id: UUID | None,
) -> None:
    """Redeploy the applications of one environment that are not at their resolved config.

    An application whose ``dedicated_ingress`` changes to a set value moves only
    onto a controller that is RUNNING with that value; it waits otherwise
    (research D4). A ``DELETING`` application is counted as evaluated and left to
    its teardown. The controller removal check runs last (research D5).
    """
    environment_config = EnvironmentConfig.model_validate(environment.config or {})
    counts.environments += 1
    deployments = await uow.deployments.find_all_by_environment(environment.id)
    counts.evaluated += len(deployments)
    applications = [
        deployment
        for deployment in deployments
        if not deployment.internal and deployment.status != DeploymentState.DELETING
    ]
    changed = _applications_to_redeploy(
        applications, cluster_config, environment_config, counts
    )

    target = _ingress_values(
        _effective_dedicated_ingress(environment_config, cluster_config)
    )
    moving_onto_controller = {
        application.id
        for application in changed
        if target is not None and _rendered_ingress_values(application) != target
    }
    controller = await _apply_controller_action(
        environment.id,
        await uow.deployments.find_internal_by_environment(environment.id),
        target,
        has_applications=bool(applications),
        has_waiting_applications=bool(moving_onto_controller),
        acting_user_id=acting_user_id,
        uow=uow,
        counts=counts,
    )
    controller_ready = (
        controller is not None
        and controller.status == DeploymentState.RUNNING
        and _rendered_ingress_values(controller) == target
    )

    for application in changed:
        if application.id in moving_onto_controller and not controller_ready:
            counts.skipped_waiting_for_ingress += 1
            continue
        await _redeploy_application(application, uow, counts)

    await _remove_unused_controller(environment.id, uow, counts)


async def _fan_out_environment_in_savepoint(
    environment: Environment,
    cluster_config: ClusterConfig,
    uow: UnitOfWork,
    counts: FanOutCounts,
    acting_user_id: UUID | None,
) -> None:
    """Run one environment's fan-out in a savepoint; a failure rolls back and counts only that environment."""
    environment_id = environment.id
    environment_counts = FanOutCounts()
    try:
        async with uow.session.begin_nested():
            await _fan_out_environment(
                environment, cluster_config, uow, environment_counts, acting_user_id
            )
    except Exception:  # noqa: BLE001 — one environment must not stop the others (FR-002)
        counts.add(FanOutCounts(environments=1, environments_failed=1))
        logger.exception(
            "cluster_config_fanout_environment_error environment_id={}", environment_id
        )
        return
    counts.add(environment_counts)


def _format_counts(counts: FanOutCounts) -> str:
    return " ".join(f"{name}={value}" for name, value in asdict(counts).items())


async def fan_out_cluster_config(
    cluster: Cluster,
    uow: UnitOfWork,
    acting_user_id: UUID,
) -> FanOutCounts:
    """Redeploy every deployment of the cluster whose resolved config changed (research D1, D7).

    The caller commits the cluster row first (FR-001). The dedicated ingress
    controllers that the fan-out creates are attributed to ``acting_user_id``,
    the administrator who submitted the config (research D4).
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
            await _fan_out_environment_in_savepoint(
                environment, cluster_config, uow, counts, acting_user_id
            )
        await uow.commit()

    logger.info(
        "cluster_config_fanout cluster_id={} {}", cluster.id, _format_counts(counts)
    )
    return counts


async def continue_environment_fan_out(
    environment_id: UUID,
    uow: UnitOfWork,
    trigger_deployment_id: UUID,
) -> FanOutCounts:
    """Run the fan-out for one environment again, from the status reporter (research D4).

    Called when the environment's dedicated ingress controller reaches RUNNING,
    so the applications that waited for it move. No controller is created, as
    no administrator acts here. Runs in the caller's transaction and does not commit.
    """
    counts = FanOutCounts()
    environment = await uow.environments.get(environment_id)
    cluster = (
        await uow.clusters.get(environment.cluster_id)
        if environment is not None
        else None
    )
    if environment is not None and cluster is not None:
        cluster_config = ClusterConfig.model_validate(cluster.config or {})
        await _fan_out_environment_in_savepoint(
            environment, cluster_config, uow, counts, acting_user_id=None
        )

    logger.info(
        "cluster_config_fanout_continued environment_id={} trigger_deployment_id={} {}",
        environment_id,
        trigger_deployment_id,
        _format_counts(counts),
    )
    return counts
