"""Provides the cluster config fan-out (021-cluster-config-update, research D1, D4, D5 and D7).

After a cluster's config is saved, every live, non-internal deployment of every
environment of the cluster whose resolved config differs from the resolved
config of its active instance is redeployed. The redeploys are ordered around
each environment's dedicated ingress controller, and the status reporter
continues the fan-out of an environment once its controller is ready.

An environment config update runs the same per-environment steps with its own
comparison (ADR-012), so it also creates, redeploys and removes the controller (#424).

Each environment is planned, then the plan is carried out with each redeploy and
each controller action in its own savepoint, so a failure rolls back and counts
only that unit (FR-002). The update call commits each environment on its own;
a dry run plans every environment and writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import StrEnum
from functools import partial
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
from styrmin_backend.domain.models import DeploymentState
from styrmin_backend.services.deployment import (
    create_ingress_controller,
    effective_dedicated_ingress,
    redeploy_for_environment_update,
    rendered_dedicated_ingress,
    tear_down_unused_ingress_controller,
)
from styrmin_backend.services.exceptions import ServiceError

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from styrmin_backend.context.models.config import DedicatedIngressConfig
    from styrmin_backend.db.models import Cluster, Environment
    from styrmin_backend.domain.models import Deployment
    from styrmin_backend.services.unit_of_work import UnitOfWork


_CLUSTER_FAN_OUT = "cluster_config_fanout"
_ENVIRONMENT_FAN_OUT = "env_config_fanout"


class ControllerAction(StrEnum):
    """What the fan-out does to an environment's dedicated ingress controller."""

    CREATE = "create"
    REDEPLOY = "redeploy"
    # Requested once no application uses the controller (research D5).
    REMOVE = "remove"


@dataclass(frozen=True)
class FanOutDeployment:
    """A deployment the fan-out redeployed, skipped or failed to start; ``task_id`` is set once started."""

    deployment_id: UUID
    deployment_name: str
    environment_id: UUID
    environment_name: str
    task_id: UUID | None = None


@dataclass(frozen=True)
class FanOutIngressController:
    environment_id: UUID
    environment_name: str
    action: ControllerAction
    failed: bool = False


@dataclass(frozen=True)
class FanOutEnvironment:
    environment_id: UUID
    environment_name: str


@dataclass
class FanOutResult:
    """What one fan-out did, or would do in a dry run; the counts are logged once per run (data-model §6)."""

    environments: int = 0
    environments_failed: int = 0
    evaluated: int = 0
    dispatched: int = 0
    skipped_noop: int = 0
    skipped_restoring: int = 0
    skipped_waiting_for_ingress: int = 0
    evaluation_failed: int = 0
    dispatch_failed: int = 0
    ingress_controllers_created: int = 0
    ingress_controllers_redeployed: int = 0
    ingress_controllers_removed: int = 0
    ingress_controller_failed: int = 0
    ingress_controller_removal_failed: int = 0
    redeployed: list[FanOutDeployment] = field(default_factory=list)
    waiting_for_ingress: list[FanOutDeployment] = field(default_factory=list)
    skipped_for_restore: list[FanOutDeployment] = field(default_factory=list)
    failed_to_start: list[FanOutDeployment] = field(default_factory=list)
    ingress_controllers: list[FanOutIngressController] = field(default_factory=list)
    failed_environments: list[FanOutEnvironment] = field(default_factory=list)

    def add(self, other: FanOutResult) -> None:
        for item in fields(self):
            value = getattr(other, item.name)
            if isinstance(value, list):
                getattr(self, item.name).extend(value)
            else:
                setattr(self, item.name, getattr(self, item.name) + value)

    def counts(self) -> dict[str, int]:
        return {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if isinstance(getattr(self, item.name), int)
        }


