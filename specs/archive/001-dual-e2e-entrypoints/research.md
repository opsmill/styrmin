# Phase 0 Research — Dual-Entrypoint E2E Tests

**Feature**: Dual-Entrypoint E2E Tests (API and UI)
**Branch**: `001-dual-e2e-entrypoints`
**Spec**: `./spec.md`

This document resolves every unknown flagged in the plan's Technical Context
so that Phase 1 (design & contracts) can proceed without `NEEDS CLARIFICATION`
items.

---

## R1. Scenario Model — single source of truth

**Decision**: Keep each scenario as a single async pytest function in
`backend/tests/e2e/` whose actions are invoked against a `ScenarioDriver`
protocol fixture. Two concrete drivers — `ApiScenarioDriver` (wraps
`StyrminClient`) and `UiScenarioDriver` (wraps a Playwright `Page` plus
page-object helpers) — implement the same protocol. The `scenario_driver`
fixture is parametrized with `pytest.param("api", id="api")` and
`pytest.param("ui", id="ui")`; each test function therefore yields two test
IDs, e.g. `test_deploy_simple_app[api]` and `test_deploy_simple_app[ui]`.
External-state assertions (kr8s service checks, HTTP probes against deployed
apps, Kubernetes CRD inspections) live outside the driver and remain shared.

**Rationale**:

- A protocol + parametrized fixture gives one scenario body (FR-003, SC-003)
  and automatically produces both variants (FR-011).
- Test IDs already embed the entrypoint, satisfying FR-006 and SC-005
  without a second reporting layer.
- Scoping the driver fixture to `function` (while underlying app fixtures
  stay `session`-scoped) means both variants reuse the same deployed stack
  within a job without leaking state across scenarios.
- Entrypoint opt-out is an explicit marker on the test
  (`@pytest.mark.api_only("<reason>")` / `@pytest.mark.ui_only("<reason>")`)
  that the parametrization helper reads to skip the non-matching variant
  with a visible reason string — never a silent skip (FR-011, edge case
  "UI flow missing at test time").

**Alternatives considered**:

- *Gherkin / pytest-bdd*: extra indirection, a parallel text DSL to learn,
  and the existing suite already reads as straight pytest — rejected.
- *Two separate test files per scenario (`_api.py` / `_ui.py`)*: violates
  FR-003 (duplication) and makes SC-003 impossible.
- *Subclassing a base TestCase with two subclasses per scenario*: pytest's
  class pattern conflicts with our async-first, fixture-driven style and
  would bypass `asyncio_mode = "auto"`.

---

## R2. UI Test Framework — pytest-playwright, Chromium only

**Decision**: Add `pytest-playwright` (and its `playwright` runtime) to the
`dev` dependency group. Drive only Chromium (FR-016). Capture traces
(`--tracing retain-on-failure`), video (`--video retain-on-failure`) and
screenshots (`--screenshot only-on-failure`) through the plugin's built-in
flags; configure via `pyproject.toml` `[tool.pytest.ini_options]` so every
invocation produces the same diagnostics (FR-009, SC-004).

**Rationale**:

- The spec names pytest-playwright as the implementation hint and the
  plugin already integrates natively with pytest's fixture graph, async
  mode, and marker system — no parallel runner is introduced.
- Chromium-only keeps the dependency surface small and aligns with
  Clarification Q1 / FR-016. Firefox and WebKit are explicitly excluded.
- Retain-on-failure is the exact behaviour FR-009 requires: no diagnostic
  artifacts are produced on success (cheap green runs), and every failure
  yields both a navigable trace and a visual capture without re-running
  locally.

**Alternatives considered**:

- *Playwright for Python without the pytest plugin*: would force us to
  rebuild fixture lifecycle and test selection from scratch. Rejected.
- *Cypress / Selenium*: Cypress is JS-only (would split the test runner
  and violate the "same invocation" assumption in the spec); Selenium
  lacks first-class tracing and has weaker auto-waiting.

---

## R3. UI Access Path — reuse the styrmin-server port-forward

**Decision**: The frontend is served as static assets by the styrmin
backend pod (`docker/Dockerfile` copies `frontend/dist` into the image;
the backend serves it at `/`). The `styrmin_deployment` fixture already
port-forwards `styrmin-server:8000` and yields the URL. The UI driver
opens Playwright's `browser_context.new_page()` against that same URL —
no new port-forward, no separate frontend service.

