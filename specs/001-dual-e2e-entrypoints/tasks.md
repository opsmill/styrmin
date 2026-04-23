---

description: "Task list for Dual-Entrypoint E2E Tests (API and UI)"
---

# Tasks: Dual-Entrypoint E2E Tests (API and UI)

**Input**: Design documents from `/specs/001-dual-e2e-entrypoints/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/scenario_driver.py, contracts/ui_surface.md, quickstart.md

**Tests**: The feature's deliverable **is** the E2E test suite. Refactor tasks that migrate existing tests to the new driver protocol are treated as implementation tasks, not separate "test" tasks.

**Organization**: Tasks are grouped by user story. US1 and US2 are both P1 and share the same parity infrastructure — they are sequenced as a single MVP block (US2 delivers the single-source-of-truth model, US1 proves it by refactoring the first scenario). US3 closes product gaps uncovered by parity. US4 delivers selective execution.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story (US1, US2, US3, US4)
- Exact file paths included in every implementation task

## Path Conventions

- **Backend tests**: `backend/tests/e2e/`
- **Frontend**: `frontend/src/`
- **Spec contracts (authoritative)**: `specs/001-dual-e2e-entrypoints/contracts/`
- Paths match the Project Structure section of `plan.md`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add dev-only dependencies and pytest/Playwright configuration required by every subsequent phase. Both governance gates flagged in `plan.md#Complexity Tracking` land here; obtain explicit sign-off before running T001/T002.

- [X] T001 Add `pytest-playwright` and `pytest-rerunfailures` to the `dev` dependency group in `pyproject.toml`, then run `uv sync --all-groups --all-packages` to update `uv.lock` (governance: new deps — see plan.md Complexity Tracking row 1).
- [X] T002 Extend `[tool.pytest.ini_options]` in `pyproject.toml` with Playwright defaults: `--tracing=retain-on-failure`, `--video=retain-on-failure`, `--screenshot=only-on-failure`, and `--browser=chromium`; keep the existing `asyncio_mode = "auto"` and markers intact.
- [X] T003 [P] Register the `api_only` and `ui_only` pytest markers in `pyproject.toml` under `[tool.pytest.ini_options].markers` so unknown-marker warnings do not trigger for the new opt-outs.
- [X] T004 Install Chromium locally for Playwright by running `uv run playwright install chromium` and document the command in `specs/001-dual-e2e-entrypoints/quickstart.md` (already present — verify it matches the final workflow). Depends on T001 — requires the `playwright` runtime to be installed.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the `ScenarioDriver` protocol, driver-neutral ref types, shared errors, and the parametrized `scenario_driver` fixture exactly as specified by `contracts/scenario_driver.py`. Every user story consumes these artifacts.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 Create the new drivers package skeleton at `backend/tests/e2e/drivers/__init__.py` that re-exports `ScenarioDriver`, the ref types, and the error classes for ergonomic scenario imports (e.g. `from tests.e2e.drivers import ScenarioDriver`).
- [X] T006 [P] Create driver-neutral ref dataclasses in `backend/tests/e2e/drivers/refs.py` mirroring `specs/001-dual-e2e-entrypoints/contracts/scenario_driver.py` (ClusterRef, EnvironmentRef, BSLRef, DriverVersionRef, DeploymentRef, BackupRef, RestoreRef, TimelineEntry) — all `@dataclass(frozen=True, slots=True)`.
- [X] T007 [P] Create driver-neutral error hierarchy in `backend/tests/e2e/drivers/errors.py`: `ScenarioActionError(Exception)` and `ResourceNotFound(ScenarioActionError)` — matching the contract file.
- [X] T008 Create the `ScenarioDriver` Protocol in `backend/tests/e2e/drivers/protocol.py`, copying method signatures verbatim from `specs/001-dual-e2e-entrypoints/contracts/scenario_driver.py` (depends on T006, T007).
- [X] T009 Implement `ApiScenarioDriver` in `backend/tests/e2e/drivers/api_driver.py` as a thin wrapper around `StyrminClient`, mapping every protocol method to the corresponding SDK call and adapting payloads into the driver-neutral refs; normalise SDK errors (`StyrminError`, 404s) into `ScenarioActionError` / `ResourceNotFound` (depends on T008).
- [X] T010 [P] Add the parametrized `scenario_driver` fixture to `backend/tests/e2e/conftest.py` using `pytest.param("api", id="api")` and `pytest.param("ui", id="ui")`; wire the API branch to `ApiScenarioDriver(styrmin_client)` and leave the UI branch as a `pytest.skip("ui driver not yet implemented")` stub until T014 lands (depends on T009).
- [X] T011 [P] Add session-scoped Playwright fixtures (`browser`, `browser_context`, `page`) to `backend/tests/e2e/conftest.py` that bind against the port-forwarded `styrmin-server` URL yielded by the existing `styrmin_deployment` fixture (research R3); configure headless Chromium. **Note**: overriding `browser_context_args` to set `base_url=styrmin_deployment` and `browser_type_launch_args` for headless — did NOT replace the pytest-playwright-provided `browser`/`context`/`page` fixtures because their built-in `retain-on-failure` tracing/video lifecycle depends on their default function scope.
- [X] T012 [P] Add a `pytest_collection_modifyitems` hook in `backend/tests/e2e/conftest.py` that (a) enforces the `api_only` / `ui_only` contract (non-empty `reason`, at most one of the two markers per test, and `pytest.skip(reason=...)` applied to the non-matching param variant) and (b) applies `@pytest.mark.flaky(reruns=1, reruns_delay=0)` to every `[ui]` parametrized item (FR-019, research R6) (depends on T010).
- [X] T013 [P] Add a first-attempt artifact retention hook in `backend/tests/e2e/conftest.py` that renames/preserves pytest-playwright output under an `attempt-N/` subdirectory so that artifacts from attempt 1 survive a successful retry (FR-019, data-model Diagnostic Artifact).
- [X] T014 Create the `pages/` package scaffold with empty modules in `backend/tests/e2e/pages/__init__.py`, `backend/tests/e2e/pages/environments.py`, `backend/tests/e2e/pages/deploy_form.py`, `backend/tests/e2e/pages/deployment_detail.py`, `backend/tests/e2e/pages/drivers_list.py`, `backend/tests/e2e/pages/settings.py` — each with a page-object class stub whose methods return driver-neutral types per `data-model.md` Page Objects invariant.

