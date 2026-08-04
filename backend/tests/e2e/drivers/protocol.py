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

    async def upgrade_deployment(
        self,
        *,
        deployment_id: str,
        version: str,
        driver_version_id: str | None = None,
    ) -> None:
        """Upgrade a deployment's application version.

        Without ``driver_version_id`` the backend binds the latest loaded
        driver version supporting ``version`` (latest-wins resolution); with
        it, the binding is pinned to that specific driver version. The UI
        driver drives the upgrade dialog's driver-version picker; the API
        driver forwards the id to the SDK.
        """

    async def update_deployment(
        self, *, deployment_id: str, config: dict[str, Any]
    ) -> None:
        """Submit a new ``config`` for an existing deployment.

        ``config`` is the test-friendly dict shape that mirrors the read
        API's ``Deployment.config`` JSON blob: snake_case keys, with
        ``env_vars`` and ``components`` as dicts keyed by name. The API
        driver translates this into the typed ``UpdateDeploymentInput`` it
        forwards to ``client.deployments.update(deployment_id,
        input=...)`` so each driver owns its own SDK<->dict adapter and
        callers don't have to import codegen types.

        The UI driver drives the Edit Scheduling dialog on the deployment
        detail page; today it only supports the ``config['scheduling']``
        sub-tree (other keys are rejected with ``ScenarioActionError``).

        Both implementations block until the server has accepted the
        mutation — callers still need ``wait_for_deployment_running`` to
        observe the reconciliation completing.
        """

    async def get_deployment_timeline(
        self, *, deployment_id: str
    ) -> list[TimelineEntry]: ...

    # --- Environments -----------------------------------------------------

    async def update_environment_via_form(
        self,
        *,
        environment_id: str,
        env_vars: dict[str, str],
    ) -> None:
        """Update env vars on an environment.

        UI driver: drives the env-vars form on the Configuration tab —
        navigates to ``/environments/{environment_id}``, opens the
        Configuration tab, adds env-var rows, clicks Save, confirms the
        redeploy dialog, and waits for the page to refresh.

        API driver: reads the existing ``Environment.config``, round-trips
        it through ``EnvironmentConfig.model_validate(config)`` so Pydantic
        coerces ``Literal["http", "https"]`` etc. automatically, modifies
        the ``env_vars`` slice, and submits a typed
        ``UpdateEnvironmentInput`` via ``client.environments.update(...)``
        — full-replacement semantics per FR-003 / FR-020.

        Both implementations result in the same persisted state and the
        same per-deployment redeploy fanout per 009. The parametrisation
        across ``[api-chromium]``/``[ui-chromium]`` IS the dual-entrypoint
        parity check (per critique E1+E2 of 011-env-config-input-hardening).
        """

    async def set_environment_backup_ttl(
        self,
        *,
        environment_id: str,
        ttl: str | None,
    ) -> None:
        """Set — or clear — an environment's ``backup_ttl`` retention policy.

        ``ttl=None`` means "no policy at this scope": resolution falls
        through to the cluster scope and then to the built-in default
        (016-backup-retention-ttl / FR-001, deepest scope wins). Scenarios
        that borrow a session-shared environment use ``None`` to restore the
        pre-test state, so implementations MUST treat it as an explicit clear
        rather than "leave unchanged".

        UI driver: drives the ``BackupRetentionForm`` on the Configuration
        tab — navigates to ``/environments/{environment_id}``, opens the
        Configuration tab, types the duration (blank input for ``None``),
        clicks Save, and confirms the redeploy dialog.

        API driver: reads the persisted ``Environment.config``, round-trips
        it through ``EnvironmentConfig.model_validate(config)`` so Pydantic
        coerces the ``Literal``-typed scalars, and resubmits a typed
        ``UpdateEnvironmentInput`` carrying every persisted field unchanged
        with only ``backup_ttl`` replaced — ``updateEnvironment`` is
        full-replacement per FR-003 / FR-020, so anything omitted would be
        persisted as its unset state.

        Both implementations result in the same persisted state and the same
        per-deployment redeploy fanout per 009. The parametrisation across
        ``[api-chromium]``/``[ui-chromium]`` IS the dual-entrypoint parity
        check for the retention setter — there is no separate assertion
        comparing the two.

        Ordering note: the UI driver leaves its page on the environment
        detail page, so a scenario that follows this with a deployment-scoped
        action must re-establish deployment context first
        (``attach_to_deployment`` + ``wait_for_deployment_running``). Both
        calls are no-ops/cheap for the API driver, so the scenario needs no
        ``driver_mode`` branch.
        """

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
