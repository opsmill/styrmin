# Driver Env Var Consumption Guide

This guide is for **driver authors**. It covers what a driver must declare so user-set
environment variables reach its pods, what Styrmin then does on its own, and the failure
modes to check for.

The short version: declare one **component container** per component in
`driver.styrmin.yml`, and do not wire user env vars into the chart's env values in
`values.j2.yml`. Styrmin merges each
component's resolved env vars into that container after the chart renders, by env var
`name`, so the chart's own env entries survive.

For the user-facing reference (where env vars are set, validated, and queried), see
[`dev/knowledge/backend/deployment-env-vars.md`](../knowledge/backend/deployment-env-vars.md).
The decision record is [ADR-057](../adr/0057-post-render-component-overrides.md). Drivers
written for the retired values-template route should follow the
[migration guide](../../docs/docs/drivers/migrating-env-vars.md).

## Declare the component container

Add `container` to each component that should receive env vars:

```yaml
# driver.styrmin.yml
spec:
  components:
    server:
      container: simple-app        # the container that receives env vars
      identifier:
        label:
          app.kubernetes.io/name: simple-app
    database:
      container: postgresql
      identifier:
        label:
          app.kubernetes.io/name: postgresql
```

- The value must be a Kubernetes container name (lowercase alphanumerics and `-`, starting
  and ending with an alphanumeric, at most 63 characters). A malformed value fails driver
  registration.
- It is optional. A component without it accepts no component-scope env vars (writes are
  rejected with `COMPONENT_CONTAINER_NOT_DECLARED`) and is skipped silently for deployment-
  and environment-scope env vars.
- One name per component. Pick the application container, not a sidecar.

Find the name by rendering the chart with your driver's values and reading the pod template
of every `Deployment` and `StatefulSet` the component's identifier label selects:

```bash
helm template styrmin-my-app <chart> -f rendered-values.yaml \
  | yq 'select(.kind == "Deployment" or .kind == "StatefulSet")
        | [.metadata.name, .metadata.labels, .spec.template.spec.containers[].name]'
```

The patch targets workloads by the component's **first** identifier label, matched against
the workload's own `metadata.labels` (a Kustomize `target.labelSelector` matches the
resource, not its pods). Most charts put the same labels on both; check that yours does.
[`specs/archive/017-post-render-env-vars/driver-containers.md`](../../specs/archive/017-post-render-env-vars/driver-containers.md)
records the command and result for every in-repo driver.

## No template wiring

`values.j2.yml` does not inject env vars. Do not write the chart's `env`, `extraEnv`, or
`extraEnvVars` keys with user values: Helm replaces lists wholesale, which is what dropped
chart defaults under the retired route.

The `component_env_vars` filter is retired. Loading a driver version that calls it fails with
`RETIRED_TEMPLATE_FILTER` and names the line of the call. A driver version loaded before that
check fails rendering with the same code; the deployment reports
`Failed to create HelmRelease: The 'component_env_vars' template filter was removed: …`.

Keep hard-coded chart wiring in the template where the chart reads a map or a dedicated key.
Where the chart's env is a list that also carries chart defaults, put your hard-coded entry
in a slot that does not replace those defaults instead of copying the defaults into the
template. The infrahub drivers set `PREFECT_SERVER_ANALYTICS_ENABLED` under
`global.prefect.env` (which the prefect-server subchart merges under `server.env`) rather than
overriding `prefect-server.server.env`.

### Read-only context fields

The resolved env vars stay in the rendering context for non-injection uses, such as building
a ConfigMap or switching a chart feature on a value:

| Field | Shape | What it carries |
|---|---|---|
| `instance.config.env_vars` | `dict[str, str]` | Deployment-effective env vars (environment → deployment, deepest-wins). |
| `components[<name>].env_vars.config` | `dict[str, str]` | Per-component env vars (environment → deployment → component, deepest-wins). |

Both keys are absent when nothing is set (the context is dumped with `exclude_none=True`), so
guard with `or {}`. Writing these values into a chart env key brings the list-replacement
problem back; Styrmin already injects them.

## What Styrmin does

For each component with a component container and at least one resolved env var, the
HelmRelease gains two strategic-merge Kustomize patches (one targeting `Deployment`, one
`StatefulSet`), appended after every other post-render patch. For a component `server` with
container `simple-app` and `LOG_LEVEL=debug`, the patch body is:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: any
spec:
  template:
    spec:
      containers:
      - name: simple-app
        env:
        - name: LOG_LEVEL
          value: debug
          valueFrom: null
