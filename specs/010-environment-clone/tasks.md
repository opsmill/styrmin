# Tasks: Environment Clone

**Input**: Design documents from `/specs/010-environment-clone/`

**Prerequisites**: plan.md, spec.md, research.md (D1–D12), data-model.md, contracts/graphql.md, quickstart.md

**Tests**: REQUIRED — Constitution §V mandates propagation tests for every GraphQL element, unit coverage for the derivation/guards, and one E2E run to a local PASS with recorded evidence.

**Organization**: Grouped by user story. US2/US3 are semantic refinements of the clone operation shipped in US1 (the mutation carries the full contract signature from the start; their phases implement and prove the semantics).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 (clone with data), US2 (selection), US3 (config override), US4 (track & discard)

## Phase 1: Setup

- [X] T001 Verify baseline: `uv run invoke format lint`, `alembic heads` shows single head `c1d2e3f4a5b6`, `uv run invoke validate-graphql` green on the merged env-backup foundation; confirm `frontend/node_modules` present (`pnpm install`) so later codegen works

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the clone record, the cross-target restore mechanism (research D2), and the shared helpers. No user story works without these.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Add `EnvironmentClone` model (fields per data-model.md, incl. nullable `source_environment_id`, `source_environment_name`, `cleared_config_fields`, `clone_errors` with `fatal` flag; docstring stating **no status column, deliberately**) in `backend/styrmin_backend/db/models.py`
- [X] T003 Generate the Alembic revision creating `environmentclone` (named FK constraints, batch-alter-compatible, no new PG enums) in `backend/styrmin_backend/db/migrations/versions/` per `dev/guides/database-migrations.md`; verify upgrade+downgrade on a head database
- [X] T004 Create `SQLModelEnvironmentCloneRepository` (create/get/save, by-source and by-created lookups, batched restore-row fetch via one `IN` query across JSON `restore_id`s) in `backend/styrmin_backend/repository/environment_clone.py`
- [X] T005 Wire `environment_clones` repository into `UnitOfWork` (incl. `_SharedTransaction` forwarding) in `backend/styrmin_backend/services/unit_of_work.py`
- [X] T006 [P] Add typed errors `EnvironmentBackupInUseByCloneError` (`IN_USE`, metadata clone id/name) and clone-specific validation errors in `backend/styrmin_backend/services/exceptions.py`
- [X] T007 [P] Extend `DeploymentSnapshot` with `service_name_overrides` and capture it in `_capture_deployment_snapshot` (pre-existing snapshots read as `None`) in `backend/styrmin_backend/services/backup/environment.py`; unit test in `backend/tests/unit/services/backup/`
- [X] T008 [P] Add optional `deployment_ids: list[UUID] | None` filter to `create_environment_backup` (filters the eligible set before snapshot/constituent fan-out; GraphQL mutation unchanged) in `backend/styrmin_backend/services/backup/environment.py`; unit test
- [X] T009 Extend `create_restore` with `target_deployment_id: UUID | None` — resolve/guard (`internal`, `RESTORING`) and flip `RESTORING` on the **target**, persist the counterpart's `target_instance_id`, keep in-place behaviour when omitted — in `backend/styrmin_backend/services/backup/service.py` (research D2.1); unit tests covering both modes in `backend/tests/unit/services/backup/`
- [X] T010 Split source identity from status-write target in `execute_restore_workflow`: new `source_deployment_id` param derives `source_namespace`; `deployment_id` stays the status-write target (identical for in-place callers) in `backend/styrmin_backend/workflows/templates/backup.py` (research D2.2)
- [X] T011 Pass the restored CR name explicitly through the USER flow (Velero `namespaceMapping` preserves the source CR name `styrmin-<source_deployment_id>`; drop the `crd_name = target_namespace` assumption) in `backend/styrmin_backend/workflows/templates/backup.py` (research D2.3)
- [X] T012 Add the cross-target recovery path: replace the restored source-named `StyrminDeployment` CR with the **counterpart's own CR body** (built from its active instance context via `backend/styrmin_backend/operator/crd/builder.py`) then finalize, in `backend/styrmin_backend/operator/restore_recovery.py` (research D2.4); unit test with a fake api client
- [X] T013 [P] Label cross-target Restore CRs with the **counterpart** instance id in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py` (research D2.6); unit test on the rendered CR
- [X] T014 Add `skip_initial_reconcile: bool = False` (+ `RESTORING` initial state for counterparts) to `deploy_application` — `_ensure_ingress_controller`, `create_services_for_deployment`, `generate_instance_from_deployment` still run; return `Task | None` — and make `redeploy_for_environment_update` skip `RESTORING` deployments, in `backend/styrmin_backend/services/deployment.py` (research D5/D8); unit tests
- [X] T015 [P] Implement `merge_environment_config(captured, override, cleared_fields)` (canonicalise → pop cleared top-level keys → top-level-field replacement merge → `validate_environment_config`; typed error on unknown cleared field) in `backend/styrmin_backend/services/backup/clone.py` (research D7); unit tests incl. clear+override precedence
- [X] T016 Implement `derive_environment_clone_status` + terminal set per the data-model.md derivation (fatal-entry rule, resolution rules for nulled FKs and missing restore rows) in `backend/styrmin_backend/services/backup/clone.py`; full unit matrix in `backend/tests/unit/services/backup/test_environment_clone_status.py` — rows: PARTIAL capture, backup-deleted-post-terminality (outcome stands), backup-deleted-mid-clone (FAILED attributed), created-environment-deleted, missing restore row, empty selection → COMPLETED, coverage identity

**Checkpoint**: cross-target restore works in isolation; clone record and derivation exist.

---

## Phase 3: User Story 1 — Clone an environment with its data (Priority: P1) 🎯 MVP

**Goal**: one ADMIN operation → capture → new environment + counterpart deployments → data restored; source untouched; every deployment attributed.

**Independent Test**: propagation suite proves mutation → rows → derived status → attribution against the real repository; the heavy E2E (Phase 7) proves the running-copy outcome on a real cluster.

- [X] T017 [US1] Implement `clone_environment` service in `backend/styrmin_backend/services/backup/clone.py`: upfront validation (source resolution ADR-031, name free via `get_by_name_in_cluster`, zero side effects — FR-011), single registration transaction (clone row + capture via `_SharedTransaction` + attribution entries incl. upfront skips), constituent dispatch, `env_clone_dispatched` audit line (research D4)
- [X] T018 [US1] Extend the environment-level operation guard for clones in `backend/styrmin_backend/services/backup/environment.py` + `backend/styrmin_backend/services/environments.py`: non-terminal-capture clones occupy the **source**; non-terminal clones occupy the **created** environment (backup/restore/clone refused, `update_environment` refused with `EnvironmentOperationInProgressError`) per research D8; unit tests
- [X] T019 [US1] Implement the `EXECUTE_ENVIRONMENT_CLONE` INTERNAL flow in `backend/styrmin_backend/workflows/templates/clone.py` + register in `backend/styrmin_backend/workflows/models.py` and `backend/styrmin_backend/workflows/catalogue.py`: poll capture derived status → gate on restorable terminal status (FR-002) → create environment (merged config, recomputed capabilities) → create counterparts (pinned `driver_version_id` from snapshot fingerprint, `service_name_overrides`, `RESTORING`, skip reconcile) → dispatch cross-target restores → update attribution; tolerate the clone row vanishing (NOT_FOUND ends quietly)
- [X] T020 [US1] Flow/service error paths with unit tests in `backend/tests/unit/services/backup/test_environment_clone_service.py`: capture FAILED → nothing materialises + fatal entry; capture PARTIAL → failed constituents attributed, rest proceed; TOCTOU name loss → fatal entry FAILED; vanished driver version → per-deployment failed, rest proceed
- [X] T021 [P] [US1] Create GraphQL types (`EnvironmentClone`, `EnvironmentCloneStatus` hand-mirrored enum, `EnvironmentCloneDeploymentResult`, outcome enum) with `strawberry.Private` db_model + computed `status()` in `backend/styrmin_backend/api/definitions/backup/environment_clone.py`
- [X] T022 [US1] Add `cloneEnvironment` mutation (`_requires(Role.ADMIN)`, full contract signature incl. `deploymentIds`/`configOverride`/`clearConfigFields`) in `backend/styrmin_backend/api/schema/mutation.py` and `environmentClone`/`environmentClones` queries in `backend/styrmin_backend/api/schema/query.py`; regenerate `schema.graphql` (`uv run styrmin export graphql-schema schema.graphql`) and run `uv run invoke generate`
- [X] T023 [US1] Propagation tests in `backend/tests/functional/graphql/test_environment_clone.py` + named operations in `backend/tests/functional/graphql/operations/`: mutation persists clone row + capture + links + upfront skips; derived-status projection matrix from real DB state; both queries; ADMIN gating (FORBIDDEN via `read_write_client`); upfront typed errors (`ALREADY_EXISTS`, `NOT_FOUND`, `ALREADY_IN_PROGRESS`)
- [X] T024 [P] [US1] SDK: `.graphql` operations (`clone_environment`, `get_environment_clone`, `list_environment_clones`), `EnvironmentCloneResource` (`create/get/list/wait_for_clone` with terminal frozenset) in `python_sdk/src/styrmin_sdk/resources/environment_clones.py`, register in `python_sdk/src/styrmin_sdk/client.py`, regenerate, tests in `python_sdk/tests/test_environment_clones.py`
- [X] T025 [P] [US1] CLI: `env-clones` Cyclopts sub-app (`create <source-env> --name … [--deployment …] [--config-override <json|@file>] [--clear-config-field …] [--wait]`, `get`, `list`; exit 1 on FAILED/PARTIAL via `_report_terminal_status` pattern) in `cli/src/styrminctl/commands/environment_clones.py`, register in `cli/src/styrminctl/cli_commands.py`, tests in `cli/tests/test_environment_clones.py`

**Checkpoint**: full clone lifecycle works through GraphQL/SDK/CLI against unit/functional fakes.

---

## Phase 4: User Story 2 — Select which deployments to include (Priority: P2)

**Goal**: explicit selection clones only the chosen eligible deployments; omission = all eligible; everything attributed.

**Independent Test**: propagation test cloning with an exclusion — clone contains exactly the selected counterpart; the excluded deployment is accounted for.

- [X] T026 [US2] Selection semantics in `clone_environment` (`backend/styrmin_backend/services/backup/clone.py`): unknown/foreign deployment ids → upfront `NOT_FOUND` (zero side effects); selected-but-ineligible → attributed `skipped` with reason (FR-004); selection threaded into the capture filter (T008); unit tests
- [X] T027 [US2] Propagation tests in `backend/tests/functional/graphql/test_environment_clone.py`: explicit selection captures/clones only the selection; omitted selection includes all eligible; never-deployed deployment skipped with reason, not an error
- [X] T028 [P] [US2] Selection argument coverage in SDK (`deployment_ids`) and CLI (repeatable `--deployment`) tests in `python_sdk/tests/test_environment_clones.py` and `cli/tests/test_environment_clones.py`

**Checkpoint**: selection provable end-to-end at the functional tier.

---

## Phase 5: User Story 3 — Override the environment config at clone time (Priority: P2)

**Goal**: override merged over the captured config — including clearing fields — before any counterpart comes up.

**Independent Test**: propagation test — created environment's config equals captured ⊕ override with cleared fields absent; first counterpart instance contexts observe the merged config.

- [X] T029 [US3] Wire `configOverride`/`clearConfigFields` through mutation → service → flow environment creation (merge happens before `create_environment`; persisted on the clone row) in `backend/styrmin_backend/services/backup/clone.py` + `backend/styrmin_backend/workflows/templates/clone.py`; unit test that counterpart instance generation happens after the merge
- [X] T030 [US3] Propagation tests: override merged over captured config; cleared scalar field absent from the created environment's config; unknown clear-field name → `VALIDATION_ERROR`; no override → config equals captured; first instances' contexts reflect the merged config
- [X] T031 [P] [US3] Override/clear argument coverage in SDK and CLI tests (JSON inline + `@file` parse for `--config-override`)

**Checkpoint**: non-interference override provable at the functional tier.

---

## Phase 6: User Story 4 — Track, and if needed discard, a clone (Priority: P3)

**Goal**: honest derived tracking on every surface; discard paths that always release everything.

**Independent Test**: derived-status projection from seeded DB states; deletion-path unit tests; frontend component tests.

- [X] T032 [US4] D9 delete guard + cascades in `backend/styrmin_backend/services/backup/environment.py` (`delete_environment_backup`): `IN_USE` only while a referencing clone's capture is in flight; post-capture deletion nulls the FK and appends `environment_backup_deleted` (`fatal` iff clone non-terminal); unit tests for all three timing windows (FR-008)
- [X] T033 [US4] Clone-aware `delete_environment` in `backend/styrmin_backend/services/environments.py`: created-environment deletion writes `created_environment_deleted` (+ null FK, fatal iff non-terminal); source deletion handles clone records **before** backups cascade (terminal → keep with nulled source FK; non-terminal → delete); unit tests incl. SC-005 re-clone-after-discard and no-IN_USE-wedge
- [X] T034 [P] [US4] `Environment.clonedFrom` field in `backend/styrmin_backend/api/definitions/environment/model.py` + propagation test; regenerate schema + types
- [X] T035 [US4] Propagation tests: `deploymentResults` join projection (outcomes, reasons, counterpart/restore ids), coverage identity on terminal clones, `cloneErrors` rendering, provenance surviving source deletion
- [X] T036 [P] [US4] Frontend GraphQL operations (`clone_environment.graphql`, `get_environment_clone.graphql`, `list_environment_clones.graphql`) in `frontend/src/graphql/` + `pnpm codegen`
- [X] T037 [US4] `CloneEnvironmentDialog` (name, deployment checkboxes with ineligible rows disabled + reason tooltip, config override, clear-fields; `IfRole minimum="ADMIN"`; invalidation in `onSuccess`) in `frontend/src/components/environment/CloneEnvironmentDialog.tsx`
- [X] T038 [US4] `EnvironmentClonesSection` (derived status badge, per-deployment outcomes, `createdOn`-relative age, links to created environment + backing backup, tab-scoped 10s polling) in `frontend/src/components/environment/EnvironmentClonesSection.tsx` + entry point on `frontend/src/pages/environments/EnvironmentDetailPage.tsx`
- [X] T039 [P] [US4] Frontend Vitest coverage (dialog validation/submission, list rendering per status, role gating) in `frontend/src/__tests__/environments/EnvironmentClone*.test.tsx`

**Checkpoint**: all four stories functional on all four surfaces.

---

## Phase 7: E2E, Documentation & Final Gates

**Purpose**: Constitution §V definition-of-done (E2E to a local PASS with evidence) and §VII documentation accuracy — one heavy node deliberately covers US1–US4 (research D12, reuse-before-you-boot).

- [ ] T040 Scenario-driver clone methods (`clone_environment`, `get_environment_clone`, `wait_for_environment_clone`) in `backend/tests/e2e/drivers/protocol.py`, `refs.py` (EnvironmentCloneRef + outcome refs), `api_driver.py`, `ui_driver.py` (ADR-038)
- [ ] T041 [P] UI page objects for the clone dialog and clones section in `backend/tests/e2e/pages/environments.py`
- [ ] T042 Write `test_environment_clone_lifecycle` (`@pytest.mark.ci`, module `shard_backup`) in `backend/tests/e2e/test_backup_restore.py` per quickstart.md step 3: marker write → clone (with override + one exclusion) → post-capture mutation → terminal clone → authenticated-write data assertion (SC-004) → source untouched (SC-002) → full attribution (SC-003) → delete cloned env → re-clone accepted & materialised without second restore-wait (SC-005); named timeout constants
- [ ] T043 Run the E2E to a local PASS for **both** `[api-chromium]` and `[ui-chromium]` variants (`sleep infinity | uv run pytest … --pdb` recipe) and record the §V evidence: node id, exact command, ISO 8601 timestamp, vcluster id + kubeconfig path, verbatim `PASSED` line — in `specs/010-environment-clone/e2e-evidence.md`
- [ ] T044 [P] Public docs: clone section in `docs/docs/concepts-and-architecture/backups-and-restores.md` (operation, selection, override + clearing, derived statuses, attribution, discard paths, **honest non-interference scoping** incl. data-borne credentials, driver credential-generation note) + changelog entry in `docs/docs/changelog.md`
- [ ] T045 [P] CLI reference: `env-clones` command table + examples in `docs/docs/reference/styrminctl.md`
- [ ] T046 [P] New ADR (clone record + cross-target restore + capture-window guard deviation + ungated-read parity decision from research D10/X2) in `dev/adr/`
- [ ] T047 [P] Add **Environment clone** to `CONTEXT.md` (first-class record; links to the new ADR)
- [ ] T048 [P] Extend `dev/knowledge/backend/backup-restore.md` with the clone service table, flow, derivation, and cross-target restore mechanics
- [ ] T049 Final gates: `uv run invoke format lint`, `uv run invoke validate-graphql`, `uv run invoke generate` (no diff), full `uv run invoke test`, frontend `pnpm test` — all green

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2**: T001 first. Within Phase 2: T002 → T003 → T004 → T005; T009 → T010 → T011 → T012 (the cross-target chain); T006/T007/T008/T013/T015 parallel; T014 independent; T016 after T002.
- **Phase 3 (US1)**: needs all of Phase 2. T017/T018 → T019 → T020; T021 → T022 → T023; T024/T025 after T022 (need `schema.graphql`).
- **Phase 4 (US2)**: needs T017 + T008. T026 → T027; T028 parallel after T024/T025.
- **Phase 5 (US3)**: needs T015 + T019. T029 → T030; T031 parallel.
- **Phase 6 (US4)**: T032/T033 need T016; T034/T035 after T022; T036 → T037/T038 → T039.
- **Phase 7**: T040/T041 → T042 → T043 (needs US1–US4 complete); T044–T048 parallel anytime after Phase 6; T049 last.

### Parallel Opportunities

- Phase 2: {T006, T007, T008, T013, T15} alongside the T009–T012 chain and T014.
- Phase 3: T021 in parallel with T017–T020; T024 ∥ T025 after T022.
- Phase 7: T044–T048 all parallel; T041 ∥ T040.

## Implementation Strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US1)**: a full-fidelity clone of all eligible deployments with attribution, on GraphQL/SDK/CLI. US2/US3 are small semantic increments; US4 completes discard integrity + the UI surface; Phase 7 is the constitutional definition-of-done (the feature is NOT done before T043's PASS evidence and T044–T048's docs land — §V/§VII are non-negotiable).

**Governance reminder** (Ask-First gates, pre-agreed in the idea brief): database schema change (T002/T003), GraphQL schema modification (T022/T034), ADMIN auth surface (T022) — flag in the PR description for reviewer sign-off.
