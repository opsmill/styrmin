"""UiScenarioDriver — satisfies the ScenarioDriver protocol via Playwright.

Composes page objects under :mod:`tests.e2e.pages`. Every action navigates
from the product's normal entry points (no hidden routes) and ends on a
deterministic success signal (toast, badge transition, or navigation
complete) so scenarios never need their own sleeps.
"""

from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING
from urllib.parse import urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from tests.e2e.drivers.errors import (
    ResourceNotFound,
    ScenarioActionError,
    ScenarioTimeout,
)
from tests.e2e.drivers.refs import (
    BackupRef,
    BSLRef,
    ClusterRef,
    DeploymentRef,
    DriverVersionRef,
    EnvironmentRef,
    RestoreRef,
    TimelineEntry,
)
from tests.e2e.pages.deploy_form import DeployFormPage
from tests.e2e.pages.deployment_detail import DeploymentDetailPage
from tests.e2e.pages.drivers_list import DriversListPage
from tests.e2e.pages.environments import (
    EnvironmentDetailPage,
    EnvironmentsListPage,
)
from tests.e2e.pages.settings import (
    BackupStorageLocationsListPage,
    SettingsPage,
)

if TYPE_CHECKING:
    from playwright.async_api import Page


def _environment_id_from_url(url: str) -> str | None:
    """Extract the environment id from a ``/environments/<id>/...`` URL."""
    path = urlparse(url).path
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "environments":
        return parts[1]
    return None


