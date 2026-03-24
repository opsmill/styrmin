"""Provides the environment services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence
from uuid import UUID

from styrmin_backend.context.exceptions import InvalidEnvironmentContextError
from styrmin_backend.context.validators import validate_environment_config
from styrmin_backend.db.models import Environment
from styrmin_backend.services.exceptions import (
    ClusterNotFoundError,
    EnvironmentAlreadyExistsError,
    EnvironmentNotFoundError,
    InvalidContextError,
)
from styrmin_backend.services.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    pass


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

        if await uow.environments.get_by_name(name):
            raise EnvironmentAlreadyExistsError(
                "An environment with this name already exists."
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
        returned_environment = await uow.environments.get_by_name(name)
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
