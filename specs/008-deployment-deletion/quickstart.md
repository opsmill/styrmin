# Quickstart: Deployment Deletion

A walkthrough for engineers and reviewers who need to drive the new flow end-to-end on a local dev environment.

## Prerequisites

- `uv sync --all-groups --all-packages` and `cd frontend && pnpm install` have been run.
- Database migration has been applied (`uv run invoke migrate` once the migration in this branch is committed).
- The agent CRD has been re-applied after the schema delta (`helm` chart picks up the YAML diff).
- GraphQL schema has been regenerated: `uv run styrmin export graphql-schema schema.graphql`.
- SDK / frontend types have been regenerated: `uv run invoke generate`.

## End-to-end via the SDK

```python
import asyncio
from uuid import UUID
from styrmin_sdk.client import StyrminClient

async def main():
    client = StyrminClient(url="http://localhost:8080/graphql")
    # 1. Resolve the target deployment.
    deployment = await client.get_deployment(name="my-app-test")

    # 2. Trigger deletion. Returns immediately with a born-complete Task.
    task = await client.delete_deployment(deployment_id=deployment.id)
    assert task.type == "DELETE_DEPLOYMENT"
    assert task.status == "SUCCESS"

    # 3. Poll for terminal state.
    while True:
        d = await client.get_deployment(id=deployment.id)
        if d.status == "DELETED":
            assert d.deleted_at is not None
            break
        await asyncio.sleep(2)

    # 4. List default — deleted record is hidden.
    assert all(d.id != deployment.id for d in await client.list_deployments())

    # 5. List with includeDeleted — deleted record reappears.
    assert any(
        d.id == deployment.id for d in await client.list_deployments(include_deleted=True)
    )

asyncio.run(main())
```

## Idempotency check

```python
# Issuing delete a second time on the same in-flight deletion returns the same Task.
t1 = await client.delete_deployment(deployment_id=deployment.id)
t2 = await client.delete_deployment(deployment_id=deployment.id)
assert t1.id == t2.id  # idempotent
```

## "Not found" on already-deleted

```python
from styrmin_sdk.exceptions import DeploymentNotFoundError

# Wait for terminal state, then re-issue.
try:
    await client.delete_deployment(deployment_id=deployment.id)
except DeploymentNotFoundError:
    pass  # expected
```

## Restore guard

```python
from styrmin_sdk.exceptions import DeploymentRestoringError

# While a restore is in progress for this deployment...
try:
    await client.delete_deployment(deployment_id=deployment.id)
except DeploymentRestoringError:
    pass  # expected
```

## End-to-end via the UI

1. Start the dev stack (backend + frontend + dev cluster). Existing dev workflow unchanged.
2. Navigate to a running deployment's detail page. Confirm the new **Delete** button appears beside **Upgrade** / **Redeploy**.
3. Click **Delete**. The dialog opens with:
   - The exact deployment name shown.
   - An input that gates the destructive button.
   - Body text describing workload + namespace teardown, retained backups, and the "Show deleted" reveal window.
4. Type a wrong / case-mismatched value — confirm the destructive button stays disabled.
5. Type the deployment name exactly — confirm the button enables.
6. Click the destructive button — the dialog closes and the page navigates to the deployment list.
7. Observe the row showing a `Deleting...` badge for the duration of teardown.
8. Once cluster teardown completes, confirm the row disappears from the default list.
9. Toggle **Show deleted** at the right of the list header. Confirm the row reappears greyed-out with a relative-time deletion timestamp and no inline action menu.
10. Click into the deleted row's detail page. Confirm the **Deleted at \<timestamp\>** banner and that all action buttons are disabled with explanatory tooltips.

## Cluster-side inspection

While teardown is in progress (or after it has completed but before janitor TTL):

```bash
export KUBECONFIG=$(ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1)

# Watch the CR phase progression.
kubectl get styrmindeployment -A -w

# Inspect the namespace teardown.
kubectl get namespace styrmin-<deployment-id>

# Once phase: Deleted, the CR lingers for DELETED_CR_TTL_HOURS (default 6h).
kubectl get styrmindeployment -A | grep Deleted
```

To reduce the TTL for local testing:

```bash
export DELETED_CR_TTL_HOURS=0    # restart the operator so it re-reads the env var
```

The janitor sweep runs every 30 minutes; the next sweep after `lastTransitionTime + DELETED_CR_TTL_HOURS` will reap the CR.

## Manual `kubectl delete` safety net

```bash
kubectl delete styrmindeployment -n <ns> <name>
```

The existing `@kopf.on.delete` handler runs the teardown pipeline. **Note**: this path does **not** create a backend tombstone — the database row is left in whatever state it was last in. Reconciling out-of-band deletions back to the DB is out of scope.

## Tests to run before merging

```bash
# GraphQL propagation unit tests.
uv run pytest backend/tests/unit/api/schema/test_propagation_delete_deployment.py -v

# E2E (requires a vcluster). API variant:
sleep infinity | uv run pytest backend/tests/e2e/test_delete_deployment_api.py -v -s --pdb 2>&1 | tee /tmp/pdb.log

# E2E UI variant:
sleep infinity | uv run pytest backend/tests/e2e/test_delete_deployment_ui.py -v -s --pdb 2>&1 | tee /tmp/pdb.log

# Lint + format.
uv run invoke format lint
cd frontend && pnpm lint
```
