from abc import ABC, abstractmethod
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy.orm import selectinload
from sqlmodel import select

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    HelmChart,
)
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository

# FIXME: Update repository for ApplicationDriver to support domain models


class ApplicationDriverRepository(BaseRepository[ApplicationDriver], ABC):
    """Repository specific to application drivers."""

    @abstractmethod
    async def get_by_name(self, name: str) -> ApplicationDriver | None:
        raise NotImplementedError()


class SQLModelApplicationDriverRepository(
    BaseSQLModelRepository[ApplicationDriver], ApplicationDriverRepository
):
    """The async SQLmodel application driver repository."""

    model_class = ApplicationDriver

    def _eager_load_options(self) -> list[Any]:
        """Return options for eager loading all relationships."""
        return [
            selectinload(self.model_class.versions).options(  # type: ignore[arg-type]
                selectinload(ApplicationDriverVersion.helm_chart).options(  # type: ignore[arg-type]
                    selectinload(HelmChart.repository),  # type: ignore[arg-type]
                ),
                selectinload(ApplicationDriverVersion.component_configs),  # type: ignore[arg-type]
                selectinload(ApplicationDriverVersion.actions),  # type: ignore[arg-type]
            )
        ]

    async def get(self, id: UUID) -> ApplicationDriver | None:
        """Get an application driver by its ID with relationships eagerly loaded."""
        statement = (
            select(self.model_class)
            .where(self.model_class.id == id)
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()

    async def get_all(self) -> Sequence[ApplicationDriver]:
        """Get all application drivers with relationships eagerly loaded."""
        statement = select(self.model_class).options(*self._eager_load_options())
        result = await self.session.exec(statement)
        return result.all()

    async def get_by_name(self, name: str) -> ApplicationDriver | None:
        """Get an application driver by its name."""
        statement = (
            select(self.model_class)
            .where(self.model_class.name == name)
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()