**Rationale**:

- Satisfies FR-008 / FR-015: the UI runs against the live stack, same
  backend, same virtual cluster, no mocks or separate UI environment.
- No helm-chart changes required.

**Alternatives considered**:

- *Run `pnpm dev` in CI alongside the stack*: introduces a second moving
  part (Vite dev server) whose behaviour differs from production
  (HMR, unminified). Rejected — tests must exercise the product as shipped.

---

## R4. Stable Selectors

**Decision**: UI driver page objects target elements in this priority
order, per FR-007:

1. `page.get_by_role(...)` with accessible name
2. `page.get_by_label(...)` for form controls
3. `page.get_by_test_id(...)` with an explicit `data-testid` attribute
   added to the React component

Test IDs are introduced only where roles/labels are ambiguous or
unstable (e.g. repeated rows in a list, icon-only buttons). Positional,
CSS-structural (`div > div:nth-child(3)`), and text-substring selectors
are forbidden in page objects.

**Rationale**:

- Enforces FR-007 and directly addresses the "unexpected dialogs / toasts"
  edge case: role-based locators uniquely identify the intended control
  and fail loudly instead of silently clicking through a transient banner.
- Matches Playwright's own guidance and keeps the selector layer readable
  in reviews.

**Alternatives considered**:

- *All-testid convention*: uniform but pollutes markup and bypasses
  accessibility signal. Rejected as the default.
- *Text-based locators*: fragile under i18n or copy tweaks. Rejected.

---

## R5. Waiting Strategy

**Decision**: Rely on Playwright's auto-wait for visibility/enabled state
plus `expect(locator).to_be_visible()` / `to_have_text(...)` polling for
assertion-shaped waits. For long-running backend operations (deployment
reaches `running`, backup completes), the UI driver polls the rendered
status badge with a generous timeout matching the API driver's existing
`_wait_for_deployment_running` timeout (5 min default, 10 min for Infrahub).
External-state assertions afterward remain the shared kr8s / HTTP checks.

**Rationale**:

- Meets the "UI rendering lag vs API response" edge case without
  weakening assertions: the success condition is the same (deployment is
  `running`), only the observation channel differs.
- Keeps the waiting logic inside the UI driver, never in the scenario body
  — so FR-003's single-source-of-truth holds even for timing.

**Alternatives considered**:

- *Fixed sleeps*: flaky, slow, and already known to rot. Rejected.
- *Cross-check the API while in the UI variant*: leaks the API
  entrypoint into the UI run and makes SC-002 impossible to demonstrate.
  Rejected.

---

## R6. Retry Policy

**Decision**: Add `pytest-rerunfailures` to the dev group. A pytest hook
(`pytest_collection_modifyitems`) marks every parametrized `[ui]` variant
with `@pytest.mark.flaky(reruns=1, reruns_delay=0)` automatically; API
variants receive no reruns. The first attempt's diagnostic artifacts
(trace, video, screenshot) are preserved via pytest-playwright's
`--output` directory naming that includes the attempt number, so
flakiness is observable even on an eventually-green retry (FR-019).

**Rationale**:

- Meets FR-019 exactly: one retry, UI-only, first-attempt diagnostics
  preserved.
- Using a collection hook keeps the retry policy out of individual
  scenarios and out of scope of the scenario author — consistent with the
  single-source-of-truth model.

**Alternatives considered**:

- *Playwright `test.describe.configure({ retries })`*: JS-side only, not
  applicable to pytest-playwright.
- *Manual `@pytest.mark.flaky` per test*: violates FR-003 by adding UI-only
  knowledge to every scenario. Rejected.

---

## R7. CI Topology and Selection Mechanism

**Decision**: Split the current `e2e-tests` job in `.github/workflows/ci.yml`
into two jobs that run in parallel, each provisioning its own vCluster:

- `e2e-tests-api`: `pytest -v -m ci -k "[api]" backend/tests/e2e`
- `e2e-tests-ui`:  `pytest -v -m ci -k "[ui]" backend/tests/e2e` plus a
  `playwright install chromium` step and `xvfb-run`/headless flag.

