from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.utils import get_session
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork


async def get_unit_of_work_dependency(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[SqlModelUnitOfWork, None]:
    """FastAPI dependency that provides a UnitOfWork via DI session."""
    uow = SqlModelUnitOfWork(session=session)
    async with uow:
        yield uow


async def get_context(
    uow: SqlModelUnitOfWork = Depends(get_unit_of_work_dependency),
) -> dict[str, Any]:
    return {"uow": uow}
