"""Storage of the install ID that telemetry reports (spec 020)."""

import warnings
from abc import ABC, abstractmethod
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Installation

_INSTALLATION_ROW_ID = 1


class InstallationRepository(ABC):
    """Repository of the single ``installation`` row."""

    @abstractmethod
    async def get_or_create_install_id(self) -> UUID:
        """Return the install ID, creating it on first use. The caller commits."""
        raise NotImplementedError


class SQLModelInstallationRepository(InstallationRepository):
    """The async SQLModel installation repository."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_install_id(self) -> UUID:
        dialect = self.session.bind.dialect.name  # type: ignore[union-attr]
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        statement = (
            insert(Installation.__table__)  # type: ignore[attr-defined]
            .values(id=_INSTALLATION_ROW_ID, install_id=uuid4())
            .on_conflict_do_nothing(index_elements=["id"])
        )
        # SQLModel's exec() is for SELECT; the DeprecationWarning that
        # execute() raises is a false positive for DML.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            await self.session.execute(statement)
        result = await self.session.exec(
            select(Installation.install_id).where(
                Installation.id == _INSTALLATION_ROW_ID
            )
        )
        return result.one()
