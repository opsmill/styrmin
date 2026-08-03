# Tasks: Configurable Backup Retention TTL

**Input**: Design documents from `/specs/016-backup-retention-ttl/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/graphql-delta.md, quickstart.md, critiques/critique-20260803-104945.md

**Tests**: INCLUDED — the spec attaches a verify clause to every FR, and Constitution §V makes propagation tests and the E2E non-negotiable.

**Organization**: Grouped by user story. Foundational phase carries the shared config field and the atomic GraphQL surface change (one regeneration), since every story depends on them.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 (environment policy), US2 (deployment override), US3 (invalid value rejected), US4 (expiry visible in UI/CLI)

## Phase 1: Setup

**Purpose**: Baseline before touching shared surface — no project scaffolding needed (all four workspaces exist).

- [X] T001 Install workspaces and record a green baseline: `uv sync`; `cd frontend && pnpm install`; then run `uv run pytest backend/tests/unit/agent/test_velero_resources.py backend/tests/unit/agent/test_backup_builders.py backend/tests/unit/context/test_base_config_section.py -q` and confirm all pass (these suites change later; baseline proves any failure is ours)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared validation/resolution module, the config field, and the complete GraphQL surface delta with a single regeneration. Every user story depends on this phase.

**⚠️ CRITICAL**: The schema-walking guard (`test_update_environment_input_covers_every_environment_config_field`) fails from the moment T003 lands until T004 lands — complete this phase atomically before running story phases.

- [X] T002 Create `backend/styrmin_backend/services/backup/ttl.py`: `DEFAULT_BACKUP_TTL = "720h"`; `BACKUP_TTL_PATTERN` (regex `^(\d+(\.\d+)?(h|m|s))+$`); `validate_backup_ttl(value: str) -> str` raising `ValueError` with the exact message contract `backup_ttl must be a positive Go duration using h/m/s units, e.g. "720h"` (reject non-matching syntax AND all-zero durations like `0h`/`0h0m0s`); `resolve_backup_ttl(deployment_config: dict | None, environment_config: dict | None, cluster_config: dict | None) -> tuple[str, str]` returning `(ttl, source_scope)` with deepest-wins precedence deployment → environment → cluster → `(DEFAULT_BACKUP_TTL, "default")` (a scope contributes only when its dict has a non-null `backup_ttl`)
- [X] T003 Add `backup_ttl: str | None = None` to `BaseConfigSection` in `backend/styrmin_backend/context/models/config.py` with a Pydantic field validator delegating to `validate_backup_ttl` (skip when `None`), so all five input surfaces reject through the existing `validate_*_config` → `Invalid*ContextError` path (data-model.md §Validation rules)
- [X] T004 [P] Add `backup_ttl: str | None = None` to `UpdateEnvironmentInput` in `backend/styrmin_backend/api/definitions/environment/inputs.py` (converter `update_environment_input_to_dict` passes scalars through generically; update `__all__` only if a new symbol is exported)
- [X] T005 [P] Add `backup_ttl: str | None = None` to `DeploymentConfigInput` in `backend/styrmin_backend/api/definitions/deployment/inputs.py` (covers both `deploy` and `updateDeployment` — `UpdateDeploymentInput` inherits it; the generic `_convert_value` handles the scalar)
- [X] T006 [P] Add nullable `ttl: str | None` and `expires_at: datetime | None` as `@strawberry.field` resolvers on the `Backup` type in `backend/styrmin_backend/api/definitions/backup/backup.py`, reading `self.db_model.metadata_` keys `ttl` / `expires_at` (copy the `component_statuses` resolver pattern at lines 52-65; `expires_at` parses the ISO string with `datetime.fromisoformat`, returning `None` when the key is absent, `metadata_` is `None`, or parsing fails)
- [X] T007 [P] Add `ttl expiresAt` to the selection sets of `python_sdk/src/styrmin_sdk/graphql/list_backups.graphql`, `python_sdk/src/styrmin_sdk/graphql/get_backup.graphql`, `python_sdk/src/styrmin_sdk/graphql/create_backup.graphql`, and `frontend/src/graphql/list_backups.graphql`
- [X] T008 Regenerate contract artifacts: `uv run styrmin export graphql-schema schema.graphql` then `uv run invoke generate`; verify the schema diff is exactly the four additions in `contracts/graphql-delta.md` (`Backup.ttl`, `Backup.expiresAt`, `UpdateEnvironmentInput.backupTtl`, `DeploymentConfigInput.backupTtl`) and commit `schema.graphql`, `python_sdk/src/styrmin_sdk/graphql/_generated/`, `frontend/src/generated/graphql.ts`

**Checkpoint**: Schema, SDK, and frontend types all expose the new surface; user story phases can begin.

---

## Phase 3: User Story 1 - Environment retention policy (Priority: P1) 🎯 MVP

**Goal**: An operator sets `backup_ttl` on an environment; every subsequent backup carries that retention on the Velero object, records it (with source scope) on the backup record, and logs the resolution.

**Independent Test**: Update an environment with `backup_ttl: "2160h"`, create a backup, assert the Velero Backup CRD carries `spec.ttl == "2160h"`, the backup record stores the applied TTL, and the workflow log names the environment scope.

### Tests for User Story 1 (write first, watch them fail)

- [X] T009 [P] [US1] Create `backend/tests/unit/services/test_backup_ttl_resolution.py`: environment-scope hop wins over cluster; all-unset falls back to `("720h", "default")`; the pinned default assertion `DEFAULT_BACKUP_TTL == "720h"` relocates here (SC-004 — this is the single home of the literal); `source_scope` values match `{"deployment","environment","cluster","default"}`
- [X] T010 [P] [US1] Extend `backend/tests/functional/graphql/test_environment_update_propagation.py` with `backup_ttl` round-trips modeled on `test_update_environment_input_ingress_class_round_trip` (line 465): set via `updateEnvironment` → `Environment.config["backup_ttl"]` in DB; update-with-field preserves; update-omitting-field clears (full-replacement semantics); this also turns the schema-walking guard green

### Implementation for User Story 1

- [X] T011 [US1] Extend `update_backup_status` in `backend/styrmin_backend/services/backup/service.py` with `metadata_updates: dict | None = None` merged by **reassignment** — `backup.metadata_ = {**(backup.metadata_ or {}), **metadata_updates}` — never in-place mutation (plain `JSON` column, no change tracking; critique M2 / research R5), preserving existing keys (`timeout`)
- [X] T012 [P] [US1] In `execute_velero_backup_flow` (`backend/styrmin_backend/workflows/templates/backup.py` lines 132-146), include Velero's `status.expiration` in the `Variable.set` result payload (available from `poll_backup_status`)
- [X] T013 [P] [US1] Make `ttl` a required parameter (no default) on `build_velero_backup` in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py` and on the `VeleroBackup` dataclass in `backend/styrmin_backend/agent/service/kubernetes/velero/resources.py`, deleting both `"720h"` literals (rendered `spec["ttl"]` shape unchanged)
- [X] T014 [US1] Wire resolution into `execute_backup_workflow` (`backend/styrmin_backend/workflows/templates/backup.py`): load deployment/environment/cluster configs in the existing UoW block, call `resolve_backup_ttl` **outside** the BSL `try/except` (research R3 caveat — a config-read failure must fall back loudly to `("720h", "default")`, never silently); log `resolved backup TTL <ttl> from <source_scope> scope`; record `{"ttl": ..., "ttl_source": ...}` via `update_backup_status(metadata_updates=...)` before building; pass `ttl=` to `build_velero_backup`; on completion, record `{"expires_at": <ISO>}` from the Velero result payload when present (Failed/PartiallyFailed report none)
- [X] T015 [US1] Update builder suites to the required-TTL signature: `backend/tests/unit/agent/test_velero_resources.py` (line 247 area) and `backend/tests/unit/agent/test_backup_builders.py` (line 27 area) supply an explicit `ttl` and assert pass-through of the supplied value (no other assertion changes — SC-004)
- [X] T016 [US1] Carry `backup_ttl` through `buildFullReplacementInput` in `frontend/src/pages/environments/EnvironmentConfigurationTab.helpers.ts` (string scalar pass-through like `dbSize`; critique M1) and add a preservation assertion to the tab's existing test coverage (`frontend/src/__tests__/EnvironmentConfigurationTab.test.tsx` or the helpers test): persisted `backup_ttl` survives an env-var-only save
- [ ] T017 [US1] Extend `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle`: set `backup_ttl: "2160h"` on the scenario environment via the SDK (`sdk.environments.update_environment`, round-tripping existing config fields), **wait for the update fanout to reach steady state before backing up** (critique E3 — the env update triggers a Helm-no-op redeploy on the session-shared environment); assert the Velero Backup CRD `spec.ttl == "2160h"` alongside the existing `assert_velero_backup_uses_bsl` assertion (helper at lines 81-108); after completion, assert `backup.ttl == "2160h"` and `backup.expires_at` is non-null via the SDK. Run to PASS: `sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" -v -s --pdb 2>&1 | tee /tmp/backup-ttl-e2e.log` and record Constitution §V evidence (node ID, command, ISO timestamp, vcluster id + kubeconfig path, verbatim `PASSED` line) in this file under Evidence below