@dataclass(frozen=True)
class _EnvironmentRef:
    """The environment's values, read once: a rolled-back environment transaction expires the ORM rows.

    ``fan_out`` prefixes the log events: the cluster or the environment fan-out.
    """

    id: UUID
    name: str
    config: dict[str, Any]
    fan_out: str = _CLUSTER_FAN_OUT

    @classmethod
    def of(
        cls, environment: Environment, fan_out: str = _CLUSTER_FAN_OUT
    ) -> _EnvironmentRef:
        return cls(
            environment.id, environment.name, dict(environment.config or {}), fan_out
        )


@dataclass
class _EnvironmentPlan:
    environment: _EnvironmentRef
    controller: Deployment | None
    controller_action: ControllerAction | None
    redeploy: list[Deployment]


def _canonical(config: Any) -> dict[str, Any]:  # noqa: ANN401
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


def _ingress_values(value: DedicatedIngressConfig | None) -> dict[str, Any] | None:
    return None if value is None else value.model_dump(exclude_none=True, mode="json")


def _rendered_ingress_values(deployment: Deployment) -> dict[str, Any] | None:
    return _ingress_values(rendered_dedicated_ingress(deployment))


def _resolved_ingress_values(
    deployment: Deployment,
    cluster_config: ClusterConfig,
    environment_config: EnvironmentConfig,
) -> dict[str, Any] | None:
    """The ``dedicated_ingress`` values the deployment's next instance is rendered with.

    The deployment's own value, else the environment's effective value.
    """
    resolved = resolve_instance_config(
        cluster=cluster_config,
        environment=environment_config,
        deployment=DeploymentConfig.model_validate(deployment.config or {}),
    )
    return _ingress_values(resolved.dedicated_ingress)


def _entry(
    deployment: Deployment, environment: _EnvironmentRef, task_id: UUID | None = None
) -> FanOutDeployment:
    return FanOutDeployment(
        deployment_id=deployment.id,
        deployment_name=deployment.name,
        environment_id=environment.id,
        environment_name=environment.name,
        task_id=task_id,
    )


def _live_controller(deployments: list[Deployment]) -> Deployment | None:
    """The environment's controller; one that is not ``DELETING`` first."""
    controllers = [deployment for deployment in deployments if deployment.internal]
    controllers.sort(
        key=lambda controller: controller.status == DeploymentState.DELETING
    )
    return controllers[0] if controllers else None


def _changed_applications(
    applications: list[Deployment],
    environment: _EnvironmentRef,
    at_config: Callable[[Deployment], bool],
    moves_onto_controller: Callable[[Deployment], bool],
    result: FanOutResult,
) -> tuple[list[Deployment], set[UUID]]:
    """The applications that ``at_config`` finds not at their config, and the ids of those that move onto the controller."""
    changed: list[Deployment] = []
    moving: set[UUID] = set()
    for application in applications:
        try:
            converged = at_config(application)
            moves = not converged and moves_onto_controller(application)
        except Exception:  # noqa: BLE001 — one deployment must not stop the others (FR-002)
            result.evaluation_failed += 1
            result.failed_to_start.append(_entry(application, environment))
            logger.exception(
                f"{environment.fan_out}_evaluation_error environment_id={{}} deployment_id={{}}",
                environment.id,
                application.id,
            )
            continue
        if converged:
            result.skipped_noop += 1
        elif application.status == DeploymentState.RESTORING:
            # The restore owns the namespace; redeploy_for_environment_update refuses it too.
            result.skipped_restoring += 1
            result.skipped_for_restore.append(_entry(application, environment))
        else:
            changed.append(application)
            if moves:
                moving.add(application.id)
    return changed, moving


def _controller_action(
    controller: Deployment | None,
    target: dict[str, Any] | None,
    *,
    has_applications: bool,
    has_waiting_applications: bool,
    can_create: bool,
) -> ControllerAction | None:
    """The action on the environment's dedicated ingress controller (research D4, D5)."""
    if target is None:
        live = controller is not None and controller.status != DeploymentState.DELETING
        return ControllerAction.REMOVE if live else None
    if controller is None:
        return ControllerAction.CREATE if has_applications and can_create else None
    if controller.status == DeploymentState.DELETING:
        return None
    values_changed = _rendered_ingress_values(controller) != target
    retry_failed = (
        controller.status == DeploymentState.FAILED and has_waiting_applications
    )
    return ControllerAction.REDEPLOY if values_changed or retry_failed else None


