# Tasks: Environment Clone

**Feature**: `specs/002-env-clone` | **Branch**: `fac/clone-restore-k93ia` | **Date**: 2026-08-06

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md) (D1–D12 + critique amendments), [data-model.md](data-model.md), [contracts/graphql.md](contracts/graphql.md), [quickstart.md](quickstart.md)

**Constitution obligations baked in**: propagation test for every new GraphQL field/argument/mutation (§V); dual-entrypoint E2E in `shard_backup` executed to a local PASS with recorded evidence (§V); documentation in the same change (§VII); Alembic revision with the model change (ADR-0001); driver-conformance tuple update.

## Phase 1 — Setup (DB schema + scaffolding)

- [ ] T001 Add `EnvironmentClone` model (columns per data-model.md) and nullable FK `Restore.environment_clone_id` to `backend/styrmin_backend/db/models.py`, with relationships (`source_environment`, `created_environment`, `environment_backup`, `restores`)
- [ ] T002 Alembic revision `down_revision = "c1d2e3f4a5b6"` in `backend/styrmin_backend/db/migrations/versions/` creating `environmentclone` + adding `restore.environment_clone_id` (no stored status enum); verify round-trip via `uv run pytest backend/tests/unit/db/ -k migration -v`
- [ ] T003 [P] Typed errors in `backend/styrmin_backend/services/exceptions.py`: `EnvironmentCloneNotFoundError` (`NOT_FOUND`), `EnvironmentCloneSelectionError` (`VALIDATION_ERROR`), `EnvironmentBackupInUseError` (`OPERATION_DENIED`) — existing codes only (research D6)
- [ ] T004 Repository pair (ABC + SQLModel) in `backend/styrmin_backend/repository/environment_clone.py` incl. the in-flight-clone EXISTS query (`finished_at IS NULL` for a given `environment_backup_id`); register `environment_clones` on `backend/styrmin_backend/services/unit_of_work.py`; unit tests in `backend/tests/unit/repository/backup/test_environment_clone_repository.py`

## Phase 2 — Foundational (cross-target restore mechanics; blocks all user stories)

