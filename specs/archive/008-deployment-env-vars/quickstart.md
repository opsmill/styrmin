# Quickstart: Deployment Env Vars

This walk-through validates the feature end-to-end against a local Kind/vCluster. It is the manual companion to `backend/tests/e2e/test_deployment_env_vars.py` — every step here also appears as an assertion there.

## Prerequisites

- A running Styrmin dev stack (`uv run invoke dev-validate` or equivalent).
- A registered `simple-app` driver (the example under `driver/examples/simple-app`) extended with a `spec.env_vars` block (Step 5 below adds this; the driver is reloaded inside the same flow).
- `kubectl` pointed at the deployment's vcluster; `KUBECONFIG` exported.

## Step 1 — Set a deployment-level env var (US1)

Through the SDK or GraphiQL:

```python
client.deployment.update(
    deployment_id=deployment_id,
    config={"env_vars": {"LOG_LEVEL": "debug"}},
)
```

Validate:

```bash
kubectl -n styrmin-<deployment-id> get pod -l app.kubernetes.io/name=simple-app \
  -o jsonpath='{.items[*].spec.containers[*].env}' | jq
```

Expected: `LOG_LEVEL=debug` appears in every container's `env:` block.

## Step 2 — Set an environment-level baseline (US2)

```python
client.environment.update(
    environment_id=environment_id,
    config={"env_vars": {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.staging"}},
)
```

Validate against a *second* deployment in the same environment:

```bash
kubectl -n styrmin-<other-deployment-id> get pod ...
```

Expected: `OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.staging` appears on the other deployment's pods, even though no per-deployment env vars are set there.

## Step 3 — Per-component override (US3)

```python
client.deployment.update(
    deployment_id=deployment_id,
    config={
        "env_vars": {"LOG_LEVEL": "info"},
        "components": {
            "worker": {"env_vars": {"LOG_LEVEL": "debug", "WORKER_QUEUE": "orders"}},
        },
    },
)
```

Validate:

```bash
# api pods (component=server)
kubectl ... get pod -l app.kubernetes.io/name=simple-app -o jsonpath='{.items[*].spec.containers[*].env}'
# worker pods
kubectl ... get pod -l app.kubernetes.io/name=simple-app-worker ...
```

Expected:

- `server` pods: `LOG_LEVEL=info`, no `WORKER_QUEUE`.
- `worker` pods: `LOG_LEVEL=debug`, `WORKER_QUEUE=orders`.

## Step 4 — Mutation rejection paths (US3 negative case)

```graphql
mutation {
  updateDeployment(
    deploymentId: "<id>"
    config: { components: { does_not_exist: { env_vars: { X: "y" } } } }
  ) { id }
}
```

Expected: GraphQL error with `extensions.code = "UNKNOWN_COMPONENT_ENV_VAR"` and a message listing the driver's known component names.

Negative cases that should also fail with precise codes:

- `{ env_vars: { "1invalid": "y" } }` → `INVALID_ENV_VAR_NAME`.
- `{ env_vars: { LOG_LEVEL: "y", LOG_LEVEL: "z" } }` (in input list form) → `DUPLICATE_ENV_VAR_NAME`.
- A value over 64 KiB → `ENV_VAR_SIZE_LIMIT_EXCEEDED`.

## Step 5 — Driver-side documentation (US4)

Add to `driver/examples/simple-app/driver.styrmin.yml`:

```yaml
spec:
  # ...existing fields...
  env_vars:
    - name: LOG_LEVEL
      description: Sets the application's log verbosity. Allowed values follow the standard Python logging levels.
      level: deployment
    - name: WORKER_QUEUE
      description: Name of the queue the worker subscribes to.
      level: component
      components: [worker]
```

Re-load the driver, then query:

```graphql
{
  applicationDriverVersion(driverName: "simple-app", version: "1") {
    envVars { name description level components }
  }
}
```

Expected: both entries returned with their declared `level` and `components`.

Negative path: change `components: [worker]` to `components: [does_not_exist]` and re-load. Expected: registration fails with the offending entry surfaced in the error.

## Step 6 — Driver upgrade with orphan (US5)

1. With the per-component env var on `worker` still set (Step 3), upgrade the driver to a version where `worker` has been renamed to `processor`.
2. Wait for the upgrade Task to settle.
3. Query:

   ```graphql
   { deployment(id: "<id>") { componentEnvVars { component envVars { name value } isOrphaned } } }
   ```

   Expected: the `worker` block is returned with `isOrphaned: true`; new `processor` pods do **not** carry `WORKER_QUEUE`.

4. Query the deployment timeline:

   ```graphql
   { deployment(id: "<id>") { timeline { task { id } contextDiff { changes { path action } } } } }
   ```

   Expected: a single timeline entry corresponding to the upgrade Task records the `componentEnvVars.worker` orphan transition.

## Step 7 — Component-level injection opt-out (US6)

Set `inject.env_vars=False` on a `debug-sidecar` component (via `config.components.debug-sidecar.scheduling.inject.env_vars=False`). Set deployment-level env vars. Validate:

```bash
kubectl ... get pod -l <debug-sidecar-selector> -o jsonpath='{.items[*].spec.containers[*].env}'
```

Expected: the `debug-sidecar` pods retain only the chart's original env entries; peer components receive the operator-set env vars.

## Step 8 — Chart conflict warning (US7)

Pick a chart that renders `LOG_LEVEL=warn` in the container env. Set `envVars: { LOG_LEVEL: "debug" }`. Reconcile.

Validate:

```bash
kubectl ... get pod ... | grep LOG_LEVEL
# → LOG_LEVEL=debug

# And query the timeline:
graphql: { deployment(id: ...) { timeline { envVarCollisions { component container name chartValue userValue } } } }
```

Expected: the rendered pod has exactly one `LOG_LEVEL` entry with value `debug`; the timeline entry for the reconcile lists one `EnvVarCollision` for `LOG_LEVEL`.

## Cleanup

```python
client.deployment.update(
    deployment_id=deployment_id,
    config={"env_vars": {}, "components": {}},
)
```

Reconciles the deployment back to the chart-default env entries.

## Failure-mode checklist

| Symptom | Likely cause |
|---|---|
| Env var not visible on pods | `inject.env_vars=False` on the component — check the resolved scheduling.inject. |
| `componentEnvVars` block exists but no values reach pods | `isOrphaned=true` — the driver upgrade renamed/removed the component. |
| Mutation rejected with `UNKNOWN_COMPONENT_ENV_VAR` | Component name in `config.components.<name>.env_vars` does not match the current driver. |
| Driver fails to register | `spec.env_vars` doc references a component not in `spec.components` — fix the doc to match. |
| Chart's value still showing on pods | Conflict detection mis-fired — check `kubectl logs` of the reconcile worker for `env_var_chart_collision` log lines. |