class UiScenarioDriver:
    def __init__(self, *, page: Page, base_url: str) -> None:
        self._page = page
        self._base_url = base_url.rstrip("/")
        self._deploy_form = DeployFormPage(page)
        self._deployment_detail = DeploymentDetailPage(page)
        self._settings = SettingsPage(page)
        self._bsl_list = BackupStorageLocationsListPage(page)
        self._drivers_list = DriversListPage(page)
        self._environments_list = EnvironmentsListPage(page)
        self._environment_detail = EnvironmentDetailPage(page)
        # environment_id passed into create_deployment — stashed so
        # wait_for_deployment_running can build the detail URL without
        # re-receiving it (matches ApiScenarioDriver's signature).
        self._environment_id: str | None = None

    # --- Platform setup ---------------------------------------------------

    async def create_cluster(self, *, name: str, config: dict[str, Any]) -> ClusterRef:
        try:
            return await self._settings.create_cluster(name=name, config=config)
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                f"UI timeout creating cluster {name!r}: {exc}"
            ) from exc

    async def create_environment(
        self, *, name: str, cluster_id: str, config: dict[str, Any]
    ) -> EnvironmentRef:
        try:
            return await self._environments_list.create_environment(
                name=name, cluster_id=cluster_id, config=config
            )
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                f"UI timeout creating environment {name!r}: {exc}"
            ) from exc

    async def delete_environment(self, *, environment_id: str) -> None:
        raise ScenarioActionError(
            "UI driver does not support delete_environment: the frontend does "
            "not expose a delete-environment surface. Scenarios relying on "
            "deletion must be marked api_only, or delete via the SDK in a "
            "fixture teardown."
        )

    async def create_backup_storage_location(
        self,
        *,
        name: str,
        endpoint: str,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> BSLRef:
        try:
            bsl_id = await self._bsl_list.create(
                name=name,
                endpoint=endpoint,
                bucket=bucket,
                region=region,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            )
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(f"UI timeout creating BSL {name!r}: {exc}") from exc
        return BSLRef(id=bsl_id, name=name)

    async def assign_bsl_to_environment(
        self, *, environment_id: str, bsl_id: str
    ) -> None:
        try:
            await self._environment_detail.assign_bsl(
                environment_id=environment_id, bsl_id=bsl_id
            )
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                f"UI timeout assigning BSL {bsl_id!r} to env {environment_id!r}: {exc}"
            ) from exc

    async def load_driver_version(self, *, git_url: str, ref: str) -> DriverVersionRef:
        try:
            return await self._drivers_list.load_remote_version(
                git_url=git_url, ref=ref
            )
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                f"UI timeout loading driver {git_url!r}@{ref!r}: {exc}"
            ) from exc

    # --- Deployments ------------------------------------------------------

    async def create_deployment(
        self,
        *,
        driver: str,
        version: str,
        environment_id: str,
        name: str | None = None,
        service_name_overrides: list[dict[str, str]] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> DeploymentRef:
        self._environment_id = environment_id
        # Deploy form requires a deployment name; scenarios that don't care
        # let us auto-generate one. Both entrypoints remain identical from
        # the scenario's point of view (which does not assert on the name).
        effective_name = name or f"scenario-{uuid.uuid4().hex[:8]}"

        try:
            await self._deploy_form.goto(environment_id=environment_id)
            await self._deploy_form.fill(
                driver=driver,
                version=version,
                name=effective_name,
                parameters=parameters,
                service_name_overrides=service_name_overrides,
            )
            return await self._deploy_form.submit()
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                f"UI timeout while creating deployment: {exc}"
            ) from exc

    async def wait_for_deployment_running(
        self, *, deployment_id: str, timeout: float = 300.0
    ) -> DeploymentRef:
        environment_id = self._require_environment_context(deployment_id=deployment_id)
        try:
            await self._deployment_detail.goto(
                environment_id=environment_id, deployment_id=deployment_id
            )
            await self._deployment_detail.wait_for_status(
                expected="running", timeout=timeout
            )
            instance_id = await self._deployment_detail.read_instance_id()
            application_version = (
                await self._deployment_detail.read_application_version()
            )
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                f"UI timeout waiting for deployment {deployment_id} "
                f"to reach 'running': {exc}"
            ) from exc
        return DeploymentRef(
            id=deployment_id,
            status="running",
            application_version=application_version,
            instance_id=instance_id,
        )

    async def upgrade_deployment(self, *, deployment_id: str, version: str) -> None:
        environment_id = self._require_environment_context(deployment_id=deployment_id)
        try:
            await self._deployment_detail.goto(
                environment_id=environment_id, deployment_id=deployment_id
            )
            await self._deployment_detail.open_upgrade_dialog()
            await self._deployment_detail.confirm_upgrade(version=version)
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                f"UI timeout upgrading deployment {deployment_id}: {exc}"
            ) from exc

    async def get_deployment_timeline(
        self, *, deployment_id: str
    ) -> list[TimelineEntry]:
        environment_id = self._require_environment_context(deployment_id=deployment_id)
        try:
            await self._deployment_detail.goto(
                environment_id=environment_id, deployment_id=deployment_id
            )
            return await self._deployment_detail.read_timeline()
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                f"UI timeout reading timeline for deployment {deployment_id}: {exc}"
            ) from exc

    def _require_environment_context(self, *, deployment_id: str) -> str:
        env_id = self._environment_id or _environment_id_from_url(self._page.url)
        if env_id is None:
            raise ScenarioActionError(
                "UI driver has no environment context for "
                f"deployment_id={deployment_id!r}; call create_deployment or "
                "navigate to a deployment page first"
            )
        return env_id

    # --- Backup / Restore -------------------------------------------------
    #
    # These methods assume the UI driver has already navigated to (or can
    # re-enter) the correct deployment detail page. ``create_backup`` does
    # not need ``instance_id`` in the UI flow — the page already knows which
    # instance it's showing — but we accept it for protocol parity and fall
    # back to re-navigating if the URL has drifted.

    async def _ensure_deployment_detail(self) -> None:
        """Ensure the Playwright page is on a deployment detail URL."""
        path = self._page.url
        if "/deployments/" not in path:
            raise ScenarioActionError(
                "UI driver can't open backup/restore flow — no deployment "
                f"detail page is active (current URL: {path})"
            )

    async def create_backup(self, *, instance_id: str) -> BackupRef:  # noqa: ARG002
        try:
            await self._ensure_deployment_detail()
            return await self._deployment_detail.create_backup()
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(f"UI timeout creating backup: {exc}") from exc

    async def wait_for_backup(
        self, *, backup_id: str, max_wait: float = 300.0
    ) -> BackupRef:
        try:
            await self._ensure_deployment_detail()
            await self._deployment_detail.open_backups_tab()
            return await self._deployment_detail.wait_for_backup_status(
                backup_id=backup_id,
                terminal_statuses=("completed", "failed"),
                max_wait=max_wait,
            )
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                f"UI timeout waiting for backup {backup_id}: {exc}"
            ) from exc

    async def create_restore(
        self, *, backup_id: str, target_namespace: str
    ) -> RestoreRef:
        try:
            await self._ensure_deployment_detail()
            return await self._deployment_detail.create_restore(
                backup_id=backup_id, target_namespace=target_namespace
            )
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(f"UI timeout creating restore: {exc}") from exc

    async def wait_for_restore(
        self, *, restore_id: str, max_wait: float = 600.0
    ) -> RestoreRef:
        try:
            await self._ensure_deployment_detail()
            await self._deployment_detail.open_backups_tab()
            return await self._deployment_detail.wait_for_restore_status(
                restore_id=restore_id,
                terminal_statuses=("completed", "failed"),
                max_wait=max_wait,
            )
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                f"UI timeout waiting for restore {restore_id}: {exc}"
            ) from exc

    async def delete_backup(self, *, backup_id: str) -> None:
        try:
            await self._ensure_deployment_detail()
            await self._deployment_detail.delete_backup(backup_id=backup_id)
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                f"UI timeout deleting backup {backup_id}: {exc}"
            ) from exc

    async def get_backup(self, *, backup_id: str) -> BackupRef:
        try:
            await self._ensure_deployment_detail()
            await self._deployment_detail.open_backups_tab()
            ref = await self._deployment_detail.read_backup(backup_id=backup_id)
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                f"UI timeout reading backup {backup_id}: {exc}"
            ) from exc
        if ref is None:
            raise ResourceNotFound(
                f"backup {backup_id} is not listed on the deployment detail page"
            )
        return ref