- [ ] T005 Target-aware `create_restore` in `backend/styrmin_backend/services/backup/service.py`: resolve source deployment (from backup) *and* target deployment (from `target_instance_id`, already a column — currently written, never read); apply the `internal` check, `RESTORING` concurrency guard, status flip, and completion updates to the **target**; absent target keeps today's in-place behaviour byte-for-byte; accept `environment_clone_id` linkage; unit tests covering both modes in `backend/tests/unit/services/backup/test_environment_clone.py`
- [ ] T006 Factor the per-strategy restore command builders out of `backend/styrmin_backend/agent/service/kubernetes/velero/hooks.py` into shared functions consumed by both the Velero-hook path and the clone transfer step (postgres, mariadb, mongodb, neo4j), with parity unit tests in `backend/tests/unit/agent/` asserting hook output is unchanged
- [ ] T007 Velero/K8s builders in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py`: `excluded_resources` parameter on the restore build path (platform-identity kinds: `styrmindeployments`, Flux `helmreleases`, `networkpolicies`, ingress/middleware); deny-all ingress+egress NetworkPolicy builder + scratch-namespace label constant (`styrmin.io/environment-clone-restore`); unit tests beside `backend/tests/unit/agent/test_backup_builders.py`
- [ ] T008 USER flow (K8s-only) in `backend/styrmin_backend/workflows/templates/clone.py`: isolation prelude (create labelled scratch ns + deny-all policy **before** the Velero restore — critique E1), scratch Velero restore with `namespaceMapping` + exclusions, per-strategy data transfer (dump streaming into the counterpart's backup mount + exec of the factored restore commands; disk = stop component → helper-pod tar-stream copy → start component), unconditional teardown in `finally` (critique E4); orchestration-decision unit tests with mocked K8s in `backend/tests/unit/`
- [ ] T009 INTERNAL flow `EXECUTE_CLONE_RESTORE` in `backend/styrmin_backend/workflows/templates/clone.py`: create the constituent `Restore` row via target-aware `create_restore`, dispatch the USER flow, bounded wait mirroring `DEFAULT_RESTORE_TIMEOUT` (critique E2), status updates; register both flows in `backend/styrmin_backend/workflows/models.py` and `catalogue.py`
- [ ] T010 `derive_environment_clone_status` + `DeploymentCloneResult` Pydantic model in `backend/styrmin_backend/services/backup/clone.py` (rules per data-model.md: `finished_at` pivot, PARTIAL/FAILED from results + linked restores, deleted-row tolerance); property-style unit tests in `backend/tests/unit/services/backup/test_environment_clone.py` (never-terminal-before-`finished_at`, deleted rows never flip a `cloned` outcome)

## Phase 3 — User Story 1 (P1): Clone an environment with its data

**Goal**: one ADMIN operation produces a running, data-bearing copy; source untouched; derived status + full attribution.
**Independent test**: unit + propagation suites green; quickstart §4 CLI smoke produces a data-bearing clone on a dev stack (full E2E proof lands in Phase 7).

- [ ] T011 [US1] Clone create service in `backend/styrmin_backend/services/backup/clone.py`: synchronous validation with zero side effects (source exists; new name free per-cluster; no env-level op in flight — `ALREADY_IN_PROGRESS`, research D4; merged config passes `validate_environment_config`), record creation (copying `source_environment_name`), dispatch `EXECUTE_ENVIRONMENT_CLONE`; unit tests for every validation branch
- [ ] T012 [US1] INTERNAL saga flow `EXECUTE_ENVIRONMENT_CLONE` in `backend/styrmin_backend/workflows/templates/clone.py`: bounded backup wait (FAILED backup → clone FAILED, nothing materialises — FR-002); create environment from captured config (+BSL copy from source, capabilities recompute); per snapshot: counterpart via `deploy_application` with fingerprint-first driver-version re-resolution (research D3, `fingerprint_fallback` attribution), bounded `RUNNING` wait, dispatch `EXECUTE_CLONE_RESTORE`; append `deployment_results` progressively; `finished_at` in `finally`; `env_clone_*` audit log lines (critique E6); flow unit tests
- [ ] T013 [US1] Read services `get_environment_clone` / `get_environment_clones` (newest-first, source-scoped) in `backend/styrmin_backend/services/backup/clone.py` + unit tests
- [ ] T014 [US1] GraphQL surface: strawberry types in `backend/styrmin_backend/api/definitions/backup/environment_clone.py` (derived `status` resolver, `deploymentResults`, nullable related resolvers per contract); `cloneEnvironment` (**ADMIN** via `_requires(Role.ADMIN)`) + `deleteEnvironmentClone` (READ_WRITE) in `backend/styrmin_backend/api/schema/mutation.py`; `environmentClone` / `environmentClones` in `query.py`; regenerate `schema.graphql` via `uv run styrmin export graphql-schema schema.graphql`
- [ ] T015 [US1] Propagation tests in `backend/tests/functional/graphql/test_environment_clone.py` + operations in `backend/tests/functional/graphql/operations/` (one per mutation/query): every field, argument, and mutation, incl. the ADMIN-gate test (`test_clone_environment_requires_admin`) and derived-status projection through `fresh_client`
- [ ] T016 [P] [US1] SDK: 4 operation files in `python_sdk/src/styrmin_sdk/graphql/` (`clone_environment`, `get_environment_clone`, `list_environment_clones`, `delete_environment_clone`), `EnvironmentCloneResource` facade + `wait_for_clone(max_wait=1800, interval=10)` in `python_sdk/src/styrmin_sdk/resources/environment_clones.py`, attach in `client.py`, aliases in `models/__init__.py`; `uv run invoke generate`
- [ ] T017 [P] [US1] CLI: `env-clones` Cyclopts sub-app in `cli/src/styrminctl/commands/environment_clones.py` (`create` with dual-identifier source resolution + `--new-name` + `--wait`, `get`, `list`, `delete`; synchronous-terminal-failure rule from env-backups); register in `cli/src/styrminctl/cli_commands.py`; mock-based tests in `cli/tests/test_environment_clones.py`
- [ ] T018 [P] [US1] Frontend: operations in `frontend/src/graphql/` (3 files), `CloneEnvironmentDialog.tsx` (ADMIN-gated via `IfRole`) + `EnvironmentClonesTab.tsx` + `EnvironmentCloneRow.tsx` in `frontend/src/components/environment/`, wiring in `EnvironmentListPage.tsx` (Clone action) and `EnvironmentDetailPage.tsx` (Clones tab, 10 s auto-refresh); verify `internal` + active-instance fields are exposed on the `Deployment` type for the eligibility pre-filter (critique P2 — an additive field requires its own propagation test in T015); Vitest tests in `frontend/src/__tests__/environments/`

## Phase 4 — User Story 2 (P2): Select which deployments are cloned

**Goal**: selection narrows both the backup and the clone; ineligible deployments skip with attribution.
**Independent test**: unit test proves only selected deployments are backed up; propagation test proves `deploymentIds` round-trips; dialog/CLI selection tests pass.

- [ ] T019 [US2] Optional `deployment_ids` selection filter on `create_environment_backup` in `backend/styrmin_backend/services/backup/environment.py` (`None` = today's behaviour, exact backward compatibility); unit tests incl. selection ∩ eligibility
- [ ] T020 [US2] Selection validation in the clone service (`EnvironmentCloneSelectionError` for unknown/ineligible ids — upfront, zero side effects) + ineligible-deployment skip attribution carried from the capture into `deployment_results`; propagation test for the `deploymentIds` argument in `backend/tests/functional/graphql/test_environment_clone.py`
- [ ] T021 [P] [US2] Selection on the client surfaces: CLI repeatable `--deployment` in `cli/src/styrminctl/commands/environment_clones.py` (+ mock tests), SDK `deployment_ids` pass-through test, dialog multi-select behaviour tests in `frontend/src/__tests__/environments/`

## Phase 5 — User Story 3 (P2): Override environment configuration at clone time

**Goal**: override merged over captured config before any counterpart materialises; source unchanged.
**Independent test**: unit test on merge + validation ordering; propagation test proves `environmentConfigOverride` lands in the created environment's config.

- [ ] T022 [US3] Top-level shallow merge (`{**captured, **override}`) applied in the saga before environment creation, validated by `validate_environment_config` at clone-create time (fail fast) *and* the merged result used at creation; unit tests: override wins, captured-only keys survive, `None` override = verbatim copy, source config untouched
- [ ] T023 [P] [US3] Propagation test for `environmentConfigOverride` (override value visible in the clone record *and* the created environment's config) in `backend/tests/functional/graphql/test_environment_clone.py`; CLI `--config-override` JSON parsing + mock tests; dialog JSON editor tests

## Phase 6 — User Story 4 (P3): Understand and discard imperfect clones

**Goal**: PARTIAL/FAILED attribution, the FR-008 backup guard, and the discard-and-retry escape hatches.
**Independent test**: unit suites for every failure branch; propagation tests for the guard and record deletion.

- [ ] T024 [US4] FR-008 guard: `delete_environment_backup` (and the `delete_environment_backups_for_environment` cascade) raises `EnvironmentBackupInUseError` while a linked clone has `finished_at IS NULL`, in `backend/styrmin_backend/services/backup/environment.py`; unit tests + propagation test (`test_delete_environment_backup_refuses_in_flight_clone`)
- [ ] T025 [US4] `delete_environment_clone` service (record-only deletion, legal regardless of derived status — releases the FR-008 guard) in `backend/styrmin_backend/services/backup/clone.py`; unit tests + propagation test for `deleteEnvironmentClone`
- [ ] T026 [US4] Failure-path unit tests in `backend/tests/unit/services/backup/test_environment_clone.py`: TOCTOU name loss at creation → clone FAILED attributed (backup retained); vanished driver version → single `failed` result, saga continues; PARTIAL backup → proceed with capture-level skips carried over; per-step timeout → `failed` + continue + `finished_at` stamped (critique E2); strategy-less constituent → `cloned` with "no restorable data strategies" note (critique Q1)

## Phase 7 — E2E (Constitution §V definition of done)

- [ ] T027 Scenario driver surface: `clone_environment`, `get_environment_clone`, `wait_for_environment_clone`, `delete_environment_clone` on `backend/tests/e2e/drivers/protocol.py` (+ `EnvironmentCloneRef` in `refs.py`), API impl in `api_driver.py`, UI impl in `ui_driver.py` + page objects (clone dialog, Clones tab) in `backend/tests/e2e/pages/environments.py`; add the four methods to the explicit tuple in `backend/tests/unit/test_e2e_driver_conformance.py` and run it to green
- [ ] T028 E2E node `test_environment_clone_lifecycle` in `backend/tests/e2e/test_backup_restore.py` (`@pytest.mark.ci`, module already `shard_backup`, dual-entrypoint — no `api_only`/`ui_only`): quickstart §3 scenario incl. data marker (SC-004), selection exclusion (SC-003), source-untouched assertions (SC-002), delete + re-clone under the same name (SC-005), zero leftover `styrmin-clone-*` namespaces (critique E4)
- [ ] T029 Execute `[api-chromium]` to a local PASS: `sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" -v -s --pdb`; record §V evidence in this file (node ID, exact command, ISO timestamp, vcluster id + kubeconfig path, verbatim `PASSED` line)
- [ ] T030 Execute `[ui-chromium]` to a local PASS; record the same §V evidence block here

