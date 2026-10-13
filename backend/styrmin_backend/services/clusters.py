"""Provides the cluster services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Sequence
from uuid import UUID

from loguru import logger

from styrmin_backend.context.exceptions import InvalidClusterContextError
from styrmin_backend.context.models.config import ClusterConfig
from styrmin_backend.context.validators import validate_cluster_config
from styrmin_backend.db.models import Cluster
from styrmin_backend.services.backup.environment import (
    guard_no_clone_occupying_environment,
)
from styrmin_backend.services.capabilities import compute_cluster_capabilities
from styrmin_backend.services.cluster_config_fanout import (
    FanOutResult,
    fan_out_cluster_config,
    plan_cluster_config_fan_out,
)
from styrmin_backend.services.exceptions import (
    AmbiguousIdentifierError,
    ClusterAlreadyExistsError,
    ClusterLimitReachedError,
    ClusterNotFoundError,
    EnvironmentOperationInProgressError,
    InvalidContextError,
)
from styrmin_backend.services.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    from styrmin_backend.db.models import Environment


def _apply_cluster_defaults(config: dict) -> dict:
    """Return a copy of ``config`` with the cluster defaults set for missing keys."""
    result = dict(config)
    result.setdefault("ingress_class", "traefik")
    result.setdefault("runtime_class", "default")
    return result


async def create_cluster(
    uow: UnitOfWork, name: str = "default", config: dict | None = None
) -> Cluster:
    """Create a cluster with the given name.

    Raises:
        ClusterLimitReachedError: If a cluster already exists.
        InvalidContextError: If the cluster context is invalid.
    """
    async with uow:
        existing_clusters = await uow.clusters.get_all()
        if existing_clusters:
            raise ClusterLimitReachedError()

        cluster = await uow.clusters.get_by_name(name)
        if cluster:
            raise ClusterAlreadyExistsError("A cluster with this name already exists.")

        config = _apply_cluster_defaults(config or {})

        try:
            validate_cluster_config(config)
        except InvalidClusterContextError as e:
            raise InvalidContextError(str(e)) from e

        cluster = Cluster(name=name, config=config)
        cluster.capabilities = compute_cluster_capabilities(cluster)
        await uow.clusters.create(cluster)
        await uow.commit()
        returned_cluster = await uow.clusters.get_by_name(name)
        assert returned_cluster is not None, "Cluster should be created successfully"
        return returned_cluster


@dataclass(frozen=True)
class ClusterUpdateResult:
    """The cluster after an update, and what the fan-out did (or would do, in a dry run)."""

    cluster: Cluster
    fan_out: FanOutResult
    dry_run: bool


def _config_changes(previous: dict, new: dict) -> dict[str, dict[str, Any]]:
    """The top-level keys whose value changed, with the previous and the new value."""
    return {
        key: {"from": previous.get(key), "to": new.get(key)}
        for key in sorted(previous.keys() | new.keys())
        if previous.get(key) != new.get(key)
    }


async def _refuse_while_cloning(environment: Environment, uow: UnitOfWork) -> None:
    try:
        await guard_no_clone_occupying_environment(environment.id, uow)
    except EnvironmentOperationInProgressError as e:
        raise EnvironmentOperationInProgressError(
            operation_id=e.operation_id,
            operation_kind=e.operation_kind,
            message=(
                f"Nothing was saved: environment '{environment.name}' is part of an "
                "environment clone that is still running. Save again when the clone "
                "has finished."
            ),
        ) from e


async def update_cluster(
    uow: UnitOfWork,
    cluster_id: UUID,
    config: dict,
    acting_user_id: UUID,
    *,
    dry_run: bool = False,
) -> ClusterUpdateResult:
    """Replace a cluster's config, then redeploy the deployments whose resolved config changed.

    The whole config is replaced: a key left out is cleared, except ``ingress_class``
    and ``runtime_class``, which get the ``create_cluster`` defaults (FR-005). The
    cluster row and its recomputed capabilities are committed before the fan-out
    starts any redeploy (FR-001, FR-007, research D7). A dry run validates the
    config and returns what the fan-out would do, without saving anything.

    Raises:
        ClusterNotFoundError: If the cluster does not exist.
        EnvironmentOperationInProgressError: If a clone is still capturing a source
            environment of the cluster, or is still building an environment of the
            cluster (FR-006, research D6).
        InvalidContextError: If the config is invalid (FR-008).
    """
    async with uow:
        cluster = await uow.clusters.get(cluster_id)
        if cluster is None:
            raise ClusterNotFoundError(f"Cluster with id {cluster_id} not found.")

        # Backups and restores in progress do not block a config update; a clone does.
        for environment in await uow.environments.get_all():
            if environment.cluster_id == cluster.id:
                await _refuse_while_cloning(environment, uow)

        new_config = _apply_cluster_defaults(config)
        try:
            validate_cluster_config(new_config)
        except InvalidClusterContextError as e:
            raise InvalidContextError(str(e)) from e

        if dry_run:
            planned = await plan_cluster_config_fan_out(
                cluster, ClusterConfig.model_validate(new_config), uow
            )
            return ClusterUpdateResult(cluster=cluster, fan_out=planned, dry_run=True)

        changes = _config_changes(cluster.config or {}, new_config)
        cluster.config = new_config
        cluster.capabilities = compute_cluster_capabilities(cluster)
        await uow.commit()

    logger.info(
        "cluster_config_updated cluster_id={} user_id={} changes={}",
        cluster_id,
        acting_user_id,
        json.dumps(changes, sort_keys=True),
    )
    fan_out = await fan_out_cluster_config(cluster, uow, acting_user_id)

    async with uow:
        refreshed = await uow.clusters.get(cluster_id)
    assert refreshed is not None, "Cluster should still exist after update"
    return ClusterUpdateResult(cluster=refreshed, fan_out=fan_out, dry_run=False)


async def resolve_cluster(
    uow: UnitOfWork,
    cluster_id: UUID | None = None,
    cluster_name: str | None = None,
) -> Cluster:
    """Resolve a cluster by ID or name. Exactly one must be provided."""
    if cluster_id is not None and cluster_name is not None:
        raise AmbiguousIdentifierError(
            "Provide either cluster_id or cluster_name, not both"
        )
    async with uow:
        if cluster_id is not None:
            cluster = await uow.clusters.get(cluster_id)
        elif cluster_name is not None:
            cluster = await uow.clusters.get_by_name(cluster_name)
        else:
            raise AmbiguousIdentifierError(
                "Either cluster_id or cluster_name is required"
            )
        if cluster is None:
            identifier = cluster_id if cluster_id is not None else repr(cluster_name)
            raise ClusterNotFoundError(f"Cluster not found: {identifier}")
        return cluster


async def get_cluster(cluster_id: UUID, uow: UnitOfWork) -> Cluster:
    """Get a cluster by its id."""
    async with uow:
        cluster = await uow.clusters.get(cluster_id)
        if cluster is None:
            raise ClusterNotFoundError(f"Cluster with id {cluster_id} not found.")

        return cluster


async def get_clusters(uow: UnitOfWork) -> Sequence[Cluster]:
    """Get all clusters."""
    async with uow:
        return await uow.clusters.get_all()


async def delete_cluster(cluster_id: UUID, uow: UnitOfWork) -> None:
    """Delete a cluster by its id."""
    async with uow:
        cluster = await uow.clusters.get(cluster_id)
        if cluster is None:
            raise ClusterNotFoundError(f"Cluster with id {cluster_id} not found.")
        await uow.clusters.delete(cluster)
        await uow.commit()
