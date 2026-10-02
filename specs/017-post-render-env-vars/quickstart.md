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
uv run pytest backend/tests/unit/agent/test_container_env_patch.py \
  backend/tests/unit/services/env_vars/test_patch_builder.py \
  backend/tests/unit/agent/test_application_builder_env_vars.py -v
```

Expected: each patch names only the component container and sets `valueFrom: null` on every
entry; one Deployment and one StatefulSet patch per component that has a container and env vars,
none otherwise; env patches come after every other patch in `postRenderers[0].kustomize.patches`.

Manual cross-check against real kustomize: render the two `ContainerEnvPatch` target patches for
`container: simple-app`, `LOG_LEVEL=debug` (label `app.kubernetes.io/name=simple-app`) into a
`kustomization.yaml` whose `resources` is the `helm template` output of
`driver/examples/simple-app/src/helm`, and run `kubectl kustomize .`. The `simple-app` container
lists `LOG_LEVEL` first, then the chart's `DB_USERNAME`, `DB_PASSWORD`, `DATABASE_URL`,
`STYRMIN_CHART_DEFAULT`, `STYRMIN_CHART_DEFAULT_FROM`; patched names move to the front.

## 2. Driver load and retired filter

```bash
uv run pytest backend/tests/unit/services/driver/test_component_container.py \
  backend/tests/unit/services/driver/test_example_drivers_container.py \
  backend/tests/unit/agent/test_render_value_template_env_vars.py -v
```

Expected: a driver with `components.server.container: simple-app` loads; `container: Simple_App`
fails registration; every example driver declares a container for each component and no
`values.j2.yml` calls `component_env_vars`; a template calling it fails rendering with
`RETIRED_TEMPLATE_FILTER` naming the migration guide (metadata `filter`, `migration_guide`).

## 3. Write validation and read flags (propagation)

```bash
uv run pytest backend/tests --ignore=backend/tests/e2e \
  -k "component_container_not_declared or is_applicable or component_container_propagat" -v
```

Expected: a new component-scope env var on a containerless component returns
`COMPONENT_CONTAINER_NOT_DECLARED` (metadata `component_name`, `components_with_container`) and
submits no task; removals and an unchanged re-submission succeed;
`Deployment.componentEnvVars[].isApplicable`, `Deployment.components[].container`, and
`ApplicationDriverVersion.componentConfigs[].container` read back as stored.

## 4. US1 end to end (simple-app, both entrypoints)

Each entrypoint needs its own pytest session (one cluster per Styrmin install):

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_deployment_env_vars.py" \
  -k "component_env_var_merges_into_chart_env and api-chromium" -v -s --pdb 2>&1 | tee /tmp/us1-api.log
sleep infinity | uv run pytest "backend/tests/e2e/test_deployment_env_vars.py" \
  -k "component_env_var_merges_into_chart_env and ui-chromium" -v -s --pdb 2>&1 | tee /tmp/us1-ui.log
```

`sleep infinity |` keeps pdb alive on failure, so a session never exits on its own: stop it once
its summary line prints. Expected for `[api-chromium]` and `[ui-chromium]`:

1. `LOG_LEVEL=debug` on `server` → the `simple-app` container has `LOG_LEVEL=debug`,
   `STYRMIN_CHART_DEFAULT=marker`, and the `STYRMIN_CHART_DEFAULT_FROM` `fieldRef`.
2. `STYRMIN_CHART_DEFAULT=override` and `STYRMIN_CHART_DEFAULT_FROM=literal` → the container
   shows both literals; `STYRMIN_CHART_DEFAULT_FROM` no longer has a `valueFrom`.
3. A stray `extraEnv` entry `STALE_VALUES_ENV` merge-patched into the live HelmRelease
   `spec.values` renders into the container (a pre-migration render).
4. Clear all three → `LOG_LEVEL` and `STALE_VALUES_ENV` absent, `STYRMIN_CHART_DEFAULT=marker`
   and the `fieldRef` back, and the HelmRelease `spec.values` carries neither name (FR-011).

Inspect while paused:

```bash
export KUBECONFIG=$(ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1)
kubectl get helmrelease -A -o jsonpath='{.items[*].spec.postRenderers[0].kustomize.patches[-2:]}'
kubectl get deploy -A -l app.kubernetes.io/name=simple-app -o jsonpath='{.items[0].spec.template.spec.containers[0].env}'
```

## 5. US2 regression and SC-003

Both modules' scenarios are `api_only`, so only `[api-chromium]` runs (one session each):

```bash
sleep infinity | uv run pytest backend/tests/e2e/test_deployment_env_vars.py \
  -k "(us2 or us3) and api-chromium" -v -s --pdb
sleep infinity | uv run pytest backend/tests/e2e/test_infrahub_services.py -k api-chromium -v -s --pdb
```

Expected: deployment/environment-scope env vars reach every component container with
deepest-wins precedence; the enterprise task manager is Ready and its `prefect-server` container
carries the chart default `PREFECT_UI_SERVE_BASE=/` and `PREFECT_SERVER_ANALYTICS_ENABLED=True`.

## 6. Frontend

```bash
cd frontend && pnpm test ComponentOverridesSection
```

Expected: a component whose `container` is null gets no env var editor and a message explaining
why; stored values show read-only with a working remove control; components with a container keep
the editable editor.

## 7. Docs and changelog

```bash
cd docs && pnpm build
uv run invoke release.draft
```

Expected: the migration guide at `/docs/drivers/migrating-env-vars` builds; the draft changelog
lists the `removed` (filter) and `changed` (injection) fragments.
