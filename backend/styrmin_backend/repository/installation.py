"""Storage of the install ID that telemetry reports (spec 020)."""

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
        select_install_id = select(Installation.install_id).where(
            Installation.id == _INSTALLATION_ROW_ID
        )
        install_id = (await self.session.exec(select_install_id)).first()
        if install_id is not None:
            return install_id
        dialect = self.session.bind.dialect.name  # type: ignore[union-attr]
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        await self.session.exec(
            insert(Installation.__table__)  # type: ignore[attr-defined]
            .values(id=_INSTALLATION_ROW_ID, install_id=uuid4())
            .on_conflict_do_nothing(index_elements=["id"])
        )
        # A concurrent first start may have inserted its ID first, so read the stored one.
        return (await self.session.exec(select_install_id)).one()
