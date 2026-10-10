"""Create the telemetry install ID when the server starts (spec 020, FR-014, research D10)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from styrmin_backend.services.unit_of_work import get_unit_of_work

if TYPE_CHECKING:
    from uuid import UUID


async def ensure_install_id() -> UUID | None:
    """Create the install ID if it is missing. A failure logs a warning and returns None."""
    try:
        async with get_unit_of_work() as uow:
            install_id = await uow.installation.get_or_create_install_id()
            await uow.commit()
    except Exception as error:  # noqa: BLE001 - telemetry must never stop the server (critique E2)
        logger.warning(
            "Could not create the telemetry install ID: {}. No action is needed: the server "
            "keeps running, and the next start or daily report creates the ID.",
            error,
        )
        return None
    return install_id
