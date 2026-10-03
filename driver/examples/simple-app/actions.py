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
    logger.info("Starting simple-app upgrade...")

    await stop_components(components=["server"], context=context)

    await upgrade_deployment_version(target_version=target_version, context=context)

    images = await get_component_images(component="server", context=context)
    # images[0] is the component container's image; drop any digest, then the tag
    # (a ":" followed by a "/" is a registry port, not a tag).
    name = images[0].split("@", 1)[0]
    repository, separator, tag = name.rpartition(":")
    image_base = repository if separator and "/" not in tag else name

    await execute_commands(
        ["simple-app-upgrade"],
        image=f"{image_base}:{target_version}",
        context=context,
        env_from_component="server",
        labels_from_component="server",
    )

    await start_components(components=["server"], context=context)

    logger.info(f"Simple-app upgrade to {target_version} complete.")


@flow
def pre_setup(context: GlobalContext):
    logger = get_run_logger()
    logger.info("Executing simple-app pre-setup...")


@flow
def post_setup(context: GlobalContext):
    logger = get_run_logger()
    logger.info("Executing simple-app post-setup...")
