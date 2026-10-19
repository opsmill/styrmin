---

description: "Tasks for 031: an in-place restore always restores into the deployment its backup was taken of"
---

# Tasks: An In-Place Restore Always Restores Into the Deployment Its Backup Was Taken Of

**Input**: Design documents from `specs/031-inplace-restore-target/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/graphql-api.md](contracts/graphql-api.md), [contracts/sdk-and-cli.md](contracts/sdk-and-cli.md), [contracts/internal-interfaces.md](contracts/internal-interfaces.md), [quickstart.md](quickstart.md)

**Tests**: Required. The spec names a test for each functional requirement (FR-001 to FR-009). The PRD agrees unit tests for the restore target resolution and for `styrminctl backups restore`, the functional GraphQL test for `createRestore` as the propagation test, and new assertions in the existing E2E node `test_backup_and_restore_lifecycle`, with no new E2E node. Constitution §V requires local PASS evidence for every E2E node this change modifies.

**Organization**: Phase 2 changes the restore service and its three callers together, because the service's signature change breaks each caller until it is updated. User Story 1 then changes the GraphQL schema and every client of `createRestore`. User Stories 2 and 3 change `styrminctl backups restore`. User Story 4 adds the checks for the environment restore and the environment clone.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US4 (spec user stories)
- Paths are relative to the repository root.

## E2E run rules (apply to every E2E task)

- Set a unique image tag for this worktree before the first session, because other worktrees build `styrmin:latest` on the same Docker daemon: `export STYRMIN_IMAGE_VER=inplace-restore-$(git rev-parse --short HEAD)`.
- Run one CI shard per pytest session, and `api-chromium` and `ui-chromium` in separate sessions.
- Run with `--pdb`. From a non-interactive shell, prefix the command with `sleep infinity |`, and stop the run by PID, never with `pkill -f`.
- Record each passing run in `specs/031-inplace-restore-target/e2e-evidence.md`: the pytest node IDs, the exact command, ISO 8601 start and end times, the vcluster name and kubeconfig path under `/tmp/pytest-of-*/pytest-*/`, and the verbatim `PASSED` lines (Constitution §V).
- A failing E2E is almost never blocked by missing infrastructure: read `backend/tests/e2e/conftest.py` before recording a blocker (AGENTS.md).

---

## Phase 1: Setup

**Purpose**: a green baseline before any change.

- [X] T001 Run `uv sync` and `cd frontend && pnpm install`, then `uv run pytest backend/tests/unit/services/backup backend/tests/unit/services/test_deployment_status_service.py backend/tests/functional/graphql/test_create_restore.py backend/tests/functional/graphql/test_environment_clone.py backend/tests/functional/graphql/test_environment_backup.py cli/tests/test_backups.py python_sdk/tests/test_backups.py -q`, and note the result as the baseline (no file change)

---

## Phase 2: Foundational — the server decides where a restore lands (blocks every story)

**Purpose**: add `resolve_restore_target`, remove `target_namespace` and `target_instance_id` from `create_restore`, and update its three callers (research R-001 to R-005).

**⚠️ CRITICAL**: The service signature change breaks the mutation, the environment restore and the clone until T005 to T007 are done. Finish the whole phase before any story.

- [X] T002 Write the unit tests for `resolve_restore_target` in `backend/tests/unit/services/backup/test_restore.py`, in a new class `TestResolveRestoreTarget`. First extend the in-place fixture `make_chain` with a keyword option that gives the deployment an active instance: build an `Instance` as `make_counterpart` does and call `deployment.set_active_instance(instance=...)`; return it so tests can compare ids (research R-013, critique E6). Cases, each asserting `target.deployment.id`, `target.namespace` and `target.instance_id`:
  - in-place, the backup belongs to the active instance → the backup's deployment, `styrmin-<deployment id>`, the active instance id;
  - in-place, the backup belongs to an earlier instance and another instance is active → the same deployment and namespace, the **active** instance id, not the backup's (ADR-063);
  - in-place, the deployment has no active instance → `instance_id is None`;
  - cross-target with `target_deployment_id=<counterpart id>` → the counterpart, `styrmin-<counterpart id>`, the counterpart's active instance id (use `make_counterpart`);
  - in-place, the backup's instance is missing, or has no `deployment_id`, or its deployment is missing → `BackupNotFoundError`;
  - cross-target, the counterpart is missing → `DeploymentNotFoundError`.
  The tests fail until T003.
- [X] T003 In `backend/styrmin_backend/services/backup/service.py`, implement the contract in `contracts/internal-interfaces.md`:
  - add the frozen dataclass `RestoreTarget(deployment: DeploymentEntity, namespace: str, instance_id: UUID | None)` and `async def resolve_restore_target(backup, uow, *, target_deployment_id=None) -> RestoreTarget`, called inside an open `uow`; compute the namespace with `get_kubernetes_reference(deployment.id)` from `styrmin_backend.agent.service.kubernetes.utils`, as `services/context.py` does; raise the same errors as the two branches of `create_restore` raise today;
  - change `create_restore` to `create_restore(backup_id, uow, name=None, timeout=DEFAULT_RESTORE_TIMEOUT, environment_restore_id=None, target_deployment_id=None)`: replace its two resolution branches by one call to `resolve_restore_target`; keep the internal and deleted-deployment refusals and both in-flight guards; call `find_in_flight_restore(uow, deployment_id=target.deployment.id, target_namespace=target.namespace)`; store `target_namespace=target.namespace` and `target_instance_id=target.instance_id` on the row; return `(restore, target.deployment.id)`; update its docstring (no namespace or instance from the caller; callers read `restore.target_namespace`);
  - reword the docstring of `find_in_flight_restore`: it no longer says that `createRestore` takes the namespace from the client; it says that a restore created by an earlier release may record another namespace, which is why two namespaces and the deployment's own backups are searched. Do not change its code (R-005).
- [X] T004 Update the existing tests in `backend/tests/unit/services/backup/test_restore.py` for the new signature:
  - drop `target_namespace=` and `target_instance_id=` from every `create_restore(...)` call;
  - in `test_create_restore_success`, also assert `restore.target_instance_id` (give the fixture an active instance);
  - where a test called `create_restore` with another namespace (`"custom-ns"`, `"other-ns"`, `f"styrmin-{uuid4()}"`) to set up a restore in flight, seed that `Restore` row directly in `make_uow(restores=[...])`, as a row from an earlier release, and keep the assertion on the guard;
  - replace `test_explicit_target_instance_id_wins_over_the_active_instance` (an explicit instance is no longer accepted) with a test that the cross-target row records the counterpart's active instance, unless an existing test already asserts it;
  - run `uv run pytest backend/tests/unit/services/backup/test_restore.py -q`: T002 and the updated tests pass.
- [X] T005 [P] In `backend/styrmin_backend/services/backup/environment.py`, `restore_environment_backup`: remove the call to `resolve_backup_target` and the fallback to `f"{_NAMESPACE_PREFIX}{snapshot.deployment_id}"`; call `create_restore(backup_id=constituent.backup_id, uow=constituent_uow, environment_restore_id=environment_restore_id)`; set `_PendingRestoreDispatch.target_namespace=restore.target_namespace`. Remove `_NAMESPACE_PREFIX` and its comment if nothing else in the module uses it; remove the `resolve_backup_target` import if it becomes unused (R-004)
- [X] T006 [P] In `backend/styrmin_backend/workflows/templates/clone.py`, `_dispatch_cross_target_restore`: remove the local `target_namespace`; call `create_restore(backup_id=constituent.backup_id, uow=uow, target_deployment_id=counterpart_deployment_id)`; pass `restore.target_namespace` as `"target_namespace"` in the `EXECUTE_RESTORE` parameters; update the docstring (the namespace and the instance come from `create_restore`). Keep `_NAMESPACE_PREFIX`, which `release_reference` still uses (R-004)
- [X] T007 In `backend/styrmin_backend/api/schema/mutation.py`, `Mutation.create_restore`: remove the `target_namespace` and `target_instance_id` arguments; call `create_restore_service(backup_id=backup_id, uow=uow)`; pass `restore.target_namespace` as `"target_namespace"` in the `EXECUTE_RESTORE` parameters; update the docstring to say that Styrmin restores the backup into the deployment it was taken of (R-006)
- [X] T008 [P] In `backend/styrmin_backend/repository/deployment.py`, reword the docstring of `delete_all_for_environment` (the bullet about `restore.target_instance_id`) and the comment above the `sa_update(RestoreModel)` call: every restore created after #532 records the instance it restored into, in-place or cross-target; a cross-target restore's row survives because its backup belongs to another environment. No code change (research R-014, critique E1)
- [X] T009 Update the tests that read `target_namespace` from the arguments of a mocked `create_restore`, so they assert on the stored row or on the dispatched `EXECUTE_RESTORE` parameters instead:
  - `backend/tests/unit/services/backup/test_environment_clone_service.py` (the fake `_create_restore(**kwargs)` that builds a row from `kwargs["target_namespace"]`, and the assertion `restore_call["target_namespace"] == f"styrmin-{counterpart_id}"`);
  - `backend/tests/functional/graphql/test_environment_clone.py` (the fake `_create_restore(**kwargs)`, the assertions on `call["target_namespace"]`, and the `(call["target_deployment_id"], call["target_namespace"])` pair);
  - `backend/tests/unit/services/backup/test_environment_backup.py` (check the three `_create_restore(*args, **kwargs)` wrappers still pass through);
  - reword the docstring of `test_in_flight_restore_into_other_namespace_keeps_restoring` in `backend/tests/unit/services/test_deployment_status_service.py`: such a row comes from an earlier release; `createRestore` no longer accepts a namespace.
- [X] T010 Run `uv run pytest backend/tests/unit/services backend/tests/unit/repository/backup backend/tests/unit/workflows backend/tests/functional/graphql/test_environment_clone.py backend/tests/functional/graphql/test_environment_backup.py -q` and `uv run invoke lint`; fix failures caused by T003 to T009

**Checkpoint**: The server records `styrmin-<deployment id>` and the active instance for every restore. `createRestore` still has no tests for the new behaviour, and the clients still send the removed arguments.

---

## Phase 3: User Story 1 - Restore a backup into its own deployment, from any client (Priority: P1) 🎯 MVP

**Goal**: `createRestore` takes only `backupId`; the SDK, the web app and the E2E drivers stop sending a namespace; every in-place restore records its deployment's namespace and active instance (FR-001 to FR-005).

**Independent Test**: `uv run pytest backend/tests/functional/graphql/test_create_restore.py -q` passes the propagation and refusal tests; the lifecycle E2E records `styrmin-<deployment id>` and the active instance.

### Tests for User Story 1

- [X] T011 [US1] In `backend/tests/functional/graphql/operations/create_restore.graphql`, drop `$targetNamespace` and its argument, and add `targetNamespace` and `targetInstanceId` to the selection set. In `backend/tests/functional/graphql/test_create_restore.py`:
  - drop `"targetNamespace"` from the variables of the two existing tests;
  - add the propagation test (research R-008): seed a deployment with two instances via `seed_application_instance`, set `deployment.active_application_instance_id` to the second, seed a `COMPLETED` backup of the first, patch `styrmin_backend.api.schema.mutation.get_manager`, call `createRestore` with only `backupId`; assert through `_read_back` that the row records `f"styrmin-{deployment.id}"` and the second instance's id, that the response returns the same two values, and that `run_action` received `parameters["target_namespace"] == f"styrmin-{deployment.id}"`;
  - add the refusal test, parametrized over `("targetNamespace", "styrmin-<uuid4>")` and `("targetInstanceId", "<uuid4>")` (research R-007): load the operation with `load_query("create_restore")`, parse it with `graphql.parse`, append a `graphql.language.ArgumentNode` with a `StringValueNode` to the `createRestore` field, print it with `graphql.print_ast`, post it with `client.post("/graphql", ...)`; assert one error whose message contains `Unknown argument '<name>'`, no `Restore` row for the backup, and `run_action.assert_not_called()`. Do not add a `.graphql` file that sends the removed argument: `validate-graphql` would fail on it.

### Implementation for User Story 1

- [X] T012 [US1] Regenerate the schema: `uv run styrmin export graphql-schema schema.graphql`; check that `schema.graphql` shows `createRestore(backupId: UUID!): Restore @requiresRole` and that the `Restore` type is unchanged (FR-002, FR-005)
- [X] T013 [P] [US1] In `python_sdk/src/styrmin_sdk/graphql/create_restore.graphql`, drop `$targetNamespace` and `$targetInstanceId` and their arguments; keep the selection set
- [X] T014 [P] [US1] In `frontend/src/graphql/create_restore.graphql`, drop `$targetNamespace` and `$targetInstanceId` and their arguments; keep the selection set
- [X] T015 [US1] Run `uv run invoke validate-graphql` (every `.graphql` file passes), then `uv run invoke generate`; check that `python_sdk/src/styrmin_sdk/graphql/_generated/create_restore.py`, `python_sdk/src/styrmin_sdk/graphql/_generated/client.py` and `frontend/src/generated/graphql.ts` changed, and that `CreateRestoreMutationVariables` holds only `backupId`. Do not edit generated files by hand
- [X] T016 [US1] In `python_sdk/src/styrmin_sdk/resources/backups.py`, change `create_restore` to `create_restore(self, backup_id: str | UUID)` and send `{"backupId": str(backup_id)}` only (FR-003). In `python_sdk/tests/test_backups.py`, update `test_create_restore` to call `create_restore(backup_id=...)` and assert that `mock_transport.execute` received exactly `{"backupId": ...}` as variables; add a test that `create_restore(backup_id=..., target_namespace="x")` raises `TypeError`; run `uv run pytest python_sdk/tests -q`
- [X] T017 [US1] In `frontend/src/pages/deployments/DeploymentDetailPage.tsx`, `handleRestore`: call `createRestoreMutation.mutateAsync({ backupId: selectedBackupId })`. Keep `targetNamespace` for the read-only "Target Namespace" field of the Restore dialog (no visible change, R-011). Run `cd frontend && pnpm exec tsc -b && pnpm lint && pnpm test`
- [X] T018 [US1] Run `uv run pytest backend/tests/functional/graphql/test_create_restore.py -q`: the propagation and refusal tests of T011 pass
- [X] T019 [US1] Update the E2E drivers (contract in `contracts/internal-interfaces.md`):
  - `backend/tests/e2e/drivers/protocol.py`: `ScenarioDriver.create_restore(self, *, backup_id: str) -> RestoreRef`;
  - `backend/tests/e2e/drivers/api_driver.py`: `ApiScenarioDriver.create_restore` calls `self._client.backups.create_restore(backup_id=backup_id)`;
  - `backend/tests/e2e/drivers/ui_driver.py`: `UiScenarioDriver.create_restore(*, backup_id)` passes `expected_namespace=f"styrmin-{self._deployment_id}"` to the page object after `_ensure_deployment_detail()`;
  - `backend/tests/e2e/pages/deployment_detail.py`: `DeploymentDetailPage.create_restore(*, backup_id, expected_namespace)` keeps its check of the dialog's read-only field against `expected_namespace`; update the docstring.
- [X] T020 [US1] Drop `target_namespace=` from every other E2E call: `backend/tests/e2e/test_backup_restore.py` (`test_backup_and_restore_lifecycle`, `test_restore_lifecycle_transitions`, `test_restore_failure_marks_failed_not_indefinite`, `test_restore_of_removed_velero_backup_fails_velero_step`), `backend/tests/e2e/test_backup_restore_databases.py` (`test_mariadb_mongodb_backup_and_restore_lifecycle`) and `backend/tests/e2e/test_infrahub_backup_restore.py` (both tests). Keep the local `namespace` variables that the tests still use for `kubectl` and port-forwards
- [X] T021 [US1] In `backend/tests/e2e/test_backup_restore.py`, `test_backup_and_restore_lifecycle`, after the restore completes and `restored_deployment` is read: read the restore with `client.backups.get_restore(created_restore.id)` and assert `target_namespace == f"styrmin-{deployment_id}"` and `str(target_instance_id) == str(restored_deployment.application_instance.id)`, the 0.2.0 active instance, although the backup belongs to the 0.1.0 instance (FR-001, FR-004, ADR-063). Add #532 to the test's docstring

**Checkpoint**: User Story 1 is complete except for its E2E runs (T038, T039).

---

## Phase 4: User Story 2 - styrminctl refuses a backup id combined with a target deployment (Priority: P2)

**Goal**: `styrminctl backups restore` drops `--target-namespace` and refuses a backup id with a target option before it calls the server (FR-006, FR-007).

**Independent Test**: `uv run pytest cli/tests/test_backups.py -q` passes the refusal tests, which assert that the SDK client is never created.

### Tests for User Story 2

- [X] T022 [US2] In `cli/tests/test_backups.py`:
  - add a test parametrized over `--target-deployment demo`, `--target-deployment-id <DEPLOYMENT_UUID>` and `--target-instance-id <INSTANCE_UUID>`: `app(["backups", "restore", BACKUP_UUID, *option])` exits with code 1, the output names `--last` and says to run the command without the option, the client was never entered (`mock_client.__aenter__.assert_not_awaited()`, which proves no server call, including the target lookup) and `mock_client.backups.create_restore.assert_not_called()`;
  - add a test that `app(["backups", "restore", BACKUP_UUID, "--target-namespace", NS])` is rejected as an unknown option and the client is never entered;
  - rewrite `test_backups_restore_conflicting_targets_rejected` to pass `--last` instead of `BACKUP_UUID`, so it keeps testing the "only one of" rule; with a backup id, the new refusal now comes first (contract in `contracts/sdk-and-cli.md`);
  - add a test that `app(["backups", "restore", BACKUP_UUID])` calls `create_restore(backup_id=BACKUP_UUID)` and nothing else;
  - remove `test_backups_restore_backup_into_explicit_namespace`, `test_backups_restore_into_deployment_derives_namespace`, `test_backups_restore_into_deployment_by_name` and `test_backups_restore_to_instance_requires_namespace`, which test the removed behaviour;
  - drop `--target-namespace` from the argument lists of `test_backups_restore_last_requires_a_target`, `test_backups_restore_last_and_backup_id_is_rejected` (including its parametrized cases) and `test_backups_restore_without_backup_id_or_last_is_rejected`, and keep what each test checks.
  The new tests fail until T023.

### Implementation for User Story 2

- [X] T023 [US2] In `cli/src/styrminctl/commands/backups.py` (contract in `contracts/sdk-and-cli.md`):
  - remove the `target_namespace` parameter of `restore`;
  - in `restore`, after the existing `--last`/backup id check and before `client.get_client()`, raise `ValueError` when `backup_id is not None` and any of `target_deployment`, `target_deployment_id`, `target_instance_id` is set. Message: the three options work only with `--last`; a backup is restored into the deployment it was taken of; run the command again without the option (FR-007);
  - change `_prepare_restore` to take no `target_namespace`, resolve the target only for `--last`, and return only the backup id; remove the namespace derivation and the "`--target-namespace` is required" error;
  - call `sdk.backups.create_restore(backup_id=backup_id)`;
  - rewrite the docstring of `restore` and the help text of `--last` so that the target options choose whose backup history the newest backup comes from, and a backup id alone is restored into the deployment it was taken of.
- [X] T024 [P] [US2] In `cli/src/styrminctl/types.py`, reword the help texts of `TargetDeploymentName`, `TargetDeploymentId` and `OptionalInstanceId` (used only by `backups restore`): "With --last: the deployment (or instance) whose newest completed backup is restored". Run `uv run pytest cli/tests/test_backups.py -q` and `uv run styrminctl backups restore --help`

**Checkpoint**: The CLI refuses the misleading form and no longer offers a namespace.

---

## Phase 5: User Story 3 - `--last` keeps choosing the newest backup of the named deployment (Priority: P2)

**Goal**: `--last` with a target option keeps working, now without a namespace (FR-008).

**Independent Test**: the `--last` tests in `cli/tests/test_backups.py` pass.

- [X] T025 [US3] In `cli/tests/test_backups.py`, update the `--last` tests (`test_backups_restore_last_by_deployment`, `test_backups_restore_last_by_instance_id`, `test_backups_restore_last_no_completed_backups_exits_nonzero` (drop `--target-namespace` from its `by-instance-id` case), `test_backups_restore_last_skips_expired_backups`, `test_backups_restore_last_of_the_current_instance_does_not_ask`, `test_backups_restore_last_of_an_earlier_instance_needs_yes_without_a_terminal`, `test_backups_restore_last_of_an_earlier_instance_asks_in_a_terminal`, `test_backups_restore_last_into_a_deleted_deployment_is_refused`, and any other that asserts `create_restore` arguments) to assert `create_restore` was called with `backup_id=<chosen id>` only. `test_backups_restore_last_by_instance_id` runs without `--target-namespace` and succeeds. Run `uv run pytest cli/tests -q`

**Checkpoint**: Scripts that use `--last` keep working (User Story 3, scenarios 1 to 3).

---

## Phase 6: User Story 4 - An environment restore and an environment clone follow the same rule (Priority: P3)

**Goal**: each constituent restore of an environment restore, and each restore of a clone, records its deployment's namespace and active instance (FR-001, FR-004, FR-009).

**Independent Test**: the environment restore and clone suites pass with the new assertions.

- [ ] T026 [P] [US4] In `backend/tests/unit/services/backup/test_environment_backup.py`, extend the environment restore test that asserts the constituent rows' `target_namespace` (`{restore.target_namespace for restore in uow.restores.models} == {...}`) so that each row's `target_instance_id` equals its deployment's active instance id; give the fixture's deployments active instances if they have none (research R-013, critique E5)
- [ ] T027 [P] [US4] In `backend/tests/functional/graphql/test_environment_clone.py`, extend the test that asserts `restore.target_namespace == f"styrmin-{counterpart.id}"` to assert that `restore.target_instance_id` is the counterpart's active instance id, unless an existing assertion already covers it; run `uv run pytest backend/tests/functional/graphql/test_environment_clone.py backend/tests/unit/services/backup -q`

**Checkpoint**: Every restore path records the target the same way.

---

## Phase 7: Documentation (Constitution §VII)

**Purpose**: no page says a user can restore into another deployment's namespace or pass a namespace (FR-010, FR-011, SC-003; research R-014).

- [ ] T028 [P] Update `cli/README.md`, "Backups and restores": the opening sentence says `restore` takes a backup id, or `--last` with `--target-deployment` or `--target-deployment-id`; the example `backups restore <backup-id> --target-deployment my-app` and its comment become `backups restore <backup-id>` ("restores the backup into the deployment it was taken of"); replace the paragraph about `--target-namespace` with a raw `--target-instance-id` by the rule that the three target options work only with `--last` and that the command refuses them with a backup id
- [ ] T029 [P] Update `docs/docs/reference/styrminctl.md` (the `backups` and `env-backups` section, around "`backups restore --last` takes it with `--target-deployment`"): `backups restore` takes a backup id alone and restores it into the deployment it was taken of; `--target-deployment`, `--target-deployment-id` and `--target-instance-id` work only with `--last`; `--target-namespace` is gone. Check the rest of the page for the restore options
- [ ] T030 [P] Update `docs/docs/concepts-and-architecture/backups-and-restores.md`: step 1 of "What happens when you restore" becomes "You pick a backup. Styrmin restores it into the deployment it was taken of, in that deployment's namespace." (remove "and a target deployment (the same one or a different one)"); in the paragraph on deleted deployments ("into the deleted deployment or into another deployment"), say that only an environment clone restores a backup into another deployment. Check the page for other mentions of a target namespace
- [ ] T031 [P] Update `dev/knowledge/backend/api.md`: the `createRestore` row becomes `backupId` → `Restore`, with a note that Styrmin derives the namespace and the target instance from the backup's deployment
- [ ] T032 [P] Update `dev/knowledge/backend/backup-restore.md`: the `create_restore(backup_id, target_namespace, uow, ...)` row of the service table (signature, `resolve_restore_target`, the recorded namespace and instance); the in-flight guard paragraph ("`createRestore` accepts any `target_namespace`" becomes "a restore created by an earlier release may record another namespace"); the GraphQL listing `createRestore(backupId: UUID!, targetNamespace: String!, targetInstanceId: UUID): Restore!`; and any diagram line that passes a namespace to `create_restore`
- [ ] T033 [P] Check the "In-place restore" entry in `CONTEXT.md` (committed with the spec) against the implementation; adjust it only if the implementation differs
- [ ] T034 [P] Create the changelog fragments with `uv run towncrier create`, one paragraph each, single line, past tense, from the user's view (dev/guidelines/changelog.md):
  - `changelog/532.removed.md`: removed `targetNamespace` and `targetInstanceId` from `createRestore`, the matching parameters of `create_restore()` in the Python SDK, and `--target-namespace` from `styrminctl backups restore`; Styrmin restores a backup into the deployment it was taken of; `styrminctl backups restore` now refuses a backup id combined with `--target-deployment`, `--target-deployment-id` or `--target-instance-id`, which work only with `--last`; upgrade `styrminctl`, the SDK and open web pages together with the server, because an older client sends `targetNamespace` on every restore and an older server requires it; Styrmin offers no way to restore a backup into another deployment until deployment clone ships (FR-011, critique X1);
  - `changelog/532.fixed.md`: fixed an in-place restore that deleted and restored into the namespace the caller named, which could be the namespace of another deployment, instead of the namespace of the deployment the backup was taken of.

---

## Phase 8: Polish & verification

- [ ] T035 Run `uv run invoke format lint`, `uv run invoke validate-graphql`, `uv run pytest backend/tests/unit backend/tests/functional cli/tests python_sdk/tests -q`, and `cd frontend && pnpm lint && pnpm test`; fix any failure
- [ ] T036 Run `git grep -n -E "target-namespace|targetNamespace: \\$|target_namespace=" -- docs cli/README.md dev/knowledge python_sdk/src cli/src frontend/src/graphql frontend/src/pages` and confirm that no hit tells a user or a caller to pass a namespace to a restore (SC-003); `Restore.targetNamespace` reads and environment restore projections are expected hits
- [ ] T037 Walk through `specs/031-inplace-restore-target/quickstart.md` steps 1, 2 and 5, and note any result that differs
- [ ] T038 E2E, `api-chromium`, one session for `shard_backup` (E2E run rules): `sleep infinity | uv run pytest backend/tests/e2e -m shard_backup -k "api-chromium" -v -s --pdb`. It covers the modified nodes `test_backup_and_restore_lifecycle`, `test_restore_lifecycle_transitions`, `test_restore_failure_marks_failed_not_indefinite`, `test_restore_of_removed_velero_backup_fails_velero_step` and `test_mariadb_mongodb_backup_and_restore_lifecycle`. On a failure, debug on the paused session with `kubectl` (`.agents/skills/e2e-troubleshoot/SKILL.md`). Record the pass in `specs/031-inplace-restore-target/e2e-evidence.md`
- [ ] T039 E2E, `ui-chromium`, a separate session: `sleep infinity | uv run pytest backend/tests/e2e -m shard_backup -k "ui-chromium" -v -s --pdb`. It covers the dual-entrypoint nodes `test_backup_and_restore_lifecycle`, `test_restore_lifecycle_transitions` and `test_mariadb_mongodb_backup_and_restore_lifecycle`. Record the pass in `e2e-evidence.md`
- [ ] T040 E2E, `shard_infrahub`: run `test_infrahub_enterprise_backup_and_restore_lifecycle` in a separate session (`api_only`). `test_infrahub_backup_and_restore_lifecycle` is skipped and needs no run. If the enterprise fixture cannot run on this host, record the exact reason in `e2e-evidence.md` and list the node as not run in the PR notes; do not mark it passed
- [ ] T041 Write `specs/031-inplace-restore-target/pr-notes.md`: link `e2e-evidence.md`; state the breaking changes (the two GraphQL arguments, the SDK parameters, `--target-namespace`, the refused CLI form, the client and server version coupling); ask the maintainer to confirm the autonomous answers in the spec's Clarifications (#531 on `develop`, `--environment` with a backup id, a deployment with no active instance) and the open question of a `security` changelog fragment (critique E3); list the critique follow-up not applied (P2: print the target namespace in the CLI success line)

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after Phase 1. Blocks every story.
- **US1 (Phase 3)**: after Phase 2. T011 → T012 → (T013, T014) → T015 → (T016, T017) → T018; T019 → T020 → T021 after T015.
- **US2 (Phase 4)**: after T015, because the CLI calls the regenerated SDK. T022 → T023; T024 in parallel with T023.
- **US3 (Phase 5)**: after T023.
- **US4 (Phase 6)**: after Phase 2; independent of US1 to US3.
- **Documentation (Phase 7)**: after the behaviour it describes (T028 and T029 after T023; T030 to T032 after T007).
- **Polish (Phase 8)**: after every other phase. T038, T039 and T040 each need a full vcluster; run them one after the other on one host.

### Within Phase 2

- T002 → T003 → T004.
- T005, T006 and T008 in parallel after T003; T007 after T003.
- T009 after T005 to T007; T010 last.

### Parallel opportunities

- T005, T006, T008 (three source files).
- T013, T014 (two operation files).
- T016, T017 after T015 (SDK and frontend).
- T026, T027 (two test files).
- T028 to T034 (seven documentation files).

## Parallel Example: after Phase 2

```text
Agent A: T011 → T012 → T013 → T015 → T016 → T018 (GraphQL, SDK)
Agent B: T014 (after T012) → T017 after T015 (frontend)
Agent C: T026, T027 (environment restore and clone assertions)
```

## Implementation Strategy

1. Phase 1 baseline.
2. Phase 2: the server takes the namespace and the instance from the backup's deployment. From here on, no code path restores into a namespace the caller chose.
3. Phase 3 (MVP): remove the arguments from the API and every client, and prove it with the propagation and refusal tests.
4. Phases 4 and 5: the CLI refuses the misleading form and keeps `--last`.
5. Phase 6: checks for the environment restore and the clone.
6. Phases 7 and 8: documentation, changelog, lint, and the E2E runs with recorded evidence. All phases ship in one change: the schema change, the clients and the CLI must reach users together (spec, Edge Cases).
