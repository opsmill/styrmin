"""Demo 1: deploy Infrahub, upgrade it, and show the upgrade task with the driver's upgrade action, and the version in
Infrahub's web UI before and after the upgrade (FR-003, FR-006)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tests.e2e.demos import infrahub_setup, stack
from tests.e2e.demos.pages.infrahub import InfrahubDevicesPage, InfrahubHomePage
from tests.e2e.demos.recorder import LIST_HOLD_SECONDS
from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.ui_driver import UiScenarioDriver
from tests.e2e.pages.deployment_detail import DeploymentDetailPage
from tests.e2e.pages.environments import EnvironmentDetailPage

if TYPE_CHECKING:
    from tests.e2e.demos.catalog import DemoContext
    from tests.e2e.demos.recorder import DemoRecorder
    from tests.e2e.drivers.refs import TimelineEntry

ENVIRONMENT_NAME = "network-lab-upgrade"
DRIVER = "infrahub"
DEPLOYMENT_NAME = "infrahub"
# The step of an upgrade task that runs the driver's `upgrade` action (backend/styrmin_backend/domain/steps.py).
UPGRADE_ACTION_STEP = "hook:upgrade:core"
# Twice the typing delay of demos 2 to 4, so that a viewer can follow each form.
KEYSTROKE_DELAY_MS = 90
DEPLOY_TIMEOUT = 900.0
UPGRADE_TIMEOUT = 900.0
READY_TIMEOUT = 300.0
# The service of the `infrahub` driver whose address opens Infrahub's web UI.
INFRAHUB_SERVICE = "infrahub"
# How long the video shows the finished upgrade task and its steps, before the closing card.
STEPS_HOLD_SECONDS = 7.0
# The image fix that the upgrade action needs; the error of a failed check names it.
IMAGE_HINT = (
    "A Styrmin image built from a commit before the fix to #372 (PR #535, develop commit bb56eac9) does not run "
    "the action: run 'uv run invoke build' and 'uv run invoke reset' from a newer checkout, then record again"
)


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


def check_about_version(shown: str | None, expected: str) -> None:
    """Raise ``ScenarioActionError`` unless Infrahub's About dialog shows the ``expected`` version, as ``v1.11.7``."""
    if shown != f"v{expected}":
        raise ScenarioActionError(
            f"Infrahub's About dialog shows {shown or 'no version'}, not v{expected}"
        )


def check_upgrade_task(entry: TimelineEntry, expected_version: str) -> None:
    """Raise ``ScenarioActionError`` unless the upgrade task's timeline ``entry`` ran the driver's upgrade
    action, the action succeeded, and the entry shows the ``expected_version`` of Infrahub.

    The timeline shows each task with the version of the newest instance created at or before the task,
    which for an upgrade task is the instance that the task rolls out. The deployment page's version does
    not prove the upgrade: Styrmin sets it when it accepts the upgrade request, before the task runs.
    """
    task_id = entry.task_id
    step = next((step for step in entry.steps if step.key == UPGRADE_ACTION_STEP), None)
    if step is None:
        shown = ", ".join(step.name for step in entry.steps) or "none"
        raise ScenarioActionError(
            f"The upgrade task {task_id} did not run the driver's upgrade action; its steps: {shown}. "
            f"{IMAGE_HINT}"
        )
    if step.status != "SUCCEEDED":
        raise ScenarioActionError(
            f"The step {step.name!r} of the upgrade task {task_id} ended {step.status}, not SUCCEEDED"
        )
    if entry.application_version != expected_version:
        raise ScenarioActionError(
            f"The upgrade task {task_id} shows Infrahub "
            f"{entry.application_version or 'with no version'}, not {expected_version}"
        )


async def setup(context: DemoContext) -> Lab:
    """Open the page of the empty environment, where the recording starts.

    When the setup demo ran before in the same run, it created the environment. The command deleted every
    other environment of this name before this setup, so an environment that exists now is that one.
    Otherwise the setup creates the environment.
    """
    found = await stack.find_environments(context.client, [ENVIRONMENT_NAME])
    environment_id = (
        found[0].id
        if found
        else await stack.create_environment(context.client, ENVIRONMENT_NAME)
    )
    await EnvironmentDetailPage(context.page).goto(environment_id=environment_id)
    return Lab(environment_id=environment_id)


