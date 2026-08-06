# Tasks: Environment-Level Backup and Restore

**Input**: Design documents from `specs/001-env-backup-restore/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/graphql.md, quickstart.md

**Tests**: REQUIRED — Constitution §V mandates propagation tests for every new GraphQL field/mutation, unit tests for new service logic, and a dual-entrypoint E2E run to a recorded local PASS before the feature is done.

**Organization**: Tasks are grouped by user story. US1 (backup) is the MVP; US2 (restore) and US3 (lifecycle/visibility) build on the same foundation. The single dual-entrypoint E2E scenario intentionally covers all three stories in one node (Constitution §V "reuse before you boot") and therefore lives in the cross-story integration phase.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 / US2 / US3 from spec.md

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: Schema, persistence, and shared service primitives every story depends on. No user story work can begin until this phase is complete.

- [X] T001 Add `EnvironmentBackup` and `EnvironmentRestore` SQLModel tables plus nullable FK columns `Backup.environment_backup_id` and `Restore.environment_restore_id` in `backend/styrmin_backend/db/models.py` (fields per data-model.md; JSON columns for `environment_config`, `deployment_snapshots`, `constituent_errors`, `skipped_constituents`; **no status columns**)
- [X] T002 Write the Alembic revision (new head after `b9c0d1e2f3a4`) creating both tables in FK-dependency order and adding the two nullable FK columns, with a clean `downgrade`, in `backend/styrmin_backend/db/migrations/versions/` (follow `dev/guides/database-migrations.md`; no DB enums are involved)
- [X] T003 [P] Create `EnvironmentBackupRepository`/`EnvironmentRestoreRepository` (ABC + SQLModel pair, mirroring `backend/styrmin_backend/repository/backup.py`) in `backend/styrmin_backend/repository/environment_backup.py`, including `get_by_environment_id(newest first)`, `get_by_environment_backup_id`, and the D6 guard queries (`has_in_progress_environment_backup`, `has_in_progress_environment_restore` — EXISTS over linked children in `PENDING`/`IN_PROGRESS`)
- [X] T004 Register both repositories on the `UnitOfWork` ABC and `SqlModelUnitOfWork` (import, ABC attribute, concrete attribute, `__aenter__` instantiation) in `backend/styrmin_backend/services/unit_of_work.py`
- [X] T005 [P] Add typed errors `EnvironmentBackupNotFoundError` (`NOT_FOUND`), `EnvironmentOperationInProgressError` (`ALREADY_IN_PROGRESS`, metadata: in-flight operation id + kind), `EnvironmentBackupNotRestorableError` (`OPERATION_DENIED`) in `backend/styrmin_backend/services/exceptions.py`
- [X] T006 [P] Create `backend/styrmin_backend/services/backup/environment.py` with the Pydantic snapshot models (`DeploymentSnapshot`, `ConstituentError`, `SkippedConstituent` per data-model.md) and the pure `derive_environment_operation_status(children_statuses, error_count)` function implementing the data-model derivation rule
- [X] T007 [P] Unit-test the derivation rule over the full outcome matrix (all-completed→`COMPLETED`, mixed→`PARTIAL`, all-failed/errors-only→`FAILED`, any non-terminal→`IN_PROGRESS`, all-pending→`PENDING`, zero children + zero errors→`COMPLETED`) in `backend/tests/unit/services/backup/test_environment_backup.py`
- [X] T008 [P] Repository unit tests (round-trip, guard queries incl. the no-children case, newest-first ordering) in `backend/tests/unit/repository/backup/test_environment_backup_repository.py`

**Checkpoint**: Foundation ready — user story phases can begin.

---

## Phase 2: User Story 1 — Coordinated environment backup in one action (Priority: P1) 🎯 MVP

**Goal**: One action captures environment config + per-deployment declared state and fans out one constituent backup per eligible deployment under a parent record with derived status.

**Independent Test**: Environment with several deployments → one `createEnvironmentBackup` → one constituent per eligible deployment, captured config/snapshots, parent status derives correctly; empty environment → config-only `COMPLETED`; conflict → recorded error + `PARTIAL`; concurrent request → typed error.

- [X] T009 [US1] Implement `create_environment_backup` in `backend/styrmin_backend/services/backup/environment.py`: resolve environment (`EnvironmentNotFoundError`), D6 concurrency guard (backup **and** restore guards), eligibility via `uow.deployments.find_all_by_environment` filtered by `not internal and active_application_instance_id is not None`, capture `environment_config` + `deployment_snapshots` (driver fingerprint per ADR-0053), create the parent row, then per-constituent: resolve component configs (reuse the `mutation.py:868-902` logic — extract it into a shared helper), call the existing `create_backup` service with `environment_backup_id`, dispatch `EXECUTE_BACKUP`; per-item `try/except` records `ConstituentError` and continues (ADR-0012 isolation); emit the `env_backup_fanout_dispatched` audit line (research.md D1 amendment)
- [X] T010 [US1] Unit tests for `create_environment_backup` in `backend/tests/unit/services/backup/test_environment_backup.py`: conflict child → recorded error + others proceed (FR-005), guard raises `ALREADY_IN_PROGRESS` (FR-009), empty environment → config-only immediate `COMPLETED` (FR-011), snapshot completeness incl. fingerprint (FR-002/FR-003), internal/tombstoned exclusion (FR-001)
- [X] T011 [US1] Add strawberry types `EnvironmentBackup`, `DeploymentSnapshot`, `EnvironmentBackupConstituent`, `EnvironmentBackupStatus` with the derived-status field resolver and constituents resolver (snapshots ⋈ linked backups ⋈ errors) in `backend/styrmin_backend/api/definitions/backup/environment_backup.py` (mirror `backup.py`'s `from_instance` pattern)
- [X] T012 [US1] Wire `createEnvironmentBackup` mutation (`_requires(Role.READ_WRITE)`) in `backend/styrmin_backend/api/schema/mutation.py` and `environmentBackup(environmentBackupId)` / `environmentBackups(environmentId)` queries in `backend/styrmin_backend/api/schema/query.py`
- [X] T013 [US1] Regenerate the schema snapshot: `uv run styrmin export graphql-schema schema.graphql`
- [X] T014 [US1] Propagation tests + named operation files in `backend/tests/functional/graphql/test_environment_backup.py` and `backend/tests/functional/graphql/operations/`: create persists parent + constituent links + snapshots to the DB; queries project derived status and per-constituent outcomes from seeded state (`dev/guides/graphql-propagation-tests.md`)
- [X] T015 [P] [US1] Add SDK operation files `create_environment_backup.graphql`, `get_environment_backup.graphql`, `list_environment_backups.graphql` in `python_sdk/src/styrmin_sdk/graphql/`
- [X] T016 [US1] Run `uv run invoke generate`; add `EnvironmentBackupResource` (`create`, `get`, `list`, `wait_for_backup` polling to terminal derived status) in `python_sdk/src/styrmin_sdk/resources/environment_backups.py`, attach `client.environment_backups` in `python_sdk/src/styrmin_sdk/client.py`, export public aliases in `python_sdk/src/styrmin_sdk/models/__init__.py` and `python_sdk/src/styrmin_sdk/__init__.py`
- [X] T017 [P] [US1] Create the `env-backups` Cyclopts sub-app with `create` (dual-identifier environment resolution per ADR-0031, `--wait/--max-wait/--interval`), `get`, `list` in `cli/src/styrminctl/commands/environment_backups.py`; register in `cli/src/styrminctl/cli_commands.py`; add `EnvironmentBackupId` alias in `cli/src/styrminctl/types.py`
- [X] T018 [P] [US1] CLI tests (mock-based, `capsys` assertions, mirroring `cli/tests/test_backups.py`) in `cli/tests/test_environment_backups.py`
- [ ] T019 [P] [US1] Add frontend operation files `create_environment_backup.graphql`, `list_environment_backups.graphql` in `frontend/src/graphql/`; run codegen (`cd frontend && pnpm codegen`)
- [ ] T020 [US1] Build `EnvironmentBackupsTab` (Create Backup button gated `READ_WRITE`, snapshot list with derived `StatusBadge`, 10s auto-refresh via `refetchInterval`, `data-testid` attributes for the UI driver) in `frontend/src/components/environment/EnvironmentBackupsTab.tsx` and wire it into `frontend/src/pages/environments/EnvironmentDetailPage.tsx` (drop the `SOON` badge and `EmptyState` stub)
- [ ] T021 [P] [US1] Frontend component tests (render list, create flow, status badges, empty state) in `frontend/src/__tests__/environments/EnvironmentBackupsTab.test.tsx`

**Checkpoint**: US1 independently deliverable — coordinated backup works end-to-end on API, SDK, CLI, and frontend.

---

## Phase 3: User Story 2 — Coordinated in-place environment restore (Priority: P2)

**Goal**: One action reverts environment config to the captured value and restores every usable constituent in place, skipping-and-reporting everything else.

**Independent Test**: Given an environment backup, mutate config + data → one `restoreEnvironmentBackup` → config equals captured value, usable constituents restored, every non-restored constituent attributed with deployment name + reason.

- [ ] T022 [US2] Implement `restore_environment_backup` in `backend/styrmin_backend/services/backup/environment.py`: existence + restorability guard (derived status ∈ {`COMPLETED`, `PARTIAL`} else `EnvironmentBackupNotRestorableError`), D6 concurrency guard, classify constituents (usable vs skipped: failed-at-creation, not-completed, deleted row, **expired via `expiresAt < now` from TTL metadata**, deployment gone/tombstoned, **deployment busy with another restore**), create the `EnvironmentRestore` row with complete `skipped_constituents`, revert `Environment.config` **by direct assignment (never via `update_environment` — its `None` no-op guard would break captured-`None` reverts)** + recompute capabilities + **commit before any dispatch** (ADR-0012), run the exclusion-aware fan-out (`redeploy_for_environment_update` only for eligible deployments NOT receiving a constituent restore), then per usable constituent call the existing `create_restore` with `environment_restore_id` + dispatch `EXECUTE_RESTORE` (a `RestoreAlreadyInProgressError` here downgrades to a skip, never an abort); emit `env_restore_fanout_dispatched` audit line
- [ ] T023 [US2] Unit tests for the restore path in `backend/tests/unit/services/backup/test_environment_backup.py`: full classification matrix incl. expired-but-`COMPLETED` constituent (critique E4), busy deployment, captured-config-`None` revert, fan-out exclusion set, restorability guard, deployment count unchanged across restore (FR-008), zero silent skips (FR-007)
- [ ] T024 [US2] Add `EnvironmentRestore`, `SkippedConstituent`, `EnvironmentRestoreStatus` strawberry types in `backend/styrmin_backend/api/definitions/backup/environment_restore.py`; wire `restoreEnvironmentBackup` mutation (`_requires(Role.ADMIN)` — config-revert privilege parity, research.md D7) in `mutation.py` and `environmentRestore(environmentRestoreId)` / `environmentRestores(environmentBackupId)` queries in `query.py`
- [ ] T025 [US2] Regenerate `schema.graphql`; add propagation tests + operation files for the restore surface (mutation persists `EnvironmentRestore` + skip records + constituent links; queries project derived status and skips) in `backend/tests/functional/graphql/`
- [ ] T026 [P] [US2] SDK: add `restore_environment_backup.graphql`, `get_environment_restore.graphql`, `list_environment_restores.graphql`; run `uv run invoke generate`; extend `EnvironmentBackupResource` with `restore`, `get_restore`, `list_restores`, `wait_for_restore`
- [ ] T027 [P] [US2] CLI: add `restore`, `restore-get`, `restore-list` commands (restore prints skipped constituents with reasons) to `cli/src/styrminctl/commands/environment_backups.py` + tests in `cli/tests/test_environment_backups.py`
- [ ] T028 [US2] Frontend: add `restore_environment_backup.graphql` + `list_environment_restores.graphql`, codegen; restore confirm dialog gated `<IfRole minimum="ADMIN">`, restore rows with per-constituent outcomes and skipped-constituent reasons in `frontend/src/components/environment/EnvironmentBackupRow.tsx`; component tests in `frontend/src/__tests__/environments/`

**Checkpoint**: US2 independently deliverable — one-action restore with attributed skips on all four surfaces.

---

## Phase 4: User Story 3 — Snapshot visibility and lifecycle management (Priority: P3)

**Goal**: Inspectable per-constituent outcomes (including gaps) and cascade deletion.

**Independent Test**: Snapshots with mixed outcomes are listable/inspectable; deleting one removes constituents + their restores; individually deleted constituent leaves a visible gap; deleting an in-progress snapshot works (escape hatch).

- [ ] T029 [US3] Implement `delete_environment_backup` (per-constituent `delete_backup` reuse + delete `EnvironmentRestore` rows + delete parent; **no status guard** — FR-010 escape hatch) in `backend/styrmin_backend/services/backup/environment.py`, and extend `delete_environment` in `backend/styrmin_backend/services/environments.py` to cascade the environment's environment backups first (FR-015); unit tests for both cascades incl. delete-while-in-progress in `backend/tests/unit/services/backup/test_environment_backup.py`
- [ ] T030 [US3] Wire `deleteEnvironmentBackup` mutation (`_requires(Role.READ_WRITE)`) in `mutation.py`; regenerate `schema.graphql`; propagation tests asserting DB-level cascade (constituents + their restores gone, gap visible after individual child deletion) in `backend/tests/functional/graphql/test_environment_backup.py`
- [ ] T031 [P] [US3] SDK `delete_environment_backup.graphql` + `delete` facade method + `uv run invoke generate`; CLI `delete` command + tests
- [ ] T032 [US3] Frontend: delete confirm dialog and per-constituent outcome expansion (constituent rows show backup status or error; gaps from deleted/expired children visible) in `frontend/src/components/environment/`; `delete_environment_backup.graphql` + codegen; component tests

**Checkpoint**: All three stories complete on all four surfaces.

---

## Phase 5: Cross-Story Integration — E2E + CI (Constitution §V definition of done)

**Purpose**: One dual-entrypoint E2E scenario covering the full US1→US2→US3 lifecycle on the already-booted `shard_backup` stack ("reuse before you boot").

- [ ] T033 Extend the scenario-driver protocol: `EnvironmentBackupRef`/`EnvironmentRestoreRef` in `backend/tests/e2e/drivers/refs.py`; `create_environment_backup`, `get_environment_backup`, `wait_for_environment_backup`, `restore_environment_backup`, `wait_for_environment_restore`, `delete_environment_backup` in `backend/tests/e2e/drivers/protocol.py`; API implementations in `backend/tests/e2e/drivers/api_driver.py`; UI implementations in `backend/tests/e2e/drivers/ui_driver.py` backed by a new environment-backups-tab page object in `backend/tests/e2e/pages/environments.py`; conformance assertions in `backend/tests/e2e/drivers/test_conformance.py`
- [ ] T034 Remove the `{entrypoint: ui, shard: backup}` matrix exclusion in `.github/workflows/ci.yml` (~line 240) — its comment pre-authorizes this when a dual-entrypoint backup test lands
- [ ] T035 Add `test_environment_backup_and_restore_lifecycle` (`@pytest.mark.ci`, module-level `shard_backup`) to `backend/tests/e2e/test_backup_restore.py`: reuse `deployed_simple_app` + create one additional deployment with unique `service_name_overrides` in `scenario_environment_id`; assert one constituent per eligible deployment (SC-001), derived-status transitions (SC-003), config mutation → restore → config equals captured value (SC-005) + data restored (SC-002) + attributed skips (SC-004), and cascade delete (US3)
- [ ] T036 Run the E2E to a local PASS for **both** entrypoints (`sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle" -v -s --pdb` filtered per `[api-chromium]`/`[ui-chromium]`) and record Constitution §V evidence: node ID, exact command, ISO 8601 timestamp, vcluster id + kubeconfig path, verbatim `PASSED` lines