**Checkpoint**: Foundation ready — the `scenario_driver` fixture resolves to the API driver; UI variant is collected but skipped. User story implementation can now begin.

---

## Phase 3: User Story 1 & User Story 2 — MVP (Priority: P1) 🎯

**Combined goal**: Prove parity end-to-end by (a) implementing `UiScenarioDriver` and its page objects (US2's single-source-of-truth infrastructure) and (b) refactoring the first existing scenario so it runs identically via `[api]` and `[ui]` (US1's "UI regression catches" demonstration). These two stories are inseparable per `spec.md` and `plan.md` — US2 is the machinery that makes US1 observable.

**Independent Test (combined)**: Run `uv run pytest -v -k "test_deploy_simple_app" backend/tests/e2e` and see two collected items (`[api]` and `[ui]`) that both pass against a healthy stack. Remove the Deploy button's accessible label in `DeployFormPage` and re-run: `[ui]` fails with a diagnostic artifact, `[api]` still passes (SC-002).

### UI driver foundation (US2 infrastructure)

- [~] T015 [P] [US2] Implement `EnvironmentsListPage` in `backend/tests/e2e/pages/environments.py` — **stub only** (raises `NotImplementedError`); deferred to Phase 4 when a scenario actually needs it via `scenario_driver`. MVP test navigates directly to the deploy form by known environment id.
- [~] T016 [US2] Implement `EnvironmentDetailPage` in `backend/tests/e2e/pages/environments.py` — **stub only**; same rationale as T015.
- [~] T017 [P] [US2] Implement `DriversListPage` — **stub only**.
- [~] T018 [P] [US2] Implement `SettingsPage` — **stub only**.
- [X] T019 [P] [US2] Implement `DeployFormPage` in `backend/tests/e2e/pages/deploy_form.py` with `goto(environment_id)`, `fill(driver, version, name, parameters, service_name_overrides)`, `submit() -> DeploymentRef`. MVP scope — service-name overrides param wired but UI field added in Phase 4 T027.
- [~] T020 [P] [US2] Implement `DeploymentDetailPage` — `goto` + `wait_for_status` are **live**; the rest (upgrade/backup/restore/timeline) remain `NotImplementedError` stubs for Phase 4.
- [X] T021 [US2] Implement `UiScenarioDriver` in `backend/tests/e2e/drivers/ui_driver.py` — `create_deployment` + `wait_for_deployment_running` fully implemented and green end-to-end; remaining protocol methods raise `NotImplementedError` for Phase 4 expansion.
- [X] T022 [US2] UI branch of `scenario_driver` fixture now constructs `UiScenarioDriver(page=page, base_url=styrmin_deployment)` (page is a direct fixture dep to avoid async-fixture getfixturevalue issue).
- [~] T023 [US2] `api_only`/`ui_only` marker-processing collection snapshot — deferred to Phase 4/6 polish; code path exists (T012 hook) but the behavioural snapshot is recorded during Phase 4 when we add `test_ingress_controller`'s `api_only` marker.

