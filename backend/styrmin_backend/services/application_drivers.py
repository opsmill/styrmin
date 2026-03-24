from typing import Sequence
from uuid import UUID

from styrmin_backend.db.models import ApplicationDriver
from styrmin_backend.services.exceptions import ApplicationDriverNotFoundError
from styrmin_backend.services.unit_of_work import UnitOfWork


async def get_application_drivers(uow: UnitOfWork) -> Sequence[ApplicationDriver]:
    """Get all application drivers."""
    async with uow:
        return await uow.application_drivers.get_all()


async def get_application_driver(
    application_driver_id: UUID, uow: UnitOfWork
) -> ApplicationDriver:
    """Get an application driver by its ID."""
    async with uow:
        driver = await uow.application_drivers.get(application_driver_id)
        if driver is None:
            raise ApplicationDriverNotFoundError(
                f"Application driver with ID {application_driver_id} not found"
            )
        return driver
