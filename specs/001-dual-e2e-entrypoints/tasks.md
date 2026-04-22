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

- [ ] T001 Add `pytest-playwright` and `pytest-rerunfailures` to the `dev` dependency group in `pyproject.toml`, then run `uv sync --all-groups --all-packages` to update `uv.lock` (governance: new deps — see plan.md Complexity Tracking row 1).
- [ ] T002 Extend `[tool.pytest.ini_options]` in `pyproject.toml` with Playwright defaults: `--tracing=retain-on-failure`, `--video=retain-on-failure`, `--screenshot=only-on-failure`, and `--browser=chromium`; keep the existing `asyncio_mode = "auto"` and markers intact.
- [ ] T003 [P] Register the `api_only` and `ui_only` pytest markers in `pyproject.toml` under `[tool.pytest.ini_options].markers` so unknown-marker warnings do not trigger for the new opt-outs.
- [ ] T004 [P] Install Chromium locally for Playwright by running `uv run playwright install chromium` and document the command in `specs/001-dual-e2e-entrypoints/quickstart.md` (already present — verify it matches the final workflow).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the `ScenarioDriver` protocol, driver-neutral ref types, shared errors, and the parametrized `scenario_driver` fixture exactly as specified by `contracts/scenario_driver.py`. Every user story consumes these artifacts.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T005 Create the new drivers package skeleton at `backend/tests/e2e/drivers/__init__.py` that re-exports `ScenarioDriver`, the ref types, and the error classes for ergonomic scenario imports (e.g. `from tests.e2e.drivers import ScenarioDriver`).
- [ ] T006 [P] Create driver-neutral ref dataclasses in `backend/tests/e2e/drivers/refs.py` mirroring `specs/001-dual-e2e-entrypoints/contracts/scenario_driver.py` (ClusterRef, EnvironmentRef, BSLRef, DriverVersionRef, DeploymentRef, BackupRef, RestoreRef, TimelineEntry) — all `@dataclass(frozen=True, slots=True)`.
- [ ] T007 [P] Create driver-neutral error hierarchy in `backend/tests/e2e/drivers/errors.py`: `ScenarioActionError(Exception)` and `ResourceNotFound(ScenarioActionError)` — matching the contract file.
- [ ] T008 Create the `ScenarioDriver` Protocol in `backend/tests/e2e/drivers/protocol.py`, copying method signatures verbatim from `specs/001-dual-e2e-entrypoints/contracts/scenario_driver.py` (depends on T006, T007).
- [ ] T009 Implement `ApiScenarioDriver` in `backend/tests/e2e/drivers/api_driver.py` as a thin wrapper around `StyrminClient`, mapping every protocol method to the corresponding SDK call and adapting payloads into the driver-neutral refs; normalise SDK errors (`StyrminError`, 404s) into `ScenarioActionError` / `ResourceNotFound` (depends on T008).
- [ ] T010 [P] Add the parametrized `scenario_driver` fixture to `backend/tests/e2e/conftest.py` using `pytest.param("api", id="api")` and `pytest.param("ui", id="ui")`; wire the API branch to `ApiScenarioDriver(styrmin_client)` and leave the UI branch as a `pytest.skip("ui driver not yet implemented")` stub until T014 lands (depends on T009).
- [ ] T011 [P] Add session-scoped Playwright fixtures (`browser`, `browser_context`, `page`) to `backend/tests/e2e/conftest.py` that bind against the port-forwarded `styrmin-server` URL yielded by the existing `styrmin_deployment` fixture (research R3); configure headless Chromium.
- [ ] T012 [P] Add a `pytest_collection_modifyitems` hook in `backend/tests/e2e/conftest.py` that (a) enforces the `api_only` / `ui_only` contract (non-empty `reason`, at most one of the two markers per test, and `pytest.skip(reason=...)` applied to the non-matching param variant) and (b) applies `@pytest.mark.flaky(reruns=1, reruns_delay=0)` to every `[ui]` parametrized item (FR-019, research R6) (depends on T010).
- [ ] T013 [P] Add a first-attempt artifact retention hook in `backend/tests/e2e/conftest.py` that renames/preserves pytest-playwright output under an `attempt-N/` subdirectory so that artifacts from attempt 1 survive a successful retry (FR-019, data-model Diagnostic Artifact).
- [ ] T014 Create the `pages/` package scaffold with empty modules in `backend/tests/e2e/pages/__init__.py`, `backend/tests/e2e/pages/environments.py`, `backend/tests/e2e/pages/deploy_form.py`, `backend/tests/e2e/pages/deployment_detail.py`, `backend/tests/e2e/pages/drivers_list.py`, `backend/tests/e2e/pages/settings.py` — each with a page-object class stub whose methods return driver-neutral types per `data-model.md` Page Objects invariant.

