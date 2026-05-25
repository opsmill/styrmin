---
description: "Task list for feature 013 — Driver Reload Identity (Provenance Fingerprint)"
---

# Tasks: Driver Reload Identity — Provenance Fingerprint

**Input**: Design documents from `/specs/013-driver-fingerprint/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/*, quickstart.md

**Tests**: Required per Constitution §V (E2E + propagation + unit). Test tasks are included.

**Organization**: Tasks are grouped by user story. Phase 2 (Foundational) introduces the shared backend infrastructure that all four user stories build on; each story phase adds the behaviour and tests specific to that story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

Web-application layout per `plan.md` — `backend/`, `frontend/`, `python_sdk/`, `cli/`, `docs/`, `dev/`.

---

## Phase 1: Setup

**Purpose**: Pre-flight checks. No new initialisation required (existing dev environment).

- [X] T001 Confirm dev stack is reachable (`uv run invoke dev` or vcluster fixture per `dev/knowledge/backend/e2e-testing.md`) before starting backend work — docker:OK, vcluster:OK on PATH
- [X] T002 Confirm pre-commit hooks are installed (`uv run invoke pre-commit-install`) per `AGENTS.md` — hooks observed firing during prep-phase commits (ruff, rumdl)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared backend infrastructure (DB columns, cascade kwargs, hash helper, provider commit-SHA exposure, repository lookup, GraphQL exposure, schema regeneration) that all four user stories build on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Database model

- [X] T003 Add two nullable columns to `ApplicationDriverVersion` in `backend/styrmin_backend/db/models.py` (`content_hash: str | None = None`, `source_commit_sha: str | None = None`)
- [X] T004 Add `sa_relationship_kwargs={"cascade": "all, delete-orphan"}` to `ApplicationDriverVersion.actions` in `backend/styrmin_backend/db/models.py`
- [X] T005 Add `sa_relationship_kwargs={"cascade": "all, delete-orphan"}` to `ApplicationDriverVersion.component_configs` in `backend/styrmin_backend/db/models.py`
- [X] T006 Add a UNIQUE composite index over the identity tuple `(application_driver_id, source_type, source_repository, source_branch, source_path, version, content_hash, source_commit_sha)` to `ApplicationDriverVersion.__table_args__` in `backend/styrmin_backend/db/models.py` (per critique R-X-1; uses Postgres `IS NOT DISTINCT FROM` nullability semantics)

### Pure hash helper

- [X] T007 [P] Create `backend/styrmin_backend/services/driver/hash.py` exposing `compute_driver_content_hash(driver_spec: bytes, values_template: bytes, actions_py: bytes | None) -> str` returning SHA-256 hex over the length-framed three-file canonical concatenation per `data-model.md`
- [X] T008 [P] Write unit tests in `backend/tests/unit/services/driver/test_hash.py` covering: identical inputs → identical hash; whitespace-only edit to any file → different hash; absent `actions_py` (None) → file omitted from hash; reordering the three files would produce a different hash (test framing); length-prefix prevents boundary collisions

### Git provider commit-SHA exposure

- [X] T009 Extend `GitDriverProvider` in `backend/styrmin_backend/services/driver/provider.py` so `provide()` resolves and stores the cloned repo's HEAD commit SHA (via `dulwich.repo.Repo(tempdir_path).head().decode()`) and exposes it via a new accessor (e.g. `get_resolved_commit_sha() -> str`) called after the context manager exits or recorded on the returned source
- [X] T010 [P] Write unit tests in `backend/tests/unit/services/driver/test_provider_commit_sha.py` covering: a clone of a small fixture repo resolves the expected 40-char SHA; the SHA is stable across two clones of the same ref; passing an unreachable repo/branch raises through `DriverLoadingError`

### Repository widened lookup

- [X] T011 In `backend/styrmin_backend/repository/application_driver_version.py`, replace `get_by_source_path_and_version` with `get_by_identity(*, application_driver_id, source_type, source_repository, source_branch, source_path, version, content_hash, source_commit_sha) -> ApplicationDriverVersion | None`. Match all identity columns; treat fingerprint nullability per `source_type` (local matches on `content_hash`, git matches on `source_commit_sha`)
- [X] T012 [P] Write unit tests in `backend/tests/unit/repository/test_application_driver_version_get_by_identity.py` covering: exact-tuple match returns row; differing fingerprint returns None; differing `source_branch` returns None; cascade delete via `delete()` removes child `Action` and `ComponentConfig` rows atomically

### GraphQL surface

- [X] T013 In `backend/styrmin_backend/api/definitions/application_driver/model.py`, add `content_hash: str | None = None` and `source_commit_sha: str | None = None` to the `ApplicationDriverVersion` Strawberry type, and populate them from the model in `from_instance()`
- [X] T014 [P] Write a propagation test in `backend/tests/functional/graphql/test_application_driver_version_propagation.py` (project-correct location per `dev/guides/graphql-propagation-tests.md`; original task path was `backend/tests/unit/api/schema/...` but the harness lives in `functional/graphql/`) that seeds an `ApplicationDriverVersion` row via the real repository layer with `source_type="local"` and a known `content_hash`, runs a GraphQL query selecting `contentHash`, and asserts the resolver returns the seeded hex verbatim
- [X] T015 [P] In the same propagation test file, add a second test that seeds a row with `source_type="git"` and a known `source_commit_sha`, queries `sourceCommitSha`, and asserts the resolver returns the seeded SHA verbatim

### Schema + SDK regeneration

- [x] T016 Run `uv run styrmin export graphql-schema schema.graphql` from the repo root to refresh `schema.graphql` with the two new fields
- [x] T017 Update any existing `.graphql` operation files under `python_sdk/src/styrmin_sdk/graphql/` that select `ApplicationDriverVersion` so they include `contentHash` and `sourceCommitSha`
- [x] T018 Run `uv run invoke generate` to regenerate Pydantic SDK types under `python_sdk/src/styrmin_sdk/graphql/_generated/`
- [x] T019 Run `uv run invoke validate-graphql` to confirm all SDK operations still schema-validate

**Checkpoint**: Foundation ready — all four user stories can now proceed in parallel.

---

## Phase 3: User Story 1 — Local driver iteration without `version` bumps (Priority: P1) 🎯 MVP

**Goal**: Loading a local driver repeatedly is idempotent on same content and creates new rows on edited content, without `version` bumps.

**Independent Test**: load a local fixture driver, edit the values template (no `version` change), reload via the SDK, observe two `ApplicationDriverVersion` rows for the same `version` with different `content_hash` values; reload again with no changes and observe the row count stays at two.

### Tests for User Story 1

- [ ] T020 [P] [US1] Write an E2E test `backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change` using a fixture local driver. Markers: `@pytest.mark.api_only(reason="Driver load is an SDK/CLI flow with no UI journey")`, `@pytest.mark.ci`, `@pytest.mark.shard_readonly`. Scenario: load driver → assert 1 row; reload (no change) → assert 1 row; edit values template → reload → assert 2 rows with same `version`, different `content_hash`, both retrievable via GraphQL
- [ ] T021 [P] [US1] Write a unit test `backend/tests/unit/services/test_applications_upsert_idempotent.py::test_local_load_same_content_is_noop` exercising the service-layer load against a real test DB; assert exactly one row exists after two identical loads
- [ ] T022 [P] [US1] In the same file, `test_local_load_new_content_creates_new_row_without_deleting_old` — load, mutate the test driver's values template on disk, reload; assert two rows, no delete

### Implementation for User Story 1

- [ ] T023 [US1] In `backend/styrmin_backend/services/driver/loaders.py` (`DriverLoader.load_driver`), capture the raw bytes of `driver.styrmin.yml`, the values template, and `actions.py` (when `spec.actions` is non-empty) and compute `content_hash` via the helper from T007; attach it to the returned `ApplicationDriver` object
- [ ] T024 [US1] In `backend/styrmin_backend/services/applications.py::load_application_driver_from_local_directory`, replace the existing `get_by_source_path_and_version` + `delete(existing)` block (lines ~309-316) with a call to the new `get_by_identity(...)`; on hit, return the existing row (idempotent); on miss, fall through to `load_application_driver_from_object` (which creates the new row). REMOVE the delete branch entirely.
- [ ] T025 [US1] In `backend/styrmin_backend/services/applications.py::load_application_driver_from_object` (or its call site), persist `content_hash` to the new row on creation for local-sourced drivers
- [ ] T026 [US1] Verify T020-T022 PASS locally; capture local PASS evidence per Constitution §V (node id, command, ISO 8601 timestamp, vcluster id, kubeconfig path, `PASSED` line) for T020 and record it in the PR description

**Checkpoint**: User Story 1 fully functional. MVP can ship here.

---

## Phase 4: User Story 2 — Git driver reload distinguishes commits (Priority: P1)

**Goal**: Loading the same `repo@branch@version` after a new commit lands creates a new `ApplicationDriverVersion` row; loading the same commit twice is a no-op.

**Independent Test**: load a fixture git driver at commit C1, then load the same `repo@branch` at C2 (after a new commit); assert two rows with same `version`, different `source_commit_sha`.

### Tests for User Story 2

- [ ] T027 [P] [US2] Write a unit test `backend/tests/unit/services/driver/test_loaders_git_commit_sha.py::test_git_load_records_resolved_commit_sha` using a mocked `GitDriverProvider` that returns a known SHA; assert the resulting `ApplicationDriverVersion` row carries that SHA on `source_commit_sha` and `content_hash` is None
- [ ] T028 [P] [US2] In the same file, `test_git_load_same_commit_is_noop` — call the load service twice with a provider that returns the same SHA both times; assert one row exists, no error
- [ ] T029 [P] [US2] In the same file, `test_git_load_new_commit_creates_new_row` — provider returns SHA1 then SHA2 on two successive loads; assert two rows, both with the same `version`, different `source_commit_sha`

### Implementation for User Story 2

- [ ] T030 [US2] In `backend/styrmin_backend/services/driver/loaders.py`, when the provider is a `GitDriverProvider`, fetch the resolved commit SHA via the accessor from T009 after `load_driver()` returns and attach it to the `ApplicationDriver` object
- [ ] T031 [US2] In `backend/styrmin_backend/services/applications.py::load_application_driver_from_git_repository`, before creating a new row call `get_by_identity(source_type="git", source_repository=..., source_branch=..., version=..., source_commit_sha=resolved_sha, ...)`; on hit return existing; on miss fall through to creation
- [ ] T032 [US2] In `backend/styrmin_backend/services/applications.py` (creation path), persist `source_commit_sha` to the new row on creation for git-sourced drivers
- [ ] T033 [US2] Verify T027-T029 PASS locally

**Checkpoint**: User Stories 1 AND 2 both ship the data behaviour.

---

## Phase 5: User Story 3 — Cascade crash on local reload is gone (Priority: P1)

**Goal**: Deleting an `ApplicationDriverVersion` row succeeds atomically — children (`Action`, `ComponentConfig`) are cascaded — even though the load path no longer triggers a delete.

**Independent Test**: programmatically create an `ApplicationDriverVersion` row with children, call the repository's `delete()`, assert no `IntegrityError`, assert child rows are gone.

### Tests for User Story 3

- [ ] T034 [P] [US3] Write a unit test `backend/tests/unit/repository/test_application_driver_version_cascade.py::test_delete_cascades_actions_and_component_configs`. Create a real DB session via the existing fixtures; insert an `ApplicationDriverVersion` with two `Action` rows and two `ComponentConfig` rows; call `repository.delete(version)`; assert: no `IntegrityError`, no rows remain in `Action` or `ComponentConfig` for that parent, no orphan FKs.

### Implementation for User Story 3

> Implementation already covered by T004 (`actions` cascade) and T005 (`component_configs` cascade) in Phase 2. This story phase only validates the behaviour via T034.

- [ ] T035 [US3] Verify T034 PASSES locally

**Checkpoint**: Cascade-delete-orphan is exercised under test.

---

## Phase 6: User Story 4 — UI/CLI users can distinguish multiple rows with the same `version` (Priority: P2)

**Goal**: Every user-visible surface renders driver-version labels as `<version>@<short>` (7-char fingerprint); detail surfaces expose the full fingerprint with a copy affordance.

**Independent Test**: with two rows of the same `version` and different fingerprints in the database, open the driver list in the frontend and the CLI `driver list` output; assert each row is labelled `<version>@<short>` with the correct short fingerprint. Open the driver detail surface; assert the full fingerprint is visible and copyable on web.

### Helper modules

- [ ] T036 [P] [US4] Create `backend/styrmin_backend/services/driver/labels.py` with `format_driver_version_label(*, version: str, content_hash: str | None, source_commit_sha: str | None) -> str` per `contracts/sdk-cli-rendering.md`
- [ ] T037 [P] [US4] Write unit tests in `backend/tests/unit/services/driver/test_labels.py` covering: local row with hash → `"<version>@<first-7>"`; git row with commit SHA → same form; both null → bare `version` (legacy fallback)
- [ ] T038 [P] [US4] Create `frontend/src/lib/driverVersion.ts` with `formatDriverVersionLabel({ version, contentHash, sourceCommitSha })` per the contract
- [ ] T039 [P] [US4] Write a Vitest unit test `frontend/src/__tests__/lib/driverVersion.test.ts` covering the same three cases

### CLI rendering

- [ ] T040 [US4] In `cli/styrminctl/commands/driver.py` (or the file rendering the `driver list` output — confirm path during implementation), wrap the version column with `format_driver_version_label`
- [ ] T041 [US4] In the CLI driver-detail rendering, add lines showing the full `Content hash:` or `Commit SHA:` value (whichever is populated)
- [ ] T042 [US4] In `cli/styrminctl/commands/deployment.py` (or equivalent), apply the helper anywhere a deployment renders its driver-version reference (list and detail)
- [ ] T043 [P] [US4] Add CLI tests in `cli/tests/` asserting the rendered output contains `<version>@<short>` for a fixture row and the full fingerprint line on detail

### Frontend rendering

- [ ] T044 [US4] In `frontend/src/components/drivers/VersionList.tsx` (or wherever the driver list renders a version label), use `formatDriverVersionLabel`
- [ ] T045 [US4] In `frontend/src/pages/drivers/DriverDetailPage.tsx` (and its Overview/Source tabs), render the full `contentHash` or `sourceCommitSha` value with a copy-to-clipboard button
- [ ] T046 [US4] In `frontend/src/components/deployment/DeploymentTimeline.tsx`, apply the helper to any driver-version reference
- [ ] T047 [US4] In `frontend/src/components/deployment/configuration/ConfigEditDrawer.tsx` and `frontend/src/components/deployment/configuration/sections/edit/IdentitySection.tsx`, apply the helper anywhere the driver-version reference is shown
- [ ] T048 [P] [US4] Add/extend frontend tests in `frontend/src/__tests__/driver-detail/VersionList.test.tsx` and a new component test for the deployment surfaces, asserting the rendered label contains `@<short>` and the detail surface contains the full fingerprint string plus a reachable copy button

### Query updates

- [ ] T049 [US4] Audit GraphQL queries used by the frontend (`frontend/src/**/*.graphql` or codegen sources) and ensure any query selecting `ApplicationDriverVersion` includes `contentHash` and `sourceCommitSha`; regenerate frontend types as needed (`cd frontend && pnpm codegen` or per project convention)
- [ ] T050 [US4] Audit `tasks/graphql/` and `python_sdk/src/styrmin_sdk/graphql/` for any operation feeding the CLI driver/deployment listings; ensure they select both new fields

**Checkpoint**: All four user stories are independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, lint/format, manual verification, audit-trail evidence.

- [ ] T051 [P] Create `dev/guides/driver-iteration.md` documenting: the no-`version`-bump iteration loop, the three-file content-hash input, the row-accumulation behaviour, the future `driver prune` follow-up, and the `<version>@<short>` display convention
- [ ] T052 [P] Update any `docs/` (user-facing Docusaurus) page that documents driver loading or the driver-version surface — particularly `docs/how-it-works/` and any quickstart that shows driver-version output — to reflect the new fingerprint suffix and the GraphQL fields
- [ ] T053 [P] Add a brief release-note entry (in the appropriate location for this project — `CHANGELOG.md`, `dev/release-notes/`, or PR template) noting the user-visible change: CLI/frontend labels now include `@<short>`, and reload no longer requires bumping `version`
- [ ] T054 Run `uv run invoke format lint` and resolve any violations
- [ ] T055 Run the full backend test suite (`uv run invoke test`) and confirm all tests PASS
- [ ] T056 Run the frontend test suite (`cd frontend && pnpm test`) and confirm all tests PASS
- [ ] T057 Walk through `specs/013-driver-fingerprint/quickstart.md` manually against a running dev stack; check every step's expected outcome
- [ ] T058 Confirm the E2E PASS evidence captured at T026 is present in the PR description per Constitution §V (node id, command, timestamp, vcluster id, kubeconfig path, `PASSED` line)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies; trivial.
- **Foundational (Phase 2)**: depends on Phase 1; BLOCKS all four user stories.
- **User Stories (Phases 3-6)**: all depend on Phase 2 completion.
  - US1, US2, US3, US4 are mutually independent post-foundational and can be developed in parallel.
- **Polish (Phase 7)**: depends on all desired user-story phases being complete.

### User Story Dependencies

- **US1 (P1, MVP)**: depends on T003-T019. No dependency on US2/US3/US4.
- **US2 (P1)**: depends on T003-T019. No dependency on US1/US3/US4.
- **US3 (P1)**: depends on T004 + T005 (cascade kwargs from Foundational). Independent of US1/US2/US4.
- **US4 (P2)**: depends on T013 (GraphQL surface). Independent of US1/US2/US3 behaviour-wise; benefits from US1/US2 being shipped so test data exists.

### Within Each User Story

- Tests are written first; assertions MUST fail before implementation, then PASS after.
- Local PASS evidence captured at the close of each user-story phase per Constitution §V.

### Parallel Opportunities

- T007 (hash helper) and T009 (provider commit SHA) — different files, can run in parallel.
- T008 (hash tests) and T010 (provider tests) — parallel after their respective sources.
- T012 (repository test), T014 + T015 (propagation tests) — parallel after T011 + T013.
- T020, T021, T022 — same test target but different test functions; safe to author in parallel.
- T027-T029 — same test file, different functions; parallel.
- T036/T037 + T038/T039 — Python helper vs TypeScript helper; parallel.
- T040-T043 (CLI) and T044-T048 (frontend) — different language ecosystems; parallel.
- T051-T053 (docs) — independent files; parallel.

---

## Parallel Example: Foundational Phase

```bash
# After T003-T006 land (db model), the following can be developed in parallel:
Task: "T007 — create services/driver/hash.py and T008 — unit tests for it"
Task: "T009 — extend GitDriverProvider with commit-SHA accessor and T010 — unit tests for it"
Task: "T011 — repository get_by_identity and T012 — repository tests"
Task: "T013 — GraphQL ApplicationDriverVersion fields and T014/T015 — propagation tests"
```

## Parallel Example: User Stories After Foundation

```bash
# Once Phase 2 is complete, four parallel tracks:
Developer A: US1 (T020-T026) — local reload + idempotency
Developer B: US2 (T027-T033) — git reload + commit SHA
Developer C: US3 (T034-T035) — cascade behaviour verification
Developer D: US4 (T036-T050) — UI/CLI labels (largest, most files)
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational — DB columns, cascade kwargs, hash helper, provider, repository, GraphQL surface, schema regen
3. Complete Phase 3: User Story 1 (local reload + E2E)
4. **STOP and VALIDATE**: run the E2E, run the unit tests, demo locally
5. Capture PASS evidence per §V

### Incremental Delivery

1. Foundation ready (Phase 2 complete).
2. Add US1 → run E2E → MVP shipped.
3. Add US2 → CI green → git path shipped.
4. Add US3 → cascade test PASSES (mechanical: already shipped in Phase 2; only the test is new).
5. Add US4 → frontend + CLI labels light up.
6. Polish: docs + manual quickstart walkthrough + evidence audit.

### Notes

- US3's implementation is bundled into Phase 2 (T004, T005) because the cascade kwargs are foundational for all later delete-paths; only the dedicated test sits in Phase 5.
- T006 (UNIQUE index) implements the R-X-1 recommendation from the critique. If the implementer determines a unique index is unsupportable on the target Postgres version, a transactional lookup-then-insert with retry-on-unique-violation is the documented fallback; either path satisfies the spec's "no duplicates" requirement.
- The E2E test count per shard is unchanged; T020 lands in `shard_readonly`.
