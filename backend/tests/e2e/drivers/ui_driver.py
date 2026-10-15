"""UiScenarioDriver — satisfies the ScenarioDriver protocol via Playwright.

Composes page objects under :mod:`tests.e2e.pages`. Every action navigates
from the product's normal entry points (no hidden routes) and ends on a
deterministic success signal (toast, badge transition, or navigation
complete) so scenarios never need their own sleeps.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, TYPE_CHECKING
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
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
    EnvironmentBackupRef,
    EnvironmentCloneRef,
    EnvironmentRef,
    EnvironmentRestoreRef,
    RestoreRef,
    TERMINAL_ENVIRONMENT_OPERATION_STATUSES,
    TimelineEntry,
)
from tests.e2e.pages.deploy_form import DeployFormPage
from tests.e2e.pages.deployment_detail import DeploymentDetailPage
from tests.e2e.pages.drivers_list import DriversListPage
from tests.e2e.pages.environments import (
    EnvironmentBackupsTabPage,
    EnvironmentClonesTabPage,
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


def _deployment_id_from_url(url: str) -> str | None:
    """Extract the deployment id from a ``.../deployments/<id>/...`` URL."""
    path = urlparse(url).path
    parts = [p for p in path.split("/") if p]
    if "deployments" not in parts:
        return None
    index = parts.index("deployments")
    if index + 1 >= len(parts):
        return None
    return parts[index + 1]


@asynccontextmanager
async def _ui_errors(action: str) -> AsyncIterator[None]:
    """Normalise Playwright exceptions into the ScenarioDriver hierarchy.

    - ``PlaywrightTimeoutError`` → ``ScenarioTimeout`` (flake-triage bucket).
    - Any other ``playwright.async_api.Error`` (TargetClosedError, detached
      handles, evaluation failures, navigation errors) → ``ScenarioActionError``
      so scenarios never see a raw Playwright traceback.
    - ``ScenarioActionError`` / subclasses pass through unchanged so page
      objects can raise descriptive errors from inside the block.
    """
    try:
        yield
    except PlaywrightTimeoutError as exc:
        raise ScenarioTimeout(f"UI timeout while {action}: {exc}") from exc
    except ScenarioActionError:
        raise
    except PlaywrightError as exc:
        raise ScenarioActionError(
            f"UI error while {action} ({type(exc).__name__}): {exc}"
        ) from exc


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
        self._environment_backups = EnvironmentBackupsTabPage(page)
        self._environment_clones = EnvironmentClonesTabPage(page)
        # environment_id passed into create_deployment — stashed so
        # wait_for_deployment_running can build the detail URL without
        # re-receiving it (matches ApiScenarioDriver's signature).
        self._environment_id: str | None = None
        # The deployment whose detail page the backup/restore flow acts on.
        # Stamped by every call that navigates to a deployment detail page, so
        # ``_ensure_deployment_detail`` can verify the page shows *that*
        # deployment rather than merely some deployment (see its docstring).
        self._deployment_id: str | None = None
        # environment_backup_id -> environment_id, and
        # environment_restore_id -> environment_backup_id. The
        # environment-level read methods only carry the child's id, but the UI
        # flow lives inside the owning environment's Backups tab (and, for a
        # restore, inside its snapshot row's expansion), so the owner has to be
        # remembered from the call that created it.
        self._environment_backup_owners: dict[str, str] = {}
        self._environment_restore_owners: dict[str, str] = {}
        # environment_clone_id -> the clone's *source* environment_id. The
        # Clones tab is scoped by source, so reading a clone by its own id needs
        # the environment whose tab lists it; the only call that carries it is
        # the one that created the clone.
        self._environment_clone_owners: dict[str, str] = {}

    def attach_to_deployment(self, *, environment_id: str) -> None:
        """Bind this driver to an environment without going through create_deployment.

        Use when a scenario observes a deployment it did not itself create
        (e.g. fixtures that deploy via the SDK then assert via the UI). The
        API driver has no analogue — environment is re-derived from each
        call's arguments — so scenarios that need both drivers should prefer
        ``create_deployment`` when possible.
        """
        self._environment_id = environment_id

    # --- Platform setup ---------------------------------------------------

    async def create_cluster(self, *, name: str, config: dict[str, Any]) -> ClusterRef:
        async with _ui_errors(f"creating cluster {name!r}"):
            return await self._settings.create_cluster(name=name, config=config)

    async def create_environment(
        self, *, name: str, cluster_id: str, config: dict[str, Any]
    ) -> EnvironmentRef:
        async with _ui_errors(f"creating environment {name!r}"):
            return await self._environments_list.create_environment(
                name=name, cluster_id=cluster_id, config=config
            )

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
        async with _ui_errors(f"creating BSL {name!r}"):
            bsl_id = await self._bsl_list.create(
                name=name,
                endpoint=endpoint,
                bucket=bucket,
                region=region,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            )
        return BSLRef(id=bsl_id, name=name)

    async def assign_bsl_to_environment(
        self, *, environment_id: str, bsl_id: str
    ) -> None:
        async with _ui_errors(f"assigning BSL {bsl_id!r} to env {environment_id!r}"):
            await self._environment_detail.assign_bsl(
                environment_id=environment_id, bsl_id=bsl_id
            )

    async def load_driver_version(self, *, git_url: str, ref: str) -> DriverVersionRef:
        async with _ui_errors(f"loading driver {git_url!r}@{ref!r}"):
            return await self._drivers_list.load_remote_version(
                git_url=git_url, ref=ref
            )

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

        async with _ui_errors("creating deployment"):
            await self._deploy_form.goto(environment_id=environment_id)
            await self._deploy_form.fill(
                driver=driver,
                version=version,
                name=effective_name,
                parameters=parameters,
                service_name_overrides=service_name_overrides,
            )
            deployment = await self._deploy_form.submit()
            self._deployment_id = deployment.id
            return deployment

    async def wait_for_deployment_running(
        self, *, deployment_id: str, timeout: float = 300.0
    ) -> DeploymentRef:
        environment_id = self._require_environment_context(deployment_id=deployment_id)
        self._deployment_id = deployment_id
        async with _ui_errors(
            f"waiting for deployment {deployment_id} to reach 'running'"
        ):
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
        return DeploymentRef(
            id=deployment_id,
            status="running",
            application_version=application_version,
            instance_id=instance_id,
        )

    async def upgrade_deployment(
        self,
        *,
        deployment_id: str,
        version: str,
        driver_version_id: str | None = None,
    ) -> None:
        environment_id = self._require_environment_context(deployment_id=deployment_id)
        async with _ui_errors(f"upgrading deployment {deployment_id}"):
            await self._deployment_detail.goto(
                environment_id=environment_id, deployment_id=deployment_id
            )
            await self._deployment_detail.open_upgrade_dialog()
            await self._deployment_detail.confirm_upgrade(
                version=version, driver_version_id=driver_version_id
            )

    async def update_deployment(
        self, *, deployment_id: str, config: dict[str, Any]
    ) -> None:
        # ``config`` is the test-friendly dict shape (see protocol docstring).
        # The Edit Scheduling dialog only surfaces the ``scheduling`` sub-tree
        # today — mirroring the frontend form's scope. Scenarios that need to
        # mutate other config keys via UI must grow the dialog first.
        scheduling = config.get("scheduling")
        if not isinstance(scheduling, dict):
            raise ScenarioActionError(
                "UI driver only supports update_deployment with a "
                "``config['scheduling']`` sub-tree; other keys are not "
                "editable through the frontend yet"
            )
        unsupported = set(config.keys()) - {"scheduling"}
        if unsupported:
            raise ScenarioActionError(
                "UI driver's update_deployment only accepts the "
                f"'scheduling' key; got unsupported keys: {sorted(unsupported)}"
            )
        environment_id = self._require_environment_context(deployment_id=deployment_id)
        async with _ui_errors(f"updating scheduling for deployment {deployment_id}"):
            await self._deployment_detail.goto(
                environment_id=environment_id, deployment_id=deployment_id
            )
            await self._deployment_detail.open_scheduling_dialog()
            await self._deployment_detail.fill_scheduling_config(scheduling)
            await self._deployment_detail.save_scheduling_config()

    async def set_component_env_vars(
        self, *, deployment_id: str, component: str, env_vars: dict[str, str]
    ) -> None:
        environment_id = self._require_environment_context(deployment_id=deployment_id)
        self._deployment_id = deployment_id
        async with _ui_errors(
            f"setting env vars on component {component!r} of deployment {deployment_id}"
        ):
            await self._deployment_detail.goto(
                environment_id=environment_id, deployment_id=deployment_id
            )
            await self._deployment_detail.set_component_env_vars(
                component=component, env_vars=env_vars
            )

    async def set_component_image(
        self, *, deployment_id: str, component: str, image: str | None
    ) -> None:
        environment_id = self._require_environment_context(deployment_id=deployment_id)
        self._deployment_id = deployment_id
        async with _ui_errors(
            f"setting the image on component {component!r} of deployment {deployment_id}"
        ):
            await self._deployment_detail.goto(
                environment_id=environment_id, deployment_id=deployment_id
            )
            await self._deployment_detail.set_component_image(
                component=component, image=image
            )

    async def set_component_container_override(
        self,
        *,
        deployment_id: str,
        component: str,
        command: list[str] | None,
        args: list[str] | None,
    ) -> None:
        environment_id = self._require_environment_context(deployment_id=deployment_id)
        self._deployment_id = deployment_id
        async with _ui_errors(
            f"setting command and args on component {component!r} of deployment "
            f"{deployment_id}"
        ):
            await self._deployment_detail.goto(
                environment_id=environment_id, deployment_id=deployment_id
            )
            await self._deployment_detail.set_component_container_override(
                component=component, command=command, args=args
            )

    async def set_component_replicas(
        self, *, deployment_id: str, component: str, replicas: int | None
    ) -> None:
        environment_id = self._require_environment_context(deployment_id=deployment_id)
        self._deployment_id = deployment_id
        async with _ui_errors(
            f"setting replicas on component {component!r} of deployment {deployment_id}"
        ):
            await self._deployment_detail.goto(
                environment_id=environment_id, deployment_id=deployment_id
            )
            await self._deployment_detail.set_component_replicas(
                component=component, replicas=replicas
            )

    async def pinned_image_components(
        self, *, deployment_id: str, target_version: str
    ) -> list[str]:
        environment_id = self._require_environment_context(deployment_id=deployment_id)
        self._deployment_id = deployment_id
        async with _ui_errors(
            f"reading pinned image overrides of deployment {deployment_id}"
        ):
            await self._deployment_detail.goto(
                environment_id=environment_id, deployment_id=deployment_id
            )
            return await self._deployment_detail.read_pinned_image_warning(
                target_version
            )

    async def update_environment_via_form(
        self,
        *,
        environment_id: str,
        env_vars: dict[str, str],
    ) -> None:
        """Drive the env-vars form on the Configuration tab.

        Per 011-env-config-input-hardening / US4 (data-model §4.2): goto
        ``/environments/{environment_id}``, open the Configuration tab,
        append a row for each ``(name, value)`` via "Add Variable", click
        Save, confirm the redeploy dialog, and wait for the page to
        return to the read state. The page object owns the selector
        details so this driver method stays a thin coordinator.
        """
        async with _ui_errors(
            f"updating env vars on environment {environment_id} via form"
        ):
            await self._environment_detail.update_env_vars_via_form(
                environment_id=environment_id, env_vars=env_vars
            )

    async def set_environment_backup_ttl(
        self,
        *,
        environment_id: str,
        ttl: str | None,
    ) -> None:
        """Drive the BackupRetentionForm on the Configuration tab (016).

        Per 016-backup-retention-ttl / US1: goto
        ``/environments/{environment_id}``, open the Configuration tab, type
        the duration into the retention input (blank for ``ttl=None``, the
        form's "clear the policy" gesture), click Save, and confirm the
        redeploy dialog. The page object owns the selector details so this
        driver method stays a thin coordinator.
        """
        async with _ui_errors(
            f"setting backup retention {ttl!r} on environment {environment_id}"
        ):
            await self._environment_detail.set_backup_ttl_via_form(
                environment_id=environment_id, ttl=ttl
            )

    async def get_deployment_timeline(
        self, *, deployment_id: str
    ) -> list[TimelineEntry]:
        environment_id = self._require_environment_context(deployment_id=deployment_id)
        async with _ui_errors(f"reading timeline for deployment {deployment_id}"):
            await self._deployment_detail.goto(
                environment_id=environment_id, deployment_id=deployment_id
            )
            return await self._deployment_detail.read_timeline()

    def _require_environment_context(self, *, deployment_id: str) -> str:
        # Prefer the explicitly-stashed environment_id (set by create_deployment
        # or attach_to_deployment); fall back to parsing the current URL so a
        # scenario that navigated manually before calling a deployment op
        # still works. If neither is available, fail loudly rather than
        # letting a downstream page.goto land on a malformed URL.
        env_id = self._environment_id or _environment_id_from_url(self._page.url)
        if env_id is None:
            raise ScenarioActionError(
                "UI driver has no environment context for "
                f"deployment_id={deployment_id!r}; call create_deployment, "
                "attach_to_deployment, or navigate to a deployment page first"
            )
        return env_id

    # --- Backup / Restore -------------------------------------------------
    #
    # These methods act on the deployment detail page of whichever deployment
    # this driver is bound to. ``create_backup`` does not need ``instance_id``
    # in the UI flow — the page already knows which instance it's showing — but
    # we accept it for protocol parity.

    async def _ensure_deployment_detail(self) -> None:
        """Ensure the page shows the deployment this driver is bound to.

        Checking only for ``"/deployments/"`` in the URL is not enough: the
        Playwright ``Page`` is **session-scoped and shared** across every
        scenario in the run, so a sibling test can leave a *different*
        deployment's detail page open. A scenario that never navigated itself
        (``test_restore_lifecycle_transitions`` and the MariaDB/MongoDB
        lifecycle both drive ``create_backup`` off the session driver without
        calling ``wait_for_deployment_running`` first) would then back up
        whichever deployment happened to be on screen — passing for the wrong
        reason, and silently changing target if collection order ever changed.

        So the bound deployment id is compared against the URL and the page is
        re-navigated when it has drifted, which is what the previous comment
        here promised but the code never did. Falling back to the id parsed out
        of the current URL preserves the old behaviour for a scenario that
        navigated by hand and never told the driver which deployment it means.
        """
        deployment_id = self._deployment_id or _deployment_id_from_url(self._page.url)
        if deployment_id is None:
            raise ScenarioActionError(
                "UI driver can't open backup/restore flow — no deployment "
                f"detail page is active and no deployment is bound (current "
                f"URL: {self._page.url}); call create_deployment or "
                "wait_for_deployment_running first"
            )
        if _deployment_id_from_url(self._page.url) != deployment_id:
            environment_id = self._require_environment_context(
                deployment_id=deployment_id
            )
            await self._deployment_detail.goto(
                environment_id=environment_id, deployment_id=deployment_id
            )

    async def create_backup(self, *, instance_id: str) -> BackupRef:  # noqa: ARG002
        async with _ui_errors("creating backup"):
            await self._ensure_deployment_detail()
            return await self._deployment_detail.create_backup()

    async def wait_for_backup(
        self, *, backup_id: str, max_wait: float = 300.0
    ) -> BackupRef:
        async with _ui_errors(f"waiting for backup {backup_id}"):
            await self._ensure_deployment_detail()
            await self._deployment_detail.open_backups_tab()
            return await self._deployment_detail.wait_for_backup_status(
                backup_id=backup_id,
                terminal_statuses=("completed", "failed"),
                max_wait=max_wait,
            )

    async def create_restore(
        self, *, backup_id: str, target_namespace: str
    ) -> RestoreRef:
        async with _ui_errors(f"creating restore from backup {backup_id}"):
            await self._ensure_deployment_detail()
            return await self._deployment_detail.create_restore(
                backup_id=backup_id, target_namespace=target_namespace
            )

    async def wait_for_restore(
        self, *, restore_id: str, max_wait: float = 600.0
    ) -> RestoreRef:
        async with _ui_errors(f"waiting for restore {restore_id}"):
            await self._ensure_deployment_detail()
            await self._deployment_detail.open_backups_tab()
            return await self._deployment_detail.wait_for_restore_status(
                restore_id=restore_id,
                terminal_statuses=("completed", "failed"),
                max_wait=max_wait,
            )

    async def delete_backup(self, *, backup_id: str) -> None:
        async with _ui_errors(f"deleting backup {backup_id}"):
            await self._ensure_deployment_detail()
            await self._deployment_detail.delete_backup(backup_id=backup_id)

    async def get_backup(self, *, backup_id: str) -> BackupRef:
        async with _ui_errors(f"reading backup {backup_id}"):
            await self._ensure_deployment_detail()
            await self._deployment_detail.open_backups_tab()
            ref = await self._deployment_detail.read_backup(backup_id=backup_id)
        if ref is None:
            raise ResourceNotFound(
                f"backup {backup_id} is not listed on the deployment detail page"
            )
        return ref

    async def list_backups(self, *, deployment_id: str) -> tuple[BackupRef, ...]:
        self._deployment_id = deployment_id
        async with _ui_errors(f"listing backups of deployment {deployment_id}"):
            await self._ensure_deployment_detail()
            return await self._deployment_detail.read_backups()

    # --- Environment-level backup / restore -------------------------------
    #
    # Driven from the Backups tab on the environment detail page. The tab's
    # ``data-*`` hooks carry the raw derived-status enum values and the
    # free-text skip reasons, so these refs are identical to the API driver's.

    def _owning_environment(self, *, environment_backup_id: str) -> str:
        """Resolve which environment's Backups tab holds a snapshot."""
        environment_id = (
            self._environment_backup_owners.get(environment_backup_id)
            or self._environment_id
        )
        if environment_id is None:
            raise ScenarioActionError(
                "UI driver has no environment context for environment backup "
                f"{environment_backup_id!r}; call create_environment_backup or "
                "attach_to_deployment first"
            )
        return environment_id

    async def create_environment_backup(
        self, *, environment_id: str
    ) -> EnvironmentBackupRef:
        async with _ui_errors(f"creating environment backup on {environment_id}"):
            ref = await self._environment_backups.create_backup(
                environment_id=environment_id
            )
        self._environment_backup_owners[ref.id] = environment_id
        return ref

    async def get_environment_backup(
        self, *, environment_backup_id: str
    ) -> EnvironmentBackupRef:
        environment_id = self._owning_environment(
            environment_backup_id=environment_backup_id
        )
        async with _ui_errors(f"reading environment backup {environment_backup_id}"):
            ref = await self._environment_backups.read_backup(
                environment_id=environment_id,
                environment_backup_id=environment_backup_id,
            )
        if ref is None:
            raise ResourceNotFound(
                f"environment backup {environment_backup_id} is not listed on the "
                f"Backups tab of environment {environment_id}"
            )
        return ref

    async def wait_for_environment_backup(
        self, *, environment_backup_id: str, max_wait: float = 600.0
    ) -> EnvironmentBackupRef:
        environment_id = self._owning_environment(
            environment_backup_id=environment_backup_id
        )
        async with _ui_errors(
            f"waiting for environment backup {environment_backup_id}"
        ):
            return await self._environment_backups.wait_for_backup_status(
                environment_id=environment_id,
                environment_backup_id=environment_backup_id,
                terminal_statuses=TERMINAL_ENVIRONMENT_OPERATION_STATUSES,
                max_wait=max_wait,
            )

    async def restore_environment_backup(
        self, *, environment_backup_id: str
    ) -> EnvironmentRestoreRef:
        environment_id = self._owning_environment(
            environment_backup_id=environment_backup_id
        )
        async with _ui_errors(f"restoring environment backup {environment_backup_id}"):
            ref = await self._environment_backups.restore_backup(
                environment_id=environment_id,
                environment_backup_id=environment_backup_id,
            )
        self._environment_restore_owners[ref.id] = environment_backup_id
        return ref

    async def wait_for_environment_restore(
        self, *, environment_restore_id: str, max_wait: float = 900.0
    ) -> EnvironmentRestoreRef:
        environment_backup_id = self._environment_restore_owners.get(
            environment_restore_id
        )
        if environment_backup_id is None:
            raise ScenarioActionError(
                "UI driver has no snapshot context for environment restore "
                f"{environment_restore_id!r}; the restore panel lives inside its "
                "snapshot row, so restore_environment_backup must have created it"
            )
        environment_id = self._owning_environment(
            environment_backup_id=environment_backup_id
        )
        async with _ui_errors(
            f"waiting for environment restore {environment_restore_id}"
        ):
            return await self._environment_backups.wait_for_restore_status(
                environment_id=environment_id,
                environment_backup_id=environment_backup_id,
                environment_restore_id=environment_restore_id,
                terminal_statuses=TERMINAL_ENVIRONMENT_OPERATION_STATUSES,
                max_wait=max_wait,
            )

    async def delete_environment_backup(self, *, environment_backup_id: str) -> None:
        environment_id = self._owning_environment(
            environment_backup_id=environment_backup_id
        )
        async with _ui_errors(f"deleting environment backup {environment_backup_id}"):
            await self._environment_backups.delete_backup(
                environment_id=environment_id,
                environment_backup_id=environment_backup_id,
            )

    # --- Environment clone ------------------------------------------------
    #
    # Driven from the Clones tab on the *source* environment's detail page: the
    # tab lists the clones taken **of** that environment, and the clone dialog's
    # trigger lives in its section header.

    def _owning_source_environment(self, *, environment_clone_id: str) -> str:
        """Resolve which environment's Clones tab lists a clone record."""
        environment_id = (
            self._environment_clone_owners.get(environment_clone_id)
            or self._environment_id
        )
        if environment_id is None:
            raise ScenarioActionError(
                "UI driver has no source-environment context for environment "
                f"clone {environment_clone_id!r}; the Clones tab is scoped by "
                "source, so clone_environment or attach_to_deployment must have "
                "named the environment first"
            )
        return environment_id

    async def clone_environment(
        self,
        *,
        environment_id: str,
        name: str,
        deployment_ids: list[str] | None = None,
        config_override: dict[str, Any] | None = None,
        clear_config_fields: list[str] | None = None,
    ) -> EnvironmentCloneRef:
        async with _ui_errors(f"cloning environment {environment_id} into {name!r}"):
            ref = await self._environment_clones.create_clone(
                environment_id=environment_id,
                name=name,
                deployment_ids=deployment_ids,
                config_override=config_override,
                clear_config_fields=clear_config_fields,
            )
        self._environment_clone_owners[ref.id] = environment_id
        return ref

    async def get_environment_clone(
        self, *, environment_clone_id: str
    ) -> EnvironmentCloneRef:
        environment_id = self._owning_source_environment(
            environment_clone_id=environment_clone_id
        )
        async with _ui_errors(f"reading environment clone {environment_clone_id}"):
            ref = await self._environment_clones.read_clone(
                environment_id=environment_id,
                environment_clone_id=environment_clone_id,
            )
        if ref is None:
            raise ResourceNotFound(
                f"environment clone {environment_clone_id} is not listed on the "
                f"Clones tab of environment {environment_id}"
            )
        return ref

    async def wait_for_environment_clone(
        self, *, environment_clone_id: str, max_wait: float = 1800.0
    ) -> EnvironmentCloneRef:
        environment_id = self._owning_source_environment(
            environment_clone_id=environment_clone_id
        )
        async with _ui_errors(f"waiting for environment clone {environment_clone_id}"):
            return await self._environment_clones.wait_for_clone_status(
                environment_id=environment_id,
                environment_clone_id=environment_clone_id,
                terminal_statuses=TERMINAL_ENVIRONMENT_OPERATION_STATUSES,
                max_wait=max_wait,
            )
