# Contract: GraphQL changes

The changes to `schema.graphql`, shown as a diff:

```graphql
type Backup {
  id: UUID!
  name: String!
+ """Optional free-text note about the backup. Null when not set."""
+ description: String
  status: String!
  ...
}

type Mutation {
- createBackup(instanceId: UUID!, name: String = null): Backup @requiresRole
+ createBackup(instanceId: UUID!, name: String = null, description: String = null): Backup @requiresRole
+ """Rename a backup or change its description. An argument that is not sent leaves its field
+ unchanged; an empty description clears it. Does not change any Kubernetes object."""
+ updateBackup(backupId: UUID!, name: String = null, description: String = null): Backup @requiresRole
}
```

`updateBackup` requires the `READ_WRITE` role, the same role as `createBackup`.

## Errors

Every error is a `ServiceError`. `StructuredErrorExtension` returns its code in `extensions.code`.

| Condition | `extensions.code` | Extra metadata |
|-----------|-------------------|----------------|
| `backupId` does not exist | `NOT_FOUND` (`BackupNotFoundError`) | — |
| Another backup of the same instance has the name | `ALREADY_EXISTS` (`BackupNameAlreadyExistsError`, new) | `existing_backup_id` |
| Name empty after whitespace is removed, or longer than 255 characters; description longer than 2,000 characters | `VALIDATION_ERROR` (`ValidationError`) | — |
| Caller has only the read-only role | the existing role-check error | — |

`createBackup` raises the same `ALREADY_EXISTS` and `VALIDATION_ERROR` errors for its `name` and `description`.

## Operation files

| Location | File | Change |
|----------|------|--------|
| SDK `python_sdk/src/styrmin_sdk/graphql/` | `update_backup.graphql` (`mutation UpdateBackup`) | New |
| SDK | `create_backup.graphql`, `get_backup.graphql`, `list_backups.graphql` | Add `description` and the new argument |
| Frontend `frontend/src/graphql/` | `update_backup.graphql` | New |
| Frontend | `create_backup.graphql`, `list_backups.graphql` | Add `description` and the new argument |
| Propagation tests `backend/tests/functional/graphql/operations/` | `update_backup.graphql`, and a create operation with `description` | New |