**Checkpoint**: US1 fully functional — environment policy lands on the Velero object, is recorded, logged, and E2E-proven. MVP deliverable.

---

## Phase 4: User Story 2 - Deployment-scope override (Priority: P2)

**Goal**: A single deployment overrides its environment's policy (deepest scope wins); cluster scope acts as the org-wide baseline.

**Independent Test**: With env `720h` and one deployment `8760h`, backups carry `8760h` for that deployment and `720h` for a sibling; with only cluster-scope set, backups inherit it.

### Tests for User Story 2 (write first)

- [ ] T018 [P] [US2] Extend `backend/tests/unit/services/test_backup_ttl_resolution.py`: deployment hop beats environment and cluster; cluster hop applies when deployment+environment unset; null-at-scope skips to the next hop (one test per precedence hop, FR-001)
- [ ] T019 [P] [US2] Add `backup_ttl` round-trips to `backend/tests/functional/graphql/test_deploy_input_propagation.py` (set at deploy → `Deployment.config["backup_ttl"]`) and `backend/tests/functional/graphql/test_update_deployment_input_propagation.py` (update-with preserves, update-omitting clears); add the field to `backend/tests/functional/graphql/test_update_deployment_input_introspection.py` if it enumerates input fields explicitly

### Implementation for User Story 2