async def _plan_environment(
    environment: _EnvironmentRef,
    cluster_config: ClusterConfig,
    uow: UnitOfWork,
    result: FanOutResult,
    *,
    can_create_controller: bool,
    at_config: Callable[[Deployment], bool] | None = None,
) -> _EnvironmentPlan:
    """Decide what the fan-out does in one environment.

    An application whose own resolved ``dedicated_ingress`` changes to a set value
    moves only onto a controller that is RUNNING with the environment's value; it
    waits otherwise (research D4, #453). A ``DELETING`` application is counted as
    evaluated and left to its teardown. ``at_config`` defaults to the
    resolved-config comparison (D1).
    """
    environment_config = EnvironmentConfig.model_validate(environment.config)
    if at_config is None:
        at_config = partial(
            _deployment_at_resolved_config,
            cluster_config=cluster_config,
            environment_config=environment_config,
        )
    deployments = await uow.deployments.find_all_by_environment(environment.id)
    result.environments += 1
    result.evaluated += len(deployments)
    applications = [
        deployment
        for deployment in deployments
        if not deployment.internal and deployment.status != DeploymentState.DELETING
    ]
    target = _ingress_values(
        effective_dedicated_ingress(environment_config, cluster_config)
    )

    def _moves_onto_controller(application: Deployment) -> bool:
        # A deployment that sets its own value keeps it, so it does not move (#453).
        if target is None:
            return False
        resolved = _resolved_ingress_values(
            application, cluster_config, environment_config
        )
        return _rendered_ingress_values(application) != resolved

    changed, moving_onto_controller = _changed_applications(
        applications, environment, at_config, _moves_onto_controller, result
    )
    controller = _live_controller(deployments)
    action = _controller_action(
        controller,
        target,
        has_applications=bool(applications),
        has_waiting_applications=bool(moving_onto_controller),
        can_create=can_create_controller,
    )
    controller_ready = (
        action is None
        and controller is not None
        and controller.status == DeploymentState.RUNNING
        and _rendered_ingress_values(controller) == target
    )

    redeploy = []
    for application in changed:
        if application.id in moving_onto_controller and not controller_ready:
            result.skipped_waiting_for_ingress += 1
            result.waiting_for_ingress.append(_entry(application, environment))
        else:
            redeploy.append(application)
    return _EnvironmentPlan(environment, controller, action, redeploy)


async def _act_on_controller(
    plan: _EnvironmentPlan,
    uow: UnitOfWork,
    acting_user_id: UUID | None,
    result: FanOutResult,
) -> bool:
    """Create or redeploy the environment's dedicated ingress controller in a savepoint; return False on failure."""
    environment_id = plan.environment.id
    try:
        async with uow.session.begin_nested():
            if plan.controller_action == ControllerAction.CREATE:
                assert acting_user_id is not None, (
                    "Only an administrator's update creates a controller"
                )
                await create_ingress_controller(environment_id, uow, acting_user_id)
                result.ingress_controllers_created += 1
            elif plan.controller is not None:
                if await redeploy_for_environment_update(plan.controller, uow):
                    result.ingress_controllers_redeployed += 1
    except Exception:  # noqa: BLE001 — the applications wait for a controller that failed to start
        result.ingress_controller_failed += 1
        logger.exception(
            f"{plan.environment.fan_out}_ingress_controller_error environment_id={{}}",
            environment_id,
        )
        return False
    return True


