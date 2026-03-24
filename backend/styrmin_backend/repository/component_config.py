from abc import ABC, abstractmethod
from uuid import UUID

from sqlmodel import select

from styrmin_backend.db.models import ComponentConfig
from styrmin_backend.domain.models import ComponentConfig as DomainComponentConfig
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class ComponentConfigRepository(BaseRepository[ComponentConfig], ABC):
    """Repository specific to component configs."""

    @abstractmethod
    async def save(
        self,
        application_driver_version_id: UUID,
        component_config: DomainComponentConfig,
    ) -> None:
        """Save a component config."""
        raise NotImplementedError()

    @abstractmethod
    async def find(self, id: UUID) -> DomainComponentConfig | None:
        """Get a component config by id."""
        raise NotImplementedError()


class SQLModelComponentConfigRepository(
    BaseSQLModelRepository[ComponentConfig], ComponentConfigRepository
):
    """The async SQLmodel component config repository."""

    model_class = ComponentConfig

    def _to_model(self, component_config: DomainComponentConfig) -> ComponentConfig:
        """Convert a domain model to a SQLModel."""
        return ComponentConfig(
            id=component_config.id,
            name=component_config.name,
            config=component_config.config,
        )

    async def save(
        self,
        application_driver_version_id: UUID,
        component_config: DomainComponentConfig,
    ) -> None:
        """Save a component config."""
        model = self._to_model(component_config)
        model.application_driver_version_id = application_driver_version_id
        await self.session.merge(model)

    async def find(self, id: UUID) -> DomainComponentConfig | None:
        """Get a component config by id."""
        result = await self.session.exec(
            select(self.model_class).where(self.model_class.id == id)
        )
        entity = result.first()

        if entity is not None:
            return DomainComponentConfig(
                id=entity.id,
                name=entity.name,
                config=entity.config,
            )
        return None