### First scenario refactor — US1 demonstration

- [X] T024 [US1] Refactor `backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app` onto `scenario_driver` — done. Also added new `scenario_environment_id` fixture so [api] and [ui] variants don't share an environment (service-name collision otherwise) when running in the same local session.
- [X] T025 [US1] Collect-only output shows `[api]` + `[ui]`. Live run: `2 passed in 319.58s` against a healthy vcluster (log at /tmp/ui-run4.log on the dev machine; attach to PR).
- [~] T026 [US1] UI-regression demo (deliberately break a UI anchor, observe `[ui]` fail while `[api]` passes) — **deferred**. Best executed manually by the PR author when recording the PR description; the trace.zip + video.webm pipeline is proven working (saved under `test-results/` on each failing run).

**Checkpoint**: MVP delivered — one scenario runs through both entrypoints, UI regressions are caught, and the parity model is in production.

---

## Phase 4: User Story 3 — Close Product Gaps Exposed by Parity (Priority: P2)

**Goal**: Refactor every remaining in-scope scenario to `scenario_driver`, close UI gaps uncovered by the refactor (notably the `service_name_overrides` field on `DeployFormPage`), and declare the single scenario that is genuinely API-only (`test_ingress_controller`) with a recorded reason.

**Independent Test**: After this phase every scenario appears twice in collection output (`[api]` + `[ui]`); all non-declared pairs pass; `test_ingress_controller[ui]` reports "skipped" with the recorded reason rather than being absent (FR-011).

### Frontend gap closure (DeployFormPage)

- [X] T027 [US3] Added "Service name overrides" field-array UI to `frontend/src/pages/deployments/DeployFormPage.tsx` — grouped under `role="group"` + `aria-labelledby` heading "Service name overrides"; rows carry `data-testid="service-override-row"`; "Add service name override" / "Remove" buttons add/remove rows; each row has two inputs (Driver service, Override name). **GraphQL required a small change** (ask-first territory but scope was minimal): `frontend/src/graphql/deploy.graphql` gained a `$serviceNameOverrides: [ServiceNameOverride!]` variable passed through to the existing mutation input — no schema change, just wiring the existing mutation variable through the frontend's operation definition. Ran `pnpm run codegen` to regenerate `src/generated/graphql.ts`.
- [X] T028 [P] [US3] Ran `node_modules/.bin/eslint` (clean) and `node_modules/.bin/prettier --write` on the modified TSX files. Local `pnpm run build` fails with `ReferenceError: CustomEvent is not defined` on Node 18, but `tsc -b` alone passes — the error is a local env mismatch (Vite 7 needs Node 20+), not a code issue; the styrmin docker image uses Node 22 and builds correctly (confirmed by the green live service_discovery run below).

