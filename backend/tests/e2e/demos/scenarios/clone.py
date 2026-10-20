"""Demo 4: clone an environment, add a device in the clone's Infrahub, and show that only the clone's Semaphore lists it (FR-013)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tests.e2e.demos import infrahub_setup, semaphore_setup, stack
from tests.e2e.demos.pages.infrahub import InfrahubDevicesPage
from tests.e2e.demos.pages.semaphore import SemaphoreTemplatesPage
from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.ui_driver import UiScenarioDriver

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tests.e2e.demos.catalog import DemoContext
    from tests.e2e.demos.recorder import DemoRecorder
    from tests.e2e.drivers.refs import EnvironmentCloneRef

ENVIRONMENT_NAME = "network-lab"
CLONE_NAME = "network-lab-clone"
INFRAHUB_DRIVER = "infrahub-enterprise"
# The `semaphore` driver's default version; the demo image's tag follows it (tasks/demo.py builds it).
SEMAPHORE_VERSION = "2.16.47"
SEMAPHORE_IMAGE_REPOSITORY = "styrmin-demo/semaphore"
DEPLOYMENT_NAMES = ("infrahub", "semaphore")
DEVICES = ("sw1", "sw2")
NEW_DEVICE = "sw3"
KEYSTROKE_DELAY_MS = 45
TASK_TIMEOUT = 120.0
CLONE_TIMEOUT = 1200.0
READY_TIMEOUT = 300.0
# How long the video shows the device list before the new device, each finished operation, and each task output.
LIST_HOLD_SECONDS = 1.5
RESULT_HOLD_SECONDS = 2.0
OUTPUT_HOLD_SECONDS = 3.0
# The line that demos/semaphore/ansible/list_hosts.yml prints.
_DEVICE_COUNT_PATTERN = re.compile(r"Devices in the inventory: (\d+)")


@dataclass(frozen=True)
class Lab:
    """The source environment of the demo and the addresses of its two web applications."""

    environment_id: str
    infrahub_url: str
    semaphore_url: str
    semaphore: semaphore_setup.SemaphoreProject


def device_count(log: str) -> int:
    """Return the device count that the playbook prints in the task ``log``.

    Raises ``ScenarioActionError`` with the last lines of ``log`` when it prints no count or two different counts.
    """
    counts = {int(count) for count in _DEVICE_COUNT_PATTERN.findall(log)}
    if len(counts) == 1:
        return counts.pop()
    tail = "\n".join([line for line in log.splitlines() if line.strip()][-10:])
    problem = (
        "no device count" if not counts else f"several device counts {sorted(counts)}"
    )
    raise ScenarioActionError(
        f"The Semaphore task output gives {problem}. Last lines of its log:\n{tail}"
    )


def check_device_count(log: str, expected: int, *, where: str) -> None:
    """Raise ``ScenarioActionError`` unless the task ``log`` gives ``expected`` devices."""
    count = device_count(log)
    if count != expected:
        raise ScenarioActionError(
            f"{where} lists {count} devices in its inventory, not {expected}"
        )


def check_clone(
    clone: EnvironmentCloneRef, deployments: Sequence[str]
) -> dict[str, str]:
    """Return the counterpart deployment id of each of ``deployments``.

    Raises ``ScenarioActionError`` unless the clone completed and cloned every deployment of ``deployments``.
    """
    results = {item.deployment_name: item for item in clone.deployment_results}
    counterparts = {
        name: result.counterpart_deployment_id
        for name, result in results.items()
        if name in deployments
        and result.outcome == "CLONED"
        and result.counterpart_deployment_id
    }
    if clone.status == "COMPLETED" and len(counterparts) == len(deployments):
        return counterparts
    shown = ", ".join(
        f"{name}: {result.outcome}" + (f" ({result.reason})" if result.reason else "")
        for name, result in sorted(results.items())
    )
    errors = f"; errors: {'; '.join(clone.clone_errors)}" if clone.clone_errors else ""
    raise ScenarioActionError(
        f"The environment clone ended {clone.status}, not COMPLETED with "
        f"{', '.join(deployments)} cloned (deployments: {shown or 'none'}){errors}"
    )


async def setup(context: DemoContext) -> Lab:
    """Deploy Infrahub and Semaphore, load the devices and the template, log in to both, and open the template."""
    client = context.client
    environment_id = await stack.create_environment(client, ENVIRONMENT_NAME)
    await stack.load_enterprise_driver(client)
    # Infrahub first: Semaphore gets the `infrahub` alias only if Infrahub runs when it is deployed.
    infrahub = await stack.deploy(
        client,
        environment_id=environment_id,
        driver=INFRAHUB_DRIVER,
        version=context.versions.latest,
        name="infrahub",
    )
    semaphore = await stack.deploy(
        client,
        environment_id=environment_id,
        driver="semaphore",
        version=SEMAPHORE_VERSION,
        name="semaphore",
        parameters={"docker_image": SEMAPHORE_IMAGE_REPOSITORY},
    )
    infrahub_url = stack.service_url(infrahub, "infrahub")
    semaphore_url = stack.service_url(semaphore, "semaphore")
    await infrahub_setup.wait_until_ready(infrahub_url, timeout=READY_TIMEOUT)
    await infrahub_setup.load_devices(infrahub_url, DEVICES)
    project = await semaphore_setup.configure(
        semaphore_url, infrahub_token=infrahub_setup.INFRAHUB_TOKEN
    )
    await InfrahubDevicesPage(context.page).log_in(infrahub_url)
    templates = SemaphoreTemplatesPage(context.page)
    await templates.log_in(semaphore_url)
    # The recording starts on the template in the source Semaphore.
    await templates.goto_template(
        semaphore_url, project.project_id, project.template_id
    )
    return Lab(
        environment_id=environment_id,
        infrahub_url=infrahub_url,
        semaphore_url=semaphore_url,
        semaphore=project,
    )


async def run_template(
    recorder: DemoRecorder,
    templates: SemaphoreTemplatesPage,
    *,
    expected: int,
    where: str,
) -> None:
    """Run the template open on screen, and fail unless its output gives ``expected`` devices."""
    await templates.run()
    async with recorder.wait("Ansible reads the inventory"):
        log = await templates.wait_for_output(TASK_TIMEOUT)
    check_device_count(log, expected, where=where)
    await asyncio.sleep(OUTPUT_HOLD_SECONDS)


async def record(context: DemoContext, lab: Lab) -> None:
    recorder = context.recorder
    driver = UiScenarioDriver(
        page=context.page,
        base_url=context.styrmin_url,
        keystroke_delay_ms=KEYSTROKE_DELAY_MS,
    )
    devices = InfrahubDevicesPage(context.page, keystroke_delay_ms=KEYSTROKE_DELAY_MS)
    templates = SemaphoreTemplatesPage(
        context.page, keystroke_delay_ms=KEYSTROKE_DELAY_MS
    )
    project = lab.semaphore

    async with recorder.step("Semaphore reads its inventory from Infrahub"):
        await run_template(
            recorder, templates, expected=len(DEVICES), where="The source Semaphore"
        )

    async with recorder.step("Clone the environment"):
        created = await driver.clone_environment(
            environment_id=lab.environment_id, name=CLONE_NAME, deployment_ids=None
        )
        async with recorder.wait("Clone in progress"):
            clone = await driver.wait_for_environment_clone(
                environment_clone_id=created.id, max_wait=CLONE_TIMEOUT
            )
        counterparts = check_clone(clone, DEPLOYMENT_NAMES)
        await asyncio.sleep(RESULT_HOLD_SECONDS)
        clone_infrahub_url = stack.service_url(
            await context.client.deployments.get(counterparts["infrahub"]), "infrahub"
        )
        clone_semaphore_url = stack.service_url(
            await context.client.deployments.get(counterparts["semaphore"]),
            "semaphore",
        )
        async with recorder.wait("The clone's Infrahub starts"):
            await infrahub_setup.wait_until_ready(
                clone_infrahub_url, timeout=READY_TIMEOUT
            )
        async with recorder.wait("The clone's Semaphore starts"):
            await semaphore_setup.wait_until_ready(
                clone_semaphore_url, timeout=READY_TIMEOUT
            )
        # The clone's applications exist only now; the logins are cut from the video (research R-016).
        async with recorder.unrecorded() as login_page:
            await InfrahubDevicesPage(login_page).log_in(clone_infrahub_url)
            await SemaphoreTemplatesPage(login_page).log_in(clone_semaphore_url)

    async with recorder.step("Add a device in the clone's Infrahub"):
        await devices.goto(clone_infrahub_url)
        await asyncio.sleep(LIST_HOLD_SECONDS)
        await devices.add_device(NEW_DEVICE)
        await asyncio.sleep(RESULT_HOLD_SECONDS)

    async with recorder.step("The clone's Semaphore lists the new device"):
        # The clone's Semaphore holds a copy of the source's project and template, with the same ids.
        await templates.goto_template(
            clone_semaphore_url, project.project_id, project.template_id
        )
        await run_template(
            recorder,
            templates,
            expected=len(DEVICES) + 1,
            where="The clone's Semaphore",
        )

    async with recorder.step("The source is unchanged"):
        await templates.goto_template(
            lab.semaphore_url, project.project_id, project.template_id
        )
        await run_template(
            recorder, templates, expected=len(DEVICES), where="The source Semaphore"
        )
