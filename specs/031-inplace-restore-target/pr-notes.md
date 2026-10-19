# PR Notes: An In-Place Restore Always Restores Into the Deployment Its Backup Was Taken Of (#532)

## Summary: a restore no longer deletes and restores into a namespace that the caller names

Before this change, `createRestore` took the target namespace from the caller ([#532](https://github.com/opsmill/styrmin/issues/532)). The restore flow deletes that namespace and restores the backup into it, so an in-place restore could delete the namespace of another deployment, or a namespace that no deployment owns, and restore the backup there ([spec.md, Context](spec.md#context)). For example, `styrminctl backups restore <backup of Y> --target-deployment X` set deployment Y to `RESTORING`, deleted deployment X's namespace and restored Y's backup into it. The spec states this from the code; it was not run.

With this change:

- Styrmin restores every in-place restore into `styrmin-<deployment id>` of the deployment that the backup's instance belongs to, from the Backups tab, `styrminctl`, the Python SDK, GraphQL and an environment restore.
- Styrmin records that deployment's active instance on the restore, also when the backup belongs to an earlier instance ([ADR-063](../../dev/adr/0063-restore-of-earlier-instance-backup.md)).
- The caller names only the backup: `createRestore`, the SDK's `create_restore()` and `styrminctl backups restore <backup-id>` take no namespace and no instance.
- An environment clone keeps restoring each constituent backup into its counterpart deployment, in `styrmin-<counterpart deployment id>`. The server now computes that namespace with the same function as for an in-place restore.

Not decided yet, for the maintainer:

- three answers that the spec gave without the maintainer (see "Autonomous answers for the maintainer to confirm");
- whether the change also needs a `security` changelog fragment (critique E3);
- whether to print the target namespace in the CLI success line, a critique follow-up that this change does not apply (critique P2).

Every E2E node that this branch modifies and that is not skipped passed locally (see "Test results").

## Breaking changes to createRestore, the Python SDK and styrminctl

The arguments are removed with no deprecation period, as #472 did for other input fields before version 1.0 ([spec.md, Clarifications](spec.md#clarifications)).

- GraphQL: the mutation is now `createRestore(backupId: UUID!)`. The arguments `targetNamespace` and `targetInstanceId` are removed, and GraphQL validation refuses a request that still sends either of them. The `Restore` type keeps `targetNamespace` and `targetInstanceId` as readable fields.
- Python SDK: `BackupResource.create_restore()` takes only `backup_id`. A caller that passes `target_namespace` or `target_instance_id` gets a Python `TypeError` ([contracts/sdk-and-cli.md](contracts/sdk-and-cli.md)).
- `styrminctl backups restore`: the option `--target-namespace` is removed, and Cyclopts rejects it as an unknown option.
- `styrminctl backups restore <backup-id>` with `--target-deployment`, `--target-deployment-id` or `--target-instance-id` is refused before any call to the server, with exit code 1. Before this change, `cli/README.md` showed `styrminctl backups restore <backup-id> --target-deployment my-app` as its example, so scripts that copied it fail after the upgrade. The error reads, for `--target-deployment`:

  ```text
  --target-deployment, --target-deployment-id and --target-instance-id work only with --last. A backup is restored into the deployment it was taken of. Run the command again without --target-deployment.
  ```

  With `--last`, the three options keep choosing whose backup history the newest completed backup comes from.
- Client and server versions must match. Upgrade `styrminctl`, the Python SDK and the server together, and reload web pages that were open during the upgrade:
  - a client from before this change sends `targetNamespace` on every restore, `--last` included, and the new server refuses it;
  - a server from before this change requires `targetNamespace`, and refuses a restore from a client after this change.
- No replacement: apart from an environment clone, Styrmin offers no way to restore a backup into another deployment until "deployment clone" ships. That is a separate feature with no issue yet.

The changelog fragments [`changelog/532.removed.md`](../../changelog/532.removed.md) and [`changelog/532.fixed.md`](../../changelog/532.fixed.md) state these changes for users.

## Changes to the restore service, the web app and the documentation

- [`backend/styrmin_backend/services/backup/service.py`](../../backend/styrmin_backend/services/backup/service.py):
  - the new `resolve_restore_target` returns the deployment that receives a restore, its namespace `styrmin-<deployment id>` and its active instance, or no instance when the deployment has none;
  - `create_restore` no longer takes `target_namespace` or `target_instance_id`, and stores the resolved values on the `Restore` row;
  - the in-flight restore guard `find_in_flight_restore` keeps its code; only its docstring changes.
- The `createRestore` mutation, the environment restore fan-out ([`environment.py`](../../backend/styrmin_backend/services/backup/environment.py)) and the environment clone ([`clone.py`](../../backend/styrmin_backend/workflows/templates/clone.py)) read `restore.target_namespace` instead of building or passing a namespace.
- The Backups tab sends only `backupId`. The Restore dialog still shows `styrmin-<deployment id>` in its read-only "Target Namespace" field.
- No database change: the `Restore` table keeps its columns. A `Restore` row that an earlier release created keeps the namespace it recorded.
- Documentation updated in the same change:
  - [`cli/README.md`](../../cli/README.md) and the [`styrminctl` reference](../../docs/docs/reference/styrminctl.md);
  - the ["Backups and restores" page](../../docs/docs/concepts-and-architecture/backups-and-restores.md);
  - [`dev/knowledge/backend/api.md`](../../dev/knowledge/backend/api.md) and [`dev/knowledge/backend/backup-restore.md`](../../dev/knowledge/backend/backup-restore.md);
  - the new "In-place restore" entry in [`CONTEXT.md`](../../CONTEXT.md).

## Test results

[e2e-evidence.md](e2e-evidence.md) records each E2E session: the node IDs, the exact command, the start and end times, the image tag and digest, the vcluster name and the verbatim `PASSED` lines.

All sessions used the image tag `inplace-restore-133ed150`, built from commit `133ed150`; no source file changed after that commit.

- `shard_backup`, `api-chromium` (T038): `6 passed, 199 deselected`. Each node passed:
  - `test_backup_and_restore_lifecycle[api-chromium]`, which now also checks that the restore records `styrmin-<deployment id>` and the active 0.2.0 instance, although the backup belongs to the 0.1.0 instance;
  - `test_restore_lifecycle_transitions[api-chromium]`;
  - `test_restore_failure_marks_failed_not_indefinite[api-chromium]`;
  - `test_restore_of_removed_velero_backup_fails_velero_step[api-chromium]`;
  - `test_renamed_bsl_cluster_objects_follow_the_location_id[api-chromium]`, which this branch does not modify;
  - `test_mariadb_mongodb_backup_and_restore_lifecycle[api-chromium]`.
- `shard_backup`, `ui-chromium` (T039): `3 passed, 3 skipped, 199 deselected`.
  - Passed: `test_backup_and_restore_lifecycle[ui-chromium]`, `test_restore_lifecycle_transitions[ui-chromium]` and `test_mariadb_mongodb_backup_and_restore_lifecycle[ui-chromium]`. Under `ui-chromium`, each restore checks that the Restore dialog's read-only "Target Namespace" field shows `styrmin-<deployment id>` before it submits.
  - Not run: the `ui-chromium` variants of `test_restore_failure_marks_failed_not_indefinite`, `test_restore_of_removed_velero_backup_fails_velero_step` and `test_renamed_bsl_cluster_objects_follow_the_location_id`, skipped by their `api_only` marker. Their `api-chromium` variants passed in T038.
- `shard_infrahub`, `api-chromium` (T040): `1 passed, 1 deselected`.
  - Passed: `test_infrahub_enterprise_backup_and_restore_lifecycle[api-chromium]`, which restores an Infrahub Enterprise backup with only the backup id and checks that a Neo4j node and an object-store file are back.
  - Not run: `test_infrahub_enterprise_backup_and_restore_lifecycle[ui-chromium]`, deselected because the test is `api_only`; CI does not run the `ui` cell of `shard_infrahub`.
  - Not run: `test_infrahub_backup_and_restore_lifecycle`. This branch changes its restore call, but the test carries `@pytest.mark.skip(reason="backup/restore not supported with community")`, so it runs in no session, locally or in CI.

Tests outside E2E:

- Before the change, the backup and restore tests passed: 683 backend unit and functional tests, 43 tests in `cli/tests/test_backups.py` and 27 in `python_sdk/tests/test_backups.py` (message of commit `1b5723ca`).
- After the change, the checks of task T035 passed: `uv run invoke format lint`, `uv run invoke validate-graphql`, the backend unit and functional tests, the CLI and SDK tests, and `pnpm lint` and `pnpm test` in `frontend/` (message of commit `133ed150`). That message does not give the test counts.
- New and changed tests that check the fix:
  - `backend/tests/unit/services/backup/test_restore.py`: the class `TestResolveRestoreTarget`, including a backup of an earlier instance, which restores into the deployment's namespace and records the active instance;
  - `backend/tests/functional/graphql/test_create_restore.py`: the propagation test, and a test that GraphQL validation refuses each removed argument before a restore row is written or a workflow is started;
  - `cli/tests/test_backups.py`: the refusal of a backup id with each target option, with no call to the SDK, and `--last` sending only the chosen backup id;
  - `python_sdk/tests/test_backups.py`, `backend/tests/unit/services/backup/test_environment_backup.py` and `backend/tests/functional/graphql/test_environment_clone.py`: the SDK sends only the backup id, and the rows of an environment restore and of a clone record each deployment's active instance.

## Autonomous answers for the maintainer to confirm

The spec gave these answers without the maintainer, because the PRD did not cover them. Each can be confirmed or rejected on its own. The quotes are from [spec.md, Clarifications](spec.md#clarifications), session "autonomous, while writing this spec".

- The fix for #530 (#531) on `develop`. Question: "`develop` moved from `a5ec9446` to `7f0455be` after the PRD was written, with the fix for #530 (#531). Does that change the fix?" Answer: "No. #531 is the change in which the PRD's "second effect" (an in-place restore into another namespace ends with no service aliases) was found. After this fix the namespaces of a restore differ exactly when its deployment ids differ, so that effect cannot occur."
- `--environment` with a backup id. Question: "`styrminctl backups restore` also takes `--environment`, which only tells `--target-deployment` which environment a deployment name belongs to. Is it refused with a backup id?" Answer: "No. The PRD names three target options. `--environment` selects no target on its own, so it keeps its current meaning and has no effect with a backup id alone."
- A deployment with no active instance. Question: "What does the `Restore` row record when the backup's deployment has no active instance?" Answer: "No target instance, as a cross-target restore into a counterpart without an active instance already does. The restore itself proceeds as today."

## Open question: a security changelog fragment (critique E3)

Before this change, a user with the `READ_WRITE` role could send any namespace to `createRestore`, and the restore flow deletes the namespace it receives. The agent chart's ClusterRole allows `delete` on namespaces in every namespace ([`helm/agent/templates/roles.yaml`](../../helm/agent/templates/roles.yaml)). The spec states this from the code; it was not run, and which service account the restore Job runs as was not checked ([spec.md, Context](spec.md#context)).

The PRD files the change as `removed` and `fixed`, and this change keeps those two fragment types. The critique asks whether the change should also carry a `security` changelog fragment, or other handling, and leaves the decision to the maintainer ([critique E3](critiques/critique-20261019-1.md)).

## Critique follow-up not applied: print the target namespace in the CLI success line (P2)

After this change, `styrminctl backups restore <backup-id>` prints only the restore's name, id and status, so the user does not see which deployment receives the restore without running `styrminctl backups restore-get`. The critique suggests printing the target namespace in the success line. It was not applied, because it is outside the PRD, and is listed for the maintainer as a follow-up ([critique P2](critiques/critique-20261019-1.md)).
