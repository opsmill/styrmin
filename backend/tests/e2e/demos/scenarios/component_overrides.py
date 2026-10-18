"""Demo 2: override the Semaphore image and run two Infrahub servers (plan demo table; FR-003, FR-015)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tests.e2e.demos import stack
from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.ui_driver import UiScenarioDriver
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

if TYPE_CHECKING:
    from tests.e2e.demos.catalog import DemoContext

ENVIRONMENT_NAME = "network-lab-overrides"
# The `semaphore` driver's default version; the demo image's tag follows it (tasks/demo.py builds it).
SEMAPHORE_VERSION = "2.16.47"
SEMAPHORE_IMAGE = f"styrmin-demo/semaphore:v{SEMAPHORE_VERSION}"
SERVER_COMPONENT = "server"
INFRAHUB_SERVERS = 2
KEYSTROKE_DELAY_MS = 45
UPDATE_TIMEOUT = 900.0
# How long the video shows the succeeded task, then the Component Overrides card, after each update.
TASK_HOLD_SECONDS = 1.5
RESULT_HOLD_SECONDS = 3.0


@dataclass(frozen=True)
class Deployments:
    """The environment, the two deployments and the tasks their timelines listed before the recording."""

    environment_id: str
    infrahub_id: str
    semaphore_id: str
    infrahub_task_ids: frozenset[str]
    semaphore_task_ids: frozenset[str]


def check_override(row_text: str, expected: str, *, deployment: str) -> None:
    """Raise ``ScenarioActionError`` unless the Component Overrides row shows ``expected``."""
    if expected not in row_text:
        shown = " ".join(row_text.split())
        raise ScenarioActionError(
            f"The {SERVER_COMPONENT} row of {deployment} shows {shown!r}, not {expected!r}"
        )


async def setup(context: DemoContext) -> Deployments:
    """Deploy Infrahub, then Semaphore with its default image, and open Semaphore's deployment page."""
    client = context.client
    environment_id = await stack.create_environment(client, ENVIRONMENT_NAME)
    # Infrahub first: Semaphore gets the `infrahub` alias only if Infrahub runs when it is deployed.
    infrahub = await stack.deploy(
        client,
        environment_id=environment_id,
        driver="infrahub",
        version=context.versions.latest,
        name="infrahub",
    )
    semaphore = await stack.deploy(
        client,
        environment_id=environment_id,
        driver="semaphore",
        version=SEMAPHORE_VERSION,
        name="semaphore",
    )
    # Read the task ids before the recording, so the video does not open each timeline twice.
    detail = DeploymentDetailPage(context.page)
    task_ids: dict[str, frozenset[str]] = {}
    for deployment_id in (str(infrahub.id), str(semaphore.id)):
        await _open_deployment(detail, environment_id, deployment_id)
        task_ids[deployment_id] = frozenset(await detail.read_task_ids())
    await _open_deployment(detail, environment_id, str(semaphore.id))
    return Deployments(
        environment_id=environment_id,
        infrahub_id=str(infrahub.id),
        semaphore_id=str(semaphore.id),
        infrahub_task_ids=task_ids[str(infrahub.id)],
        semaphore_task_ids=task_ids[str(semaphore.id)],
    )


async def record(context: DemoContext, deployments: Deployments) -> None:
    recorder = context.recorder
    driver = UiScenarioDriver(
        page=context.page,
        base_url=context.styrmin_url,
        keystroke_delay_ms=KEYSTROKE_DELAY_MS,
    )
    driver.attach_to_deployment(environment_id=deployments.environment_id)
    detail = DeploymentDetailPage(context.page, keystroke_delay_ms=KEYSTROKE_DELAY_MS)

    async with recorder.step("Use an image with the Infrahub Ansible collection"):
        await driver.set_component_image(
            deployment_id=deployments.semaphore_id,
            component=SERVER_COMPONENT,
            image=SEMAPHORE_IMAGE,
        )
        await detail.open_timeline()
        async with recorder.wait("Semaphore restarts with the new image"):
            await detail.wait_for_new_task(
                "update_instance",
                known_task_ids=set(deployments.semaphore_task_ids),
                timeout=UPDATE_TIMEOUT,
            )
        await asyncio.sleep(TASK_HOLD_SECONDS)
        row = await detail.show_component_overrides(component=SERVER_COMPONENT)
        check_override(row, SEMAPHORE_IMAGE, deployment="semaphore")
        await asyncio.sleep(RESULT_HOLD_SECONDS)

    await _open_deployment(detail, deployments.environment_id, deployments.infrahub_id)
    async with recorder.step("Run two Infrahub servers"):
        await driver.set_component_replicas(
            deployment_id=deployments.infrahub_id,
            component=SERVER_COMPONENT,
            replicas=INFRAHUB_SERVERS,
        )
        await detail.open_timeline()
        async with recorder.wait("A second Infrahub server starts"):
            await detail.wait_for_new_task(
                "update_instance",
                known_task_ids=set(deployments.infrahub_task_ids),
                timeout=UPDATE_TIMEOUT,
            )
        await asyncio.sleep(TASK_HOLD_SECONDS)
        row = await detail.show_component_overrides(component=SERVER_COMPONENT)
        check_override(row, f"{INFRAHUB_SERVERS} (override)", deployment="infrahub")
        await asyncio.sleep(RESULT_HOLD_SECONDS)


async def _open_deployment(
    detail: DeploymentDetailPage, environment_id: str, deployment_id: str
) -> None:
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    await detail.wait_for_status(expected="running", timeout=60)
