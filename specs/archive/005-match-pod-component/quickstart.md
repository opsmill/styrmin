# Quickstart: Manually Verify Pod Component Attribution

This is the local, hands-on loop for verifying the feature is working end-to-end before running the formal E2E test.

## Prerequisites

- Working dev environment (see `dev/`).
- A driver with at least two declared components. The shipped `infrahub` driver has `server`, `task-worker`, `database`, `cache` — perfect for this.
- `kubectl` and `psql` (or any Postgres client) available.

## 1. Apply the migration

```bash
uv run alembic upgrade head
```

Expect: a single new column `podstatus.component_name` (nullable VARCHAR).

```bash
psql "$STYRMIN_DB_URL" -c "\\d podstatus" | grep component_name
# component_name | character varying |           |          |
```

## 2. Deploy a multi-component driver

Through the UI or the SDK, deploy the `infrahub` driver in a test environment. Wait for the deployment to reach `RUNNING`.

## 3. Check the agent's view

Tail the agent logs:

```bash
kubectl logs -n styrmin -l app.kubernetes.io/name=styrmin-agent -f | grep "Status poll"
```

You should see a poll log line per cycle.

## 4. Query pod statuses for the deployment

Using the SDK or `gql` directly:

```graphql
query {
  deployment(deploymentId: "<DEPLOYMENT_ID>") {
    name
    podStatuses {
      podName
      phase
      ready
      componentName
    }
  }
}
```

**Expected**:

- Every pod whose name starts with `infrahub-server-…` reports `componentName: "server"`.
- Every pod whose name starts with `infrahub-task-worker-…` reports `componentName: "task-worker"`.
- Every pod whose name starts with `infrahub-database-…` reports `componentName: "database"`.
- Every pod whose name starts with `infrahub-cache-…` reports `componentName: "cache"`.
- Any sidecar pods (e.g., `linkerd-proxy`-style if your env has them) without the `styrmin/component` label report `componentName: null`.

## 5. Manually drop a label, verify reclassification

In a second shell, scale up a deployment with a pod that lacks the label:

```bash
kubectl run -n styrmin-<deployment-id> debug-pod --image=busybox -- sleep 3600
```

Wait one poll cycle (~5 s by default). Re-run the query above. The new pod must appear in `podStatuses` with `componentName: null`.

```bash
kubectl delete pod -n styrmin-<deployment-id> debug-pod
```

After another cycle, the row is removed by `delete_stale`.

## 6. Manually set an unknown label, verify it's stored as-is

```bash
kubectl label pod -n styrmin-<deployment-id> debug-pod-2 styrmin/component=ghost
```

Wait one poll cycle. The pod must report `componentName: "ghost"` — no error, no coercion.

## What to do if any of the above fails

- `componentName` always `null` even on labelled pods → check `_extract_pod_data`; the label key string is `styrmin/component` literally (lowercase, single slash).
- Migration fails → `down_revision` may be wrong. Run `alembic history` and chain from the most recent revision.
- `componentName` field absent from GraphQL response → `schema.graphql` not regenerated, or the SDK query doesn't select it. Re-run `uv run styrmin export graphql-schema schema.graphql && uv run invoke generate`.