async def _redeploy_application(
    deployment: Deployment,
    environment: _EnvironmentRef,
    uow: UnitOfWork,
    result: FanOutResult,
) -> None:
    """Redeploy one application in a savepoint and record the outcome."""
    try:
        async with uow.session.begin_nested():
            task = await redeploy_for_environment_update(deployment, uow)
    except Exception:  # noqa: BLE001 — one deployment must not stop the others (FR-002)
        result.dispatch_failed += 1
        result.failed_to_start.append(_entry(deployment, environment))
        logger.exception(
            f"{environment.fan_out}_dispatch_error environment_id={{}} deployment_id={{}}",
            environment.id,
            deployment.id,
        )
        return
    if task is None:
        # Only a RESTORING deployment returns None; the restore owns its namespace.
        result.skipped_restoring += 1
        result.skipped_for_restore.append(_entry(deployment, environment))
        return
    result.dispatched += 1
    result.redeployed.append(_entry(deployment, environment, task.id))


async def _remove_unused_controller(
    environment: _EnvironmentRef, uow: UnitOfWork, result: FanOutResult
) -> None:
    try:
        async with uow.session.begin_nested():
            removed = await tear_down_unused_ingress_controller(environment.id, uow)
    except Exception:  # noqa: BLE001 — the redeploys already started must still commit
        result.ingress_controller_removal_failed += 1
        logger.exception(
            f"{environment.fan_out}_ingress_removal_error environment_id={{}}",
            environment.id,
        )
        return
    result.ingress_controllers_removed += removed


def _controller_entry(
    plan: _EnvironmentPlan, *, failed: bool = False
) -> list[FanOutIngressController]:
    if plan.controller_action is None:
        return []
    environment = plan.environment
    return [
        FanOutIngressController(
            environment.id, environment.name, plan.controller_action, failed=failed
        )
    ]


async def _fan_out_environment(
    environment: _EnvironmentRef,
    cluster_config: ClusterConfig,
    uow: UnitOfWork,
    result: FanOutResult,
    acting_user_id: UUID | None,
    at_config: Callable[[Deployment], bool] | None = None,
) -> None:
    """Plan one environment, start the controller action and the redeploys, then run the removal check (D5)."""
    plan = await _plan_environment(
        environment,
        cluster_config,
        uow,
        result,
        can_create_controller=acting_user_id is not None,
        at_config=at_config,
    )
    started = True
    if plan.controller_action in (ControllerAction.CREATE, ControllerAction.REDEPLOY):
        started = await _act_on_controller(plan, uow, acting_user_id, result)
    result.ingress_controllers.extend(_controller_entry(plan, failed=not started))
    for application in plan.redeploy:
        await _redeploy_application(application, environment, uow, result)
    controller = plan.controller
    if controller is not None and controller.status != DeploymentState.DELETING:
        await _remove_unused_controller(environment, uow, result)


def _record_environment_failure(
    environment: _EnvironmentRef, result: FanOutResult
) -> None:
    result.add(
        FanOutResult(
            environments=1,
            environments_failed=1,
            failed_environments=[FanOutEnvironment(environment.id, environment.name)],
        )
    )
    logger.exception(
        "cluster_config_fanout_environment_error environment_id={}", environment.id
    )


def _format_counts(result: FanOutResult) -> str:
    return " ".join(f"{name}={value}" for name, value in result.counts().items())


async def _cluster_environments(
    cluster_id: UUID, uow: UnitOfWork
) -> list[_EnvironmentRef]:
    return [
        _EnvironmentRef.of(env)
        for env in await uow.environments.get_all()
        if env.cluster_id == cluster_id
    ]


async def plan_cluster_config_fan_out(
    cluster: Cluster,
    cluster_config: ClusterConfig,
    uow: UnitOfWork,
) -> FanOutResult:
    """Return what :func:`fan_out_cluster_config` would do with ``cluster_config``, without writing anything.

    Runs in the caller's unit of work. ``task_id`` is never set.
    """
    result = FanOutResult()
    for environment in await _cluster_environments(cluster.id, uow):
        environment_result = FanOutResult()
        try:
            plan = await _plan_environment(
                environment,
                cluster_config,
                uow,
                environment_result,
                can_create_controller=True,
            )
        except Exception:  # noqa: BLE001 — one environment must not stop the others (FR-002)
            _record_environment_failure(environment, result)
            continue
        environment_result.ingress_controllers.extend(_controller_entry(plan))
        environment_result.redeployed.extend(
            _entry(application, environment) for application in plan.redeploy
        )
        result.add(environment_result)
    return result


