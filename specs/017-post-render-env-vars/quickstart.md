# Quickstart: Validating Post-Render Env Var Injection

**Feature**: 017-post-render-env-vars | Contracts: [post-render-patch.md](contracts/post-render-patch.md),
[graphql-deltas.md](contracts/graphql-deltas.md), [errors.md](contracts/errors.md)

## Prerequisites

- `uv sync` and `cd frontend && pnpm install` done.
- `vcluster` and `docker` on PATH (E2E fixtures boot their own cluster — see
  `dev/knowledge/backend/e2e-testing.md`).
- `kubectl` with built-in kustomize (≥ v5) for the offline patch check.

## 1. Offline: the patch merges by name

```bash
uv run pytest backend/tests/unit -k "container_env_patch or env_var_patch_builder" -v
```

Expected: chart entries kept, same-name entries replaced (including `valueFrom`), no patch for a
component without a container or without env vars, env patches last in `postRenderers`.

Manual cross-check against real kustomize: render a HelmRelease for simple-app with
`LOG_LEVEL=debug` on `server`, copy its `postRenderers[0].kustomize.patches` into a
`kustomization.yaml` next to `helm template` output of `driver/examples/simple-app/src/helm`, and
run `kubectl kustomize .`. The `simple-app` container lists `LOG_LEVEL` first, then
`DB_USERNAME`, `DB_PASSWORD`, `DATABASE_URL`, `STYRMIN_CHART_DEFAULT`.

## 2. Driver load and retired filter

```bash
uv run pytest backend/tests/unit -k "component_container or retired_template_filter" -v
```

Expected: a driver with `components.server.container: simple-app` loads; `container: Simple_App`
fails registration; a `values.j2.yml` calling `component_env_vars` fails rendering with
`RETIRED_TEMPLATE_FILTER` naming the migration guide.

## 3. Write validation and read flags (propagation)

```bash
uv run pytest backend/tests -k "component_container_not_declared or is_applicable or component_container_propagation" -v
```

Expected: a new component-scope env var on a containerless component returns
`COMPONENT_CONTAINER_NOT_DECLARED` and submits no task; an unchanged re-submission succeeds;
`componentEnvVars[].isApplicable` and `components[].container` / `componentConfigs[].container`
read back as stored.

## 4. US1 end to end (simple-app, both entrypoints)

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_deployment_env_vars.py" \
  -k "component_env_var_merges_into_chart_env" -v -s --pdb 2>&1 | tee /tmp/us1.log
```

Expected for `[api-chromium]` and `[ui-chromium]`:

1. `LOG_LEVEL=debug` on `server` → the `simple-app` container has `LOG_LEVEL=debug` and
   `STYRMIN_CHART_DEFAULT=marker`.
2. `STYRMIN_CHART_DEFAULT=override` and `STYRMIN_CHART_DEFAULT_FROM=literal` → the container
   shows both literals; `STYRMIN_CHART_DEFAULT_FROM` no longer has a `valueFrom`.
3. Clear all three → `LOG_LEVEL` absent, `STYRMIN_CHART_DEFAULT=marker` and the
   `STYRMIN_CHART_DEFAULT_FROM` `fieldRef` back.
4. A stray `extraEnv` entry seeded into the live HelmRelease `spec.values` is gone after the
   next reconcile (FR-011).

Inspect while paused:

```bash
export KUBECONFIG=$(ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1)
kubectl get helmrelease -A -o jsonpath='{.items[*].spec.postRenderers[0].kustomize.patches[-1:]}'
kubectl get deploy -A -l app.kubernetes.io/name=simple-app -o jsonpath='{.items[0].spec.template.spec.containers[0].env}'
```

## 5. US2 regression and SC-003

```bash
sleep infinity | uv run pytest backend/tests/e2e/test_deployment_env_vars.py -k "us2 or us3" -v -s --pdb
sleep infinity | uv run pytest backend/tests/e2e/test_infrahub_services.py -v -s --pdb
```

Expected: deployment/environment-scope env vars reach every component container with
deepest-wins precedence; the enterprise task manager is Ready and its `prefect-server` container
carries the chart default `PREFECT_UI_SERVE_BASE=/`.

## 6. Frontend

```bash
cd frontend && pnpm test -- ComponentOverridesSection
```

Expected: the env var editor is disabled for a component whose `container` is null, with stored
values shown read-only and removable.

## 7. Docs and changelog

```bash
cd docs && pnpm build
uv run towncrier build --draft
```

Expected: the migration guide at `/docs/drivers/migrating-env-vars` builds; the draft changelog
lists the `removed` (filter) and `changed` (injection) fragments.
