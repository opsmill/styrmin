from abc import ABC
from uuid import UUID

from sqlmodel import select

from styrmin_backend.db.models import Component
from styrmin_backend.domain.models import Component as DomainComponent
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class ComponentRepository(BaseRepository[Component], ABC):
    """Repository specific to components."""


class SQLModelComponentRepository(
    BaseSQLModelRepository[Component], ComponentRepository
):
    """The async SQLmodel component repository."""

    model_class = Component

    def _to_model(self, component_config: DomainComponent) -> Component:
        """Convert a domain model to a SQLModel."""
        return Component(
            id=component_config.id,
            name=component_config.name,
            enabled=component_config.enabled,
        )

    async def save(
        self, application_instance_id: UUID, component: DomainComponent
    ) -> None:
        """Save a component config."""
        model = self._to_model(component)
        model.application_instance_id = application_instance_id
        await self.session.merge(model)

    async def get(self, id: str) -> DomainComponent | None:  # type: ignore[override]
        """Get a component config by id."""
        result = await self.session.exec(
            select(self.model_class).where(self.model_class.id == id)
        )
        entity = result.first()

        if entity is not None:
            return DomainComponent(  # type: ignore[call-arg]
                id=entity.id,
                name=entity.name,
                enabled=entity.enabled,
            )
        return None
