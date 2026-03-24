from styrmin_backend.actions import (
    GlobalContext,
    start_components,
    stop_components,
    upgrade_deployment_version,
)
from prefect import flow, get_run_logger


@flow
async def upgrade(context: GlobalContext, target_version: str):
    logger = get_run_logger()
    logger.info("Starting Semaphore upgrade...")

    await stop_components(components=["server"], context=context)

    await upgrade_deployment_version(target_version=target_version, context=context)

    await start_components(components=["server"], context=context)

    logger.info(f"Semaphore upgrade to {target_version} complete.")


@flow
def pre_setup(context: GlobalContext):
    logger = get_run_logger()
    logger.info("Executing Semaphore pre-setup...")


@flow
def post_setup(context: GlobalContext):
    logger = get_run_logger()
    logger.info("Executing Semaphore post-setup...")