---

## Phase 6: Polish, Documentation & Final Gates (Constitution §VII)

- [ ] T037 [P] Add the environment-level backup/restore section to `docs/docs/concepts-and-architecture/backups-and-restores.md` (semantics: near-consistent, config + data not topology, derived status, skip reasons, terminal-status-vs-convergence note, escape hatch)
- [ ] T038 [P] Update `docs/docs/alpha-status.md` (remove the issue-#7 "coming before beta" bullet, lines 30-32), `docs/docs/reference/styrminctl.md` (`env-backups` group), and `docs/docs/concepts-and-architecture/glossary.md` (environment backup / environment restore entries)
- [ ] T039 [P] Update `dev/knowledge/backend/backup-restore.md` with the environment-level flow (fan-out diagram, derived status, restore ordering)
- [ ] T040 [P] Write the new ADR `dev/adr/0055-environment-backup-parent-records.md`: parent record + derived status design, restore ordering (D4), and the justified deviation from ADR-0012's umbrella-record rejection
- [ ] T041 Final gates: `uv run invoke format lint` (includes `validate-graphql` + `generate-validate` codegen-drift checks), `uv run invoke test`, `cd frontend && pnpm test`, `cd cli && uv run pytest` — all green

---

## Dependencies

- **Phase 1 → everything**: T001→T002 (models before revision); T003/T005/T006 parallel after T001; T004 after T003; T007/T008 after T006/T003.
- **US1 (Phase 2)**: T009 after Phase 1; T010 after T009; T011/T012 after T009; T013 after T012; T014 after T013; T015 parallel with T011-T014; T016 after T013+T015; T017/T018 after T016; T019 parallel after T013; T020 after T019; T021 after T020.
- **US2 (Phase 3)**: starts after Phase 1; service (T022) is independent of US1's API layer but the E2E needs both — recommended after US1. T024→T025→T026/T027/T028 mirror the US1 ordering.
- **US3 (Phase 4)**: T029 after Phase 1; T030 after T029; T031/T032 after T030.
- **Phase 5**: T033 after US1-US3 API surfaces (UI driver additionally needs T020/T028/T032 frontend pieces); T035 after T033+T034; T036 after T035.
- **Phase 6**: T037-T040 parallel anytime after US2; T041 last.

## Parallel Execution Examples

- After T001: T003, T005, T006 in parallel (different files).
- Within US1 after T013: T015 (SDK ops), T017/T018 (CLI, after T016), T019 (frontend ops) in parallel across surfaces.
- Phase 6: T037, T038, T039, T040 all parallel.

## Implementation Strategy

**MVP = Phase 1 + Phase 2 (US1)**: coordinated backup with traceable parent record delivers the core issue-#7 value standalone. US2 adds recovery, US3 completes lifecycle management, Phase 5 is the constitutional definition of done (E2E PASS evidence for both entrypoints), Phase 6 closes the documentation obligations. Each user-story phase is independently testable via its checkpoint criteria; commit at every checkpoint via `speckit-checkpoint-commit`.
