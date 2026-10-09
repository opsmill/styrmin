"""Provides the application instances related services."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from styrmin_backend.domain.payloads import (
    UtilityKind,
    UtilityPayload,
)
from styrmin_backend.services.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    from styrmin_backend.db.models import ApplicationInstance


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


async def get_instances_by_ids(
    instance_ids: Sequence[UUID], uow: UnitOfWork
) -> dict[UUID, ApplicationInstance]:
    """The application instances with these ids in one query, keyed by id."""
    async with uow:
        instances = await uow.application_instances.get_by_ids(instance_ids)
    return {instance.id: instance for instance in instances}