async def fan_out_cluster_config(
    cluster: Cluster,
    uow: UnitOfWork,
    acting_user_id: UUID,
) -> FanOutResult:
    """Redeploy every deployment of the cluster whose resolved config changed (research D1, D7).

    The caller commits the cluster row first (FR-001). Each environment runs in its
    own transaction and is committed before the next one starts, so a flow never
    waits long for its task row and no transaction spans the whole installation.
    The dedicated ingress controllers that the fan-out creates are attributed to
    ``acting_user_id``, the administrator who submitted the config (research D4).
    """
    result = FanOutResult()
    cluster_id = cluster.id
    cluster_config = ClusterConfig.model_validate(cluster.config or {})
    async with uow:
        environments = await _cluster_environments(cluster_id, uow)
    for environment in environments:
        environment_result = FanOutResult()
        try:
            async with uow:
                await _fan_out_environment(
                    environment, cluster_config, uow, environment_result, acting_user_id
                )
                await uow.commit()
        except Exception:  # noqa: BLE001 — one environment must not stop the others (FR-002)
            _record_environment_failure(environment, result)
            continue
        result.add(environment_result)

    logger.info(
        "cluster_config_fanout cluster_id={} {}", cluster_id, _format_counts(result)
    )
    return result


async def fan_out_environment_config(
    environment: Environment,
    uow: UnitOfWork,
    acting_user_id: UUID,
    at_config: Callable[[Deployment], bool],
) -> FanOutResult:
    """Carry out an environment config update with the per-environment steps of the cluster fan-out (#424).

    ``at_config`` is the environment fan-out's comparison (ADR-012). The
    applications wait for the environment's dedicated ingress controller as in
    the cluster fan-out, and a controller that this update creates is attributed
    to ``acting_user_id``. Runs in the caller's transaction and does not commit.
    """
    cluster = await uow.clusters.get(environment.cluster_id)
    cluster_config = ClusterConfig.model_validate(
        cluster.config or {} if cluster is not None else {}
    )
    result = FanOutResult()
    await _fan_out_environment(
        _EnvironmentRef.of(environment, _ENVIRONMENT_FAN_OUT),
        cluster_config,
        uow,
        result,
        acting_user_id,
        at_config=at_config,
    )
    return result


async def continue_environment_fan_out(
    environment_id: UUID,
    uow: UnitOfWork,
    trigger_deployment_id: UUID,
) -> FanOutResult:
    """Run the fan-out for one environment again, from the status reporter (research D4).

    Called when the environment's dedicated ingress controller reaches RUNNING,
    so the applications that waited for it move. No controller is created, as
    no administrator acts here. Runs in a savepoint of the caller's transaction
    and does not commit.
    """
    result = FanOutResult()
    environment = await uow.environments.get(environment_id)
    cluster = (
        await uow.clusters.get(environment.cluster_id)
        if environment is not None
        else None
    )
    if environment is not None and cluster is not None:
        ref = _EnvironmentRef.of(environment)
        environment_result = FanOutResult()
        try:
            async with uow.session.begin_nested():
                cluster_config = ClusterConfig.model_validate(cluster.config or {})
                await _fan_out_environment(
                    ref, cluster_config, uow, environment_result, None
                )
        except Exception:  # noqa: BLE001 — the status report must still commit
            _record_environment_failure(ref, result)
        else:
            result.add(environment_result)

    logger.info(
        "cluster_config_fanout_continued environment_id={} trigger_deployment_id={} {}",
        environment_id,
        trigger_deployment_id,
        _format_counts(result),
    )
    return result
