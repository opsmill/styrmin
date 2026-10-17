# Handoff Notes: Deployment References Stored by Id

Issues: [#508](https://github.com/opsmill/styrmin/issues/508) (feature), [#492](https://github.com/opsmill/styrmin/issues/492) (failure it fixes). Spec: [spec.md](spec.md). Plan: [plan.md](plan.md). Research: [research.md](research.md). Tasks: [tasks.md](tasks.md). E2E evidence: [e2e-evidence.md](e2e-evidence.md). Decision: [ADR-075](../../dev/adr/0075-deployment-references-stored-by-id.md).

## Summary: a rename no longer breaks the affinity terms that name the deployment

Problem: Styrmin stored the deployment reference of an affinity term as the name that the operator wrote, and looked the name up at each reconcile. After an operator renamed the named deployment, the name matched no deployment ([#492](https://github.com/opsmill/styrmin/issues/492), [spec Context](spec.md#context)):

- every later update of a deployment whose term named the renamed deployment was refused;
- every config fan-out redeploy in an environment whose config had such a term failed;
- the rename itself was refused when the environment's config had a term that named the deployment being renamed.

What changed:

- Every write that stores a config (`deploy`, `updateDeployment`, `updateDeploymentVersion`, `createEnvironment`, `updateEnvironment`, and `styrminctl deployments apply` through them) replaces a name in a deployment reference with the id of the named deployment before it saves anything. A write whose term names a deployment that the environment does not have, or a tombstoned deployment, is refused with `VALIDATION_ERROR` and the term's path (commit aacbc2b3).
- Each reconcile resolves stored ids only, to the label selector `styrmin/deployment_id=<id>`. A rename changes no stored term and restarts no pod (commit 4d172c63).
- An environment clone gives each counterpart deployment its id before it creates anything, points every copied term at the counterpart of the deployment it named, and refuses a request whose copied terms name a deployment that the clone does not copy (commit fe534af0, commit ebdde558).
- An environment restore runs each redeploy in its own savepoint, so one failed redeploy no longer drops the redeploys of the other deployments (commit 4350614b).

Not done in this change ([spec Out of Scope](spec.md#out-of-scope)):

- Showing which deployment a term names, next to the id. The user files the follow-up issue (see [Follow-up issue that the user files](#follow-up-issue-that-the-user-files)).
- Upgrading existing installations: no data migration for configs or backups that give names. The spec records that no Styrmin installation is running yet ([spec Clarifications](spec.md#clarifications)).
- Making `deployments apply` resolve terms after the whole batch. The order of manifests matters for a term in a deployment's config.
- The limits listed under [Known limits](#known-limits).

## E2E evidence: local passes of the new tests and of the whole `shard_env_backup` shard

[e2e-evidence.md](e2e-evidence.md) records, for each run, the command, the start and end times, the vCluster id, the kubeconfig path when the log prints it, and the verbatim `PASSED` line:

- `backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql[api-chromium]` (`shard_compute`, `api_only`): rename of the deployment that an affinity term names. Passed at 2026-10-17T00:21:55+00:00 on commit `256bb517`.
- `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]` (`shard_env_backup`): environment clone whose peer names the primary in an affinity term, and the refused clone request. Passed at 2026-10-17T02:44:57+00:00 on commit `14cbc24c`.
- `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]` (`shard_env_backup`): the same, with the clone started from the clone dialog. Passed at 2026-10-17T02:50:55+00:00 on commit `14cbc24c`.
- The whole `shard_env_backup` shard, `test_environment_backup_and_restore_lifecycle` and `test_environment_clone_lifecycle`, on commit `06645477`, one variant per pytest session ([e2e-evidence.md](e2e-evidence.md#whole-shard_env_backup-shard-after-the-environment-restore-change)): `[api-chromium]` passed at 2026-10-17T03:56:18+00:00 (`2 passed, 199 deselected`), `[ui-chromium]` passed at 2026-10-17T04:04:52+00:00 (`2 passed, 199 deselected`).

Commit `4350614b` (environment restore savepoints) changed production code after the first three runs. The shard run on commit `06645477` includes `test_environment_backup_and_restore_lifecycle`, which restores an environment backup, and passed in both variants. The change is also covered by a unit test and a functional test (T036, T037).

Commits `ee5d0f99` (restore log fields), `6a3d7c33` (the binder checks each deployment reference with `DeploymentReference`), `b781eace` (clone log line `env_clone_environment_reference_not_cloned`) and the test-only commits `64accb4e` and `0f069283` came after the shard run. They were verified by the unit and functional suites only ([e2e-evidence.md](e2e-evidence.md#commits-after-the-shard-run)).

## High-risk areas for review

### GraphQL: description text of `DeploymentReferenceInput`

- Only the descriptions of the `DeploymentReferenceInput` type and of its `deploymentId` and `deploymentName` fields change. No type, field or argument is added, removed or changed ([`inputs.py`](../../backend/styrmin_backend/api/definitions/config/inputs.py), commit 413455d9, [contracts/graphql-and-errors.md](contracts/graphql-and-errors.md)).
- Compared with the base commit `ca9c19f9`, `schema.graphql`, `python_sdk/src/styrmin_sdk/graphql/_generated/input_types.py` and `frontend/src/generated/graphql.ts` change only in these descriptions.
- What a client reads back changes: a config written with `deploymentName` is read back with `deployment_id` only.

### Environment clone flow

Files: [`workflows/templates/clone.py`](../../backend/styrmin_backend/workflows/templates/clone.py) and [`services/backup/clone.py`](../../backend/styrmin_backend/services/backup/clone.py) ([research R-007](research.md#r-007-the-clone-request-check), [research R-008](research.md#r-008-the-clone-flow-gives-counterparts-their-ids-before-it-creates-them), commit fe534af0, commit ebdde558):

- Ids given in advance: the flow generates one id per usable snapshot and passes it to `deploy_application`. `_create_counterpart` returns that id instead of reading the counterpart back by name.
- Remap: `remap_deployment_references` replaces each source deployment's id with its counterpart's id in the merged environment config and in each snapshot config. `create_environment` and `deploy_application` accept the ids of the counterparts that the clone is about to create (`upcoming_deployments`).
- Order: `order_counterparts` creates each counterpart after the counterparts its terms name. Among those that can come next, the ones named by the environment's config come first, then source-name order; a cycle is broken in source-name order. Counterparts with no terms are now created in source-name order, not in snapshot order.
- Cascade: a counterpart whose config's terms name a deployment whose captured data cannot be used (capture failed; backup deleted, not completed or expired) or whose creation failed is attributed `FAILED` with the reason "an affinity term names deployment {name}, which was not cloned", is not created, and is logged as `env_clone_reference_not_cloned`. The terms of the driver version's component definitions are not part of the cascade: `deploy_application` looks their names up, and a name that no counterpart has fails the counterpart with `UnresolvableAffinityReferenceError`, whose message becomes the reason.
- New fatal step `referenced_deployment_not_cloned`: written when the new environment's config names a deployment that has no counterpart (its captured data cannot be used, or the capture cascade failed it) or whose creation failed. In the first case the clone creates no environment and logs `env_clone_environment_reference_not_cloned` (commit b781eace); after a failed creation it creates no further counterpart. The step and the reason are plain strings, so the GraphQL schema and the frontend do not change.
- Request-time check: `clone_environment` refuses, before it creates a clone record or a backup or starts a flow, a request whose copied terms name a deployment that the clone does not copy (`UnclonedDeploymentReferenceError`, code `VALIDATION_ERROR`, `extensions.deployments` with ids, names and term paths).
- Request-time merge: the check runs `merge_environment_config` at request time, so a source environment config that no longer validates is now refused when the request is made. Before, the flow failed the clone.

### Environment restore

- `restore_environment_backup` in [`services/backup/environment.py`](../../backend/styrmin_backend/services/backup/environment.py) now runs each redeploy in `uow.session.begin_nested()` ([research R-009](research.md#r-009-an-environment-restore-puts-the-captured-config-back-unchanged), commit 4350614b).
- Before, one failed redeploy rolled back the whole transaction. That dropped the redeploys written before it, and the restore returned `INTERNAL_ERROR` although the config revert was already committed.
- The restore still writes the captured environment config back as captured, without binding, so a captured term that names a deployment deleted since the backup does not refuse the restore (FR-006).
- A failed redeploy is logged as `env_restore_fanout_dispatch_error` with `environment_restore_id`, `error_code` and `path`, and counted in `config_redeploy_failed` of `env_restore_fanout_dispatched` and in the `env_restore_fanout_deployments_total` metric line with `outcome=config_redeploy_failed` (commit ee5d0f99).

### Unit of work: a failure inside a caller's savepoint

- [`services/unit_of_work.py`](../../backend/styrmin_backend/services/unit_of_work.py), commit ef007e71. This is a defect found during this work; `develop` has the same nested code path.
- Before: when two or more `async with uow` levels were open inside a caller's savepoint and the inner one raised, the inner level rolled back the savepoint and the next level rolled back the whole transaction. The caller lost its earlier writes in that transaction.
- After: `SqlModelUnitOfWork` records the savepoint that is open when each level is entered. A level entered inside a savepoint that exits with an exception rolls back only that savepoint, once. A level entered with no savepoint open rolls back the whole transaction, as before.
- Callers whose behaviour changes: the cluster config fan-out and the environment config fan-out ([ADR-066](../../dev/adr/0066-cluster-config-fanout.md)), the status reporter hooks, and the environment restore. They now keep their other writes when one item fails.

## Behaviour changes a reviewer should know

- Per-level resolution: each reconcile resolves the terms of the environment's config, the deployment's config and each component's config one level at a time, before the levels are merged. A term that a deeper level discards with `replace: true` is therefore still resolved, and a term that names a deleted deployment fails the reconcile even when a deeper level replaces it ([`context.py`](../../backend/styrmin_backend/services/context.py), `resolvedScheduling` in [`deployment/model.py`](../../backend/styrmin_backend/api/definitions/deployment/model.py), [pod-scheduling guide](../../dev/guides/pod-scheduling.md#each-reconcile-resolves-the-stored-id)).
- `updateDeployment` binds the whole stored config on every call. A stored id of a tombstoned deployment is refused before anything is saved, including for an update that changes only the deployment's name. [Research R-006](research.md#r-006-what-updatedeployment-saves-when-a-reconcile-time-term-fails) expected this case to fail after the request's config was saved; commit aacbc2b3 records the change.
- `createEnvironment` and `styrminctl environments create -c` refuse every term that names a deployment, because a new environment has no deployment yet. Before, the write was accepted and the term failed at the first reconcile.
- `cloneEnvironment` checks the copied terms before the concurrency guard. A request whose copied terms name a deployment that the clone does not copy gets `VALIDATION_ERROR` even while another environment operation runs on the source, instead of `EnvironmentOperationInProgressError`. The deployment selection was already checked before the guard.
- `deploy_application` now resolves the deployment's name before it checks the ingress controller, so a name conflict no longer starts an ingress controller flow run (commit aacbc2b3).

## Known limits

- Terms from a driver version are looked up by name at each copy ([research R-005](research.md#r-005-a-components-terms-come-from-the-driver-version), [pod-scheduling guide](../../dev/guides/pod-scheduling.md#terms-from-a-driver-version-are-looked-up-by-name-at-each-copy)). A driver version's component definitions can give only a name. Styrmin looks that name up each time it copies the definitions to a deployment's components:
  - at `deploy`;
  - at `updateDeploymentVersion`, only when the request moves the deployment to another driver version; with the same driver version, the stored component configs stay as they are;
  - when an environment clone creates a counterpart deployment.

  After the named deployment is renamed, the stored id keeps working at each reconcile. A `deploy` with that driver version, an `updateDeploymentVersion` to a driver version whose definitions give the old name, and a clone that copies a deployment of that driver version are refused, with the name and the `component[<name>]` path. Fixing this needs drivers that do not name deployments.
- A cycle of terms with a creation failure in a clone ([research R-008](research.md#r-008-the-clone-flow-gives-counterparts-their-ids-before-it-creates-them)). Inside a cycle of terms, a counterpart created before a peer whose creation then fails keeps a term with the peer's id. The clone attributes it `CLONED`, and its next reconcile is refused with the term's path. A creation failure after a successful capture needs the driver version to disappear or the database to fail, so the case is recorded, not handled.
- An environment restore records a refused redeploy only in the server log, not on the `EnvironmentRestore` record: `env_restore_fanout_dispatch_error` gives `environment_restore_id`, `deployment_id`, `error_code` and `path`; `env_restore_fanout_dispatched` counts the redeploy in `config_redeploy_failed` and `dispatch_failed`; and `metric=env_restore_fanout_deployments_total` is logged with `outcome=config_redeployed` and `outcome=config_redeploy_failed` (commit ee5d0f99) ([backup-restore knowledge page](../../dev/knowledge/backend/backup-restore.md), [changelog/508.fixed.md](../../changelog/508.fixed.md)).
- The SDK error for a clone request that leaves out a named deployment does not carry the GraphQL extensions. The SDK raises `OperationFailedError` with `typename == "VALIDATION_ERROR"` and the message, which lists the names. Only raw GraphQL clients read `extensions.deployments` with the term paths ([e2e-evidence.md](e2e-evidence.md), `test_environment_clone_lifecycle` in [`test_backup_restore.py`](../../backend/tests/e2e/test_backup_restore.py)).

## Checks run locally: all passed

The branch was rebased onto `develop` (`ce8cb7d8`) on 2026-10-17, which brought in #493 and 17 other commits. After the rebase, `uv run invoke format lint`, `uv run invoke validate-graphql`, the unit suite (4217 passed), the functional suite (774 passed) and the SDK suite (298 passed) all passed. No E2E test was run after the rebase. The conflicts and the times are in [e2e-evidence.md](e2e-evidence.md#rebase-onto-develop-on-2026-10-17). The commit ids in this file are the ids after the rebase, and the runs below were made before it.

All local runs below were made on commit `09accc64` (T044, T045 in [tasks.md](tasks.md)). The T044 runs had no uncommitted change; the T045 runs had only this file and the T045 section of `e2e-evidence.md` uncommitted. The quickstart walk-through is also recorded in [e2e-evidence.md](e2e-evidence.md#t045-walk-through-of-quickstart-sections-1-2-and-5).

T044:

- `uv run invoke format lint`, with `npm_config_ignore_workspace=true`: exit code 0, finished at 2026-10-17T03:39:25+00:00.
  - Ruff format: "960 files left unchanged". Ruff check and ty: "All checks passed!". rumdl: "No issues found".
  - yamllint: two warnings, in `driver/examples/infrahub-mcp/driver.styrmin.yml` and `.specify/workflows/speckit/workflow.yml`, files that this change does not touch.
  - GraphQL validation: "277/277 .graphql files passed validation." The generated SDK and frontend types are up to date.
- `uv run invoke validate-graphql`: exit code 0, finished at 2026-10-17T03:39:34+00:00, "277/277 .graphql files passed validation."
- `uv run invoke test` (runs `pytest tests --ignore=tests/e2e` in `backend/`): exit code 0, finished at 2026-10-17T03:42:44+00:00, `5017 passed, 3 skipped, 35 warnings in 157.04s (0:02:37)`. This change adds no skip marker.
- `uv run pytest backend/tests/functional -q`: exit code 0, finished at 2026-10-17T03:44:21+00:00, `769 passed, 2 skipped, 2 warnings in 58.62s`.

Quickstart ([quickstart.md](quickstart.md)):

- §1, generated surface:
  - `uv run styrmin export graphql-schema schema.graphql`: exit code 0, finished at 2026-10-17T03:44:29+00:00.
  - `uv run invoke generate`: the SDK step (`ariadne-codegen`) completed; the frontend step failed with exit code 1 at 2026-10-17T03:44:33+00:00 and printed only `ELIFECYCLE Command failed with exit code 1`, so the cause is not known (this host runs Node 18.19.1; commit 413455d9 records the same failure). `pnpm -C frontend --ignore-workspace codegen`, run directly, gave exit code 0 at 2026-10-17T03:44:40+00:00.
  - `git diff --stat schema.graphql python_sdk/src/styrmin_sdk/graphql/_generated frontend/src/generated` printed nothing: the regenerated files equal the committed ones. Compared with `ca9c19f9`, only the descriptions of `DeploymentReferenceInput` change, as expected.
- §2, unit tests: exit code 0, finished at 2026-10-17T03:44:51+00:00, `137 passed in 0.49s`.
- §2, functional tests: exit code 0, finished at 2026-10-17T03:45:10+00:00, `148 passed in 11.32s`.
- §5, `uv run invoke format lint`: exit code 0, finished at 2026-10-17T03:46:21+00:00, with the same results as the T044 run. rumdl excludes `specs/`, so `uv run rumdl check --no-exclude` was also run on this file and on `e2e-evidence.md`: "No issues found in 2 files".

E2E: the passes listed under [E2E evidence: local passes of the new tests and of the whole `shard_env_backup` shard](#e2e-evidence-local-passes-of-the-new-tests-and-of-the-whole-shard_env_backup-shard). §3 of the quickstart (manual check on the dev stack) is optional and was not run.

## Database: no schema change

No file under `backend/styrmin_backend/db/` changes, and the change ships no Alembic revision. Only the content of the JSON configs changes: a stored deployment reference gives `deployment_id` instead of `deployment_name`. `Deployment.create` in [`domain/models.py`](../../backend/styrmin_backend/domain/models.py) gains an optional `id` argument; no column changes.

## Follow-up issue that the user files

The user files the follow-up issue for showing which deployment a term names, next to the id ([spec Out of Scope](spec.md#out-of-scope), [critique P2](critiques/critique-20261016.md)). It was not filed during implementation.
