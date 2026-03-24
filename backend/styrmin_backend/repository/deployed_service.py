from abc import ABC, abstractmethod
from typing import Sequence
from uuid import UUID

from sqlmodel import select

from styrmin_backend.db.models import DeployedService as DeployedServiceModel
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class DeployedServiceRepository(BaseRepository[DeployedServiceModel], ABC):
    """Repository specific to deployed services."""

    @abstractmethod
    async def get_by_environment_id(
        self, environment_id: UUID
    ) -> Sequence[DeployedServiceModel]:
        raise NotImplementedError

    @abstractmethod
    async def get_by_deployment_id(
        self, deployment_id: UUID
    ) -> Sequence[DeployedServiceModel]:
        raise NotImplementedError

    @abstractmethod
    async def get_by_resolved_name_and_environment_id(
        self, resolved_name: str, environment_id: UUID
    ) -> DeployedServiceModel | None:
        raise NotImplementedError

    @abstractmethod
    async def delete_by_deployment_id(self, deployment_id: UUID) -> None:
        raise NotImplementedError


class SQLModelDeployedServiceRepository(
    BaseSQLModelRepository[DeployedServiceModel], DeployedServiceRepository
):
    """The async SQLmodel deployed service repository."""

    model_class = DeployedServiceModel

    async def get_by_environment_id(
        self, environment_id: UUID
    ) -> Sequence[DeployedServiceModel]:
        result = await self.session.exec(
            select(self.model_class).where(
                self.model_class.environment_id == environment_id
            )
        )
        return result.all()

    async def get_by_deployment_id(
        self, deployment_id: UUID
    ) -> Sequence[DeployedServiceModel]:
        result = await self.session.exec(
            select(self.model_class).where(
                self.model_class.deployment_id == deployment_id
            )
        )
        return result.all()

    async def get_by_resolved_name_and_environment_id(
        self, resolved_name: str, environment_id: UUID
    ) -> DeployedServiceModel | None:
        result = await self.session.exec(
            select(self.model_class)
            .where(self.model_class.resolved_name == resolved_name)
            .where(self.model_class.environment_id == environment_id)
        )
        return result.first()

    async def delete_by_deployment_id(self, deployment_id: UUID) -> None:
        existing = await self.get_by_deployment_id(deployment_id)
        for entity in existing:
            await self.session.delete(entity)