async def show_infrahub(
    recorder: DemoRecorder, home: InfrahubHomePage, url: str, expected: str
) -> None:
    """Open Infrahub at ``url`` and its About dialog; fail unless the dialog shows the ``expected`` version."""
    # Infrahub shows a white page while it loads after a switch from another web application.
    async with recorder.cut():
        await recorder.caption(f"Infrahub in {ENVIRONMENT_NAME}")
        await home.goto(url)
    await recorder.hold(LIST_HOLD_SECONDS)
    check_about_version(await home.open_about(), expected)
    await recorder.hold()
    await home.close_about()


async def record(context: DemoContext, lab: Lab) -> None:
    recorder = context.recorder
    versions = context.versions
    driver = UiScenarioDriver(
        page=context.page,
        base_url=context.styrmin_url,
        keystroke_delay_ms=KEYSTROKE_DELAY_MS,
    )
    detail = DeploymentDetailPage(context.page, keystroke_delay_ms=KEYSTROKE_DELAY_MS)
    home = InfrahubHomePage(context.page)
    await recorder.caption(f"Styrmin: environment {ENVIRONMENT_NAME}")

    async with recorder.step(f"Deploy Infrahub {versions.previous}"):
        deployment = await driver.create_deployment(
            driver=DRIVER,
            version=versions.previous,
            environment_id=lab.environment_id,
            name=DEPLOYMENT_NAME,
        )
        async with recorder.wait(f"Infrahub {versions.previous} starts"):
            await driver.wait_for_deployment_running(
                deployment_id=deployment.id, timeout=DEPLOY_TIMEOUT
            )
            infrahub_url = stack.service_url(
                await context.client.deployments.get(deployment.id), INFRAHUB_SERVICE
            )
            await infrahub_setup.wait_until_ready(infrahub_url, timeout=READY_TIMEOUT)
        check_version(await detail.read_application_version(), versions.previous)
        # Read the task ids at the end of this chapter, so the chapter ends on the Timeline tab
        # with the succeeded "Create" task.
        known_task_ids = await detail.read_task_ids()
        await recorder.hold()
        # Infrahub exists only now; the login is cut from the video (research R-016).
        async with recorder.unrecorded() as login_page:
            await InfrahubDevicesPage(login_page).log_in(infrahub_url)

    async with recorder.step(f"Open Infrahub {versions.previous}"):
        await show_infrahub(recorder, home, infrahub_url, versions.previous)

    async with recorder.cut():
        await recorder.caption(f"Styrmin: environment {ENVIRONMENT_NAME}")
        await detail.goto(
            environment_id=lab.environment_id, deployment_id=deployment.id
        )
        # The page shows the deployment once its data has loaded.
        check_version(await detail.read_application_version(), versions.previous)
    async with recorder.step(f"Upgrade to Infrahub {versions.latest}"):
        # The page object opens the Upgrade dialog from the tab on screen. The scenario driver's
        # upgrade_deployment first opens the page by its address, which jumps to the Overview tab.
        await detail.open_upgrade_dialog()
        await detail.confirm_upgrade(version=versions.latest)
        # Open the timeline before the wait, so the click plays at normal speed.
        await detail.open_timeline()
        async with recorder.wait("The upgrade runs"):
            task_id = await detail.wait_for_new_task(
                "upgrade_instance",
                known_task_ids=known_task_ids,
                timeout=UPGRADE_TIMEOUT,
            )
            await infrahub_setup.wait_until_ready(infrahub_url, timeout=READY_TIMEOUT)

    async with recorder.step("The upgrade task and its steps"):
        # The tasks that the upgrade action started are listed above the upgrade task.
        check_upgrade_task(await detail.show_timeline_entry(task_id), versions.latest)
        await recorder.hold(STEPS_HOLD_SECONDS)

    async with recorder.step(f"Open Infrahub {versions.latest}"):
        await show_infrahub(recorder, home, infrahub_url, versions.latest)
