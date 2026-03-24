from abc import ABC, abstractmethod

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
