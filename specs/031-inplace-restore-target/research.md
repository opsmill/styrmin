# Research: An In-Place Restore Always Restores Into the Deployment Its Backup Was Taken Of

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-19

The spec leaves no `NEEDS CLARIFICATION` marker. The decisions below cover where the rule lives, how each caller changes, how the removed arguments are tested, and the third-party dependencies involved. Code references are to `develop` at `7f0455be`.

## R-001: One service function decides where a restore lands

**Decision**: Add `resolve_restore_target(backup, uow, *, target_deployment_id=None) -> RestoreTarget` to [`services/backup/service.py`](../../backend/styrmin_backend/services/backup/service.py). `RestoreTarget` is a frozen dataclass with three fields:

- `deployment`: the `DeploymentEntity` that receives the data.
- `namespace`: `get_kubernetes_reference(deployment.id)`, that is `styrmin-<deployment id>`.
- `instance_id`: `deployment.active_instance.id`, or `None` when the deployment has no active instance.

For an in-place restore (`target_deployment_id is None`), the deployment is the one that the backup's instance belongs to. For a cross-target restore, it is the counterpart named by `target_deployment_id`. The function raises the errors that `create_restore` raises today: `BackupNotFoundError` when the backup's instance or deployment cannot be found, and `DeploymentNotFoundError` when the counterpart cannot be found. `create_restore` calls it inside its transaction, in place of the two branches it has today.

**Rationale**:

- The PRD asks for "the one place that decides where a restore lands", which receives the backup and, for a cross-target restore, the counterpart, and returns the deployment, its namespace and its active instance.
- `get_kubernetes_reference` is the helper that the service layer already uses to name a deployment's namespace ([`services/context.py`](../../backend/styrmin_backend/services/context.py), [`services/deployment.py`](../../backend/styrmin_backend/services/deployment.py)). Using it keeps one rule for every namespace that Styrmin derives from a deployment id ([ADR-073](../../dev/adr/0073-kubernetes-objects-named-and-found-by-record-id.md)).
- The cross-target branch already defaults the target instance to the counterpart's active instance ([`service.py`](../../backend/styrmin_backend/services/backup/service.py), `create_restore`). The function applies the same rule to an in-place restore, which is FR-004.
- The refusals for an internal or a deleted deployment stay in `create_restore`. They decide whether a restore may start, not where it lands, and keeping them out of the function keeps it testable on its own.

**Alternatives considered**:

- Compute the namespace in each caller (mutation, environment restore, clone) and keep a `target_namespace` parameter on `create_restore`. Rejected: this is the shape that allowed the defect, and the PRD asks callers to stop passing a namespace.
- Read `active_application_instance_id` from the database row instead of `DeploymentEntity.active_instance`. Rejected: `create_restore` already loads the entity through `uow.deployments.find`, and the cross-target branch reads `active_instance` today.

## R-002: `create_restore` loses `target_namespace` and `target_instance_id`; callers read the row

**Decision**: The new signature is `create_restore(backup_id, uow, name=None, timeout=DEFAULT_RESTORE_TIMEOUT, environment_restore_id=None, target_deployment_id=None) -> tuple[Restore, UUID]`. The `Restore` row stores `target.namespace` and `target.instance_id`. Each caller reads `restore.target_namespace` from the returned row when it dispatches `execute_restore`.

**Rationale**: The returned row already carries the namespace, so no caller needs a third return value, and no caller can dispatch a flow to a namespace that differs from the one recorded.

**Alternatives considered**: Return a `(Restore, RestoreTarget)` pair. Rejected: it changes every caller's unpacking for a value the row already holds.

## R-003: The restore flow keeps its `target_namespace` parameter

**Decision**: `execute_restore_workflow(restore_id, backup_id, deployment_id, target_namespace, source_deployment_id=None)` keeps its signature. Its callers pass `restore.target_namespace`.

**Rationale**: The flow is internal, and after this change its `target_namespace` always comes from the service. Changing the flow's parameters would change the Prefect deployment's parameter contract for no user-visible gain, and a flow run scheduled before the upgrade would still carry the old parameter.

**Alternatives considered**: Drop the parameter and let the flow compute `styrmin-<deployment_id>`. Rejected for the reason above. The PRD lists no change to the flow.

## R-004: The environment restore and the clone stop building a namespace

**Decision**:

- In `restore_environment_backup` ([`environment.py`](../../backend/styrmin_backend/services/backup/environment.py)), remove the call to `resolve_backup_target` and the fallback to `styrmin-<snapshot.deployment_id>`. `_PendingRestoreDispatch.target_namespace` is set from `restore.target_namespace`.
- In `_dispatch_cross_target_restore` ([`clone.py`](../../backend/styrmin_backend/workflows/templates/clone.py)), remove `target_namespace = f"{_NAMESPACE_PREFIX}{counterpart_deployment_id}"`. The dispatch reads `restore.target_namespace`.
- `_NAMESPACE_PREFIX` stays in `environment.py` and `clone.py` where other code still uses it; it is removed where it has no remaining use.

