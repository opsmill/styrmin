"""Daily Prefect flow that drops expired session rows. See ADR-016."""

from __future__ import annotations

from prefect import flow
from prefect.logging import get_run_logger
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend import config
from styrmin_backend.db.utils import get_async_engine
from styrmin_backend.services.auth.cleanup import delete_expired_sessions


@flow(name="cleanup_expired_sessions")
async def cleanup_expired_sessions_flow() -> int:
    """Sweep expired session rows. Returns the number of rows deleted."""
    config.SETTINGS.initialize_and_exit()
    log = get_run_logger()
    async with AsyncSession(get_async_engine(), expire_on_commit=False) as session:
        deleted = await delete_expired_sessions(session)
    log.info("Deleted %d expired session row(s)", deleted)
    return deleted
