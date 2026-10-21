"""Demo 0: on an empty demo stack, add the cluster and the backup storage location, load the Infrahub driver, and
create the environment that demo 1 deploys Infrahub into."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from tests.e2e.demos import stack
from tests.e2e.demos.recorder import LIST_HOLD_SECONDS
from tests.e2e.demos.scenarios import deploy_upgrade
from tests.e2e.pages.drivers_list import DriversListPage
from tests.e2e.pages.environments import EnvironmentDetailPage, EnvironmentsListPage
from tests.e2e.pages.settings import BackupStorageLocationsListPage, SettingsPage
from tests.e2e.pages.sidebar import SidebarPage

if TYPE_CHECKING:
    from tests.e2e.demos.catalog import DemoContext

CLUSTER_NAME = stack.CLUSTER_NAME
BACKUP_STORAGE_LOCATION_NAME = stack.BACKUP_STORAGE_LOCATION_NAME
ENVIRONMENT_NAME = deploy_upgrade.ENVIRONMENT_NAME
INFRAHUB_DRIVER_PATH = "/styrmin/drivers/infrahub"
# Demos 2 to 4 deploy Semaphore; the setup loads its driver before the recording.
SEMAPHORE_DRIVER_PATH = "/styrmin/drivers/semaphore"
KEYSTROKE_DELAY_MS = 90
# The cluster and the backup storage location get the values that `uv run invoke start` gives them (tasks/dev.py
# bootstrap and tasks/utils.py); a unit test compares the two.
INGRESS_CLASS = "traefik"
RUNTIME_CLASS = "default"
STORAGE_CLASS = "local-path"
GARAGE_ENDPOINT = "http://garage.styrmin.svc:3900"
GARAGE_BUCKET = "velero"
GARAGE_REGION = "garage"
GARAGE_ACCESS_KEY_ID = "GKdeadbeefdeadbeefdeadbeef"
# A value of the demo stack's Garage (dev/local/garage.yaml), not a secret.
GARAGE_SECRET_ACCESS_KEY = (
    "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"  # noqa: S105
)


def cluster_config(styrmin_url: str) -> dict[str, Any]:
    """Return the configuration of the demo cluster for the Styrmin at ``styrmin_url``.

    For ``http://styrmin.local.styrmin.io:8080``, each application's address ends in ``local.styrmin.io`` and
    uses the scheme ``http`` and the port 8080, the address of the demo stack's Traefik port-forward.
    """
    parts = urlsplit(styrmin_url)
    _, _, fqdn_suffix = (parts.hostname or "").partition(".")
    if not fqdn_suffix:
        raise ValueError(
            f"The Styrmin URL {styrmin_url!r} has no domain to give the applications"
        )
    config: dict[str, Any] = {
        "ingress_class": INGRESS_CLASS,
        "fqdn_suffix": fqdn_suffix,
        "runtime_class": RUNTIME_CLASS,
        "external_url_scheme": parts.scheme,
        "standard_storage": {"storage_class": STORAGE_CLASS},
        "fast_storage": {"storage_class": STORAGE_CLASS},
    }
    if parts.port is not None:
        config["external_url_port"] = parts.port
    return config


async def setup(context: DemoContext) -> None:
    """Load the Semaphore driver and open the Clusters page, where the recording starts."""
    await stack.load_local_driver(context.client, SEMAPHORE_DRIVER_PATH)
    await SettingsPage(context.page).goto()


async def record(context: DemoContext, _state: None) -> None:
    recorder = context.recorder
    page = context.page
    # The demo opens each page from the sidebar, as a viewer would.
    sidebar = SidebarPage(page)
    await recorder.caption("Styrmin")

    async with recorder.step("Add the Kubernetes cluster"):
        cluster = await SettingsPage(
            page, keystroke_delay_ms=KEYSTROKE_DELAY_MS
        ).create_cluster(
            name=CLUSTER_NAME,
            config=cluster_config(context.styrmin_url),
            open_page=False,
        )
        await recorder.hold()

    async with recorder.step("Add a backup storage location"):
        await sidebar.open("Backup Storage")
        location_id = await BackupStorageLocationsListPage(
            page, keystroke_delay_ms=KEYSTROKE_DELAY_MS
        ).create(
            name=BACKUP_STORAGE_LOCATION_NAME,
            endpoint=GARAGE_ENDPOINT,
            bucket=GARAGE_BUCKET,
            region=GARAGE_REGION,
            access_key_id=GARAGE_ACCESS_KEY_ID,
            secret_access_key=GARAGE_SECRET_ACCESS_KEY,
            open_page=False,
        )
        await recorder.hold()

    async with recorder.step("Load the Infrahub driver"):
        await sidebar.open("Drivers")
        await DriversListPage(
            page, keystroke_delay_ms=KEYSTROKE_DELAY_MS
        ).load_local_version(path=INFRAHUB_DRIVER_PATH, open_page=False)
        await recorder.hold()

    environments = EnvironmentsListPage(page, keystroke_delay_ms=KEYSTROKE_DELAY_MS)
    async with recorder.step("Create the environment"):
        await sidebar.open("Environments")
        environment = await environments.create_environment(
            name=ENVIRONMENT_NAME, cluster_id=cluster.id, config={}, open_page=False
        )
        await recorder.hold(LIST_HOLD_SECONDS)

    async with recorder.step(
        f"Keep the environment's backups in {BACKUP_STORAGE_LOCATION_NAME}"
    ):
        await environments.open_card(environment_id=environment.id)
        await recorder.caption(f"Styrmin: environment {ENVIRONMENT_NAME}")
        await EnvironmentDetailPage(page).assign_bsl(
            environment_id=environment.id, bsl_id=location_id, open_page=False
        )
        await recorder.hold()