**Rationale**: FR-009 asks that the clone's namespace be computed by the same rule as an in-place restore. Both paths already produce `styrmin-<deployment id>`, so the recorded values do not change.

The environment restore's fallback existed because `resolve_backup_target` returns an empty namespace when the instance row cannot be walked. With the new function, a missing instance raises `BackupNotFoundError`, which the fan-out already records as a `BACKUP_DELETED` skip. Before this change, `create_restore` raised the same error for the same case after the fallback, so the outcome is unchanged.

**Alternatives considered**: Keep `resolve_backup_target` in the environment restore for its namespace. Rejected: it would leave a second place that derives a restore's namespace.

## R-005: The in-flight restore guard does not change

**Decision**: `find_in_flight_restore(uow, deployment_id, target_namespace)` and `has_in_flight_restore` keep their code. `create_restore` calls the guard with `target.namespace`. The docstring of `find_in_flight_restore` is reworded: it no longer says that `createRestore` takes the namespace from the client, and says instead that a restore created by an earlier release may record another namespace.

**Rationale**: The PRD keeps the guard unchanged and puts its simplification out of scope. Rows from earlier releases can still name another namespace, and the guard must keep finding them while they are pending or in progress (spec, Edge Cases).

**Alternatives considered**: Simplify the guard to the canonical namespace only. Rejected: out of scope in the PRD.

## R-006: `createRestore` loses both arguments; GraphQL validation refuses them

**Decision**: The resolver becomes `create_restore(self, backup_id: UUID, info) -> RestoreType | None` in [`mutation.py`](../../backend/styrmin_backend/api/schema/mutation.py). It passes `restore.target_namespace` in the `EXECUTE_RESTORE` parameters. `schema.graphql` is regenerated. No deprecation period and no new error code.

**Third-party evaluation (Strawberry GraphQL 0.312.2, graphql-core 3.2.8)**: A removed argument needs no extension. graphql-core's `KnownArgumentNamesRule`, part of the standard validation rules that Strawberry runs, refuses a request that sends an unknown argument, with the message `Unknown argument 'targetNamespace' on field 'Mutation.createRestore'.`, before the resolver runs. No extension mechanism or upstream change is needed.

**Alternatives considered**:

- Keep the arguments with `deprecation_reason` and ignore them. Rejected by the PRD: a client that sends another namespace would believe it was honoured. #472 removed input fields without a deprecation period before version 1.0.
- Keep the arguments and raise a typed `ServiceError` when they differ from the computed values. Rejected by the PRD ("no new server error codes").

## R-007: The functional test sends the removed arguments without an operation file that fails validation

**Decision**: In [`test_create_restore.py`](../../backend/tests/functional/graphql/test_create_restore.py), the refusal test loads the valid `create_restore.graphql` operation, parses it with graphql-core, adds one argument node (`targetNamespace: "styrmin-<other id>"` or `targetInstanceId: "<uuid>"`) to the `createRestore` field, prints the document with `print_ast`, and posts it. It asserts the GraphQL validation error, that no `Restore` row exists for the backup, and that `run_action` was not called. The test is parametrized over the two arguments.

**Rationale**:

- AGENTS.md forbids inline GraphQL strings in Python.
- `uv run invoke validate-graphql` validates every `.graphql` file in the repository except `specs/`, `.venv` and `node_modules` ([`tasks/graphql_validate.py`](../../tasks/graphql_validate.py)). An operation file that sends a removed argument would fail that check in CI.
- Deriving the request from the valid operation sends exactly the request a client from before the change sends, differing only by the removed argument.

**Alternatives considered**:

- An operation file with the removed argument in a directory that `validate-graphql` skips. Rejected: it needs a new exclusion in the task, and a file that is invalid on purpose is easy to "fix" by mistake.
- Only an introspection test that pins the argument list, as [`test_update_deployment_input_introspection.py`](../../backend/tests/functional/graphql/test_update_deployment_input_introspection.py) does for #472. Rejected as the only check: FR-002 asks for a test that sends each argument.

## R-008: The functional test is the propagation test

**Decision**: `test_create_restore.py` gains a propagation test: seed a deployment with two instances, make the second one active, take a completed backup of the first one, call `createRestore` with only `backupId`, and assert through a fresh session that the `Restore` row records `styrmin-<deployment id>` and the second instance's id, that the response returns the same values, and that `EXECUTE_RESTORE` was dispatched with that namespace. The operation file [`operations/create_restore.graphql`](../../backend/tests/functional/graphql/operations/create_restore.graphql) drops `$targetNamespace` and selects `targetNamespace` and `targetInstanceId`. The two existing tests in the file drop the variable.

