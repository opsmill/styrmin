"""Provides the environment services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence
from uuid import UUID

from styrmin_backend.context.exceptions import InvalidEnvironmentContextError
from styrmin_backend.context.validators import validate_environment_config
from styrmin_backend.db.models import Environment
from styrmin_backend.services.clusters import resolve_cluster
from styrmin_backend.services.exceptions import (
    AmbiguousIdentifierError,
    ClusterNotFoundError,
    EnvironmentAlreadyExistsError,
    EnvironmentNotFoundError,
    InvalidContextError,
)
from styrmin_backend.services.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    pass


async def resolve_environment(
    uow: UnitOfWork,
    environment_id: UUID | None = None,
    environment_name: str | None = None,
    cluster_id: UUID | None = None,
    cluster_name: str | None = None,
) -> Environment:
    """Resolve an environment by ID or name. When using name, cluster context is required."""
    if environment_id is not None and environment_name is not None:
        raise AmbiguousIdentifierError(
            "Provide either environment_id or environment_name, not both"
        )
    if environment_id is not None:
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError()
        return environment
    if environment_name is not None:
        cluster = await resolve_cluster(
            uow, cluster_id=cluster_id, cluster_name=cluster_name
        )
        environment = await uow.environments.get_by_name_in_cluster(
            environment_name, cluster.id
        )
        if environment is None:
            raise EnvironmentNotFoundError()
        return environment
    raise AmbiguousIdentifierError(
        "Either environment_id or environment_name is required"
    )


async def create_environment(
    name: str, cluster_id: UUID, uow: UnitOfWork, config: dict | None = None
) -> Environment:
    """Create an environment with the given name and cluster_id.

    Raises:
        InvalidContextError: If the environment context is invalid.
    """
    async with uow:
        cluster = await uow.clusters.get(cluster_id)
        if not cluster:
            raise ClusterNotFoundError(f"The cluster with id {id} could not be found")

        if await uow.environments.get_by_name_in_cluster(name, cluster_id):
            raise EnvironmentAlreadyExistsError(
                "An environment with this name already exists in this cluster."
            )

        if config is None:
            config = {}

        try:
            validate_environment_config(config)
        except InvalidEnvironmentContextError as e:
            raise InvalidContextError from e

        await uow.environments.create(
            Environment(name=name, cluster_id=cluster_id, config=config)
        )
        await uow.commit()
        returned_environment = await uow.environments.get_by_name_in_cluster(
            name, cluster_id
        )
        assert returned_environment is not None, (
            "Environment should be created successfully"
        )
        return returned_environment


async def get_environment(environment_id: UUID, uow: UnitOfWork) -> Environment:
    """Get an environment by its id."""
    async with uow:
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )

        return environment


async def get_environments(uow: UnitOfWork) -> Sequence[Environment]:
    """Get all the environments."""
    async with uow:
        return await uow.environments.get_all()


async def delete_environment(environment_id: UUID, uow: UnitOfWork) -> None:
    """Delete an environment by its id."""
    async with uow:
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )
        await uow.environments.delete(environment)
        await uow.commit()
