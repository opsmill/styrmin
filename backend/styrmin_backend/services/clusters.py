"""Provides the cluster services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence
from uuid import UUID

from styrmin_backend.context.exceptions import InvalidClusterContextError
from styrmin_backend.context.validators import validate_cluster_config
from styrmin_backend.db.models import Cluster
from styrmin_backend.services.exceptions import (
    ClusterAlreadyExistsError,
    ClusterLimitReachedError,
    ClusterNotFoundError,
    InvalidContextError,
)
from styrmin_backend.services.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    pass


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

        if config is None:
            config = {}

        # Apply cluster defaults
        config.setdefault("dedicated_ingress", {})
        config.setdefault("ingress_class", "traefik")
        config.setdefault("runtime_class", "default")

        try:
            validate_cluster_config(config)
        except InvalidClusterContextError as e:
            raise InvalidContextError() from e

        await uow.clusters.create(Cluster(name=name, config=config))
        await uow.commit()
        returned_cluster = await uow.clusters.get_by_name(name)
        assert returned_cluster is not None, "Cluster should be created successfully"
        return returned_cluster


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