**Rationale**: Constitution §V requires a propagation test for every changed mutation. Using a backup of an earlier instance also covers the ADR-063 edge case: the row records the active instance, not the backup's instance.

## R-009: The Python SDK loses both parameters

**Decision**: `BackupsResource.create_restore(self, backup_id: str | UUID)` in [`resources/backups.py`](../../python_sdk/src/styrmin_sdk/resources/backups.py). The operation file [`create_restore.graphql`](../../python_sdk/src/styrmin_sdk/graphql/create_restore.graphql) takes only `$backupId`. `uv run invoke generate` regenerates `_generated/create_restore.py` and `_generated/client.py`.

**Third-party evaluation (ariadne-codegen)**: The generated client follows the operation file; no gap.

**Alternatives considered**: Keep `target_namespace` as an ignored keyword. Rejected by FR-003.

## R-010: `styrminctl backups restore` refuses a backup id with a target option, in the command body

**Decision**: In [`backups.py`](../../cli/src/styrminctl/commands/backups.py):

- Remove the `--target-namespace` parameter.
- At the top of `restore`, next to the existing `--last`/backup id check and before `client.get_client()`, raise `ValueError` when a backup id is given together with `--target-deployment`, `--target-deployment-id` or `--target-instance-id`. The message names the three options, says that they work only with `--last`, and says that a backup is restored into the deployment it was taken of.
- `_prepare_restore` returns only the backup id. Target resolution runs only for `--last`. The namespace derivation and the error "`--target-namespace` is required when restoring to a raw `--target-instance-id`" are removed.
- The call becomes `sdk.backups.create_restore(backup_id=backup_id)`.
- The command's docstring and the `--last` help text are updated.
- `--environment` keeps its meaning: it tells `--target-deployment` which environment a name belongs to (spec, autonomous clarification).

**Third-party evaluation (Cyclopts 4.10.1)**: Cyclopts supports this check without an extension: a `Group` with the `mutually_exclusive` validator or a custom group validator could express "a backup id excludes the target options". It is not used because:

- the command's other combination rules (`--last` with a backup id, more than one target option, `--last` without a target) raise `ValueError` inside `styrmin_error_handler()`, which prints the project's error format, and the existing tests assert on that output;
- the message must say that the options work only with `--last`, which needs a custom validator anyway;
- no other command in `styrminctl` uses Cyclopts groups, so a group here would be a second pattern for the same kind of rule.

**Alternatives considered**: Silently ignore the target options when a backup id is given. Rejected by FR-007.

## R-011: The Backups tab stops sending the namespace and keeps showing it

**Decision**: [`frontend/src/graphql/create_restore.graphql`](../../frontend/src/graphql/create_restore.graphql) takes only `$backupId`. `pnpm codegen` (run by `uv run invoke generate`) regenerates `src/generated/graphql.ts`. [`DeploymentDetailPage.tsx`](../../frontend/src/pages/deployments/DeploymentDetailPage.tsx) calls `mutateAsync({ backupId })` and keeps computing `styrmin-<deployment id>` for the read-only "Target Namespace" field of the Restore dialog.

**Third-party evaluation (graphql-codegen)**: The generated `CreateRestoreMutationVariables` follows the operation file. A page that still passes `targetNamespace` fails the TypeScript check, so the compiler finds any missed caller. No gap.

**Rationale**: The PRD says the Backups tab has no visible change.

**Alternatives considered**: Remove the read-only field. Rejected: a visible change the PRD does not ask for.

## R-012: E2E coverage extends `test_backup_and_restore_lifecycle`; the drivers lose the namespace

**Decision**:

- `ScenarioDriver.create_restore(*, backup_id)` in [`drivers/protocol.py`](../../backend/tests/e2e/drivers/protocol.py), [`api_driver.py`](../../backend/tests/e2e/drivers/api_driver.py) and [`ui_driver.py`](../../backend/tests/e2e/drivers/ui_driver.py).
- The UI driver passes `expected_namespace=f"styrmin-{self._deployment_id}"` to the page object [`pages/deployment_detail.py`](../../backend/tests/e2e/pages/deployment_detail.py), which keeps checking the dialog's read-only field.
- [`test_backup_restore.py`](../../backend/tests/e2e/test_backup_restore.py), `test_backup_and_restore_lifecycle` (`shard_backup`, both variants): after the restore completes, read it with `client.backups.get_restore` and assert `target_namespace == f"styrmin-{deployment_id}"` and `target_instance_id` equals the deployment's active instance id. The backup restored in that test belongs to the 0.1.0 instance while the active instance is 0.2.0, so the assertion also covers ADR-063.
- The other E2E calls drop the argument: [`test_backup_restore.py`](../../backend/tests/e2e/test_backup_restore.py) (three more calls), [`test_backup_restore_databases.py`](../../backend/tests/e2e/test_backup_restore_databases.py) and [`test_infrahub_backup_restore.py`](../../backend/tests/e2e/test_infrahub_backup_restore.py) (two calls).