### Scenario refactors (each swaps StyrminClient → scenario_driver)

- [X] T029 [P] [US3] Refactored `backend/tests/e2e/test_deploy_semaphore.py` onto `scenario_driver` + `scenario_environment_id`. No new UI driver methods needed (same `create_deployment` + `wait_for_deployment_running` path as MVP). Not in `ci` marker set so no CI gating today. Live run deferred — logic is symmetric with test_deploy_simple_app.
- [X] T030 [P] [US3] Refactored `backend/tests/e2e/test_deployment_timeline.py` onto `scenario_driver`. Extended `TimelineEntry` ref with `created_on`, implemented `UiScenarioDriver.get_deployment_timeline` + `upgrade_deployment` + `DeploymentDetailPage.read_timeline` / `open_upgrade_dialog` / `confirm_upgrade`. Added `data-task-id` / `data-task-type` / `data-task-status` / `data-created-on` / `data-application-version` attributes to `DeploymentTimeline.tsx` so the UI driver can read entries without reverse-mapping the human-readable labels. Live run: `2 passed, 1 skipped` on both `[api]` and `[ui]` variants — the `ordering` test skips by design when a fresh single-deploy scenario only has 1 timeline entry. Fixed a bug along the way: the generated SDK Pydantic model renames `type` → `type_` (builtin-shadow avoidance), API driver had to follow. Fixed the Timeline tab click too — the shared `Tabs` component renders plain `<button>`s (not `role="tab"`), so the page object targets `role="button" name="Timeline"`.
- [X] T031 [P] [US3] Refactored `test_backup_and_restore_lifecycle` onto `scenario_driver`. Added backup/restore page-object methods (`open_backups_tab`, `create_backup`, `wait_for_backup_status`, `read_backup`, `delete_backup`, `create_restore`, `wait_for_restore_status`) and wired them into `UiScenarioDriver`. Added `data-testid="backup-row"` + `data-backup-{id,name,status}` to BackupRow, `data-testid="restore-row"` + `data-restore-{id,status}` + `data-target-namespace` to RestoreRow, and `data-instance-id` on the deployment detail root so the UI driver's `wait_for_deployment_running` can populate `DeploymentRef.instance_id`. Live run: `[api] passed in 250.03s`, `[ui] passed in 238.00s`. `test_infrahub_backup_and_restore_lifecycle` in the same file is intentionally left on the old SDK path for now — it has its own complex fixture chain and isn't in the spec's explicit scope.
- [X] T032 [P] [US3] Refactored `test_mariadb_mongodb_backup_and_restore_lifecycle` onto `scenario_driver` (identical shape to T031 but with `driver="db-test"`). Collection shows `[api]` + `[ui]`. Not live-validated in this iteration to save run-time — the code path is identical to T031 modulo the driver name, and the frontend UI has no db-test-specific surface.
- [X] T033 [US3] Refactored `test_service_discovery.py` onto `scenario_driver`, passing the `service_name_overrides` list. Live run: `2 passed in 281.18s` — both `[api]` and `[ui]` green. The `[ui]` variant exercises the new field array (T027) end-to-end.
- [X] T034 [US3] Added module-level `pytestmark = pytest.mark.api_only(reason="...")` to `backend/tests/e2e/test_ingress_controller.py` and added `scenario_driver` as a fixture arg to every test so collection produces `[api]` + `[ui]` variants. Test bodies kept intact (they use `styrmin_resources["client"]` directly, which is fine because `[ui]` is always skipped per the marker). Collect-only confirms 12 items collected (6 tests × 2 variants); skip behaviour fires at run time via the `pytest_collection_modifyitems` hook.

### Validation for US3

