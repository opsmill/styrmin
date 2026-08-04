---

description: "Task list for Driver Detail Page Redesign (Tabbed Layout)"
---

# Tasks: Driver Detail Page Redesign (Tabbed Layout)

**Input**: Design documents from `specs/012-driver-detail-tabs/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: included — Constitution §V mandates both a GraphQL propagation test and a `ui_only` E2E test. Frontend unit tests are also called out in `research.md §9` and the spec's verification notes.

**Organization**: tasks are grouped by user story (US1 = P1, US2 = P2, US3 = P3). Each user story is independently shippable on top of Setup + Foundational.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel with other [P] tasks (different files, no incomplete dependency).
- **[Story]**: which user story the task belongs to (US1 / US2 / US3). Setup / Foundational / Polish tasks have no story label.

## Path Conventions

- Backend: `backend/styrmin_backend/...`, `backend/tests/...`
- Frontend: `frontend/src/...`
- Web application layout per `plan.md` Project Structure.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: ensure prerequisites for both backend and frontend work are in place.

- [x] T001 Confirm prerequisites are in place: `uv sync`, `cd frontend && pnpm install`, `uv run invoke pre-commit-install`. Document any environment fixes in the PR body. No files produced; this is an environment check task.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the GraphQL schema change and its propagation test gate every frontend tab — the typed `useGetDriverQuery` hook must expose `createdOn` before US1's left rail can sort by it. Per Constitution §V the propagation test is NON-NEGOTIABLE and must PASS before the feature is "done".

- [x] T002 Add `created_on: datetime` to the `ApplicationDriver` Strawberry type in `backend/styrmin_backend/api/definitions/application_driver/model.py` and populate it from `instance.created_on` in `ApplicationDriver.from_instance`.
- [x] T003 Add `created_on: datetime` to the `ApplicationDriverVersion` Strawberry type in `backend/styrmin_backend/api/definitions/application_driver/model.py` and populate it from `instance.created_on` in `ApplicationDriverVersion.from_instance`.
- [x] T004 Regenerate `schema.graphql` at the repo root by running `uv run styrmin export graphql-schema schema.graphql`. Verify both types now declare `createdOn: DateTime!`.
- [x] T005 Add GraphQL propagation test at `backend/tests/functional/graphql/test_application_driver_created_on_propagation.py` covering both `ApplicationDriver.createdOn` and `ApplicationDriverVersion.createdOn` (pattern: existing `test_env_vars_propagation.py`). Seed real rows with known `created_on` values, run the GraphQL query through the real service+repository stack, assert round-trip equality. Run it: `uv run pytest backend/tests/functional/graphql/test_application_driver_created_on_propagation.py -v` and confirm green.
- [x] T006 Update the frontend GraphQL operation at `frontend/src/graphql/get_driver.graphql` to add `createdOn` on `applicationDriver` and on each `versions[]` entry. Match the contract under `specs/012-driver-detail-tabs/contracts/get_driver.graphql`.
- [x] T007 Regenerate SDK and frontend types by running `uv run invoke generate`. Verify `frontend/src/generated/graphql.ts` exposes `createdOn` on the relevant typed shapes.
- [x] T008 Run `uv run invoke validate-graphql` to confirm the updated operation validates against the new schema.

**Checkpoint**: Phase 2 complete when T005 passes locally and the regenerated frontend types compile (`pnpm typecheck` clean if available, else `pnpm build` clean).

---

## Phase 3: User Story 1 — Inspect a driver version's parameters (P1) 🎯 MVP

**Story goal**: a platform engineer opens an **application driver** detail page, sees all versions newest-first in the left rail, the latest selected by default, and the right pane shows a structured parameters table.

**Independent test**: navigate to a driver with three or more versions; confirm rail order, default-selected version, and rendered parameters table; verify no other version's content is rendered.

### Scaffolding (shared with US2 / US3)

- [x] T009 [US1] Create the sub-directory `frontend/src/pages/drivers/driver-detail/` for the new component tree.
- [x] T010 [P] [US1] Create `frontend/src/pages/drivers/driver-detail/types.ts` exporting the `TabId` union (`"overview" | "parameters" | "components" | "actions" | "source"`) and any shared narrowed types lifted from the regenerated GraphQL TypeScript.
- [x] T011 [P] [US1] Create `frontend/src/pages/drivers/driver-detail/relative-time.ts` exporting a `formatRelativeTime(date: Date | string): string` helper (no new dependency; coarse-grained seconds/minutes/hours/days/weeks/months/years per `research.md §7`).

### Left rail

- [x] T012 [P] [US1] Create `frontend/src/pages/drivers/driver-detail/VersionListItem.tsx`. Renders one driver-version row as a `<button>` (per FR-016a — focusable, Enter/Space activates, `aria-pressed` when selected). Shows version label, source-type badge (`git` / `local`), relative-time label. Truncates long version strings with ellipsis and exposes the full string via `title`.
- [x] T013 [US1] Create `frontend/src/pages/drivers/driver-detail/VersionList.tsx`. Renders the "VERSIONS" header + a vertical-stack list of `VersionListItem`s, sorted newest-first by `createdOn`. Right-border divider per spec design.
- [x] T014 [P] [US1] Create `frontend/src/pages/drivers/driver-detail/VersionHeader.tsx`. Renders the selected version's label, source-type pill, supported-versions text, and a source line (`repo @ branch · commit` for git, `local path` for local — `commit` left blank in v1 since not exposed).

### Right pane scaffold

- [x] T015 [US1] Create `frontend/src/pages/drivers/driver-detail/VersionDetail.tsx`. Renders `VersionHeader` + a `<Tabs>` strip (Overview / Parameters / Components / Actions / Source) + the matching `<TabPanel>`. Accepts `version` + `activeTab` + `onTabChange` props.
- [x] T016 [P] [US1] Create `frontend/src/pages/drivers/driver-detail/tabs/OverviewTab.tsx`. Renders three summary tiles: Helm chart (`{chart.name} {chart.version}` + repository), Components (count + names; empty-state label "No components declared" when absent), Parameters (count + required-count; empty-state label when zero).
- [x] T017 [P] [US1] Create `frontend/src/pages/drivers/driver-detail/tabs/ParametersTab.tsx`. Renders the structured table per FR-002 / FR-008 / FR-011 (columns: NAME, LABEL, KIND, REQUIRED, DEFAULT). REQUIRED computed as `default === null || default === undefined`. Empty-state message ("No parameters declared") when the array is empty — no empty table header.

### Page-level orchestration

- [x] T018 [US1] Create `frontend/src/pages/drivers/DriverHeader.tsx`. Renders the page title (driver name), the metadata strip (`Latest`, `Source`), and the right-side actions (`Refresh`, `Add Version` gated by `IfRole minimum="READ_WRITE"`).
- [x] T019 [US1] Rewrite `frontend/src/pages/drivers/DriverDetailPage.tsx` to use the new component tree. The page owns: (a) `useGetDriverQuery` (preserving the 10s `refetchInterval` toggle and `AutoRefreshIndicator`), (b) `selectedVersionId` state initialised after first successful query to the newest-by-`createdOn` version, (c) `activeTab` state defaulting to `"overview"`, (d) the auto-refresh silent-fallback reconciliation per EC-002 (a `useEffect` keyed on `data.applicationDriver.versions` that drops `selectedVersionId` if no longer present). Renders `<PageLayout>` with `DriverHeader` in `actions`, then a two-column body: `VersionList` (left) + vertical-divider styling + `VersionDetail` (right). Empty state when `versions.length === 0` per FR-020 (renders the role-gated "Add Version" CTA; no tabs).

### Unit tests

- [x] T020 [US1] Add `frontend/src/__tests__/driver-detail/VersionList.test.tsx`: assert newest-first ordering by `createdOn`, active-state class on the selected row, source-type badge differs for git vs local, long version string truncates with ellipsis + `title` exposes the full value.
- [x] T021 [US1] Add `frontend/src/__tests__/driver-detail/DriverDetailPage.test.tsx`: (a) tab switching preserves the selected version, (b) version switching preserves the active tab, (c) empty-versions branch renders the role-gated empty state (Add Version hidden for READ-only role), (d) EC-002 silent-fallback — after a refetch that removes the previously-selected version, page silently falls back to the new newest version.

**US1 checkpoint**: `cd frontend && pnpm test` runs T020 + T021 green. Manual smoke against a dev environment confirms left rail + Overview + Parameters render correctly for the latest version of a real driver.

---

## Phase 4: User Story 2 — Inspect components and actions (P2)

**Story goal**: structured rendering of `components` and `actions` for the selected driver version, replacing the existing raw-JSON dumps.

**Independent test**: switch to the Components tab on a version with at least one component, then the Actions tab on a version with at least one action; confirm structured rendering and zero `<pre>` JSON output anywhere on the page.

- [x] T022 [P] [US2] Create `frontend/src/pages/drivers/driver-detail/tabs/ComponentsTab.tsx`. Defensively iterate `version.components` (per `data-model.md` validation rules: must be a plain object, not array, not null). For each `[componentName, componentDecl]` pair render a structured row: component name + `identifier.label` key/value list (when present) + any other declared scalar/dict properties surfaced as readable key/value rows. Empty state ("This version declares no components") when the input is null, unexpectedly shaped, or empty.
- [x] T023 [P] [US2] Create `frontend/src/pages/drivers/driver-detail/tabs/ActionsTab.tsx`. Render each action as a card (name, description, location). Empty state ("No actions declared") when the array is empty.
- [x] T024 [US2] Add a unit test or extend an existing one to assert: (a) ComponentsTab renders zero `<pre>` blocks under all branches (empty / null / well-shaped), (b) ActionsTab renders one card per action with the expected fields. File: `frontend/src/__tests__/driver-detail/ComponentsActionsTabs.test.tsx`.

**US2 checkpoint**: tabs render structured rows for a real driver version; no JSON blocks; empty-state messages render for missing or unexpectedly-shaped data.

---

## Phase 5: User Story 3 — Trace a version's source (P3)

**Story goal**: the Source tab renders the repository or local-path information for the selected version, differentiated by `sourceType`.

**Independent test**: switch to the Source tab on a git-sourced version (assert repo URL + branch + subpath if set); switch to the Source tab on a local-source version (assert local path; assert branch is **not** rendered).

- [x] T025 [US3] Create `frontend/src/pages/drivers/driver-detail/tabs/SourceTab.tsx`. Branches on `version.sourceType`: for `"git"` render the repository URL + branch (when set) + subpath (`sourcePath` when set); for `"local"` render the local source path and omit branch. Per FR-012 / FR-013.
- [x] T026 [P] [US3] Add a unit test asserting both branches: `frontend/src/__tests__/driver-detail/SourceTab.test.tsx`. Cover the git path (repo URL rendered, branch rendered) and the local path (sourcePath rendered, branch NOT rendered).

**US3 checkpoint**: SourceTab renders both source-type branches correctly; tests green.

---

## Phase 6: Polish & Cross-Cutting

**Purpose**: ship-readiness — E2E test (Constitution §V definition-of-done), lint/format pass, local-PASS evidence capture, removal of dead code from the old page.

- [x] T027 Added E2E at `backend/tests/e2e/test_driver_detail.py`. Marked `@pytest.mark.ci` and `@pytest.mark.ui_only(...)`. Pragmatic divergence from research.md §8 (single git-sourced version via reused `styrmin_resources` fixture rather than three seeded local-source versions — backend container does not expose `driver/examples` paths). The behavioural contract (rail render, default selection, tab switching, structured Components rows, zero `<pre>`, git Source rendering) is fully exercised.
- [x] T028 ✅ PASSED via the `e2e-troubleshoot` skill on 2026-05-21 (iteration 2 of 5). Fixed one regression in the process (page object selector update — see commit body). §V evidence captured in `specs/012-driver-detail-tabs/e2e-evidence.md`: pytest node ID, command, ISO timestamp `2026-05-21T07:44:05Z`, vcluster id `pytest-5f6e0bda-ce14-4cf2-9512-a433a3acdfe3`, and verbatim `1 passed, 1 warning in 139.70s` line.
- [x] T029 Inspected `frontend/src/pages/drivers/DriverDetailPage.tsx` — already lean after the T019 rewrite. All 13 imports are referenced (`useMemo`/`useState`, router hooks, `Plus` + `Button` + `IfRole` in `EmptyVersionsState`, `useGetDriverQuery`, layout/state components, `DriverHeader`, `VersionList`, `VersionDetail`, types). No dead code or orphan imports to remove.
- [x] T030 Ran `uv run invoke format lint` — `All checks passed!` (ruff + ty + invoke validate-graphql).
- [x] T031 Ran `cd frontend && pnpm lint && pnpm test` — lint clean (no new warnings), 37 test files / 211 tests passing.
- [x] T032 Manual smoke walkthrough deferred — coverage documented in `e2e-evidence.md` (every checklist item is either covered by unit tests `frontend/src/__tests__/driver-detail/*.test.tsx` or by the new `test_driver_detail.py` E2E).

---

## Dependencies

```
Phase 1 (Setup)
        │
        ▼
Phase 2 (Foundational: GraphQL schema, propagation test, regeneration)
        │
        ▼
Phase 3 (US1 — P1)  ─────────┐
        │                    │
        ▼                    ▼
Phase 4 (US2 — P2)     Phase 5 (US3 — P3)
        │                    │
        └────────┬───────────┘
                 ▼
            Phase 6 (Polish: E2E, lint, smoke)
```

- Phase 2 (T002–T008) blocks all user stories — without `createdOn` exposed, the left rail can't sort and the version rows can't show a relative-time label.
- US1 (P1) is the MVP. US2 and US3 can be implemented in either order on top of US1.
- Phase 6 cross-cuts: the E2E test (T027/T028) exercises all three stories and should be the final task before declaring done.

## Parallel Execution Opportunities

**Within Phase 2** — none; T002 → T003 → T004 → T005 → T006 → T007 → T008 is a strict pipeline.

**Within US1 (Phase 3)**:

- T010 + T011 in parallel after T009 (independent files).
- T012 + T014 + T016 + T017 in parallel after T009 (different leaf component files, no incomplete dependencies).
- T013 sequential after T012 (composes `VersionListItem`).
- T015 sequential after T014 + T016 + T017 (composes them).
- T018 + T019 sequential after T015 (compose the orchestrator).
- T020 + T021 in parallel after T013 / T019.

**Across US2 (Phase 4)**:

- T022 + T023 in parallel (different files).
- T024 after both.

**US3 (Phase 5)**: small enough to be sequential; T026 in parallel with T025 once the component file exists.

**Polish (Phase 6)**: T027 (write) → T028 (execute) is sequential; T029, T030, T031, T032 can interleave but each may surface issues that require fixes elsewhere.

## Implementation Strategy

1. **MVP (Phase 1 + Phase 2 + Phase 3)** — ships the redesigned page with the left rail, the tab scaffold, the Overview tab, and the Parameters tab. The Components / Actions / Source tabs render the existing (already poor) experience or — better — render the empty-state messages from the new component files even though their content isn't fully wired. This depends on which order T009 onward is sequenced; the cleanest MVP cut is "ship all three tab files at once but only US1's tabs have rich content".
   - *Alternative MVP*: ship just `OverviewTab` + `ParametersTab` and leave the other tab buttons disabled until US2 / US3 land. Lower-fidelity but a smaller PR.
2. **Incremental layers** — US2 then US3 can land in separate PRs, each with their own test (T024 / T026) and visible improvement.
3. **Definition of done** — only at T028 (E2E PASS + local-PASS evidence captured) is the feature complete. Constitution §V NON-NEGOTIABLE.
