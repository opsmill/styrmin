# Contract: Python SDK

## GraphQL operation file

`python_sdk/src/styrmin_sdk/graphql/delete_deployment.graphql`

```graphql
mutation DeleteDeployment($id: UUID!) {
    deleteDeployment(id: $id) {
        id
        type
        status
        message
        deploymentId
    }
}
```

Per project conventions:

- One operation per `.graphql` file.
- Operation **must** have a name (`DeleteDeployment`, not anonymous).
- File name is the snake_case derivation of the operation name (`delete_deployment.graphql`).
- Loaded via `load_query("delete_deployment")`; never embedded as an inline string.

## High-level client method

The SDK exposes `delete_deployment` on its deployment-facing client surface (matching the existing pattern of `deploy`, `update_deployment`, `update_deployment_version`, etc.):

```python
async def delete_deployment(self, deployment_id: UUID) -> Task:
    """Request deletion of a deployment.

    Patches the cluster-side custom resource and returns immediately. The
    deployment's lifecycle progresses through DELETING -> DELETED on the
    server side; poll `Deployment.status` to observe terminal state.

    Idempotent: a call against an already-DELETING deployment returns the
    existing in-flight task without duplicating side effects.

    Raises:
        DeploymentNotFoundError: id is unknown OR the deployment is already
            DELETED (intentionally conflated per the platform contract;
            check the error code DEPLOYMENT_NOT_FOUND to distinguish from
            a transport-level 404).
        DeploymentRestoringError: a restore is in progress on this
            deployment; deletion is refused for data-integrity reasons.
    """
```

The implementation:

1. Calls `await self._gql.execute(load_query("delete_deployment"), {"id": str(deployment_id)})`.
2. Maps GraphQL error codes via the existing structured-error decoder:
   - `DEPLOYMENT_NOT_FOUND` → `DeploymentNotFoundError`
   - `DEPLOYMENT_RESTORING` → `DeploymentRestoringError`
3. Validates the response payload through the regenerated Pydantic `Task` model and returns it.

## Type regeneration

After this `.graphql` file is added (and the schema includes the new mutation), regenerate types:

```bash
uv run invoke generate
```

This updates `python_sdk/src/styrmin_sdk/graphql/_generated/` with `DeleteDeployment` operation types and the new `TaskType.DELETE_DEPLOYMENT` enum value.

## Error type

If `DeploymentRestoringError` does not already exist in the SDK exceptions module, add it as a sibling of `DeploymentNotFoundError`:

```python
class DeploymentRestoringError(StyrminSDKError):
    """Raised when a delete is attempted on a deployment that is restoring."""
```

The decoder maps `extensions.code == "DEPLOYMENT_RESTORING"` → this class.

## Semantics summary (for downstream test harnesses)

| SDK call | Server state | Outcome |
|----------|--------------|---------|
| `delete_deployment(id)` first time, deployment `RUNNING` | patches CRD; new task | Returns Task |
| `delete_deployment(id)` second time, deployment `DELETING` | no patch (idempotent) | Returns same Task as before |
| `delete_deployment(id)` after deployment `DELETED` | resolver guard | Raises `DeploymentNotFoundError` |
| `delete_deployment(id)` while deployment `RESTORING` | resolver guard | Raises `DeploymentRestoringError` |
| `delete_deployment(unknown_id)` | resolver lookup | Raises `DeploymentNotFoundError` |

## Validation

`uv run invoke validate-graphql` must pass before commit (existing CI gate).
