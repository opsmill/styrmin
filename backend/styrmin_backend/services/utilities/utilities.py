from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Utility
from styrmin_backend.db.utils import get_async_engine
from styrmin_backend.domain.payloads import UtilityKind
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork, UnitOfWork

DEFAULT_UTILITY_KINDS = [UtilityKind.INGRESS]


async def initialize_utilities() -> None:
    """Initialize the utilities in the database."""
    async with AsyncSession(get_async_engine(), expire_on_commit=False) as session:
        uow = SqlModelUnitOfWork(session=session)
        async with uow:
            for kind in DEFAULT_UTILITY_KINDS:
                await initialize_utility(kind=kind, uow=uow)
            await uow.commit()


async def initialize_utility(kind: UtilityKind, uow: UnitOfWork) -> None:
    """Initialize a specific utility in the database."""
    if await uow.utilities.get_by_kind(kind):
        return
    logger.info(f"Creating Utility {kind.value}")
    await uow.utilities.create(Utility(kind=kind.value))
