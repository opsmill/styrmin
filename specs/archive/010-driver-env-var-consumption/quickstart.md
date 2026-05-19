# Quickstart: Driver-Side Env Var Consumption

This walk-through validates the pivot end-to-end. Every step also appears as an assertion in `backend/tests/e2e/test_deployment_env_vars.py` (the 008 E2E that this feature must keep green via driver-side consumption).

## Prerequisites

- A running Styrmin dev stack (`uv run invoke dev-validate` or equivalent).
- The simple-app driver registered, with the **post-010** `values.j2.yml` that consumes `instance.config.env_vars`.
- `kubectl` pointed at the deployment's vcluster.

## Step 1 — Operator sets `LOG_LEVEL=debug` on a simple-app deployment

```python
client.deployment.update(
    deployment_id=deployment_id,
    config={"env_vars": {"LOG_LEVEL": "debug"}},
)
```

Wait for the reconcile to settle.

## Step 2 — Verify the chart's default env entries are intact (FR-014a)

```bash
kubectl -n styrmin-<deployment-id> get pod -l app.kubernetes.io/name=simple-app \
  -o jsonpath='{.items[*].spec.containers[0].env}' | jq
```

Expected: every env entry the simple-app Helm chart sets by default is present, AND `LOG_LEVEL=debug` is also present. The platform did NOT replace, modify, or strip any chart-rendered env entry — the new render path adds operator-set env vars through the chart's own templating, on the same footing as chart-default env entries.

**This is the load-bearing assertion vs 008's broken behaviour.** Under 008, the chart's defaults would be wiped and only `LOG_LEVEL=debug` would survive. The retained E2E test for this scenario MUST explicitly assert at least one chart-default env entry is preserved (FR-014a) — the existing 008 E2E body's "operator-set entry reaches the pod" assertion is necessary but not sufficient; SC-002 requires the chart-default invariant to be exercised as well.

## Step 3 — Verify the broken injection layer is gone

From the repo root:

```bash
grep -rn "EnvVarsPatch\|build_env_vars_post_rendering_patches\|ChartEnvCollision\|envVarCollisions\|env_var_collisions" \
    backend/styrmin_backend/ python_sdk/src/ frontend/src/ schema.graphql
```

Expected: zero hits. (Spec docs under `specs/008-deployment-env-vars/` and `specs/010-driver-env-var-consumption/` may match — that's historical context, not live code.)

Also verify:

```bash
grep -rn "PostRenderInjection.*env_vars\|inject.env_vars" \
    backend/styrmin_backend/ python_sdk/src/ frontend/src/ schema.graphql
```

Expected: zero hits.

## Step 4 — Drop env vars; verify chart-default state

```python
client.deployment.update(
    deployment_id=deployment_id,
    config={"env_vars": {}},
)
```

After reconcile, the pod's container env should reflect ONLY the chart's default entries — the operator-set entries from Step 1 are gone (the values template renders an empty `env:` list from operator-set env vars; chart-default entries remain).

## Step 5 — Driver opt-out demonstration

Register a different driver whose `values.j2.yml` does NOT reference `instance.config.env_vars`. Set env vars on a deployment using this driver. After reconcile, query `Deployment.envVars` — the env vars are stored and visible. Inspect the pod's container env — the operator-set env vars are NOT present (the driver opted out by not consuming them).

This confirms that drivers control consumption. The platform's role is to expose the resolved env-var dict; whether it reaches a pod is the driver author's choice.

## Step 6 — Per-component scoping (multi-component driver)

For a driver that consumes `components[<name>].env_vars.config` per component:

```python
client.deployment.update(
    deployment_id=deployment_id,
    config={
        "env_vars": {"LOG_LEVEL": "info"},
        "components": {
            "worker": {"env_vars": {"WORKER_QUEUE": "orders", "LOG_LEVEL": "debug"}},
        },
    },
)
```

Expected after reconcile:

- The `worker` component's pods carry `LOG_LEVEL=debug` (component-scope wins over deployment-scope per-key) and `WORKER_QUEUE=orders`.
- Other components' pods carry `LOG_LEVEL=info` (the deployment-scope value flows through their `instance.config.env_vars` consumption).
- All chart-default env entries on every component's pods are intact.

## Step 7 — Driver-author guide check

Open `dev/guides/driver-env-var-consumption.md`. Confirm:

- A "How env vars reach your template" section names `instance.config.env_vars` and `components[<name>].env_vars.config`.
- Three worked examples cover: single-component consumption, multi-component consumption, combining chart-default env with operator-set env.
- The guide cross-links to `dev/knowledge/backend/deployment-env-vars.md` (operator-facing) and `dev/adr/adr-013-driver-env-var-consumption.md` (durable record).

## Failure-mode checklist

| Symptom | Likely cause |
|---|---|
| Pod's chart-default env entries are missing after operator sets env vars | The broken injection layer is still in place — verify with Step 3 grep. |
| Operator-set env vars don't reach the pod, but other env vars do | Driver's `values.j2.yml` doesn't consume `instance.config.env_vars` — driver must update. |
| Operator-set env vars reach some pods but not others (multi-component) | Driver's template consumes the per-component dict for some components but not all. Driver author chooses per-component scoping deliberately. |
| Mutation succeeds but pods don't update | Per-deployment no-op detection (009 / FR-010) is correctly skipping the redeploy because the deployment's active instance is already at the new config. Verify by checking the deployment's active-instance config. |