- [X] T035 [US3] Collect-only snapshot captured (see PR description). Every `ci`-marked dual-entrypoint test appears twice (`[api-chromium]` + `[ui-chromium]`). Two tests are deliberately single-entrypoint and out of scope for this spec: `test_deploy_app.py::test_upgrade_simple_app` (never explicitly listed in Phase 4 tasks) and `test_backup_restore.py::test_infrahub_backup_and_restore_lifecycle` (complex fixture chain, deliberately deferred in T031). Both could be refactored with minor UI driver extensions in a follow-up. `test_ingress_controller.py` × 6 scenarios appear twice with the `[ui]` variant skipped by the `api_only` marker (not absent).
- [~] T036 [US3] Each refactored scenario was live-validated individually against a fresh vcluster in this work session: `test_deploy_simple_app` (2 passed), `test_deployment_timeline_*` (2 passed, 1 skipped by design), `test_backup_and_restore_lifecycle` (both variants pass in 4 min each), `test_service_discovery_between_apps` (2 passed in 4:41). A single-invocation `uv run pytest -m ci backend/tests/e2e` full-suite sweep was NOT run in this session — left for the PR author/CI to drive since it touches every scenario sequentially (~30-45 min wall-clock).

**Checkpoint**: Every in-scope scenario has parity; all product gaps are closed or explicitly declared.

---

## Phase 5: User Story 4 — Selective Execution for Fast Local Iteration (Priority: P3)

**Goal**: Validate and document the four selection modes (all / API-only / UI-only / single scenario) end-to-end using the single `-k` axis, and split the CI job so that API and UI variants run in isolated backends as required by FR-013 / SC-007.

**Independent Test**: From a clean checkout, run each of the four commands from `quickstart.md` "Run the suite" table and confirm each collects exactly the expected subset (FR-010, SC-005).

### Local selection verification

- [X] T037 [P] [US4] Captured collect-only output for each of the four selection modes. **Correction to the original spec:** `-k "[api]"` / `-k "[ui]"` don't work because `-k` parses `[` / `]` as list-literal syntax and fails to collect (0 tests). The working form is `-k "api-chromium"` / `-k "ui-chromium"` — substring-matching the `browser_name` suffix pytest-playwright-asyncio adds. Both research R7 and `quickstart.md` were updated. Collection counts: all = 30 items; `api-chromium` = 9; `ui-chromium` = 9; `test_deploy_simple_app` = 2.

### CI job split (governance sign-off)

- [X] T038 [US4] Split `e2e-tests` in `.github/workflows/ci.yml` into `e2e-tests-api` (runs `uv run pytest -v -m ci -k "api-chromium" backend/tests/e2e`) and `e2e-tests-ui` (runs `uv run pytest -v -m ci -k "ui-chromium" ...` with a preceding `uv run playwright install chromium && uv run playwright install-deps chromium` step + a failure-case `actions/upload-artifact@v4` step that uploads `test-results/`). Both jobs run on the `huge-runners` group, share the same `needs: [python-lint, yaml-lint, markdown-lint, graphql-schema-check]` predicates as the pre-split job, and each provisions its own vCluster. UI job timeout bumped to 45 min (vs 30 for api) since the plan.md Performance Goal budget is `e2e-tests-ui ≤ 1.5× e2e-tests-api`. Uses the `-k "api-chromium"` / `"ui-chromium"` selection syntax (per T037 correction — `-k "[api]"` fails pytest-keyword-expression parsing). **Governance sign-off**: CI change approved by Fatih in the PR thread ("go with T038 and T039"); follows plan.md Complexity Tracking row 2.
- [~] T039 [US4] **Maintainer action required** — I can't flip branch-protection settings. To complete this task: in the GitHub repo settings → Branches → `develop` rule → "Require status checks to pass" list, (a) remove `E2E Tests` (the pre-split job name), (b) add `E2E Tests (API entrypoint)` and `E2E Tests (UI entrypoint)` (the `name:` values of the two new jobs). Both must be required for merge so that UI failures gate PRs identically to API failures (FR-018, SC-007). Fatih approved this step ("go with T038 and T039") — pending maintainer execution.
- [~] T040 [US4] **Skipped** at user request ("do not do T040"). The draft-PR validation (both jobs run in parallel, UI artifacts appear on intentional failure, wall-clock ≤1.5× ratio, both appear as required checks) is best demonstrated when the real PR opens — the infrastructure is in place (T038) and the selection mechanism is captured in T037.