```

The result on the rendered workload:

- chart env entries the user did not name are kept;
- a user entry with the same name as a chart entry replaces it, including a chart
  `valueFrom` entry;
- entries the user clears disappear on the next reconcile; the chart's value comes back;
- values are passed as strings that Styrmin does not escape, coerce, or expand (`"true"`,
  `"0123"`, and multi-line values arrive as written); Kubernetes still applies its normal
  `$(VAR)` expansion to references to earlier entries (see "Ordering and `$(VAR)` references"
  below);
- the user value wins over the same key from the chart's `envFrom` (Kubernetes `env` over
  `envFrom` precedence).

Precedence between scopes is resolved before the patch is built: per-key deepest-wins,
environment → deployment → component. Disabled components still get the patch; their replica
count is managed separately.

### Ordering and `$(VAR)` references

The merge puts every user entry, new or replacing, **before** the chart's remaining entries,
and moves the component container to `containers[0]` of the pod. Kubernetes expands a
`$(VAR)` reference only to entries listed earlier, so:

- a chart entry that references a user var (`$(USER_VAR)`) expands;
- a user value that references a chart var (`$(CHART_VAR)`) does not;
- user entries are ordered environment keys first, then keys new at deployment scope, then
  keys new at component scope; a key overridden by a deeper scope keeps its earlier position.
  A user-to-user reference expands only when the referenced key comes first.

This is the current behaviour of the kyaml strategic-merge engine in Flux's post-renderer,
not a documented Kubernetes contract. Do not build on the exact order.

A multi-container component reorders its containers once, when its first env var is set.
`kubectl logs` without `-c` picks the first container (unless the pod sets the
`kubectl.kubernetes.io/default-container` annotation), which is now the component container.

### Scope: Deployment and StatefulSet, one container

Only the component container of `Deployment` and `StatefulSet` workloads receives user env
vars. These do not:

- other containers in the same pod (sidecars);
- init containers;
- `Job`, `CronJob`, and `DaemonSet` workloads, including chart migration and hook Jobs that
  share the component's label.

If your application needs a user value in a Job, read it from the context and template it
explicitly. Action Jobs started with `execute_commands(env_from_component=...)` copy the
env of the component container (else the pod template's first container) and set the env
vars of the action's context on top, so env vars set in the apply that changes the version
reach the upgrade Job. An env var removed in that apply is still copied from the workload.

## Failure modes to check

- **Wrong container name.** The post-render guard fails the Helm release with
  `error in remove for path: '/spec/template/spec/styrmin.io~1component-container~1<component>~1<container>/image'`,
  and the operator fails the deployment with `COMPONENT_CONTAINER_NOT_FOUND`, naming the
  component and the container; Styrmin never adds a container. Nothing fails until a user
  first sets an env var, an image override, or a `command` or `args` override on that
  component, so verify the name when you write the driver.
- **Identifier label not on the workload.** If the first identifier label matches only pods,
  or only a kind other than `Deployment`/`StatefulSet`, the patch matches nothing and the env
  vars silently never arrive.
- **One label, several workloads.** Every matched `Deployment` and `StatefulSet` gets the
  patch, so each must contain the named container.
- **Container dropped in a driver upgrade.** Stored component-scope env vars are kept and
  read back with `isApplicable: false`; they are not injected until a version declares the
  container again.

## Verifying a driver

1. Load the driver and deploy it.
2. Set a component-scope env var whose name matches a chart default, for example through the
   deployment's Configuration tab.
3. Read the live pod template and confirm the container carries the user value and every
   other chart entry:

   ```bash
   kubectl get deploy,statefulset -n <namespace> -l <identifier-label> \
     -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{.spec.template.spec.containers[0].env}{"\n"}{end}'
   ```

4. Clear the env var and confirm the chart default is back.

## Extending the renderer

The Jinja environment for `values.j2.yml` is built in
`backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py:get_jinja_environment`.
Custom filters (`to_fqdn_label`, `split`, and the retired `component_env_vars`,
`component_command` and `component_args` stubs) are registered there. Add a unit test that
drives a new filter through `ApplicationHelmReleaseBuilder.render_value_template`
(see `backend/tests/unit/agent/test_render_value_template_env_vars.py`).

The env var patches are built by `build_component_container_patches()` in
`backend/styrmin_backend/services/component_container/patch_builder.py` and rendered by
`ContainerMergePatch` (the merge, which also carries `command` and `args` overrides) and
`ComponentContainerPatch` (the guard) in
`backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py`.

## Related

- [ADR-057](../adr/0057-post-render-component-overrides.md) — the decision, ordering facts, and
  consequences.
- [ADR-013](../adr/0013-driver-env-var-consumption.md) — the retired values-template route
  (superseded in part).
- [`dev/knowledge/backend/deployment-env-vars.md`](../knowledge/backend/deployment-env-vars.md) —
  scopes, validation, read surface.
- [`docs/docs/drivers/migrating-env-vars.md`](../../docs/docs/drivers/migrating-env-vars.md) —
  user and driver-author migration steps.
- [ADR-069](../adr/0069-container-command-args-by-post-render.md) and
  [`docs/docs/drivers/migrating-container-overrides.md`](../../docs/docs/drivers/migrating-container-overrides.md) —
  `command` and `args` overrides, which use the same component container and patches.
- Reference driver: `driver/examples/simple-app/driver.styrmin.yml` and
  `driver/examples/simple-app/src/helm/templates/deployment.yaml` (the `STYRMIN_CHART_DEFAULT`
  and `STYRMIN_CHART_DEFAULT_FROM` entries are the chart defaults the E2E asserts survive).
