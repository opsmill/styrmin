"""Upgrade action of the ``failing-actions`` E2E driver (spec 019).

The target version chooses the failure: ``RAISE_VERSION`` raises an error and
``COMMAND_VERSION`` runs a command that prints two lines and exits with 3.
Every other version succeeds without doing anything.
"""

from prefect import flow, get_run_logger
from styrmin_backend.actions import GlobalContext, execute_commands

# Kept in step with backend/tests/e2e/test_task_steps.py.
RAISE_VERSION = "0.9.0+raise"
COMMAND_VERSION = "0.9.0+command"
RAISE_MESSAGE = "failing-actions: the upgrade action raised on purpose"
COMMAND_IMAGE = "simple-app:0.1.0"


@flow
async def upgrade(context: GlobalContext, target_version: str) -> None:
    logger = get_run_logger()
    if target_version == RAISE_VERSION:
        raise RuntimeError(RAISE_MESSAGE)
    if target_version == COMMAND_VERSION:
        await execute_commands(
            ["sh", "-c", "echo step-output-1; echo step-output-2; exit 3"],
            image=COMMAND_IMAGE,
            context=context,
        )
    logger.info("failing-actions: nothing to do for %s", target_version)
