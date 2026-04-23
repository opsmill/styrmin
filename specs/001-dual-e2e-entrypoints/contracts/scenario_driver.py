"""ScenarioDriver protocol contract.

This file is the authoritative contract for the test-side abstraction
that makes the API and UI entrypoints interchangeable in the E2E suite.

It lives in the spec tree (not under backend/tests) because it is a
design artifact of `/speckit.plan` Phase 1. The implementation under
`backend/tests/e2e/drivers/` MUST match this shape; drift between the
two is a spec violation, not a refactor.

Nothing in this file is imported by production code. Do not add
runtime logic here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Driver-neutral reference types
#
# Each ref carries only the fields scenarios actually assert on today.
# Both ApiScenarioDriver and UiScenarioDriver construct identical refs from
# their respective underlying representations (SDK payload vs. rendered DOM).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClusterRef:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class EnvironmentRef:
    id: str
    name: str
    cluster_id: str


@dataclass(frozen=True, slots=True)
class BSLRef:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class DriverVersionRef:
    id: str
    application_driver_id: str
    driver_name: str
    version: str


@dataclass(frozen=True, slots=True)
class DeploymentRef:
    id: str
    status: str
    application_version: str | None
    instance_id: str | None


@dataclass(frozen=True, slots=True)
class BackupRef:
    id: str
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class RestoreRef:
    id: str
    status: str


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    task_id: str
    task_type: str
    task_status: str
    application_version: str | None
    created_on: str | None


# ---------------------------------------------------------------------------
# Driver-neutral errors
# ---------------------------------------------------------------------------


class ScenarioActionError(Exception):
    """Raised by a driver when an action fails at the entrypoint level.

    Drivers normalise underlying exceptions (SDK StyrminError, Playwright
    TimeoutError, UI-level validation errors) into this single type so
    scenario assertions are identical across entrypoints.
    """


class ResourceNotFound(ScenarioActionError):
    """Raised when a lookup returns nothing (e.g. get_backup after delete)."""


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


@runtime_checkable
class ScenarioDriver(Protocol):
    """Actions a scenario can request, entrypoint-agnostic.

    Implementations MUST:
      - Return the driver-neutral ref types above (never SDK models or
        Playwright Locators).
      - Raise ScenarioActionError / ResourceNotFound — never propagate
        implementation-specific exceptions.
      - End each action on a deterministic success signal so that
        callers never need to add their own sleeps.
    """

    # --- Platform setup ---------------------------------------------------

    async def create_cluster(self, *, name: str, config: dict[str, Any]) -> ClusterRef: ...

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

    async def wait_for_deployment_running(
        self, *, deployment_id: str, timeout: float = 300.0
    ) -> DeploymentRef: ...

    async def upgrade_deployment(
        self, *, deployment_id: str, version: str
    ) -> None: ...

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


# ---------------------------------------------------------------------------
# Parametrization contract
#
# Scenarios consume a single pytest fixture named `scenario_driver` that is
# parametrized with two IDs: "api" and "ui". The test function therefore
# appears twice in collection output:
#
#     backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[api]
#     backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[ui]
#
# Opt-out markers:
#
#     @pytest.mark.api_only(reason="<non-empty>")   # skips [ui]
#     @pytest.mark.ui_only(reason="<non-empty>")    # skips [api]
#
# A test carrying neither marker is dual-entrypoint (the default per FR-011).
# A test carrying both markers, or either marker with an empty reason, fails
# collection — this prevents silent skipping.
# ---------------------------------------------------------------------------
