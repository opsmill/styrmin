"""Provides the application instances related services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from styrmin_backend.domain.payloads import (
    UtilityKind,
    UtilityPayload,
)
from styrmin_backend.services.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    pass


async def get_utilities_payloads(uow: UnitOfWork) -> list[UtilityPayload]:
    """Build and return the utilities payloads to be sent to the workflows.

    Exclusively use the unit of work to fetch the utilities and their associated helm charts and repositories.
    No commit is performed in this function.
    """

    # Prepare the utilities information to send to the workflow
    utilities = await uow.utilities.get_all()
    utilities_payload = []
    for utility in utilities:
        utilities_payload.append(
            UtilityPayload(
                utility_kind=UtilityKind(utility.kind),
            )
        )

    return utilities_payload
