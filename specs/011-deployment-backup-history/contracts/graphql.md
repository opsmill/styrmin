# Contract: `backups` GraphQL query

**Feature**: [../spec.md](../spec.md) | **Requirements**: FR-001, FR-003, FR-006, FR-007

## Signature

Before (`schema.graphql`):

```graphql
backups(instanceId: UUID!, status: BackupStatus = null): [Backup!]!
```

After:

```graphql
"""
List backups. Pass exactly one of deploymentId or instanceId.
deploymentId lists the deployment's backup history: the backups of every
instance the deployment has had, newest first. instanceId lists the backups
of that one instance.
"""
backups(
  deploymentId: UUID = null
  instanceId: UUID = null
  status: BackupStatus = null
): [Backup!]!
```

The `Backup` type does not change. It already exposes `instance: ApplicationInstance!`, and `ApplicationInstance.applicationVersion: String!`.

## Behaviour

| Call | Result |
|------|--------|
| `backups(deploymentId: D)` | Every backup of every instance of `D`, by `createdOn` descending |
| `backups(deploymentId: D, status: COMPLETED)` | The same list, only completed backups |
| `backups(deploymentId: <unknown id>)` | `[]` |
| `backups(deploymentId: <deleted deployment>)` | The deleted deployment's history |
| `backups(instanceId: I)` | The backups of instance `I` only, by `createdOn` descending, as before this change |
| `backups(instanceId: <inactive instance>)` | That instance's backups, as before this change |
| `backups(deploymentId: D, instanceId: I)` | Error, `extensions.code = "VALIDATION_ERROR"` |
| `backups` with neither argument | Error, `extensions.code = "VALIDATION_ERROR"` |

## Compatibility

- An existing operation that declares `$instanceId: UUID!` and passes it to `backups(instanceId:)` keeps validating and keeps returning the same results (SC-004). A non-null variable is allowed in a nullable argument position.
- No field-level role check is added. The `backups` field has none today.

## Error shape

Raised as `AmbiguousIdentifierError` (a `ServiceError` subclass) in the backup service and mapped by `StructuredErrorExtension`:

```json
{
  "errors": [
    {
      "message": "Provide exactly one of deployment_id or instance_id",
      "path": ["backups"],
      "extensions": { "code": "VALIDATION_ERROR" }
    }
  ],
  "data": null
}
```

The exact message is set by the implementation. Clients branch on `extensions.code`.

## Client operations that change

SDK, `python_sdk/src/styrmin_sdk/graphql/list_backups.graphql`:

```graphql
query ListBackups($deploymentId: UUID, $instanceId: UUID, $status: BackupStatus) {
    backups(deploymentId: $deploymentId, instanceId: $instanceId, status: $status) {
        # existing selection unchanged, plus:
        instance {
            id
            applicationVersion
        }
    }
}
```

Frontend, `frontend/src/graphql/list_backups.graphql`:

```graphql
query ListBackups($deploymentId: UUID!) {
  backups(deploymentId: $deploymentId) {
    # existing selection unchanged, plus:
    instance {
      id
      applicationVersion
    }
  }
}
```

Propagation test operation, `backend/tests/functional/graphql/operations/list_backup_history.graphql`: one named operation that accepts both optional variables and selects `id`, `status`, `createdOn`, `instanceId` and `instance { id applicationVersion }`, so the same file can send valid and invalid argument combinations.
