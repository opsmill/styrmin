# Phase 1 Data Model — Dual-Entrypoint E2E Tests

This feature does not introduce persisted data or new database entities.
Its "data model" is the set of test-side abstractions that make the two
entrypoints interchangeable from a scenario's point of view. Each entity
below maps to one of the **Key Entities** in `spec.md` and to the
contracts under `./contracts/`.

---

## ScenarioDriver (protocol)

A `typing.Protocol` defining every action a scenario can ask the system
to perform. Two concrete implementations exist — `ApiScenarioDriver` and
`UiScenarioDriver` — and are interchangeable behind this protocol.

**Fields**: none (driver instances are stateless facades over their
underlying clients).

**Methods (one per Scenario Action)**:

| Method                                                                  | Purpose                                                                 |
| ----------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `async create_cluster(name, config) -> ClusterRef`                      | Register a cluster record.                                              |
| `async create_environment(name, cluster_id, config) -> EnvironmentRef`  | Create an environment bound to a cluster.                               |
| `async delete_environment(environment_id) -> None`                      | Remove an environment. (UI gap — see research R8.)                      |
| `async create_backup_storage_location(**fields) -> BSLRef`              | Register a Velero-backed backup storage location.                       |
| `async assign_bsl_to_environment(environment_id, bsl_id) -> None`       | Wire a BSL to an environment.                                           |
| `async load_driver_version(git_url, ref) -> DriverVersionRef`           | Pull an Application Driver version from a git URL.                      |
| `async create_deployment(driver, version, environment_id, **opts) -> DeploymentRef` | Start a deployment (opts include `service_name_overrides`, `name`, `parameters`). |
| `async wait_for_deployment_running(deployment_id, timeout) -> DeploymentRef` | Block until status == `running` or timeout.                           |
| `async upgrade_deployment(deployment_id, version) -> None`              | Change the application version of a deployment.                         |
| `async create_backup(instance_id) -> BackupRef`                         | Initiate a backup.                                                      |
| `async wait_for_backup(backup_id, max_wait) -> BackupRef`               | Block until backup is `completed`.                                      |
| `async create_restore(backup_id, target_namespace) -> RestoreRef`       | Initiate a restore from a backup.                                       |
| `async wait_for_restore(restore_id, max_wait) -> RestoreRef`            | Block until restore is `completed`.                                     |
| `async delete_backup(backup_id) -> None`                                | Remove a backup (and assert 404 on re-fetch via `get_backup`).          |
| `async get_backup(backup_id) -> BackupRef`                              | Read a backup; raises `ResourceNotFound` if deleted.                    |
| `async get_deployment_timeline(deployment_id) -> list[TimelineEntry]`   | Read the deployment timeline.                                           |

The protocol intentionally mirrors the existing `StyrminClient` method
names so that the API driver is a near-direct passthrough. The UI driver
implements each method by composing page-object interactions (see below)
and returning the same Ref types, so scenarios never branch on
entrypoint.

**Invariants**:

- Every method accepts and returns **driver-neutral** ref types (plain
  dataclasses defined in the test package). No SDK model, no Playwright
  `Locator`, no GraphQL payload leaks through.
- Action methods raise a shared `ScenarioActionError` on failure so that
  assertions in scenario bodies match across drivers.
- Methods are idempotent where the underlying product operation is
  idempotent (e.g. re-creating an existing cluster surfaces the same ref
  without error) — required by Principle I.

**State transitions**: none at the driver level. Product-side state is
the system under test.

---

## ApiScenarioDriver

Thin wrapper around `styrmin_sdk.StyrminClient`. One-to-one mapping:
`driver.create_deployment(...)` → `self._client.deployments.create(...)`,
with the result adapted to the driver-neutral ref.

**Fields**: `_client: StyrminClient`.

---

## UiScenarioDriver

Composes page objects (see below) to satisfy the same protocol. Opens
pages via a Playwright `browser_context.new_page()` bound to the
port-forwarded `styrmin-server` URL.

