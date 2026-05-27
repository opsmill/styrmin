from styrmin_backend.actions import (
    GlobalContext,
    execute_commands,
    get_component_images,
    start_components,
    stop_components,
    upgrade_deployment_version,
)
from prefect import flow, get_run_logger


@flow
async def upgrade(context: GlobalContext, target_version: str):
    logger = get_run_logger()
    logger.info("Executing upgrade user actions...")
    logger.info(type(context))
    logger.info(f"Context: {context}")

    await stop_components(components=["server", "task-worker"], context=context)
    await upgrade_deployment_version(target_version=target_version, context=context)

    images = await get_component_images(component="server", context=context)
    image = next(img for img in images if "infrahub" in img)
    image_base = image.rsplit(":", 1)[0]

    await execute_commands(
        [
            "sh",
            "-c",
            "infrahub upgrade --help && infrahub upgrade || (infrahub db migrate && infrahub db update-core-schema)",
        ],
        image=f"{image_base}:{target_version}",
        context=context,
        env_from_component="server",
        labels_from_component="server",
    )
    await start_components(
        components=["server", "task-worker"],
        context=context,
    )


@flow
def pre_setup(context: GlobalContext):
    logger = get_run_logger()
    logger.info("Executing setup user actions before setup action...")
    logger.info(f"Context: {context}")


@flow
def post_setup(context: GlobalContext):
    logger = get_run_logger()
    logger.info("Executing setup user actions after setup action...")
    logger.info(f"Context: {context}")