**Rationale**: The maintainer agreed to extend an existing E2E node instead of adding one (PRD; AGENTS.md "Ask First"; Constitution §V "Reuse before you boot"). The lifecycle test already runs an in-place restore through the API and the web app.

**Run requirement**: Constitution §V requires local PASS evidence for the modified E2E node in both variants (`[api-chromium]` and `[ui-chromium]`). Set `STYRMIN_IMAGE_VER` to a tag unique to this worktree before the run, because other worktrees build `styrmin:latest` on the same Docker daemon.

## R-013: Unit tests

**Decision**:

- [`test_restore.py`](../../backend/tests/unit/services/backup/test_restore.py): new tests for `resolve_restore_target` (in-place restore of the active instance's backup; in-place restore of an earlier instance's backup; deployment without an active instance; cross-target restore; backup whose instance or deployment is missing; counterpart missing). Existing `create_restore` calls drop `target_namespace`. Tests that created a restore into another namespace through `create_restore`, to exercise the in-flight guard, insert that row through the fake repository instead, as a row from an earlier release.
- [`cli/tests/test_backups.py`](../../cli/tests/test_backups.py): new tests for the refusal (each of the three options with a backup id; the SDK is never called; the message names `--last`) and for `--target-namespace` being unknown. Tests that used `--target-namespace` are removed or rewritten. The `--last` tests assert `create_restore(backup_id=...)` only.
- [`python_sdk/tests/test_backups.py`](../../python_sdk/tests/test_backups.py): `test_create_restore` asserts that the transport receives only `backupId`, and a new test asserts that passing `target_namespace` raises `TypeError`.
- Tests that mock `create_restore` and read `kwargs["target_namespace"]` ([`test_environment_clone_service.py`](../../backend/tests/unit/services/backup/test_environment_clone_service.py), [`test_environment_clone.py`](../../backend/tests/functional/graphql/test_environment_clone.py)) assert on the dispatched `target_namespace` or on the stored row instead.

**Rationale**: The PRD agrees unit tests for the restore target resolution and for `styrminctl backups restore`; the other modules are covered by their existing suites, adjusted for the removed parameters.

## R-014: Documentation and changelog

**Decision**: Update in the same change:

- [`cli/README.md`](../../cli/README.md): the restore example with a backup id drops `--target-deployment`; the paragraph about `--target-namespace` with a raw `--target-instance-id` is replaced by the refusal rule.
- [`docs/docs/reference/styrminctl.md`](../../docs/docs/reference/styrminctl.md): `backups restore` takes a backup id alone, or `--last` with a target option.
- [`docs/docs/concepts-and-architecture/backups-and-restores.md`](../../docs/docs/concepts-and-architecture/backups-and-restores.md): step 1 of "What happens when you restore" says that you pick a backup and Styrmin restores it into the deployment it was taken of; the paragraph about a deleted deployment's backups says that only an environment clone restores into another deployment.
- [`dev/knowledge/backend/api.md`](../../dev/knowledge/backend/api.md) and [`dev/knowledge/backend/backup-restore.md`](../../dev/knowledge/backend/backup-restore.md): the `createRestore` signature, the `create_restore` service row, the in-flight guard paragraph, and the GraphQL listing.
- [`CONTEXT.md`](../../CONTEXT.md): the "In-place restore" entry, already committed with the spec.
- Changelog: `changelog/532.removed.md` (the two GraphQL arguments, the SDK parameters and `--target-namespace`; no replacement until deployment clone ships) and `changelog/532.fixed.md` (the bug).

**Rationale**: Constitution §VII, and the PRD's list.

**Not changed**: No ADR. The decision follows from ADR-056 and ADR-063, and the extract phase can record one after implementation. [`ingress-and-networking.md`](../../docs/docs/concepts-and-architecture/ingress-and-networking.md) mentions "a restore into another deployment" for the clone's cross-target restore, which stays correct.

## R-015: No database or migration change

**Decision**: None. `Restore.target_namespace` and `Restore.target_instance_id` keep their columns; only how Styrmin fills them changes. Rows from earlier releases are not migrated (spec, Assumptions).

## R-016: Effect of #531 on `develop`

**Decision**: No change to the design. Since #531, the Velero Restore leaves out the service aliases when the namespaces differ, and only a restore whose deployment ids differ writes aliases after its recovery ([`builders/backup.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py), `build_velero_restore`; [`workflows/templates/backup.py`](../../backend/styrmin_backend/workflows/templates/backup.py), `execute_restore_workflow`). After this change the namespaces differ exactly when the deployment ids differ, so both decisions agree on every restore. Neither file changes.