**Fields**:
- `_page: playwright.async_api.Page`
- `_base_url: str`
- `_page_objects: UiPageObjectRegistry` (lazy factories)

Behaviour-level notes:

- Every action navigates from the product's normal entry points — no
  `page.goto(hidden-route)` shortcuts (SC-006).
- Every action ends on a deterministic success signal (a visible
  confirmation toast, a status badge transition, or a navigation
  complete). The method does not return until that signal is observed.

---

## Page Objects (UI driver internal)

Not exposed to scenarios. One class per product area, each responsible
for locator strategy, accessibility queries, and fallbacks to
`data-testid` where role/label is insufficient (research R4).

| Page Object              | Covers                                                                  |
| ------------------------ | ----------------------------------------------------------------------- |
| `EnvironmentsListPage`   | `/environments` list, create-environment dialog                         |
| `EnvironmentDetailPage`  | `/environments/$id` detail, BSL assign/unassign, deploy button          |
| `DeployFormPage`         | `/environments/$id/deploy` form + service-name overrides (new field)    |
| `DeploymentDetailPage`   | `/deployments/$id` detail, Upgrade dialog, backup create/delete/restore |
| `DriversListPage`        | `/drivers` list, add-driver dialog                                      |
| `SettingsPage`           | `/settings` navigation and clusters sub-page                            |

**Invariant**: every page object method accepts/returns driver-neutral
types (strings, dataclasses) — never `Locator` or `Page` — so the driver
surface can be refactored without churn in scenarios.

---

## Entrypoint Declaration

A pair of pytest markers on a scenario, declared **at most on the
opposite side of the default** (tests are dual by default — FR-011):

```python
@pytest.mark.api_only(reason="ingress configured at cluster level, no UI surface")
async def test_ingress_controller(...): ...

@pytest.mark.ui_only(reason="pure visual refresh flow — no API operation backs it")
async def test_refresh_after_upgrade(...): ...
```

**Fields (per marker)**: `reason: str` (required — empty string rejected
at collection time).

**Processing**:

- The parametrization helper reads these markers during collection.
  `api_only` makes the `[ui]` variant `pytest.skip(reason=...)`;
  `ui_only` skips the `[api]` variant symmetrically. Both variants are
  still *collected* so the skip shows up in reports with its reason —
  never silently dropped (FR-011, FR-014).
- `conftest` enforces: a test may carry at most one of the two markers;
  an empty `reason` fails collection.

---

## Diagnostic Artifact

A bundle emitted by pytest-playwright (and kept by pytest-rerunfailures
across attempts) on UI-variant failure.

**Fields**:

- `trace_zip: Path` — Playwright trace viewer archive.
- `video_webm: Path` — recorded video of the failing attempt.
- `screenshot_png: Path` — snapshot taken at failure.
- `attempt_index: int` — 1 (first attempt) or 2 (retry); artifacts from
  attempt 1 are preserved even when attempt 2 succeeds (FR-019).

**Invariant**: no artifacts are produced on first-attempt success to
keep green runs cheap. The retention policy is `retain-on-failure` for
all three kinds, configured in `pyproject.toml`.

---

## TimelineEntry, DeploymentRef, EnvironmentRef, ClusterRef, BSLRef, BackupRef, RestoreRef, DriverVersionRef

Driver-neutral dataclasses (frozen, `slots=True`) carrying only the
fields scenarios actually assert on today. Each is constructed by both
drivers from their underlying payload. Example:

```python
@dataclass(frozen=True, slots=True)
class DeploymentRef:
    id: str
    status: str
    application_version: str | None
    instance_id: str | None
```

**Rationale for driver-neutral types**: scenarios must not branch on
which driver populated the ref, so both drivers converge on the same
shape. If a field is used by the UI driver's internals but not asserted
by any scenario, it does not belong on the ref.
