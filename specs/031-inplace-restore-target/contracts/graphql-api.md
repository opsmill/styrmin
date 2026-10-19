# Contract: GraphQL `createRestore`

**Feature**: [spec.md](../spec.md) | **Research**: [R-006](../research.md#r-006-createrestore-loses-both-arguments-graphql-validation-refuses-them), [R-007](../research.md#r-007-the-functional-test-sends-the-removed-arguments-without-an-operation-file-that-fails-validation), [R-008](../research.md#r-008-the-functional-test-is-the-propagation-test)

## Signature

Before (`schema.graphql` on `develop` at `7f0455be`):

```graphql
createRestore(backupId: UUID!, targetNamespace: String!, targetInstanceId: UUID = null): Restore @requiresRole
```

After:

```graphql
createRestore(backupId: UUID!): Restore @requiresRole
```

- Role: `READ_WRITE`, unchanged.
- The `Restore` type is unchanged. `targetNamespace: String!` and `targetInstanceId: UUID` stay readable (FR-005).

## Behaviour

| Request | Result |
|---------|--------|
| `createRestore(backupId: <backup of deployment Y>)` | A `PENDING` restore. `targetNamespace` is `styrmin-<Y id>`. `targetInstanceId` is Y's active instance, or `null` when Y has none. Y moves to `RESTORING`. `EXECUTE_RESTORE` is dispatched with `target_namespace = styrmin-<Y id>`. |
| `createRestore(backupId: <backup of an earlier instance of Y>)` | Same as above. The row records Y's active instance, not the backup's instance, and Y keeps its active instance (ADR-063). |
| `createRestore(backupId: ..., targetNamespace: "...")` | GraphQL validation error `Unknown argument 'targetNamespace' on field 'Mutation.createRestore'.` No row, no status change, no dispatch. |
| `createRestore(backupId: ..., targetInstanceId: "...")` | GraphQL validation error `Unknown argument 'targetInstanceId' on field 'Mutation.createRestore'.` No row, no status change, no dispatch. |
| Unknown backup id | `BackupNotFoundError`, as today. |
| Backup of an internal deployment | `InternalDeploymentError`, as today. |
| Backup of a deleted deployment | `DeletedDeploymentRestoreError` (`OPERATION_DENIED`), as today. |
| A restore already pending or in progress for Y, or for the same backup | `RestoreAlreadyInProgressError` naming that restore, as today. |
| The workflow cannot be dispatched | The restore and Y are marked `FAILED` with the dispatch error, as today. |

No new error code.

## Operation files that change

| File | Change |
|------|--------|
| [`python_sdk/src/styrmin_sdk/graphql/create_restore.graphql`](../../../python_sdk/src/styrmin_sdk/graphql/create_restore.graphql) | Drop `$targetNamespace` and `$targetInstanceId`. Selection set unchanged. |
| [`frontend/src/graphql/create_restore.graphql`](../../../frontend/src/graphql/create_restore.graphql) | Drop `$targetNamespace` and `$targetInstanceId`. Selection set unchanged. |
| [`backend/tests/functional/graphql/operations/create_restore.graphql`](../../../backend/tests/functional/graphql/operations/create_restore.graphql) | Drop `$targetNamespace`. Add `targetNamespace` and `targetInstanceId` to the selection set. |

Generated files that follow: `schema.graphql`, `python_sdk/src/styrmin_sdk/graphql/_generated/create_restore.py`, `python_sdk/src/styrmin_sdk/graphql/_generated/client.py`, `frontend/src/generated/graphql.ts`.

## Propagation test

[`backend/tests/functional/graphql/test_create_restore.py`](../../../backend/tests/functional/graphql/test_create_restore.py):

- `createRestore(backupId)` for a backup of an earlier instance: the row read through a fresh session records `styrmin-<deployment id>` and the active instance; the response returns the same values; `EXECUTE_RESTORE` received the same namespace.
- Parametrized over `targetNamespace` and `targetInstanceId`: the request derived from the operation file with the argument added returns the validation error; no `Restore` row exists for the backup; `run_action` was not called.
