from abc import ABC, abstractmethod
from uuid import UUID

from sqlalchemy import asc
from sqlmodel import select

from styrmin_backend.db.models import ApplicationInstance
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class ApplicationInstanceRepository(BaseRepository[ApplicationInstance], ABC):
    """Repository specific to application instances."""

    @abstractmethod
    async def update(
        self,
        instance: ApplicationInstance,
    ) -> ApplicationInstance:
        """Update an application instance."""
        raise NotImplementedError("Method not implemented yet.")

    @abstractmethod
    async def find_by_deployment(
        self, deployment_id: UUID
    ) -> list[ApplicationInstance]:
        """Get all application instances for a deployment, ordered by created_on."""
        raise NotImplementedError("Method not implemented yet.")


class SQLModelApplicationInstanceRepository(
    BaseSQLModelRepository[ApplicationInstance], ApplicationInstanceRepository
):
    """The async SQLmodel application repository."""

    model_class = ApplicationInstance

    async def update(
        self,
        instance: ApplicationInstance,
    ) -> ApplicationInstance:
        """Update an application instance."""
        self.session.add(instance)
        return instance

    async def find_by_deployment(
        self, deployment_id: UUID
    ) -> list[ApplicationInstance]:
        """Get all application instances for a deployment, ordered by created_on."""
        statement = (
            select(self.model_class)
            .where(self.model_class.deployment_id == deployment_id)
            .order_by(asc(self.model_class.created_on))  # type: ignore[arg-type]
        )
        result = await self.session.exec(statement)
        return list(result.all())