**Checkpoint**: Foundation ready — the `scenario_driver` fixture resolves to the API driver; UI variant is collected but skipped. User story implementation can now begin.

---

## Phase 3: User Story 1 & User Story 2 — MVP (Priority: P1) 🎯

**Combined goal**: Prove parity end-to-end by (a) implementing `UiScenarioDriver` and its page objects (US2's single-source-of-truth infrastructure) and (b) refactoring the first existing scenario so it runs identically via `[api]` and `[ui]` (US1's "UI regression catches" demonstration). These two stories are inseparable per `spec.md` and `plan.md` — US2 is the machinery that makes US1 observable.

**Independent Test (combined)**: Run `uv run pytest -v -k "test_deploy_simple_app" backend/tests/e2e` and see two collected items (`[api]` and `[ui]`) that both pass against a healthy stack. Remove the Deploy button's accessible label in `DeployFormPage` and re-run: `[ui]` fails with a diagnostic artifact, `[api]` still passes (SC-002).

### UI driver foundation (US2 infrastructure)

- [ ] T015 [P] [US2] Implement `EnvironmentsListPage` in `backend/tests/e2e/pages/environments.py` with `create_environment(name, cluster_id, config) -> EnvironmentRef` and `open_environment(environment_id) -> EnvironmentDetailPage`, using `get_by_role` / `get_by_label` per research R4 and `ui_surface.md`.
- [ ] T016 [P] [US2] Implement `EnvironmentDetailPage` in `backend/tests/e2e/pages/environments.py` (same file — separate class) with `assign_bsl(bsl_id)`, `open_deploy_form() -> DeployFormPage` — stable anchors per `contracts/ui_surface.md`.
- [ ] T017 [P] [US2] Implement `DriversListPage` in `backend/tests/e2e/pages/drivers_list.py` with `add_driver(git_url, ref) -> DriverVersionRef` — targets the "Add driver" dialog per `ui_surface.md`.
- [ ] T018 [P] [US2] Implement `SettingsPage` in `backend/tests/e2e/pages/settings.py` with `open_clusters_tab()` and `create_cluster(name, config) -> ClusterRef` — targets Settings → Clusters per `ui_surface.md`.
- [ ] T019 [P] [US2] Implement `DeployFormPage` in `backend/tests/e2e/pages/deploy_form.py` with `fill(driver, version, name, parameters)`, `submit() -> DeploymentRef` (service-name overrides field added later in US3 T033).
- [ ] T020 [P] [US2] Implement `DeploymentDetailPage` in `backend/tests/e2e/pages/deployment_detail.py` with `wait_for_status(expected, timeout)`, `open_upgrade_dialog()`, `confirm_upgrade(version)`, `read_timeline() -> list[TimelineEntry]`, `open_backups_tab()`, `create_backup() -> BackupRef`, `delete_backup(backup_id)`, `open_restores_tab()`, `create_restore(backup_id, target_namespace) -> RestoreRef`, using `data-testid="backup-status"` / `data-testid="restore-status"` fallbacks where roles are ambiguous.
- [ ] T021 [US2] Implement `UiScenarioDriver` in `backend/tests/e2e/drivers/ui_driver.py` composing the page objects from T015–T020 to satisfy every method of `ScenarioDriver.Protocol`; each action must end on a deterministic success signal (toast, status badge transition, or navigation complete) per `data-model.md` (depends on T015–T020).
- [ ] T022 [US2] Replace the UI-branch `pytest.skip(...)` stub in `backend/tests/e2e/conftest.py` (from T010) with `UiScenarioDriver(page=page, base_url=styrmin_deployment_url)` construction (depends on T021).
- [ ] T023 [US2] Confirm the `api_only` / `ui_only` marker processing from T012 produces the right collection output by writing a single `@pytest.mark.api_only(reason="...")` scenario stub temporarily in `backend/tests/e2e/test_deploy_app.py` and verifying `[ui]` is reported as skipped (not missing) — delete the stub once verified. No separate test file is introduced.

### First scenario refactor — US1 demonstration

