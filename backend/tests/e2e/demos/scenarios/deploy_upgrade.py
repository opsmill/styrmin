"""Demo 1: deploy Infrahub, upgrade it, and show the upgrade task with the driver's upgrade action (FR-003, FR-006)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tests.e2e.demos import stack
from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.ui_driver import UiScenarioDriver
from tests.e2e.pages.deployment_detail import DeploymentDetailPage
from tests.e2e.pages.environments import EnvironmentDetailPage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tests.e2e.demos.catalog import DemoContext
    from tests.e2e.drivers.refs import StepRef

ENVIRONMENT_NAME = "network-lab-upgrade"
DRIVER = "infrahub"
DEPLOYMENT_NAME = "infrahub"
# The step of an upgrade task that runs the driver's `upgrade` action (backend/styrmin_backend/domain/steps.py).
UPGRADE_ACTION_STEP = "hook:upgrade:core"
KEYSTROKE_DELAY_MS = 45
DEPLOY_TIMEOUT = 900.0
UPGRADE_TIMEOUT = 900.0
# How long the video shows the running deployment's timeline, then the finished upgrade task and its steps.
RESULT_HOLD_SECONDS = 1.5
STEPS_HOLD_SECONDS = 3.0


@dataclass(frozen=True)
class Lab:
    """The environment the demo deploys Infrahub into during the recording."""

    environment_id: str


def check_version(shown: str | None, expected: str) -> None:
    """Raise ``ScenarioActionError`` unless the deployment page shows the ``expected`` Infrahub version."""
    if shown != expected:
        raise ScenarioActionError(
            f"The deployment shows Infrahub {shown or 'with no version'}, not {expected}"
        )


def check_upgrade_action(steps: Sequence[StepRef], task_id: str) -> None:
    """Raise ``ScenarioActionError`` unless the upgrade task's ``steps`` ran the driver's upgrade action and it succeeded."""
    step = next((step for step in steps if step.key == UPGRADE_ACTION_STEP), None)
    if step is None:
        shown = ", ".join(step.name for step in steps) or "none"
        raise ScenarioActionError(
            f"The upgrade task {task_id} did not run the driver's upgrade action; its steps: {shown}"
        )
    if step.status != "SUCCEEDED":
        raise ScenarioActionError(
            f"The step {step.name!r} of the upgrade task {task_id} ended {step.status}, not SUCCEEDED"
        )


async def setup(context: DemoContext) -> Lab:
    """Create the empty environment and open its page, where the recording starts."""
    environment_id = await stack.create_environment(context.client, ENVIRONMENT_NAME)
    await EnvironmentDetailPage(context.page).goto(environment_id=environment_id)
    return Lab(environment_id=environment_id)


async def record(context: DemoContext, lab: Lab) -> None:
    recorder = context.recorder
    versions = context.versions
    driver = UiScenarioDriver(
        page=context.page,
        base_url=context.styrmin_url,
        keystroke_delay_ms=KEYSTROKE_DELAY_MS,
    )
    detail = DeploymentDetailPage(context.page, keystroke_delay_ms=KEYSTROKE_DELAY_MS)

    async with recorder.step(f"Deploy Infrahub {versions.previous}"):
        deployment = await driver.create_deployment(
            driver=DRIVER,
            version=versions.previous,
            environment_id=lab.environment_id,
            name=DEPLOYMENT_NAME,
        )
        async with recorder.wait(f"Infrahub {versions.previous} is starting"):
            await driver.wait_for_deployment_running(
                deployment_id=deployment.id, timeout=DEPLOY_TIMEOUT
            )
        check_version(await detail.read_application_version(), versions.previous)
        # Read the tasks here, so the page does not show the timeline and reload at once in the next step.
        known_task_ids = await detail.read_task_ids()
        await asyncio.sleep(RESULT_HOLD_SECONDS)

    async with recorder.step(f"Upgrade to Infrahub {versions.latest}"):
        await driver.upgrade_deployment(
            deployment_id=deployment.id, version=versions.latest
        )
        # Open the timeline before the wait, so the click plays at normal speed.
        await detail.open_timeline()
        async with recorder.wait("Upgrade in progress"):
            task_id = await detail.wait_for_new_task(
                "upgrade_instance",
                known_task_ids=known_task_ids,
                timeout=UPGRADE_TIMEOUT,
            )

    async with recorder.step("The upgrade task and its steps"):
        await detail.open_timeline()
        # The tasks that the upgrade action started are listed above the upgrade task.
        check_upgrade_action(await detail.show_timeline_entry(task_id), task_id)
        check_version(await detail.read_application_version(), versions.latest)
        await asyncio.sleep(STEPS_HOLD_SECONDS)