## Phase 8 — Polish & documentation (Constitution §VII, same change)

- [ ] T031 [P] Docs site: "Cloning an environment" section in `docs/docs/concepts-and-architecture/backups-and-restores.md` (data-only cross-target model; "What to expect while a clone runs" — hydration window + sequential duration, critique P1/E5; `action`-strategy and `service_name_overrides` limitations; deny-all scratch isolation + CNI caveat); `env-clones` group in `docs/docs/reference/styrminctl.md`; glossary entry in `docs/docs/concepts-and-architecture/glossary.md`; check `docs/docs/alpha-status.md` for an issue-#6 mention and update if present
- [ ] T032 [P] Internal docs: clone pipeline + scratch-namespace mechanics in `dev/knowledge/backend/backup-restore.md`; new ADR `dev/adr/00XX-environment-clone-data-only-cross-target-restore.md` (records research D1/D2/D5, the two documented deviations, parallelism as future work); `CONTEXT.md` amendments to the **Environment clone** entry (D4 concurrency ruling, record deletability)
- [ ] T033 Final gates: `uv run invoke format lint` (includes `validate-graphql` + `generate-validate`), full backend unit + functional suites, `cd frontend && pnpm test`, `cd cli && uv run pytest` — all green with zero codegen drift

## Dependencies

