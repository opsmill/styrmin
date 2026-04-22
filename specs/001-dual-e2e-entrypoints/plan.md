# Implementation Plan: Dual-Entrypoint E2E Tests (API and UI)

**Branch**: `001-dual-e2e-entrypoints` | **Date**: 2026-04-22 | **Spec**: [./spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-dual-e2e-entrypoints/spec.md`

## Summary

Extend the existing programmatic-API E2E suite in `backend/tests/e2e/`
with a second, interchangeable UI entrypoint so that every scenario
runs twice — once through `StyrminClient`, once through the web
frontend — with a single scenario body and identical external-state
assertions. Parity is implemented as a `ScenarioDriver` protocol with
two concrete drivers (`ApiScenarioDriver`, `UiScenarioDriver`) selected
by a parametrized pytest fixture; each scenario appears as
`test_name[api]` and `test_name[ui]` in collection. UI flows are
driven by pytest-playwright against Chromium only, with
retain-on-failure traces/video/screenshots as diagnostics and one
automatic retry for UI-variant failures. CI runs the two entrypoints
as separate jobs, each against its own vCluster, and both gate PR
merges. Product gaps uncovered by parity — notably the missing
service-name-overrides field on `DeployFormPage` — are closed in this
feature, not worked around by shrinking scenarios.

## Technical Context

**Language/Version**: Python 3.14 (backend tests), TypeScript 5.9 (frontend changes)
**Primary Dependencies**: pytest 9, pytest-asyncio, pytest-playwright (new), pytest-rerunfailures (new), playwright (Chromium), styrmin_sdk, kr8s, kubernetes-asyncio, Strawberry GraphQL (unchanged), React 19 / TanStack Router / Base UI (frontend, unchanged except for the new `DeployFormPage` field array)
**Storage**: N/A — no persistent data changes
**Testing**: pytest (backend E2E suite); Vitest unchanged; the feature's deliverable is the E2E suite itself
**Target Platform**: Linux (GitHub Actions `huge-runners` group, same as current `e2e-tests` job). Chromium runs headless under `xvfb-run` or Playwright's bundled headless driver.
**Project Type**: Web application — backend + frontend already established (see `backend/AGENTS.md`, `frontend/AGENTS.md`).
**Performance Goals**: UI job wall-clock ≤ 1.5× API job wall-clock (vCluster bring-up dominates both); first-attempt UI flakiness visible in diagnostics even when retry succeeds.
**Constraints**: Chromium only (FR-016); behaviour-only assertions, no pixel-comparison (FR-017); UI failures block merges identically to API failures (FR-018); one automatic retry for UI variants only (FR-019); cross-variant isolation achieved by separate CI jobs, no resource-name coordination scheme (FR-013, SC-007).
**Scale/Scope**: 8 existing E2E test files; ~12 test functions currently marked `ci`. Each gains a `[ui]` variant by construction. One net-new UI flow (service-name overrides field array) is added; all other UI actions already exist (see `contracts/ui_surface.md`).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Gates derived from `.specify/memory/constitution.md` (v1.0.0):

| Principle / Boundary                                     | Verdict | Notes                                                                                                                                                                                                                                                                                                                      |
| -------------------------------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| I. Declarative State Reconciliation                      | Pass    | Test-only feature; the reconciler is unaffected. Driver methods remain idempotent where the underlying product operation is idempotent (data-model invariant).                                                                                                                                                             |
| II. Driver-Based Deployment                              | Pass    | No deployment behaviour change. Application Drivers are untouched.                                                                                                                                                                                                                                                         |
| III. Layered Architecture                                | Pass    | Backend layers untouched. The UI-surface additions (one field array in `DeployFormPage`) use the existing GraphQL mutation — no new service or repository code.                                                                                                                                                            |
| IV. Type Safety and Typed Errors                         | Pass    | `ScenarioDriver` is a typed `typing.Protocol`; driver-neutral refs are `@dataclass(frozen=True, slots=True)` with explicit fields; drivers normalise underlying exceptions into `ScenarioActionError` / `ResourceNotFound` (no union-based error handling).                                                                |
| V. Test-First Development                                | Pass    | The feature *is* the test suite expansion. No product code ships without a scenario exercising it through both entrypoints (FR-002, FR-011).                                                                                                                                                                               |
| VI. Format and Lint Before Commit                        | Pass    | All new Python files under `backend/tests/e2e/` pass `uv run invoke format lint`. New TS file changes pass `pnpm lint` / `pnpm format`.                                                                                                                                                                                    |
| Governance gate: New dependencies                        | Pass with ask | `pytest-playwright`, `playwright`, `pytest-rerunfailures` are dev-only. Enumerated in `research.md#R9`. Requires explicit sign-off at `/speckit.tasks` time — flagged below under *Complexity Tracking* as a governance surface, not a constitution violation. |
| Governance gate: CI/CD workflow changes                  | Pass with ask | `.github/workflows/ci.yml` grows a sibling `e2e-tests-ui` job (research R7). Structural change (split of one required check into two) requires sign-off at tasks time.                                                                                                                                                    |
| Governance gate: GraphQL schema / DB migrations / Auth   | Pass    | None required. `service_name_overrides` is already part of the existing `deploy` mutation input.                                                                                                                                                                                                                           |
| Boundary: `update-agent-context.sh` MUST NOT be executed | Pass    | Phase 1 explicitly skips the script per constitution Boundaries. Agent context files are maintained manually.                                                                                                                                                                                                              |

**Result**: Constitution gates are satisfied. No violations to justify.
The two governance "ask first" surfaces (new dev deps + CI job split)
are called out explicitly so the tasks phase cannot proceed without
acknowledgement.

### Re-check after Phase 1 design

Artifacts produced by Phase 1 (`research.md`, `data-model.md`,
`contracts/scenario_driver.py`, `contracts/ui_surface.md`,
`quickstart.md`) reviewed against the principles above:

- No layered-architecture violation introduced by the driver protocol
  (III): drivers are test scaffolding, not a cross-layer bypass.
- No typed-error regression (IV): `ScenarioActionError` /
  `ResourceNotFound` form a small exception hierarchy; no union error
  returns.
- No test-first violation (V): the only product change
  (`DeployFormPage` service-name overrides) is paired with a scenario
  that requires it (`test_service_discovery`), which fails at the UI
  variant until the field ships.

Gates continue to pass.

## Project Structure

### Documentation (this feature)

```text
specs/001-dual-e2e-entrypoints/
├── plan.md                 # This file (/speckit.plan command output)
├── research.md             # Phase 0 output
├── data-model.md           # Phase 1 output
├── quickstart.md           # Phase 1 output
├── contracts/
│   ├── scenario_driver.py  # Authoritative ScenarioDriver protocol + refs
│   └── ui_surface.md       # Required UI flows, stable anchors, gap table
├── spec.md                 # Feature specification (pre-existing)
└── tasks.md                # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

Concrete paths that this feature touches. Paths not listed below are
untouched by the plan.

```text
backend/
├── tests/
│   └── e2e/
│       ├── conftest.py                  # Extend: add `scenario_driver` parametrized fixture,
│       │                                # `api_only` / `ui_only` marker processing, UI browser/context
│       │                                # fixtures (session-scoped), first-attempt artifact retention hook.
│       ├── drivers/                     # NEW — driver implementations + neutral refs
│       │   ├── __init__.py
│       │   ├── refs.py                  # Mirrors contracts/scenario_driver.py ref types
│       │   ├── errors.py                # ScenarioActionError, ResourceNotFound
│       │   ├── protocol.py              # ScenarioDriver Protocol (imported by tests)
│       │   ├── api_driver.py            # ApiScenarioDriver (wraps StyrminClient)
│       │   └── ui_driver.py             # UiScenarioDriver (wraps Playwright Page)
│       ├── pages/                       # NEW — UI page objects used only by ui_driver.py
│       │   ├── __init__.py
│       │   ├── environments.py
│       │   ├── deploy_form.py
│       │   ├── deployment_detail.py
│       │   ├── drivers_list.py
│       │   └── settings.py
│       ├── test_backup_restore.py               # Refactor: swap StyrminClient usage for scenario_driver
│       ├── test_backup_restore_databases.py     # Refactor
│       ├── test_deploy_app.py                   # Refactor (dual already by param)
│       ├── test_deploy_semaphore.py             # Refactor
│       ├── test_deployment_timeline.py          # Refactor
│       ├── test_ingress_controller.py           # Refactor; likely carry @pytest.mark.api_only with reason
│       └── test_service_discovery.py            # Refactor; requires the new UI field array to pass [ui]

frontend/
└── src/
    └── pages/
        └── deployments/
            └── DeployFormPage.tsx       # Add: "Service name overrides" field array feeding the existing
                                         # `deploy` mutation's `service_name_overrides` input.

pyproject.toml                           # Add dev deps: pytest-playwright, pytest-rerunfailures.
                                         # Extend [tool.pytest.ini_options]: playwright tracing/video/
                                         # screenshot retain-on-failure defaults.

.github/workflows/ci.yml                 # Split `e2e-tests` into `e2e-tests-api` and `e2e-tests-ui`;
                                         # both required; UI job adds `playwright install chromium`.
```

**Structure Decision**: This is a **web application** following the
established `backend/` + `frontend/` layout (see `AGENTS.md` and
`frontend/AGENTS.md`). The feature is almost entirely scoped to
`backend/tests/e2e/` — two new subpackages (`drivers/`, `pages/`),
extensions to `conftest.py`, and refactors of the existing test files
to use the `scenario_driver` fixture. The single frontend change
(`DeployFormPage.tsx`) closes the one identified UI gap. Root-level
changes are limited to `pyproject.toml` (dev deps + pytest options)
and `.github/workflows/ci.yml` (CI job split).

## Complexity Tracking

> *Fill ONLY if Constitution Check has violations that must be justified.*

No constitution violations to justify. The table below records the two
governance "ask first" surfaces called out in the Constitution Check so
they are visible at `/speckit.tasks` and implementation time.

| Surface                                  | Why needed                                                                                           | Simpler alternative rejected because                                                                                        |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| New dev deps: pytest-playwright + pytest-rerunfailures | pytest-playwright is the integration path named by the spec; rerunfailures implements FR-019 without per-test scaffolding. | Writing a bespoke Playwright runner or manual `@pytest.mark.flaky` per test would violate FR-003 (single source of truth) and add more code than the deps they replace. |
| CI split: `e2e-tests-api` + `e2e-tests-ui` | FR-013 / SC-007 require separate backends per variant; also caps wall-clock impact by running in parallel. | A single job running both entrypoints serially doubles PR feedback time and shares state across variants, violating the isolation invariant. |
