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
    EnvironmentBackupRef,
    EnvironmentCloneRef,
    EnvironmentRef,
    EnvironmentRestoreRef,
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
        self, *, git_url: str, ref: str, driver_directory: str | None = None
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
        component_replicas: dict[str, int] | None = None,
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

    async def set_component_env_vars(
        self, *, deployment_id: str, component: str, env_vars: dict[str, str]
    ) -> None:
        """Replace one component's component-scope env vars on a deployment.

        ``env_vars`` is the complete desired set for ``component``; an empty
        dict clears it. Every other stored config field, including the other
        components' blocks and this component's ``command``/``args``, is
        preserved.

        API driver: reads the stored ``Deployment.config``, swaps
        ``components[<component>].env_vars``, and resubmits the whole config
        through ``update_deployment`` (``updateDeployment`` is
        full-replacement). A block left empty is dropped.

        UI driver: opens the Settings tab's edit drawer, expands
        ``component-override-trigger-<component>``, edits the env var rows in
        place to match ``env_vars`` (adding, renaming and removing rows),
        then applies through the diff dialog. A block left with no env vars,
        command or args is removed.

        Both block until the server has accepted the mutation; callers still
        need ``wait_for_deployment_running`` to observe the reconcile.
        """

    async def set_component_image(
        self, *, deployment_id: str, component: str, image: str | None
    ) -> None:
        """Set or clear one component's image override on a deployment (018).

        ``image`` is the stored reference (it may carry ``{{ app.version }}``);
        ``None`` clears it. Every other stored config field, including the
        other components' blocks and this component's env vars and
        ``command``/``args``, is preserved.

        API driver: reads the stored ``Deployment.config``, swaps
        ``components[<component>].image``, and resubmits the whole config
        through ``update_deployment``. A block left empty is dropped.

        UI driver: opens the Settings tab's edit drawer, expands
        ``component-override-trigger-<component>``, fills or clears the
        ``Image for <component>`` input, then applies through the diff dialog.
        A block left with no image, env vars, command or args is removed.

        Both block until the server has accepted the mutation; callers still
        wait for the reconcile to reach the workload.
        """

    async def set_component_container_override(
        self,
        *,
        deployment_id: str,
        component: str,
        command: list[str] | None,
        args: list[str] | None,
    ) -> None:
        """Set or clear one component's ``command`` and ``args`` overrides (022).

        ``None`` clears a field. Every other stored config field, including the
        other components' blocks and this component's env vars and image, is
        preserved.

        API driver: reads the stored ``Deployment.config``, swaps
        ``components[<component>].command`` and ``.args``, and resubmits the
        whole config through ``update_deployment``. A block left empty is
        dropped.

        UI driver: opens the Settings tab's edit drawer, expands
        ``component-override-trigger-<component>``, edits the Command and Args
        rows in place (adding, changing and removing rows), then applies
        through the diff dialog. The block stays, so a clear submits only the
        ``command`` and ``args`` removal.

        Both block until the server has accepted the mutation; callers still
        wait for the reconcile to reach the workload.
        """

    async def set_component_replicas(
        self, *, deployment_id: str, component: str, replicas: int | None
    ) -> None:
        """Set or clear one component's replica override on a deployment (023).

        ``None`` clears it, so the driver default or the chart's count applies.
        Every other stored config field, including the other components' blocks
        and this component's env vars, image and ``command``/``args``, is
        preserved.

        API driver: reads the stored ``Deployment.config``, swaps
        ``components[<component>].replicas``, and resubmits the whole config
        through ``update_deployment``. A block left empty is dropped.

        UI driver: opens the Settings tab's edit drawer, expands
        ``component-override-trigger-<component>``, fills or clears the
        ``comp-replicas-<component>`` field, then applies through the diff
        dialog. A block left with no override is removed. Raises
        ``ScenarioActionError`` for a singleton component, whose field is
        read-only.

        Both block until the server has accepted the mutation; callers still
        wait for the update task to complete.
        """

    async def pinned_image_components(
        self, *, deployment_id: str, target_version: str
    ) -> list[str]:
        """Components, sorted, whose image override stays pinned on an upgrade (018).

        Pinned means applicable (the component has a container) and without the
        ``{{ app.version }}`` token. Nothing is upgraded.

        API driver: applies the SDK ``pinned_image_components`` helper to the
        applicable rows of ``Deployment.componentImageOverrides``;
        ``target_version`` is unused because the listing does not depend on it.

        UI driver: opens the Upgrade dialog, types ``target_version``, reads
        the components in the "Pinned image overrides" notice (none when it is
        absent), then cancels.
        """

    async def get_deployment_timeline(
        self, *, deployment_id: str
    ) -> list[TimelineEntry]:
        """Timeline entries newest first, each with its task's steps in API order.

        API driver: maps ``deploymentTimeline`` from the SDK, steps included.

        UI driver: reads the ``timeline-entry`` and ``step-row`` data attributes
        of the Timeline tab; collapsed entries keep their steps in the DOM.
        ``StepRef.errors`` come from each row's ``step-error`` elements, put back
        in the API's oldest-first order, and ``detail`` from its ``step-detail``.
        """

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
    ) -> BackupRef:
        """The backup once terminal, with one step per component in API order.

        API driver: ``Backup.steps`` from the SDK. UI driver: the ``step-row``
        attributes inside the row's ``backup-steps`` container, which keeps its
        rows in the DOM while collapsed.
        """

    async def create_restore(
        self, *, backup_id: str, target_namespace: str
    ) -> RestoreRef: ...

    async def wait_for_restore(
        self, *, restore_id: str, max_wait: float = 600.0
    ) -> RestoreRef:
        """The restore once terminal, with its steps in API order.

        API driver: ``Restore.steps`` from the SDK. UI driver: the ``step-row``
        attributes inside the row's ``restore-steps`` container.
        """

    async def delete_backup(self, *, backup_id: str) -> None: ...

    async def get_backup(self, *, backup_id: str) -> BackupRef:
        """The backup with its steps, as ``wait_for_backup`` reads them."""

    async def list_backups(self, *, deployment_id: str) -> tuple[BackupRef, ...]:
        """The deployment's backup history: the backups of every instance it has had.

        Each ref carries ``application_version``, the version of the instance
        the backup was taken of; ``steps`` stays empty.

        API driver: ``client.backups.list_backups(deployment_id=...)``.

        UI driver: every ``backup-row`` on the deployment's Backups tab, read
        from ``data-backup-id``, ``data-backup-name``, ``data-backup-status``
        and ``data-backup-application-version``.
        """

    # --- Environment-level backup / restore -------------------------------
    #
    # Ordering contract: the UI flow lives on the environment detail page's
    # Backups tab, so every method below needs the owning environment.
    # ``create_environment_backup`` takes it explicitly and stashes it;
    # the read/act methods that only carry a parent id reuse that stash (or
    # whatever ``attach_to_deployment`` last set) and raise
    # ``ScenarioActionError`` if the driver has no environment context yet.
    # The API driver ignores the stash — every call re-derives what it needs
    # from its arguments — so scenarios need no ``driver_mode`` branch.

    async def create_environment_backup(
        self, *, environment_id: str
    ) -> EnvironmentBackupRef:
        """Trigger one coordinated snapshot of an environment.

        Returns as soon as the fan-out has been dispatched, so the returned
        ``status`` is normally ``PENDING``/``IN_PROGRESS`` — or ``COMPLETED``
        immediately for a config-only snapshot of an environment with no
        eligible deployments (spec FR-011).
        """

    async def get_environment_backup(
        self, *, environment_backup_id: str
    ) -> EnvironmentBackupRef:
        """Read one snapshot, including its per-constituent outcomes.

        Raises ``ResourceNotFound`` when the snapshot no longer exists, so a
        scenario can assert a cascade delete took effect.
        """

    async def wait_for_environment_backup(
        self, *, environment_backup_id: str, max_wait: float = 600.0
    ) -> EnvironmentBackupRef:
        """Poll until the *derived* parent status is terminal.

        Terminal means ``COMPLETED`` / ``PARTIAL`` / ``FAILED``. ``PARTIAL`` is
        a final outcome, not a transitional one.
        """

    async def restore_environment_backup(
        self, *, environment_backup_id: str
    ) -> EnvironmentRestoreRef:
        """Restore a snapshot in place: revert env config, restore constituents.

        ADMIN-only on both entrypoints (it reverts the environment's config).
        Constituent classification is synchronous, so ``skipped`` on the
        returned ref is already complete: every constituent that will not be
        restored is named with a free-text reason (spec FR-007).
        """

    async def wait_for_environment_restore(
        self, *, environment_restore_id: str, max_wait: float = 900.0
    ) -> EnvironmentRestoreRef:
        """Poll until the restore's derived parent status is terminal."""

    async def delete_environment_backup(self, *, environment_backup_id: str) -> None:
        """Delete a snapshot and cascade through its constituents.

        Legal regardless of derived status — the FR-010 escape hatch for a
        snapshot pinned in progress by a constituent that was never picked up.
        """

    # --- Environment clone ------------------------------------------------
    #
    # Ordering contract: the UI flow lives on the environment detail page's
    # Clones tab, scoped by the clone's **source** environment.
    # ``clone_environment`` takes that environment explicitly and stashes it;
    # the two read methods only carry the clone's own id and reuse the stash,
    # raising ``ScenarioActionError`` when the driver has never been told which
    # environment a clone belongs to. The API driver ignores the stash — the
    # clone id is addressable on its own — so scenarios need no ``driver_mode``
    # branch.

    async def clone_environment(
        self,
        *,
        environment_id: str,
        name: str,
        deployment_ids: list[str] | None = None,
        config_override: dict[str, Any] | None = None,
        clear_config_fields: list[str] | None = None,
    ) -> EnvironmentCloneRef:
        """Clone ``environment_id`` into a new environment called ``name``.

        ADMIN-only on both entrypoints — a clone creates an environment and
        reads every included deployment's data, so the UI wraps the whole
        surface (trigger included) in ``IfRole minimum="ADMIN"`` rather than
        merely disabling it.

        ``deployment_ids`` is **tri-state** and implementations must preserve
        the distinction: ``None`` omits the argument entirely ("every eligible
        deployment", FR-003), while ``[]`` is a legal and *different* request
        meaning "clone the environment configuration only". Never pass ``[]``
        to mean "no filter".

        ``config_override`` is a ``dict`` in the **camelCase**
        ``UpdateEnvironmentInput`` spelling (``{"envVars": [...],
        "backupTtl": "..."}``) — the same shape the UI's override textarea takes
        and the shape the API driver validates through the typed input model.
        ``clear_config_fields`` names **snake_case** top-level
        ``EnvironmentConfig`` fields (``"backup_ttl"``), which is the persisted
        spelling both entrypoints use.

        Returns as soon as the clone record exists, so the returned ``status``
        is normally ``PENDING`` or ``IN_PROGRESS`` — an upfront skip already
        counts as progress, so ``PENDING`` is not guaranteed as a first
        observation.

        Entrypoint asymmetry: the UI can only express what the dialog renders.
        A ``deployment_ids`` entry naming an *ineligible* deployment, or a
        ``clear_config_fields`` entry naming a field the source's config does
        not set, has no checkbox to tick — the UI driver raises
        ``ScenarioActionError`` rather than silently sending a different
        request.
        """

    async def get_environment_clone(
        self, *, environment_clone_id: str
    ) -> EnvironmentCloneRef:
        """Read one clone record, including its per-deployment attribution.

        Raises ``ResourceNotFound`` when the record no longer exists, so a
        scenario can assert that deleting a source environment removed a
        still-running clone.
        """

    async def wait_for_environment_clone(
        self, *, environment_clone_id: str, max_wait: float = 1800.0
    ) -> EnvironmentCloneRef:
        """Poll until the *derived* clone status is terminal.

        Terminal means ``COMPLETED`` / ``PARTIAL`` / ``FAILED``. The default
        budget is the widest of the environment-level waiters because a clone
        contains a whole capture *and* a whole cross-target restore, with an
        environment and its counterpart deployments created in between.
        """
