"""Actions of the ``local-actions`` E2E driver (spec 029, #372).

This file must be in the Styrmin image, at
``/source/backend/tests/e2e/fixtures/drivers/local-actions``: the test loads
the driver from that path, and each action runs from the same path as a
process in the agent pod, which runs the Styrmin image. ``docker/Dockerfile``
copies ``backend/`` into ``/source/backend``.

Each action logs a marker, which the test reads in the logs of the action's
flow run. The ``upgrade`` action also runs ``execute_commands`` with the
image of the ``server`` component, which the cluster already holds, so each
upgrade of a deployment creates the Job ``<release reference>-job`` again
(#372). Kept in step with backend/tests/e2e/test_local_driver_actions.py.
"""

from prefect import flow, get_run_logger
from styrmin_backend.actions import (
    GlobalContext,
    execute_commands,
    get_component_images,
)


@flow
def pre_setup(context: GlobalContext) -> None:
    get_run_logger().info("LOCAL-ACTIONS-MARKER pre_setup code=A")


@flow
def post_setup(context: GlobalContext) -> None:
    get_run_logger().info("LOCAL-ACTIONS-MARKER post_setup code=A")


@flow
async def upgrade(context: GlobalContext, target_version: str) -> None:
    get_run_logger().info("LOCAL-ACTIONS-MARKER upgrade code=A")
    images = await get_component_images(component="server", context=context)
    await execute_commands(
        ["sh", "-c", f"echo LOCAL-ACTIONS-JOB upgrade {target_version}"],
        image=images[0],
        context=context,
    )
