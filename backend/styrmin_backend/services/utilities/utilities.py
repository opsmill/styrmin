from pathlib import Path

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Utility
from styrmin_backend.db.utils import get_async_engine
from styrmin_backend.domain.payloads import Utility as DomainUtility
from styrmin_backend.domain.payloads import UtilityKind
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork, UnitOfWork

DEFAULT_UTILITIES = [
    DomainUtility(
        kind=UtilityKind.INGRESS,
        values_template_file="ingress-controller-chart-values.j2.yaml",
    )
]


async def initialize_utilities() -> None:
    """Initialize the utilities in the database."""
    async with AsyncSession(get_async_engine(), expire_on_commit=False) as session:
        uow = SqlModelUnitOfWork(session=session)
        async with uow:
            for utility in DEFAULT_UTILITIES:
                await initialize_utility(utility_data=utility, uow=uow)
            await uow.commit()


async def initialize_utility(utility_data: DomainUtility, uow: UnitOfWork) -> None:
    """Initialize a specific utility in the database."""
    # Load the resource template from file
    with open(
        Path(__file__).parent / "templates" / utility_data.values_template_file, "r"
    ) as file:
        resource_template = file.read()

    # Create the Utility if it doesn't exist
    utility = await uow.utilities.get_by_kind(utility_data.kind)
    if not utility:
        logger.info(f"Creating Utility {utility_data.kind.value}")
        await uow.utilities.create(
            Utility(
                kind=utility_data.kind.value,
                resource_template=resource_template,
            )
        )
    else:
        # Update the resource template if it changed
        if utility.resource_template != resource_template:
            logger.info(
                f"Updating resource template for Utility {utility_data.kind.value}"
            )
            utility.resource_template = resource_template
