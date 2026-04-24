"""ScenarioDriver protocol — the test-side abstraction that makes the API
and UI entrypoints interchangeable in the E2E suite.

Implementations MUST:
  - Return the driver-neutral ref types from ``refs`` (never SDK models or
    Playwright Locators).
  - Raise ScenarioActionError / ResourceNotFound — never propagate
    implementation-specific exceptions.
  - End each action on a deterministic success signal so that callers
    never need to add their own sleeps.

Ordering contract (UI-driver specific but observable through this protocol):
  Deployment operations (``wait_for_deployment_running``, ``upgrade_deployment``,
  ``get_deployment_timeline``, ``create_backup`` …) require the driver to know
  the owning environment. ``create_deployment`` sets that context implicitly;
  scenarios that observe a deployment created elsewhere must navigate the UI
  driver to it first (see ``UiScenarioDriver.attach_to_deployment``) or accept
  a ``ScenarioActionError``.

Entrypoint asymmetry:
  ``create_deployment(parameters=...)`` is API-only today — the UI driver
  rejects non-empty ``parameters`` with ``ScenarioActionError``. Scenarios
  exercising parameters must mark themselves ``api_only``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class ScenarioDriver(Protocol):
    # --- Platform setup ---------------------------------------------------

    async def create_cluster(
        self, *, name: str, config: dict[str, Any]
    ) -> ClusterRef: ...

    async def create_environment(
        self, *, name: str, cluster_id: str, config: dict[str, Any]
    ) -> EnvironmentRef: ...

    async def delete_environment(self, *, environment_id: str) -> None: ...

    async def create_backup_storage_location(
        self,
        *,
        name: str,
        endpoint: str,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> BSLRef: ...

    async def assign_bsl_to_environment(
        self, *, environment_id: str, bsl_id: str
    ) -> None: ...

    async def load_driver_version(
        self, *, git_url: str, ref: str
    ) -> DriverVersionRef: ...

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
    ) -> DeploymentRef: ...

    def attach_to_deployment(self, *, environment_id: str) -> None:
        """Bind the driver to an environment without going through ``create_deployment``.

        Use when a scenario observes a deployment created by a module-scoped
        fixture (which creates via the session-scoped driver) and then uses
        the function-scoped driver for subsequent operations — the function-
        scoped instance has not seen the environment yet. API driver
        implementations may be no-ops since they re-derive the environment
        from each call's arguments.
        """

    async def wait_for_deployment_running(
        self, *, deployment_id: str, timeout: float = 300.0
    ) -> DeploymentRef: ...

    async def upgrade_deployment(self, *, deployment_id: str, version: str) -> None: ...

    async def update_deployment(
        self, *, deployment_id: str, config: dict[str, Any]
    ) -> None:
        """Submit a new ``config`` for an existing deployment.

        The UI driver drives the Edit Scheduling dialog on the deployment
        detail page; the API driver calls ``client.deployments.update``.
        Both implementations block until the server has accepted the
        mutation — callers still need ``wait_for_deployment_running`` to
        observe the reconciliation completing.
        """

    async def get_deployment_timeline(
        self, *, deployment_id: str
    ) -> list[TimelineEntry]: ...

    # --- Backup / Restore -------------------------------------------------

    async def create_backup(self, *, instance_id: str) -> BackupRef: ...

    async def wait_for_backup(
        self, *, backup_id: str, max_wait: float = 300.0
    ) -> BackupRef: ...

    async def create_restore(
        self, *, backup_id: str, target_namespace: str
    ) -> RestoreRef: ...

    async def wait_for_restore(
        self, *, restore_id: str, max_wait: float = 600.0
    ) -> RestoreRef: ...

    async def delete_backup(self, *, backup_id: str) -> None: ...

    async def get_backup(self, *, backup_id: str) -> BackupRef: ...
