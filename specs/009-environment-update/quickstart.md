# Quickstart: Environment-Config Update with Deployment Fanout

This walk-through validates the feature end-to-end against a local Kind/vCluster. It is the manual companion to `backend/tests/e2e/test_environment_update.py` — every step here also appears as an assertion there.

## Prerequisites

- A running Styrmin dev stack (`uv run invoke dev-validate` or equivalent).
- A registered `simple-app` driver (the example under `driver/examples/simple-app`, with the `spec.env_vars` block from 008-deployment-env-vars).
- An environment named `staging` on a working cluster.
- `kubectl` pointed at the deployment's vcluster; `KUBECONFIG` exported.

## Step 1 — Create three deployments in `staging` (US1 setup)

Through the SDK or GraphiQL, create three deployments of `simple-app` in the `staging` environment:

```python
deployments = [
    await client.deployment.deploy(driver="simple-app", environment_name="staging", name="d1"),
    await client.deployment.deploy(driver="simple-app", environment_name="staging", name="d2"),
    await client.deployment.deploy(driver="simple-app", environment_name="staging", name="d3"),
]
# Wait for all to reach Running.
```

## Step 2 — Update environment env vars via the typed mutation (US1 + US2)

Through the SDK (post-feature):

```python
from styrmin_sdk.graphql import UpdateEnvironmentInput, EnvVarInput

await client.environments.update(
    environment_id=staging_id,
    input=UpdateEnvironmentInput(
        env_vars=[EnvVarInput(name="OTEL_EXPORTER_OTLP_ENDPOINT", value="https://otel.staging")],
        # Remember: full-replacement. If staging had an ip_whitelist before, include it here too;
        # otherwise it gets cleared.
    ),
)
```

The mutation MUST return success once the env-config row is persisted and three redeploy Tasks are dispatched.

## Step 3 — Validate fanout (US1 headline)

```bash
# d1
kubectl -n styrmin-<d1-id> get pod -l app.kubernetes.io/name=simple-app \
  -o jsonpath='{.items[*].spec.containers[0].env}' | jq

# d2
kubectl -n styrmin-<d2-id> get pod ... | jq

# d3
kubectl -n styrmin-<d3-id> get pod ... | jq
```

Expected: `OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.staging` appears on the first container of every pod across all three deployments within one reconcile cycle.

## Step 4 — Validate per-deployment timeline entries (US1)

For each deployment, query the deployment timeline:

```graphql
{ deploymentTimeline(deploymentId: "<d1-id>") { task { id type status } applicationVersion contextDiff { changes { path action } } } }
```

Expected: each deployment's timeline has a fresh entry whose `contextDiff` records the env-config change (the `env_vars` path appears in `changes`).

## Step 5 — Per-deployment no-op (FR-010)

Submit the same `updateEnvironment(input: ...)` mutation with byte-for-byte identical content. Both d1, d2, and d3 are already at the new config (Step 3 confirmed their pods carry the env value).

Expected: mutation returns success; **no new Task is created** on any of d1/d2/d3 (per-deployment no-op detection skips all three). The structured log entry shows `dispatched=0`, `skipped_noop=3`, `dispatch_failed=0`. Verify by re-querying each deployment's timeline — the entry count must not have increased.

Then induce a partial-fanout state to validate recovery:

1. Manually delete or roll back one of d1/d2/d3's active instance to a config that predates the env update (e.g., via `kubectl delete applicationinstance <id>` and a manual reconcile, or by simulating with the test fixture).
2. Submit the **same** `updateEnvironment(input=...)` mutation again.
3. Expected: a new Task is created **only** for the deployment that was rolled back; the other two report `skipped_noop` in the structured log. This is the partial-fanout-recovery contract — see spec FR-010 / acceptance scenarios for US1.

## Step 6 — Mutation rejection paths (US2 negative cases)

Through GraphiQL or the SDK:

```graphql
mutation { updateEnvironment(environmentId: "<id>", input: { envVars: [{ name: "1invalid", value: "y" }] }) { id } }
```

Expected: `extensions.code = "INVALID_ENV_VAR_NAME"`.

Also verify (each in its own request):

- `envVars: [{ name: "X", value: "<65 KiB string>" }]` → `ENV_VAR_SIZE_LIMIT_EXCEEDED`.
- `envVars: [{ name: "X", value: "1" }, { name: "X", value: "2" }]` → `DUPLICATE_ENV_VAR_NAME`.
- `environmentId: "<random uuid>"` → `ENVIRONMENT_NOT_FOUND`.

## Step 7 — Failure-isolation (US1 acceptance scenario 2)

Set up an environment with two deployments where deployment B has a chart whose render fails under a specific scheduling override:

```python
await client.environments.update(
    environment_id=staging_id,
    input=UpdateEnvironmentInput(
        env_vars=[EnvVarInput(name="LOG_LEVEL", value="debug")],
        scheduling=SchedulingInput(runtime_class="<a-runtime-class-only-d1-tolerates>"),
    ),
)
```

Expected:

- The mutation returns success.
- Deployment A converges to `LOG_LEVEL=debug`.
- Deployment B's timeline records a failed Task for the redeploy.
- The `Environment.config` row shows the new state regardless of B's failure.

## Step 8 — Frontend environment detail page (US3)

Navigate to the environment detail page in the frontend (e.g., `/environments/<staging-id>`). Click the "Configuration" tab.

Expected:

- The Environment Variables section lists `OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.staging`.
- The IP Allowlist section lists configured CIDRs (or "no allowlist set" if empty).
- Sections for Dedicated Ingress, Scheduling, FQDN/External-DNS settings render with their current values or empty-state messaging.
- Empty sections (e.g., no scheduling overrides) display a "no overrides set" message rather than a blank panel.

## Step 9 — Frontend env-vars edit form (US4)

In the Environment Variables section of the Configuration tab:

1. Click "Add Variable", enter `LOG_LEVEL=info`. Click Save.
2. Confirmation dialog appears, listing 3 deployments to be redeployed (d1, d2, d3).
3. Click Redeploy.
4. Page refreshes; the env vars list now shows both `OTEL_EXPORTER_OTLP_ENDPOINT` and `LOG_LEVEL`.
5. Navigate to one of the deployment detail pages; the timeline shows a fresh redeploy entry for the env-config change.

Negative validation paths:

- Type a name like `1invalid` → inline error "name must match POSIX env var pattern"; Save button disabled.
- Add two rows with name `X` → inline error "duplicate name"; Save button disabled.
- Type a 65 KiB value → inline error "value exceeds 64 KiB cap"; Save button disabled.

## Cleanup

```python
await client.environments.update(
    environment_id=staging_id,
    input=UpdateEnvironmentInput(env_vars=[]),  # full-replace clears env vars
)
```

This still triggers a redeploy fanout (env vars going from set → unset is a real config change).

## Failure-mode checklist

| Symptom | Likely cause |
|---|---|
| Mutation returns success but pods don't show the new env var | The fanout dispatched but the per-deployment Task may have failed — check the deployment's timeline for failed Tasks. |
| Some deployments updated, others didn't | Per-deployment failures during fanout; check each deployment's timeline. |
| No new Task on any deployment | Likely no-op update (input identical to persisted config). |
| Mutation returns `INVALID_CONTEXT` instead of a precise code | `_prevalidate_environment_env_vars` may not be running before `model_validate`; check the call order in `update_environment`. |
| Frontend form shows "0 deployments will be redeployed" | The environment genuinely has no deployments, OR the `Environment.deployments` query is misprojecting; check the page's GraphQL query. |
