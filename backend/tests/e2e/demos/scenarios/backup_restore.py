"""Demo 3: back up an environment, delete a device and a template, restore, and show both back (FR-002, FR-019)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tests.e2e.demos import infrahub_setup, semaphore_image, semaphore_setup, stack
from tests.e2e.demos.pages.infrahub import InfrahubDevicesPage
from tests.e2e.demos.pages.semaphore import SemaphoreTemplatesPage
from tests.e2e.demos.recorder import LIST_HOLD_SECONDS
from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.ui_driver import UiScenarioDriver
from tests.e2e.helpers.infrahub import INFRAHUB_ADMIN_TOKEN
from tests.e2e.pages.environments import EnvironmentDetailPage

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from tests.e2e.demos.catalog import DemoContext
    from tests.e2e.drivers.refs import EnvironmentBackupRef, EnvironmentRestoreRef

ENVIRONMENT_NAME = "network-lab-backup"
INFRAHUB_DRIVER = "infrahub-enterprise"
DEPLOYMENT_NAMES = ("infrahub", "semaphore")
DEVICES = ("sw1", "sw2")
DELETED_DEVICE = "sw2"
KEYSTROKE_DELAY_MS = 45
BACKUP_TIMEOUT = 600.0
RESTORE_TIMEOUT = 900.0
READY_TIMEOUT = 300.0


@dataclass(frozen=True)
class Lab:
    """The environment of the demo and the addresses of its two web applications."""

    environment_id: str
    infrahub_url: str
    semaphore_url: str
    semaphore: semaphore_setup.SemaphoreProject


def check_backup(backup: EnvironmentBackupRef, deployments: Sequence[str]) -> None:
    """Raise unless the backup completed with one completed constituent per deployment name."""
    outcomes = {item.deployment_name: item.outcome for item in backup.constituents}
    if backup.status == "COMPLETED" and all(
        outcomes.get(name) == "completed" for name in deployments
    ):
        return
    shown = ", ".join(
        f"{name}: {outcome}" for name, outcome in sorted(outcomes.items())
    )
    raise ScenarioActionError(
        f"The environment backup ended {backup.status}, not COMPLETED for "
        f"{', '.join(deployments)} (constituents: {shown or 'none'})"
    )


def check_restore(restore: EnvironmentRestoreRef) -> None:
    """Raise unless the restore completed and skipped no deployment."""
    if restore.status == "COMPLETED" and not restore.skipped:
        return
    skipped = ", ".join(
        f"{item.deployment_name} ({item.reason})" for item in restore.skipped
    )
    raise ScenarioActionError(
        f"The environment restore ended {restore.status}"
        + (f" and skipped {skipped}" if skipped else "")
    )


def check_listed(
    names: Collection[str], name: str, *, listed: bool, where: str
) -> None:
    """Raise unless ``name`` is in ``names`` (``listed``) or is not in it."""
    if (name in names) == listed:
        return
    state = "does not list" if listed else "still lists"
    raise ScenarioActionError(
        f"{where} {state} {name!r}; it lists: {', '.join(names) or 'nothing'}"
    )


async def setup(context: DemoContext) -> Lab:
    """Deploy Infrahub and Semaphore, load the devices and the template, and log in to both."""
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
        version=semaphore_image.SEMAPHORE_VERSION,
        name="semaphore",
        parameters={"docker_image": semaphore_image.REPOSITORY},
    )
    infrahub_url = stack.service_url(infrahub, "infrahub")
    semaphore_url = stack.service_url(semaphore, "semaphore")
    await infrahub_setup.wait_until_ready(infrahub_url, timeout=READY_TIMEOUT)
    await infrahub_setup.load_devices(infrahub_url, DEVICES)
    project = await semaphore_setup.configure(
        semaphore_url, infrahub_token=INFRAHUB_ADMIN_TOKEN
    )
    # Log in before the recording; the sessions exist before the backup, so the restore keeps them.
    await InfrahubDevicesPage(context.page).log_in(infrahub_url)
    await SemaphoreTemplatesPage(context.page).log_in(semaphore_url)
    await EnvironmentDetailPage(context.page).goto(environment_id=environment_id)
    return Lab(
        environment_id=environment_id,
        infrahub_url=infrahub_url,
        semaphore_url=semaphore_url,
        semaphore=project,
    )


async def record(context: DemoContext, lab: Lab) -> None:
    recorder = context.recorder
    driver = UiScenarioDriver(
        page=context.page,
        base_url=context.styrmin_url,
        keystroke_delay_ms=KEYSTROKE_DELAY_MS,
    )
    driver.attach_to_deployment(environment_id=lab.environment_id)
    devices = InfrahubDevicesPage(context.page, keystroke_delay_ms=KEYSTROKE_DELAY_MS)
    templates = SemaphoreTemplatesPage(
        context.page, keystroke_delay_ms=KEYSTROKE_DELAY_MS
    )
    project_id = lab.semaphore.project_id
    template = semaphore_setup.TEMPLATE_NAME

    await recorder.caption(f"Styrmin: environment {ENVIRONMENT_NAME}")
    async with recorder.step("Back up the whole environment"):
        created = await driver.create_environment_backup(
            environment_id=lab.environment_id
        )
        async with recorder.wait("The backup runs"):
            backup = await driver.wait_for_environment_backup(
                environment_backup_id=created.id, max_wait=BACKUP_TIMEOUT
            )
        check_backup(backup, DEPLOYMENT_NAMES)
        await recorder.hold()

    async with recorder.step("Delete a device in Infrahub"):
        await recorder.caption(f"Infrahub in {ENVIRONMENT_NAME}")
        await devices.goto(lab.infrahub_url)
        check_listed(
            await devices.list_device_names(),
            DELETED_DEVICE,
            listed=True,
            where="Infrahub",
        )
        await recorder.hold(LIST_HOLD_SECONDS)
        await devices.delete_device(DELETED_DEVICE)
        await recorder.hold()

    # Semaphore shows a white page while it loads after a switch from another web application.
    async with recorder.cut():
        await recorder.caption(f"Semaphore in {ENVIRONMENT_NAME}")
        await templates.goto_template_list(lab.semaphore_url, project_id)
    async with recorder.step("Delete the task template in Semaphore"):
        check_listed(
            await templates.listed_template_names(),
            template,
            listed=True,
            where="Semaphore",
        )
        await recorder.hold(LIST_HOLD_SECONDS)
        await templates.open_template(template)
        await templates.delete_template()
        # Semaphore opens the template list after the deletion.
        check_listed(
            await templates.listed_template_names(),
            template,
            listed=False,
            where="Semaphore",
        )
        await recorder.hold()

    await recorder.caption(f"Styrmin: environment {ENVIRONMENT_NAME}")
    async with recorder.step("Restore the backup"):
        started = await driver.restore_environment_backup(
            environment_backup_id=backup.id
        )
        async with recorder.wait("The restore runs"):
            restore = await driver.wait_for_environment_restore(
                environment_restore_id=started.id, max_wait=RESTORE_TIMEOUT
            )
        check_restore(restore)
        await recorder.hold()
        async with recorder.wait("Infrahub restarts"):
            await infrahub_setup.wait_until_ready(
                lab.infrahub_url, timeout=READY_TIMEOUT
            )
        async with recorder.wait("Semaphore restarts"):
            await semaphore_setup.wait_until_ready(
                lab.semaphore_url, timeout=READY_TIMEOUT
            )

    async with recorder.step("The device and the template are back"):
        await recorder.caption(f"Infrahub in {ENVIRONMENT_NAME}")
        await devices.goto(lab.infrahub_url)
        check_listed(
            await devices.list_device_names(),
            DELETED_DEVICE,
            listed=True,
            where="Infrahub",
        )
        await recorder.hold()
        async with recorder.cut():
            await recorder.caption(f"Semaphore in {ENVIRONMENT_NAME}")
            await templates.goto_template_list(lab.semaphore_url, project_id)
        check_listed(
            await templates.listed_template_names(),
            template,
            listed=True,
            where="Semaphore",
        )
        await recorder.hold()
