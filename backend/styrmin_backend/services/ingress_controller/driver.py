from pathlib import Path

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    HelmChart,
    HelmRepository,
)
from styrmin_backend.db.utils import get_async_engine
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

INTERNAL_DRIVER_NAME = "styrmin-ingress-controller"
INTERNAL_DRIVER_VERSION = "1.0.0"
TRAEFIK_CHART_NAME = "traefik"
TRAEFIK_CHART_VERSION = "40.2.0"
TRAEFIK_REPO_URL = "https://traefik.github.io/charts"


async def initialize_internal_drivers() -> None:
    """Initialize internal Application Drivers in the database.

    Creates the HelmRepository, HelmChart, ApplicationDriver, and
    ApplicationDriverVersion records for the internal ingress controller.
    Idempotent: safe to call on every startup.
    """
    async with AsyncSession(get_async_engine(), expire_on_commit=False) as session:
        uow = SqlModelUnitOfWork(session=session)
        async with uow:
            await _initialize_ingress_controller_driver(uow=uow)
            await uow.commit()


async def _initialize_ingress_controller_driver(uow: SqlModelUnitOfWork) -> None:
    """Create or update the internal ingress controller driver records."""
    # Load the values template from disk
    template_path = Path(__file__).parent / "templates" / "chart_values.j2.yaml"
    with open(template_path) as f:
        values_template = f.read()

    # 1. Ensure HelmRepository exists
    helm_repo = await uow.helm_repositories.get_by_url(TRAEFIK_REPO_URL)
    if helm_repo is None:
        logger.info("Creating HelmRepository for Traefik: {}", TRAEFIK_REPO_URL)
        helm_repo = await uow.helm_repositories.create(
            HelmRepository(url=TRAEFIK_REPO_URL)
        )

    # 2. Ensure HelmChart exists
    helm_chart = await uow.helm_charts.get_by_name_version(
        name=TRAEFIK_CHART_NAME, version=TRAEFIK_CHART_VERSION
    )
    if helm_chart is None:
        logger.info(
            "Creating HelmChart {}/{}",
            TRAEFIK_CHART_NAME,
            TRAEFIK_CHART_VERSION,
        )
        helm_chart = await uow.helm_charts.create(
            HelmChart(
                name=TRAEFIK_CHART_NAME,
                version=TRAEFIK_CHART_VERSION,
                values_template=values_template,
                repository_id=helm_repo.id,
            )
        )
    elif helm_chart.values_template != values_template:
        logger.info("Updating HelmChart values template for {}", TRAEFIK_CHART_NAME)
        helm_chart.values_template = values_template

    # 3. Ensure ApplicationDriver exists
    app_driver = await uow.application_drivers.get_by_name(INTERNAL_DRIVER_NAME)
    if app_driver is None:
        logger.info("Creating ApplicationDriver: {}", INTERNAL_DRIVER_NAME)
        app_driver = await uow.application_drivers.create(
            ApplicationDriver(name=INTERNAL_DRIVER_NAME)
        )

    # 4. Ensure ApplicationDriverVersion exists
    existing_version = await uow.application_driver_versions.get_by_driver_and_version(
        application_driver_id=app_driver.id,
        version=INTERNAL_DRIVER_VERSION,
    )

    if existing_version is None:
        logger.info(
            "Creating ApplicationDriverVersion: {} v{}",
            INTERNAL_DRIVER_NAME,
            INTERNAL_DRIVER_VERSION,
        )
        await uow.application_driver_versions.create(
            ApplicationDriverVersion(
                version=INTERNAL_DRIVER_VERSION,
                application_supported_versions=f"=={INTERNAL_DRIVER_VERSION}",
                source_type="internal",
                source_repository="styrmin",
                application_driver_id=app_driver.id,
                helm_chart_id=helm_chart.id,
            )
        )
    else:
        # Update helm chart reference if needed
        if existing_version.helm_chart_id != helm_chart.id:
            logger.info(
                "Updating ApplicationDriverVersion helm chart for {} v{}",
                INTERNAL_DRIVER_NAME,
                INTERNAL_DRIVER_VERSION,
            )
            existing_version.helm_chart_id = helm_chart.id