```text
Phase 1 (T001→T002; T003, T004 after T001)
  → Phase 2 (T005..T010; T008 needs T006+T007; T009 needs T005+T008)
    → US1 (T011 needs T004+T010; T012 needs T009+T011; T014 needs T011..T013; T015 needs T014; T016/T017/T018 [P] need T014)
      → US2 (T019 independent of US1 backend but merged after; T020 needs T011+T019; T021 [P] needs T016..T018)
      → US3 (T022 needs T012; T023 [P] needs T014+T017+T018)
      → US4 (T024 needs T004; T025 needs T013; T026 needs T012)
        → Phase 7 (T027 needs T016; T028 needs T027 + all US phases; T029→T030 after T028)
          → Phase 8 (T031/T032 [P] anytime after designs stabilise; T033 last)
```

US2/US3/US4 are independently mergeable increments on top of US1; none depends on another user story.

## Parallel execution examples

- After T014 lands: T016 (SDK), T017 (CLI), T018 (frontend) in parallel — three surfaces, disjoint files.
- After US1: T021 (US2 surfaces), T023 (US3 surfaces) in parallel with US4's backend tasks.
- T031 and T032 (docs) in parallel with Phase 7 execution runs.

## Implementation strategy

**MVP = Phase 1 + Phase 2 + US1** — a full-environment clone with default selection, no override: independently shippable and demoable (SC-001/002/004 hold). US2 (selection) and US3 (override) are additive arguments on an existing mutation; US4 hardens failure paths that US1's happy path already records structurally. E2E (Phase 7) is the §V gate before the feature is declared done — evidence blocks are appended to this file by T029/T030, not deferred.
