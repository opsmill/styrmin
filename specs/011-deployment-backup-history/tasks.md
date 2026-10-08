---
description: "Task list for keeping a deployment's backup history when it gets a new instance (#304)"
---

# Tasks: Keep a Deployment's Backup History When It Gets a New Instance

**Input**: Design documents from `specs/011-deployment-backup-history/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md), [critique](critiques/critique-20261008-223639.md)

**Tests**: REQUIRED. Constitution §V requires unit tests for new repository and service logic, a GraphQL propagation test for the new `deploymentId` argument, and an E2E test extended and observed to PASS in both variants. The PRD's "Testing decisions" names each test file.

**Organization**: Tasks are grouped by the user stories in spec.md. The shared read path (repository, service, `backups` argument, SDK binding, code generation) is foundational, because every story lists backups through it. The one E2E extension covers US1 (view and restore after a new instance) and lives in the US1 phase.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 to US4, from spec.md
- Paths are relative to the repository root

## Path Conventions

- Backend: `backend/styrmin_backend/`, tests in `backend/tests/`
- SDK: `python_sdk/src/styrmin_sdk/`, tests in `python_sdk/tests/`
- CLI: `cli/src/styrminctl/`, tests in `cli/tests/`
- Frontend: `frontend/src/`, tests in `frontend/src/__tests__/`

---

## Phase 1: Setup

**Purpose**: Working environment and a green baseline for the files this change touches.

- [X] T001 Install dependencies with `uv sync` and `cd frontend && pnpm install --ignore-workspace` (`--ignore-workspace` keeps pnpm from resolving a parent workspace when the checkout is a nested worktree), then confirm `uv run invoke generate` runs cleanly before any change
- [X] T002 Run the baseline of the affected test files and record any failure that exists before this change: `uv run pytest backend/tests/unit/repository/backup/test_backup_repository.py backend/tests/unit/services/backup/test_backup_service.py backend/tests/functional/graphql/test_backup_fields.py backend/tests/functional/graphql/test_backup_restore_steps_propagation.py python_sdk/tests/test_backups.py cli/tests/test_backups.py` and `cd frontend && pnpm test -- deployment-detail`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The deployment-scoped read path from the database to the SDK. Every user story depends on it.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Repository

- [X] T003 Add the abstract method `get_by_deployment_id(self, deployment_id: UUID, status: BackupStatus | None = None) -> Sequence[Backup]` to `BackupRepository`, and implement it in `SQLModelBackupRepository` in `backend/styrmin_backend/repository/backup.py`: `select(Backup).join(ApplicationInstance, Backup.instance_id == ApplicationInstance.id).where(ApplicationInstance.deployment_id == deployment_id)`, optional `Backup.status == status`, `order_by(Backup.created_on.desc())`, as in [data-model.md](data-model.md). Keep `get_by_instance_id` unchanged.
- [X] T004 [P] Extend `backend/tests/unit/repository/backup/test_backup_repository.py` with tests for `get_by_deployment_id`:
  - backups of two instances of one deployment are both returned, newest first
  - backups of an instance of another deployment are not returned
  - `status` filters the result
  - an id that matches no deployment returns an empty list
  - a constituent backup (with `environment_backup_id` set) is included

### Service

- [X] T005 Add `FakeBackupRepository.get_by_deployment_id` in `backend/tests/unit/services/fakes.py`, walking backup → instance → `deployment_id` through an `instance_source` attribute wired by `FakeUnitOfWork`, the same way `FakeRestoreRepository.instance_source` is wired. Return results newest first by `created_on`, honour `status`.
- [X] T006 Change `get_backups` in `backend/styrmin_backend/services/backup/service.py` to `async def get_backups(uow: UnitOfWork, *, deployment_id: UUID | None = None, instance_id: UUID | None = None, status: BackupStatus | None = None) -> Sequence[Backup]`. Raise `AmbiguousIdentifierError` (from `services/exceptions.py`) with "Provide either deployment_id or instance_id, not both" when both are set, and "Either deployment_id or instance_id is required" when neither is set, modelled on `resolve_cluster` in `services/clusters.py`. Dispatch to `uow.backups.get_by_deployment_id` or `uow.backups.get_by_instance_id`. Update the docstring to describe the backup history.
- [X] T007 Extend `backend/tests/unit/services/backup/test_backup_service.py`: update the two existing `get_backups(instance_id=...)` call sites (around lines 235 and 253) to the new keyword-only signature, and add tests that `deployment_id` returns backups of every instance of the deployment, that `instance_id` returns only that instance's backups, and that both or neither raise `AmbiguousIdentifierError` with `error_code == "VALIDATION_ERROR"` (research R3)

### GraphQL

- [X] T008 Change the `backups` resolver in `backend/styrmin_backend/api/schema/query.py` to take `deployment_id: UUID | None = None`, `instance_id: UUID | None = None` and `status: BackupStatusType | None = None`, forward all three to `get_backups` without validating them, and give the field a description stating the exactly-one rule and that `deploymentId` lists the deployment's backup history ([contracts/graphql.md](contracts/graphql.md))
- [X] T009 Regenerate `schema.graphql` with `uv run styrmin export graphql-schema schema.graphql` and check the `backups` signature matches [contracts/graphql.md](contracts/graphql.md)
- [X] T010 Create `backend/tests/functional/graphql/operations/list_backup_history.graphql` with one named operation `query ListBackupHistory($deploymentId: UUID, $instanceId: UUID, $status: BackupStatus)` that calls `backups(deploymentId: $deploymentId, instanceId: $instanceId, status: $status)` and selects `id`, `status`, `createdOn`, `instanceId` and `instance { id applicationVersion }`
- [X] T011 Create the GraphQL propagation test `backend/tests/functional/graphql/test_backup_history_propagation.py` (read recipe in `dev/guides/graphql-propagation-tests.md`, seeds from `seeds.py`, `load_query("list_backup_history")`). Seed one deployment with two instances at different application versions, a backup of each, and a backup of an instance of a second deployment. Assert:
  - `backups(deploymentId:)` returns both backups of the first deployment, newest first, each with the `instance.applicationVersion` of its own instance
  - the second deployment's backup is not returned
  - `status: COMPLETED` filters the history
  - an unknown `deploymentId` returns `[]` (research R4)
  - `backups(instanceId:)` with the inactive instance returns only that instance's backup (SC-004)
  - passing both arguments, and passing neither, returns an error with `extensions.code == "VALIDATION_ERROR"`
- [X] T012 Run `uv run invoke validate-graphql` and confirm the existing operations that declare `$instanceId: UUID!` (`backend/tests/functional/graphql/operations/list_backup_statuses.graphql`, `list_backup_steps.graphql`) still validate (critique E7)

### SDK

- [X] T013 Update `python_sdk/src/styrmin_sdk/graphql/list_backups.graphql` to `query ListBackups($deploymentId: UUID, $instanceId: UUID, $status: BackupStatus)` calling `backups(deploymentId: $deploymentId, instanceId: $instanceId, status: $status)`, and add `instance { id applicationVersion }` to the selection ([contracts/graphql.md](contracts/graphql.md))
- [X] T014 Change `BackupsResource.list_backups` in `python_sdk/src/styrmin_sdk/resources/backups.py` to `list_backups(self, instance_id: str | UUID | None = None, status: BackupStatus | str | None = None, *, deployment_id: str | UUID | None = None)`, sending only the variables that are set (`deploymentId`, `instanceId`, `status`), and update its docstring ([contracts/sdk.md](contracts/sdk.md))
- [X] T015 Regenerate the SDK and frontend types with `uv run invoke generate` (commits the changes under `python_sdk/src/styrmin_sdk/graphql/_generated/` and `frontend/src/generated/`); do not edit generated files by hand

**Checkpoint**: `backups(deploymentId:)` works end to end through the SDK. User story phases can begin.

---

## Phase 3: User Story 1 - View and restore a backup taken before the deployment got a new instance (Priority: P1) 🎯 MVP

**Goal**: After an upgrade, a config edit, a refresh or an environment config change, the Backups tab, `styrminctl backups list <deployment>` and `backups(deploymentId:)` still list the earlier backups, each with its application version, and the operator can restore one from the Backups tab.

**Independent Test**: Take a backup, run one of the four operations, then list the deployment's backups in all three places; the earlier backup is listed with its application version and restores from the Backups tab (spec US1).

### Tests for User Story 1

- [X] T016 [US1] Add the four-operation integration test to `backend/tests/functional/graphql/test_backup_history_propagation.py`, parametrized over upgrade, config edit, refresh and environment config change (research R8). For each case:
  - seed a deployment with an active instance and a completed backup of it
  - arm Prefect with the `_arm_prefect` pattern from `test_driver_version_reselection_propagation.py`
  - run the operation: `updateDeploymentVersion` (operation file `update_deployment_version.graphql`, with a second driver version seeded so the upgrade is not a no-op), `updateDeployment` (`update_deployment_config.graphql`, with a changed config), `updateEnvironment` (`update_environment.graphql`, with a changed environment config), and `refresh_deployment` called directly with a real `SqlModelUnitOfWork` over the test session, because it has no GraphQL field (research R2)
  - assert the deployment's `active_application_instance_id` changed
  - query `list_backup_history` with `deploymentId` and assert the earlier backup is returned with the application version of the instance it was taken of
- [X] T017 [P] [US1] Extend `frontend/src/__tests__/deployment-detail/BackupExpiry.test.tsx`: assert `useListBackupsQuery` is called with `{ deploymentId }` from the route, and that the query is enabled when `deployment.applicationInstance` is null; assert each row shows the **Application version** column value and carries `data-backup-application-version`
- [X] T018 [P] [US1] Extend `cli/tests/test_backups.py`:
  - change `test_backups_list_by_deployment_name` (asserts at line 160) to expect `list_backups(deployment_id=<deployment id>, status=None)`
  - add a test that `list --id <deployment-id>` lists by `deployment_id` and works when the deployment has no active instance
  - keep `test_backups_list_by_instance_id_escape_hatch` expecting `instance_id=`
  - add a test that the table has an `application_version` column filled from `backup.instance.application_version`
  - set `instance.application_version` on the existing `mock_backup` fixtures so the output is deterministic

### Implementation for User Story 1

- [X] T019 [US1] Update `frontend/src/graphql/list_backups.graphql` to `query ListBackups($deploymentId: UUID!)` calling `backups(deploymentId: $deploymentId)`, and add `instance { id applicationVersion }` to the selection; regenerate with `uv run invoke generate` (or `cd frontend && pnpm codegen`)
- [X] T020 [US1] In `frontend/src/pages/deployments/DeploymentDetailPage.tsx`:
  - call `useListBackupsQuery({ deploymentId }, { refetchInterval: ... })` with the route's `deploymentId`, and remove the `enabled: !!instanceId` gate
  - add an **Application version** column header after **Status** in the Backups tab table
  - in `BackupRow`, add `instance: { applicationVersion: string }` to the `backup` prop type, render the version cell, and set `data-backup-application-version` on the `backup-row` element
  - leave "Create Backup", restore and delete behaviour unchanged ([contracts/ui.md](contracts/ui.md))
- [X] T021 [US1] Update every frontend test that builds a `ListBackupsQuery` backup fixture so it includes `instance: { id, applicationVersion }`, and every test that asserts the `useListBackupsQuery` arguments: `frontend/src/__tests__/deployment-detail/BackupRestoreSteps.test.tsx`, `DocumentTitle.test.tsx`, `TaskResult.test.tsx`, `DeploymentDetailHeader.test.tsx`, `UpgradeDialogPinnedImages.test.tsx`; then run `cd frontend && pnpm test && pnpm build` (`build` runs `tsc -b`)
- [X] T022 [US1] Add `resolve_deployment_id(sdk, *, deployment_name, deployment_id, environment) -> str` to `cli/src/styrminctl/resolve.py`: validate that exactly one of a name or `--id` is given (and that `--environment` is used only with a name), reuse `_resolve_by_name` for names, call `sdk.deployments.get` for `--id`, and do not require an active instance (research R7)
- [X] T023 [US1] Change `list_backups` in `cli/src/styrminctl/commands/backups.py`:
  - with `--instance-id`, call `sdk.backups.list_backups(instance_id=..., status=status)` as today
  - otherwise call `resolve_deployment_id` and `sdk.backups.list_backups(deployment_id=..., status=status)`
  - add the `application_version` column after `status`, read from `b.instance.application_version`
  - replace the docstring with the help text in [contracts/cli.md](contracts/cli.md)

### E2E for User Story 1

- [X] T024 [P] [US1] Add `application_version: str | None = None` to `BackupRef` in `backend/tests/e2e/drivers/refs.py`, after `steps`, so existing constructors keep working
- [X] T025 [US1] Add `async def list_backups(self, *, deployment_id: str) -> tuple[BackupRef, ...]` to the `ScenarioDriver` protocol in `backend/tests/e2e/drivers/protocol.py`, with a docstring stating the API source (`client.backups.list_backups(deployment_id=...)`) and the UI source (every `backup-row` on the Backups tab, including `data-backup-application-version`)
- [X] T026 [P] [US1] Implement `list_backups` in `backend/tests/e2e/drivers/api_driver.py`: call `client.backups.list_backups(deployment_id=...)` and map each result to `BackupRef(id, name, status, application_version=b.instance.application_version)`
- [X] T027 [P] [US1] Implement `list_backups` in `backend/tests/e2e/drivers/ui_driver.py` and a `read_backups()` page method in `backend/tests/e2e/pages/deployment_detail.py`: ensure the deployment detail page, open the Backups tab, read every `[data-testid=backup-row]` with `_required_attr` for `data-backup-id`, `data-backup-name`, `data-backup-status` and `data-backup-application-version`
- [X] T028 [US1] Extend `test_backup_and_restore_lifecycle` in `backend/tests/e2e/test_backup_restore.py` (research R9):
  - after the step-0 fanout settles, re-read the deployment's active instance id with `client.deployments.get(deployment_id)` and pass it to `create_backup`, replacing the stale fixture value
  - after step 2d, read the `server` component's current env vars from the stored deployment config, call `scenario_driver.set_component_env_vars(deployment_id=..., component="server", env_vars={"STYRMIN_E2E_BACKUP_HISTORY": "1"})`, then `scenario_driver.wait_for_deployment_running(...)` and `wait_for_pods_ready(...)`
  - assert the active instance id changed
  - assert `scenario_driver.list_backups(deployment_id=...)` contains the backup with `application_version == "0.1.0"`
  - keep steps 3 to 6 (restore, data check, delete) unchanged, so they run against a backup of an earlier instance
  - in `finally`, revert the `server` env vars to their previous value inside their own `try`/`finally` that wraps the existing `backup_ttl` revert, so neither revert can skip the other or hide the test's failure (critique E5)
  - keep the `ci` and `shard_backup` markers; do not add `api_only` or `ui_only`
- [X] T029 [US1] Run the extended E2E test to a PASS in each variant, each variant in its own pytest session (`-k api-chromium`, then `-k ui-chromium`), because running both in one session breaks the UI variant's setup, with the commands in [quickstart.md](quickstart.md) §2. If the restore step becomes unstable after the config edit, apply the fallback in research R9 (move the edit and the history check after step 5) and record the move. Record for each variant the evidence Constitution §V requires in `specs/011-deployment-backup-history/e2e-evidence.md`:
  - node id
  - exact command
  - ISO 8601 timestamp of the passing run
  - vcluster id and kubeconfig path
  - the verbatim `PASSED` line

**Checkpoint**: US1 works in the Backups tab, the CLI list and the API, and the E2E test passes in both variants.

---

## Phase 4: User Story 2 - Restore the latest backup from the CLI after a config edit (Priority: P2)

**Goal**: `styrminctl backups restore --last --target-deployment <name>` chooses the newest completed backup in the deployment's history.

**Independent Test**: Take a backup, edit the deployment's config, run `restore --last --target-deployment <name>`; a restore of the newest completed backup in the history starts (spec US2).

### Tests for User Story 2

- [X] T030 [US2] Extend `cli/tests/test_backups.py`:
  - change `test_backups_restore_last_by_deployment` (assert at line 355) to expect `list_backups(deployment_id=<deployment id>, status="completed")`, and check that the chosen backup can belong to an instance that is not the active one
  - keep `test_backups_restore_last_by_instance_id` expecting `instance_id=` (spec FR-004, critique P4)
  - change `test_backups_restore_last_no_completed_backups_exits_nonzero` to check the message names the deployment when targeted by deployment, and add a case for `--target-instance-id` that keeps the instance message

### Implementation for User Story 2

- [X] T031 [US2] In `_prepare_restore` in `cli/src/styrminctl/commands/backups.py`, when `last` is set and `target.deployment_id` is not `None`, call `sdk.backups.list_backups(deployment_id=target.deployment_id, status="completed")` and fail with `No completed backups found for deployment '<name or id>'`; when the target is a raw `--target-instance-id`, keep `list_backups(instance_id=..., status="completed")` and the existing message ([contracts/cli.md](contracts/cli.md))
- [X] T032 [US2] Update the help text of the `restore` command's `--last` parameter in `cli/src/styrminctl/commands/backups.py` to say it chooses the newest completed backup from the deployment's backup history, or from the instance's backups with `--target-instance-id`

**Checkpoint**: US2 works with the CLI tests green.

---

## Phase 5: User Story 3 - List a deployment's backups by deployment id from the API and SDK (Priority: P2)

**Goal**: API and SDK users list a deployment's history by deployment id; `instanceId` callers keep the same results; invalid argument combinations fail with `VALIDATION_ERROR`.

**Independent Test**: Call `backups(deploymentId:)`, `backups(instanceId:)`, and both or neither; check results and errors (spec US3). The GraphQL side is covered by T011; this phase covers the SDK.

### Tests for User Story 3

- [X] T033 [P] [US3] Extend `python_sdk/tests/test_backups.py`:
  - `list_backups(deployment_id=...)` sends `{"deploymentId": ...}` and no `instanceId`
  - `list_backups(instance_id=...)` and positional `list_backups(<id>)` send `{"instanceId": ...}` as before
  - `status` is coerced and sent with either
  - a response that includes `instance { id applicationVersion }` parses to `backups[0].instance.application_version`
  - a `VALIDATION_ERROR` response raises the SDK's existing exception for that code
  - update the existing mocked responses (around lines 111 and 375) to include the `instance` field

### Implementation for User Story 3

- [X] T034 [US3] Check the docstring of `BackupsResource.list_backups` in `python_sdk/src/styrmin_sdk/resources/backups.py` describes both arguments, says the server enforces the exactly-one rule, and gives one example for each argument; `python_sdk/AGENTS.md` and the `docs/` pages do not document `list_backups` today, so no other SDK page changes

**Checkpoint**: US3 works with the SDK tests and the propagation test green.

---

## Phase 6: User Story 4 - View the backup history of a deleted deployment (Priority: P3)

**Goal**: A deleted deployment's page and the API list its backup history; a new deployment that reuses its name starts empty.

**Independent Test**: Take a backup, delete the deployment, list its backups by deployment id; the backup is listed. Create a new deployment with the same name; its history is empty (spec US4).

### Tests for User Story 4

- [X] T035 [P] [US4] Add cases to `backend/tests/functional/graphql/test_backup_history_propagation.py`: a deployment marked deleted (`deleted_at` set, status `DELETED`, as `test_deployments_include_deleted.py` seeds it) still returns its backups through `backups(deploymentId:)`; a second deployment with the same name in the same environment returns `[]`
- [X] T036 [P] [US4] Extend `frontend/src/__tests__/deployment-detail/BackupExpiry.test.tsx` (or the existing deleted-deployment test file that renders `DeploymentDetailPage`) with a deleted deployment whose `applicationInstance` is set: the Backups tab lists the history rows and the restore and delete actions stay disabled, as they are today for a deleted deployment

### Implementation for User Story 4

No production code beyond Phase 2 and T020. Listing by deployment id already covers deleted deployments (research R1, R4).

**Checkpoint**: US4 is covered by tests.

---

## Phase 7: Polish, Documentation and Final Gates (Constitution §VI, §VII)

**Purpose**: Documentation in the same change, the changelog, and the full local gate.

- [ ] T037 [P] Update `docs/docs/concepts-and-architecture/backups-and-restores.md`: add a "Backup history" passage explaining that a deployment's backup list contains the backups of every instance the deployment has had, newest first, and that each one shows the application version it was taken at; name the four operations that give a deployment a new instance; and say that restores do not check the application version
- [ ] T038 [P] Update `docs/docs/reference/styrminctl.md`: replace the statement that `backups` options are instance-scoped with one that `backups list` and `restore --last` work on a deployment's backup history, and `--instance-id` / `--target-instance-id` on one instance
- [ ] T039 [P] Update the "Backups and restores" section of `cli/README.md`: `backups list` lists the deployment's whole history with an `application_version` column; `restore --last` chooses from that history; a deleted deployment's history is listed with `--id`
- [ ] T040 [P] Update `dev/knowledge/backend/backup-restore.md`: the `get_backups` row in the service table (keyword-only `deployment_id` / `instance_id`, exactly one) and the `backups(...)` signature in "GraphQL API → Queries"
- [ ] T041 [P] Add a **Backup history** entry to "Infrastructure entities" in `CONTEXT.md`, next to the backup entries: every backup taken of any instance of one deployment, newest first, found through the instances, not stored; listed by `backups(deploymentId:)`; survives upgrades, config edits, refreshes, environment config changes and deployment deletion; link issue #304. Add an "Avoid" line for "instance backups" when the deployment-wide list is meant
- [ ] T042 [P] Create the changelog fragment `changelog/304.fixed.md` with `uv run towncrier create -c "..." 304.fixed.md`, written from the operator's view: backups taken before an upgrade, a config edit, a refresh or an environment config change stay listed on the Backups tab, in `styrminctl backups list` and in `styrminctl backups restore --last`, with the application version each was taken at; API users can list them with `backups(deploymentId:)` (see `dev/guidelines/changelog.md`)
- [ ] T043 Run `uv run invoke format lint` and fix every finding; run `cd frontend && pnpm lint && pnpm build`
- [ ] T044 Run the full backend, SDK and CLI suites with `uv run invoke test`, and the frontend suite with `cd frontend && pnpm test`; confirm `uv run invoke validate-graphql` and that `uv run invoke generate` leaves no diff
- [ ] T045 Walk through [quickstart.md](quickstart.md) §1 and §2 and confirm every expected outcome; confirm `specs/011-deployment-backup-history/e2e-evidence.md` holds the evidence for both variants

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no dependency
- **Phase 2 (Foundational)**: after Phase 1; blocks every user story
- **Phase 3 (US1)**: after Phase 2
- **Phase 4 (US2)**: after Phase 2; touches the same CLI files as T018 and T023, so run it after US1's CLI tasks to avoid edit conflicts
- **Phase 5 (US3)**: after Phase 2; independent of US1 and US2
- **Phase 6 (US4)**: after Phase 2; T036 after T020
- **Phase 7 (Polish)**: after all stories; T037 to T042 can run in parallel

### Within Phase 2

T003 → T004, T005 → T006 → T007 → T008 → T009 → T010 → T011 → T012 → T013 → T014 → T015. T004 can run in parallel with T005.

### Within US1

- Frontend: T019 → T020 → T021 → T017
- CLI: T022 → T023 → T018
- E2E: T024 → T025 → T026 and T027 (parallel) → T028 → T029, after T020 and T015
- T016 needs only Phase 2

### Parallel Opportunities

- T004 with T005
- In US1: the frontend chain, the CLI chain, the E2E driver tasks T024 to T027 and T016 are independent of each other
- T033 (US3) and T035 (US4) can run while US1 is in progress
- T037 to T042

---

## Parallel Example: User Story 1

```text
Chain A (frontend): T019 → T020 → T021 → T017
Chain B (CLI):      T022 → T023 → T018
Chain C (E2E):      T024 → T025 → [T026 | T027] → T028
Independent:        T016
Then:               T029 (needs chains A and C)
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 and Phase 2: the deployment-scoped read path and the GraphQL argument, with the propagation test green.
2. Phase 3: the Backups tab, the CLI list and the E2E extension. Stop and validate: the bug in issue #304 is fixed for every place an operator lists backups.

### Incremental Delivery

1. US1: the bug fix as operators see it.
2. US2: `restore --last` picks from the history.
3. US3: SDK coverage of the new argument.
4. US4: deleted-deployment coverage.
5. Phase 7: documentation, changelog and the full gate. The change is not done until Phase 7 is complete (Constitution §VII).

---

## Notes

- Every task names its file. Tasks marked [P] touch different files from the tasks they run alongside.
- No Alembic revision: `backend/styrmin_backend/db/models.py` does not change.
- Do not edit `python_sdk/src/styrmin_sdk/graphql/_generated/`, `frontend/src/generated/` or `CHANGELOG.md` by hand.
- Out of scope (spec "Out of Scope"): restore version checks, a `Deployment.backups` field, pagination, database changes, the driver version in the list.
- Commit after each phase or logical group of tasks.