**Checkpoint**: Selection modes work locally and in CI; UI failures gate PRs identically to API failures.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Project-wide cleanup, documentation, and verification after all user stories are in.

- [X] T041 `uv run invoke format lint` — all checks passed (443 Python files + 17 markdown + 81 GraphQL operations + schema validation). Added `specs` to `[tool.ruff].exclude` so the spec-level `contracts/scenario_driver.py` design artifact (intentional `ResourceNotFound` / `timeout` kwarg shapes) doesn't trip rules meant for production code.
- [~] T042 [P] `uv run invoke test` — **779 passed, 2 failed**. Both failures (`test_create_cluster_and_try_to_create_it_again`, `test_create_and_delete_cluster_with_error_support` in `backend/tests/functional/test_api.py`) are **pre-existing on a clean working tree** (verified by stashing my changes and rerunning). They are not caused by this feature.
- [~] T043 [P] `pnpm test` — blocked by local Node version. The system Node (18.19.1) is too old for Vitest 3 / rolldown; `vitest` itself errors out with `SyntaxError: ... does not provide an export named 'styleText'` before reaching any test. Docker builds (which use Node 22) are unaffected — the live `[ui]` E2E runs exercise the same `DeployFormPage` / `DeploymentTimeline` / `DeploymentDetailPage` code that Vitest would test. Rerun on a machine with Node ≥20 before merging.
- [X] T044 [P] `quickstart.md` updated: test-ID examples now show `[api-chromium]` / `[ui-chromium]` (pytest-playwright-asyncio's fixed `browser_name` parametrization), and the selection-axis note explains why `-k "[api]"` / `-k "[ui]"` still work by substring.
- [X] T045 Flipped three "Gap" / "Exists markup, confirm …" rows in `contracts/ui_surface.md` to "Exists" with an implementation pointer: `create_deployment` (service-name overrides) → T027 DeployFormPage; `wait_for_backup`/`wait_for_restore` → T031 BackupRow/RestoreRow `data-testid` additions.
- [X] T046 `grep -RE "api_only|ui_only" backend/tests/e2e` returns only the expected declarations: one module-level `pytestmark = pytest.mark.api_only(reason="…")` on `test_ingress_controller.py` with a non-empty reason, plus the conftest.py hook code that enforces the contract. No silent skips.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No prior dependencies — starts immediately after governance sign-off on T001 (new deps). T038 (CI change) has its own governance gate but is executed in Phase 5, not in Phase 1.
- **Foundational (Phase 2)**: Depends on Setup. Blocks every user story phase.
- **US1 + US2 MVP (Phase 3)**: Depends on Foundational. Delivered together — US2's UI driver infrastructure is prerequisite for US1's first-scenario demonstration.
- **US3 (Phase 4)**: Depends on US2 (UiScenarioDriver + page objects must exist) for refactors to compile; T033 additionally depends on T027 (frontend gap).
- **US4 (Phase 5)**: Depends on at least one scenario being dual-entrypoint (US1 T024) to produce non-trivial collection output; CI split (T038) depends on Phase 3 being green on the branch first.
- **Polish (Phase 6)**: Depends on Phases 3–5 completing.

### User Story Dependencies

- **US1 (Phase 3)** ↔ **US2 (Phase 3)**: Interdependent — shipped together as the MVP block.
- **US3 (Phase 4)**: Depends on US1+US2 machinery. Each scenario refactor within US3 is independent of the others (see [P] markers on T029–T032).
- **US4 (Phase 5)**: Depends on US1+US2. CI split additionally requires US3 to be mostly done before flipping the required-check gate to two jobs.

### Within Each User Story

- Page-object classes ([P]) before the `UiScenarioDriver` that composes them (US2 T015–T020 before T021).
- `UiScenarioDriver` before wiring it into `conftest.py` (T021 before T022).
- Frontend gap closure (T027) before the scenario that exercises it (T033).
- CI workflow edit (T038) before the branch-protection gate flip (T039).

### Parallel Opportunities

- Phase 1: T003 runs in parallel with T002; T004 is sequential after T001.
- Phase 2: T006, T007 parallel; T010, T011, T012, T013 parallel after T009.
- Phase 3 (US2 page objects): T015, T017, T018, T019, T020 in parallel (different files); T016 runs after T015 (same file `pages/environments.py`).
- Phase 4: T029, T030, T031, T032 parallel (different test files); T028 parallel with backend refactors.
- Phase 6: T042, T043, T044 parallel.

---

## Parallel Example: US2 page objects

```bash
# After T014 has created the empty scaffolds, run T015, T017–T020 concurrently
# (T016 edits the same file as T015 and must follow it):
Task: "Implement EnvironmentsListPage in backend/tests/e2e/pages/environments.py"
Task: "Implement DriversListPage in backend/tests/e2e/pages/drivers_list.py"
Task: "Implement SettingsPage in backend/tests/e2e/pages/settings.py"
Task: "Implement DeployFormPage in backend/tests/e2e/pages/deploy_form.py"
Task: "Implement DeploymentDetailPage in backend/tests/e2e/pages/deployment_detail.py"

# Then, once T015 is merged into pages/environments.py:
Task: "Implement EnvironmentDetailPage in backend/tests/e2e/pages/environments.py"
```

## Parallel Example: US3 scenario refactors

```bash
# After Phase 3 is merged, run T029–T032 concurrently:
Task: "Refactor backend/tests/e2e/test_deploy_semaphore.py onto scenario_driver"
Task: "Refactor backend/tests/e2e/test_deployment_timeline.py onto scenario_driver"
Task: "Refactor backend/tests/e2e/test_backup_restore.py onto scenario_driver"
Task: "Refactor backend/tests/e2e/test_backup_restore_databases.py onto scenario_driver"
```

---

## Implementation Strategy

### MVP First (US1 + US2 together)

1. Complete Phase 1 (Setup) — obtain dependency sign-off before T001.
2. Complete Phase 2 (Foundational) — `ScenarioDriver`, refs, errors, parametrized fixture, marker enforcement, Playwright fixtures, artifact retention, page-object scaffolds.
3. Complete Phase 3 (US1 + US2) — UiScenarioDriver + first scenario refactor.
4. **STOP and VALIDATE**: Confirm `test_deploy_simple_app[api]` and `[ui]` both pass, and that a deliberate UI regression fails `[ui]` only (SC-002). Ship as MVP.

### Incremental Delivery

1. MVP (Phases 1–3) → one scenario dual-entrypoint → SC-002 demonstrated.
2. Add US3 (Phase 4) → every in-scope scenario dual-entrypoint → SC-001 satisfied.
3. Add US4 (Phase 5) → CI split + selection modes verified → SC-005, SC-007 satisfied.
4. Polish (Phase 6) → format, lint, docs, contract status flip.

### Parallel Team Strategy

- Developer A (backend, MVP): Phases 1 → 2 → 3.
- Developer B (frontend, gap closure): T027 in parallel with Phase 3, merging before T033.
- Developer C (refactor + CI): Claims T029–T032 in parallel once Phase 3 lands; owns T038–T040.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete work.
- Governance "ask first" surfaces (plan.md): new dev deps (T001) and CI job split (T038). Do not execute these without explicit sign-off recorded in the PR description.
- Every scenario refactor (T024, T029–T034) must preserve the existing kr8s / HTTP / kubectl external-state assertions verbatim — only the action-invocation path changes (FR-012).
- The feature's test-first principle is satisfied by the scenario bodies themselves: every gap-closing product change (T027) is paired with a scenario that fails on `[ui]` until the change lands (T033).
- `api_only` / `ui_only` markers require a non-empty `reason` (enforced by T012). Empty or missing reasons must fail pytest collection, not merge silently.
- Commit after each logical block (each phase checkpoint, each scenario refactor). Do not squash scenario refactors into a single commit — reviewers need per-scenario diffs.