- [ ] T024 [US1] Refactor `backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app` to take `scenario_driver: ScenarioDriver` (instead of `styrmin_client: StyrminClient`) and drive every product action through the driver; keep all kr8s / HTTP external-state assertions as-is (FR-012, quickstart "Example").
- [ ] T025 [US1] Verify `pytest --collect-only backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app` reports exactly two items (`[api]` and `[ui]`); then run both locally against a healthy stack per `quickstart.md` and confirm both pass.
- [ ] T026 [US1] Validate Acceptance Scenario 2 by temporarily modifying a UI anchor in `frontend/src/pages/deployments/DeployFormPage.tsx` (e.g., remove the Deploy button's accessible label), re-running the suite, observing `[ui]` fail with a `trace.zip` + `video.webm` + `test-failed-*.png` under `test-results/` while `[api]` passes — then revert the change. Record the demonstration in the PR description.

**Checkpoint**: MVP delivered — one scenario runs through both entrypoints, UI regressions are caught, and the parity model is in production.

---

## Phase 4: User Story 3 — Close Product Gaps Exposed by Parity (Priority: P2)

**Goal**: Refactor every remaining in-scope scenario to `scenario_driver`, close UI gaps uncovered by the refactor (notably the `service_name_overrides` field on `DeployFormPage`), and declare the single scenario that is genuinely API-only (`test_ingress_controller`) with a recorded reason.

**Independent Test**: After this phase every scenario appears twice in collection output (`[api]` + `[ui]`); all non-declared pairs pass; `test_ingress_controller[ui]` reports "skipped" with the recorded reason rather than being absent (FR-011).

### Frontend gap closure (DeployFormPage)

- [ ] T027 [US3] Add a "Service name overrides" field-array UI to `frontend/src/pages/deployments/DeployFormPage.tsx`: grouped under `role="group"` with `aria-labelledby` pointing at a heading "Service name overrides"; rows wired to the existing `deploy` mutation's `service_name_overrides` input (no GraphQL change). Add `data-testid="service-override-row"` on each row for stable anchoring.
- [ ] T028 [P] [US3] Run `pnpm lint` and `pnpm format` in `frontend/` and fix any issues introduced by T027.

### Scenario refactors (each swaps StyrminClient → scenario_driver)

- [ ] T029 [P] [US3] Refactor `backend/tests/e2e/test_deploy_semaphore.py` to take `scenario_driver: ScenarioDriver`; keep all non-driver fixtures and external assertions unchanged.
- [ ] T030 [P] [US3] Refactor `backend/tests/e2e/test_deployment_timeline.py` to take `scenario_driver: ScenarioDriver`; drive every action through the driver, including `get_deployment_timeline`.
- [ ] T031 [P] [US3] Refactor `backend/tests/e2e/test_backup_restore.py` (covers `test_backup_and_restore_lifecycle`) to take `scenario_driver: ScenarioDriver`; verify BSL-assignment, backup, restore, and delete paths all route through the driver.
- [ ] T032 [P] [US3] Refactor `backend/tests/e2e/test_backup_restore_databases.py` to take `scenario_driver: ScenarioDriver`.
- [ ] T033 [US3] Refactor `backend/tests/e2e/test_service_discovery.py` to take `scenario_driver: ScenarioDriver` and pass `service_name_overrides=[...]` into `create_deployment`; the `[ui]` variant exercises the new field-array added in T027 (depends on T027, T019).
- [ ] T034 [US3] Mark `backend/tests/e2e/test_ingress_controller.py` with `@pytest.mark.api_only(reason="ingress controller is configured at cluster level via the styrmin_resources fixture; no UI surface today")` and refactor its body to use `scenario_driver` where applicable (cluster creation, environment creation). The `[ui]` variant will be collected and reported as skipped with this reason (FR-011, research R8) (depends on T012).

### Validation for US3

- [ ] T035 [US3] Run `uv run pytest --collect-only backend/tests/e2e` and confirm every test function except those marked `api_only`/`ui_only` appears twice in collection; single-entrypoint tests must still appear twice, with the opposite variant reported as skipped (never absent). Save collection output snippet in the PR description for reviewer verification.
- [ ] T036 [US3] Run the full suite locally against a healthy stack (`uv run pytest -m ci backend/tests/e2e`) and confirm every `[api]` + `[ui]` pair passes; investigate any UI flakiness that survives the automatic retry before merging.

**Checkpoint**: Every in-scope scenario has parity; all product gaps are closed or explicitly declared.

---

## Phase 5: User Story 4 — Selective Execution for Fast Local Iteration (Priority: P3)

**Goal**: Validate and document the four selection modes (all / API-only / UI-only / single scenario) end-to-end using the single `-k` axis, and split the CI job so that API and UI variants run in isolated backends as required by FR-013 / SC-007.

**Independent Test**: From a clean checkout, run each of the four commands from `quickstart.md` "Run the suite" table and confirm each collects exactly the expected subset (FR-010, SC-005).

### Local selection verification

- [ ] T037 [P] [US4] Execute each of the four selection commands from `specs/001-dual-e2e-entrypoints/quickstart.md` (all / `-k "[api]"` / `-k "[ui]"` / single scenario), capture `pytest --collect-only` output for each, and paste the four outputs into the PR description to demonstrate SC-005.

### CI job split (governance sign-off)

- [ ] T038 [US4] Split the existing `e2e-tests` job in `.github/workflows/ci.yml` into `e2e-tests-api` (runs `uv run pytest -v -m ci -k "[api]" backend/tests/e2e`) and `e2e-tests-ui` (runs `uv run pytest -v -m ci -k "[ui]" backend/tests/e2e` plus a `uv run playwright install chromium` step); both run on the `huge-runners` group, each provisions its own vCluster, and both are required for PR merge (FR-018, governance: CI/CD change — see plan.md Complexity Tracking row 2).
- [ ] T039 [US4] Update the required-status-checks list in the repository's branch protection (or document the change so a maintainer applies it) so that both `e2e-tests-api` and `e2e-tests-ui` block merges to `develop` — matching the pre-split `e2e-tests` gate exactly (FR-018, SC-007).
- [ ] T040 [US4] Trigger the new workflow on a draft PR and confirm: (a) both jobs run in parallel against independent vClusters, (b) the UI job produces `test-results/` artifacts on an intentionally failing commit, and (c) both jobs appear as required checks. Revert the intentional failure before merging.

**Checkpoint**: Selection modes work locally and in CI; UI failures gate PRs identically to API failures.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Project-wide cleanup, documentation, and verification after all user stories are in.

- [ ] T041 Run `uv run invoke format lint` at repo root and fix any issues across `backend/tests/e2e/**` introduced by the refactor (project guideline: format before commit).
- [ ] T042 [P] Run `uv run invoke test` to confirm no unrelated backend tests regressed.
- [ ] T043 [P] Run `pnpm test` in `frontend/` to confirm `DeployFormPage` component tests still pass after the T027 change.
- [ ] T044 [P] Verify `specs/001-dual-e2e-entrypoints/quickstart.md` still matches final behaviour end-to-end; update any drift in commands, artifact paths, or example scenario.
- [ ] T045 Walk the `specs/001-dual-e2e-entrypoints/contracts/ui_surface.md` "Status" column against the implementation and flip every row from "Gap" to "Exists"; add an "as of <PR URL>" note so reviewers can trace the closure.
- [ ] T046 Double-check that no scenario silently omits either entrypoint (FR-011): `grep -RE "api_only|ui_only" backend/tests/e2e` must return only expected declarations with non-empty `reason`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No prior dependencies — starts immediately after governance sign-off on T001 (new deps) and T038 (CI change, executed in Phase 5).
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

- Phase 1: T003, T004 run in parallel.
- Phase 2: T006, T007 parallel; T010, T011, T012, T013 parallel after T009.
- Phase 3 (US2 page objects): T015–T020 all in parallel (different files / different classes).
- Phase 4: T029, T030, T031, T032 parallel (different test files); T028 parallel with backend refactors.
- Phase 6: T042, T043, T044 parallel.

---

## Parallel Example: US2 page objects

```bash
# After T014 has created the empty scaffolds, run T015–T020 concurrently:
Task: "Implement EnvironmentsListPage in backend/tests/e2e/pages/environments.py"
Task: "Implement EnvironmentDetailPage in backend/tests/e2e/pages/environments.py"
Task: "Implement DriversListPage in backend/tests/e2e/pages/drivers_list.py"
Task: "Implement SettingsPage in backend/tests/e2e/pages/settings.py"
Task: "Implement DeployFormPage in backend/tests/e2e/pages/deploy_form.py"
Task: "Implement DeploymentDetailPage in backend/tests/e2e/pages/deployment_detail.py"
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
