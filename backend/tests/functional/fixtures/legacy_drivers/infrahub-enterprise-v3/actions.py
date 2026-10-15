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
    # images[0] is the component container's image; drop any digest, then the tag
    # (a ":" followed by a "/" is a registry port, not a tag).
    name = images[0].split("@", 1)[0]
    repository, separator, tag = name.rpartition(":")
    image_base = repository if separator and "/" not in tag else name

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