- [ ] T020 [US2] Frontend deployment round-trip (FR-005): map `backup_ttl` ↔ `backupTtl` in `deploymentConfigToInput` in `frontend/src/lib/deployment-input.ts` and register `backupTtl` in the scalar registry of `frontend/src/lib/config-diff.ts` (section: the backup/storage-adjacent group; makes the field visible in config diffs); update any registry-enumerating tests

**Checkpoint**: Precedence proven at every hop; deployment-scope value settable via typed input, preserved by the UI, visible in diffs. (Backend resolution logic itself shipped in US1 — this story adds the deployment/cluster hops' proof and client plumbing.)

---

## Phase 5: User Story 4 - Expiry visible in web UI and CLI (Priority: P2)

**Goal**: Backup lists answer "when does this backup disappear?" without cluster access — web UI expiry column with TTL tooltip, CLI Expires column, "—" for null.

**Independent Test**: Render the backup list (UI component test / CLI unit test) with backups that have and lack expiry metadata; assert the date and the "—" fallback.

### Tests for User Story 4 (write first)

- [ ] T021 [P] [US4] Create `backend/tests/functional/graphql/test_backup_fields.py`: seed a `Backup` row with `metadata_ = {"ttl": "2160h", "expires_at": "<ISO>"}` and assert `Backup.ttl`/`Backup.expiresAt` project through GraphQL **reading back via a fresh session/UoW** (critique E4 — catches the JSON change-tracking class); seed `metadata_ = None` (pre-existing row) and a Failed-style row without `expires_at` → both fields / `expiresAt` null
- [ ] T022 [P] [US4] Extend `cli/tests/test_backups.py` (model on `test_backups_list_by_deployment_name`, line 144): mock backups with and without `expires_at`; assert the `Expires` column shows the value and `—` respectively; assert `backups get` output includes TTL/Expires lines
- [ ] T023 [P] [US4] Create `frontend/src/__tests__/deployment-detail/BackupExpiry.test.tsx` (mocking pattern from `DeploymentDetailHeader.test.tsx` lines 57-67): backup with `expiresAt` renders the localized date and its TTL is exposed via the tooltip/title; backup without renders `—`

### Implementation for User Story 4

- [ ] T024 [P] [US4] `cli/src/styrminctl/commands/backups.py`: add `"expires_at"` to the row dicts and an `Expires` column to `print_table` in `list_backups` (line 121-132), rendering `—` when null; add `TTL` / `Expires` lines to the `get` command's per-field block (lines 81-89)
- [ ] T025 [P] [US4] `frontend/src/pages/deployments/DeploymentDetailPage.tsx`: add an `Expires` header to the backups-tab column row (lines 613-629) and an expiry cell to `BackupRow` (line 993; extend its inline prop type with `ttl`/`expiresAt`) — localized date via the file's `new Date(x).toLocaleDateString()` convention, `—` when null, applied TTL exposed accessibly (Base UI Tooltip or `title` attribute per page convention — critique P2, not hover-only-invisible to keyboard/screen readers)

**Checkpoint**: SC-005 satisfied end-to-end — expiry readable from UI and CLI with no cluster access.

---

## Phase 6: User Story 3 - Invalid value rejected loudly (Priority: P3)

**Goal**: Malformed `backup_ttl` fails at submission on every surface with a typed error naming the field and hinting `720h`-style syntax; nothing is persisted.

**Independent Test**: Submit `30d` (and the reject matrix) through config surfaces; assert the typed error and unchanged stored config.

### Tests for User Story 3 (validator shipped in Phase 2 — these prove it)

- [ ] T026 [P] [US3] Extend `backend/tests/unit/context/test_base_config_section.py` with parametrised cases (FR-004): accept `720h`, `2160h`, `8760h`, `1h`, `90m`, `3600s`, `1h30m`, `1.5h`; reject `30d`, `0h`, `-24h`, `720`, `""`, `0h0m0s`; assert the message names `backup_ttl` and contains the `720h` hint; assert the field is accepted by `ClusterConfig`, `EnvironmentConfig`, and `DeploymentConfig` alike
- [ ] T027 [US3] Add a mutation-level rejection test (extend `backend/tests/functional/graphql/test_environment_update_propagation.py` or the deployment errors suite `test_update_deployment_input_errors.py`): `updateEnvironment` with `backupTtl: "30d"` returns a typed error (`extensions.code` from the `Invalid*ContextError` family) whose message names the field and hints the syntax, and the environment's stored config is unchanged (SC-003)

**Checkpoint**: All four user stories independently proven.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation (Constitution §VII — same-change, non-negotiable), final regression, evidence.

- [ ] T028 [P] Add a **Retention** section to `docs/docs/concepts-and-architecture/backups-and-restores.md`: the `backup_ttl` knob, three scopes + deepest-wins, `720h` default, applies-to-future-backups-only limitation (FR-009), expired-backup restore warning (cross-ref #304 behaviour), cluster-scope-is-set-at-create note, and a concrete `updateEnvironment` GraphQL example (critique P1 — the docs are the setter's UX; there is no first-party UI/CLI setter)
- [ ] T029 [P] Update `dev/knowledge/backend/backup-restore.md`: `metadata_` keys (`ttl`, `ttl_source`, `expires_at`), the `services/backup/ttl.py` resolver, the required-TTL builder signature, the `status.expiration` plumbing, and the new `Backup.ttl`/`expiresAt` GraphQL fields
- [ ] T030 [P] Add a **Backup retention TTL** glossary entry to `CONTEXT.md` after **Backup storage location** (line ~53), following the `**Term**:` / description / `_Avoid_:` three-line house convention, explicitly distinguished from `BackupSchedule.retention_count` (count-based, currently unenforced)
- [ ] T031 Full regression + gates: `uv run invoke format lint`; `uv run pytest backend/tests/unit backend/tests/functional -q`; `cd frontend && pnpm test`; `uv run pytest cli/tests -q`; confirm SC-004 (no assertion changes beyond the relocated pinned default) and that `git diff --exit-code` is clean after a fresh `uv run invoke generate`
- [ ] T032 Run the remaining `quickstart.md` scenarios (sections 1-3, 6; section 4 already executed in T017) and fill the Evidence block below

---

## Evidence (Constitution §V — fill during T017/T032)

| Item | Value |
|---|---|
| E2E node ID | `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle` (variants as parametrised) |
| Exact command | _(record)_ |
| PASS timestamp (ISO 8601) | _(record)_ |
| Cluster id + kubeconfig | _(record: vcluster<N>, /tmp/pytest-of-*/pytest-*/...)_ |
| Verbatim PASSED line | _(record)_ |

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after Setup. T002 → T003; T004/T005/T006/T007 parallel after T003 (T004 strictly after T003 to keep the schema-walk guard window short); T008 after T003-T007. **Blocks all stories.**
- **US1 (Phase 3)**: after Phase 2. T009/T010 first (fail), then T011/T012/T013 in parallel, T014 after T011+T012+T013, T015 after T013, T016 parallel with backend tasks, T017 last (needs everything in the story).
- **US2 (Phase 4)**: after Phase 2; independent of US1 for T018/T019/T020, but its end-to-end meaning rides US1's workflow wiring (T014). Run after US1.
- **US4 (Phase 5)**: after Phase 2 (fields exist); expiry *values* need US1's T012/T014 for live data — component/CLI tests use seeded/mocked data, so the story is independently testable.
- **US3 (Phase 6)**: after Phase 2 only (validator is foundational); placed last by priority.
- **Polish (Phase 7)**: after all stories. T028/T029/T030 parallel; T031 → T032 last.

### Parallel Opportunities

- Phase 2: T004, T005, T006, T007 (four different files).
- US1: T009 ∥ T010; T011 ∥ T012 ∥ T013; T016 ∥ any backend task.
- US2: T018 ∥ T019.
- US4: T021 ∥ T022 ∥ T023, then T024 ∥ T025.
- Polish: T028 ∥ T029 ∥ T030.

## Implementation Strategy

**MVP first**: Phases 1 → 2 → 3 deliver User Story 1 (environment policy, recorded + logged + E2E-proven) — a complete, shippable increment. Stop and validate at the Phase 3 checkpoint.

**Incremental delivery**: add US2 (precedence proof + client plumbing), then US4 (visibility surfaces), then US3 (rejection proof), then Polish. Each checkpoint leaves the suite green and the previous stories intact. Commit at each checkpoint via `speckit-checkpoint-commit`; note that T008's regenerated artifacts must be committed together with T003-T007 (CI fails on schema/SDK drift).