Both are required checks for PR merge (FR-018). Locally, the same four
modes spec'd by FR-010 / SC-005 use one selection axis — `pytest -k`:

| Mode                 | Command                                                               |
| -------------------- | --------------------------------------------------------------------- |
| All variants         | `uv run pytest -m ci backend/tests/e2e`                               |
| API only             | `uv run pytest -m ci -k "[api]" backend/tests/e2e`                    |
| UI only              | `uv run pytest -m ci -k "[ui]" backend/tests/e2e`                     |
| Single scenario both | `uv run pytest -m ci -k "test_deploy_simple_app" backend/tests/e2e`   |

**Rationale**:

- Separate CI jobs satisfy FR-013 / SC-007 and the "cross-variant
  isolation" edge case without any resource-name coordination scheme.
- A single `-k` axis spans local and CI, so SC-005's "single documented
  selection mechanism" holds.
- Both jobs require the same base image and the same `uv sync` step; the
  UI job adds only `playwright install chromium`, keeping CI runtime
  manageable (the UI job is expected to run slightly longer than the API
  job, not 2× longer, because the vCluster bring-up dominates).

**Alternatives considered**:

- *One job, both entrypoints sequentially*: doubles wall-clock time for
  every PR and breaks the "separate backend per variant" invariant.
  Rejected.
- *Two pytest markers (`api_entry`/`ui_entry`) instead of `-k` on
  param IDs*: adds a second selection axis and a second place to update
  when the param IDs change. Rejected.

---

## R8. Product Gaps (Story 3 — initial audit)

These are the gaps identified from an initial read of
`backend/tests/e2e/*.py` against `frontend/src/pages/**`. They are
confirmed during Phase 1 contract generation and become concrete
follow-up tasks in `tasks.md`. Each gap is closed by extending the
weaker entrypoint, per FR-004 / FR-005 / SC-006.

| Scenario                            | Action needed                                | Side           | Current state                                   | Resolution                                                                                   |
| ----------------------------------- | -------------------------------------------- | -------------- | ----------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `test_service_discovery`            | Deploy with service-name overrides           | UI missing     | `DeployFormPage` has no service-override field  | Add a "Service name overrides" field-array to `DeployFormPage` surfaced via product nav.     |
| `test_backup_and_restore_lifecycle` | Create + restore + delete backup             | UI covered     | `DeploymentDetailPage` already has all three    | None.                                                                                        |
| `test_backup_and_restore_lifecycle` | Assign BSL to environment                    | UI covered     | `EnvironmentDetailPage` assigns/unassigns BSLs  | None.                                                                                        |
| `test_deploy_simple_app` (upgrade)  | Trigger upgrade from v0.1.0 to v0.2.0        | UI covered     | `DeploymentDetailPage` has Upgrade dialog       | None.                                                                                        |
| `test_deployment_timeline_*`        | Read deployment timeline                     | UI covered     | `DeploymentDetailPage` renders a timeline tab   | None.                                                                                        |
| Environment deletion (future tests) | Delete an environment                        | UI missing     | No delete control on `EnvironmentDetailPage`    | Out of scope for this feature — no existing scenario exercises it; flagged for follow-up.    |
| `test_ingress_controller`           | Configure dedicated ingress                  | To confirm     | Created via `styrmin_resources` fixture, not UI | Declare API-only with recorded rationale if the UI cannot surface cluster-level config.      |

**Rationale**: the audit's contract is "every scenario in scope at the
start of this work has a clearly identified resolution path"; this table
is that inventory. Any gap that turns out not to be closable is declared
single-entrypoint per FR-011 with its reason recorded on the test, not
silently skipped.

---

## R9. Dependencies to Add

Ask-first items (governance gate: "New dependencies") — all dev-only:

- `pytest-playwright` (and transitively the `playwright` runtime + its
  Chromium download)
- `pytest-rerunfailures`

No runtime/production dependencies are added. No database schema,
GraphQL schema, auth, or CI/CD structure changes beyond adding the
second e2e job.

**Note for the plan phase**: these are listed here so the approval gate
is explicit. They are added to `[dependency-groups] dev` in
`pyproject.toml` and installed via `uv sync --all-groups --all-packages`.
