---
title: Migrating Env Var Wiring
sidebar_position: 5
description: Move drivers and deployments from the removed component_env_vars template filter to component containers.
---

## Migrating Env Var Wiring

Styrmin now injects the env vars users set on a deployment by itself, after the Helm chart
renders. Each driver names one **component container** per component, and Styrmin merges the
env vars into that container by env var name. The `component_env_vars` template filter that
drivers used to write env vars into their Helm values is removed.

If you arrived here from an error like this one on a deployment:

```text
Failed to create HelmRelease: The 'component_env_vars' template filter was removed: Styrmin
now injects env vars into each component's declared component container. ...
```

that deployment is pinned to a driver version written for the old route. Follow
[If you run deployments](#if-you-run-deployments) to fix it, and
[If you write drivers](#if-you-write-drivers) to migrate a driver.

### Why it changed

Under the old route, a driver's `values.j2.yml` wrote user env vars into the chart's env
key. When a chart models env as a list, Helm replaces the whole list, so every default env
var the chart ships was dropped. The `infrahub` task manager lost `PROMETHEUS_MULTIPROC_DIR`
and `PREFECT_UI_SERVE_BASE` this way and crash-looped.

Now the chart renders untouched and Styrmin merges user env vars into the component
container afterwards. Chart env entries survive. A user env var with the same name as a chart
entry replaces it, including a chart entry that uses `valueFrom`.

### If you run deployments

Do these steps in order.

1. **Load driver versions that declare component containers.** The example drivers that ship
   in the Styrmin image at `/styrmin/drivers/<name>` are already migrated. After upgrading
   Styrmin, reload each one you use, for example:

   ```shell
   uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
   ```

   For your own drivers, load the migrated version from its git repository or directory (see
   [Loading a Driver](./loading-drivers.md)). If the driver is not migrated yet, its author
   needs [If you write drivers](#if-you-write-drivers) first.

2. **Upgrade every deployment onto the migrated driver version.** Re-run an upgrade at the
   deployment's current application version; Styrmin re-resolves it to the newest matching
   driver build (see
   [Selecting a driver version](./loading-drivers.md#selecting-a-driver-version-when-deploying-or-upgrading)):

   ```shell
   uv run styrminctl deployments update-version <deployment-id> <current-application-version>
   ```

   Do this **before** you edit env vars on an environment. An environment env var edit
   redeploys every deployment in that environment, and each one still pinned to an old driver
   version fails rendering. A running deployment on an old version keeps running: Styrmin does
   not re-render it until something about it changes.

3. **Then set or edit env vars.** On its first reconcile on the migrated version, a deployment
   drops the env entries the old template wrote into its Helm values, so clearing an env var
   later brings the chart default back.

:::note With `styrminctl apply`

`apply` writes `spec.config` together with the version change, and checks it against the driver
version the manifest moves to. One manifest can move a deployment onto a migrated driver version
and add component env vars in the same apply.

:::

### If you write drivers

1. **Declare a component container on every component.** Add `container` next to the
   component's `identifier` in `driver.styrmin.yml`:

   ```yaml
   spec:
     components:
       server:
         container: my-app          # the container that receives env vars
         identifier:
           label:
             app.kubernetes.io/name: my-app
   ```

   The name must be a Kubernetes container name, and it must exist in every `Deployment`
   and `StatefulSet` the component's first identifier label selects (matched against the
   workload's own labels). Find it by rendering the chart with your driver's values:

   ```shell
   helm template styrmin-my-app <chart> -f rendered-values.yaml > rendered.yaml
   ```

   In `rendered.yaml`, find the `Deployment` or `StatefulSet` whose `metadata.labels` carry
   the identifier label, and read the application container's name under
   `spec.template.spec.containers`.

   A component without `container` accepts no component-scope env vars and is skipped for
   deployment- and environment-scope ones.

2. **Remove every `component_env_vars` call from `values.j2.yml`.** Delete the keys that only
   carried user env vars, such as `extraEnv` or `extraEnvVars`:

   ```yaml
   # Before
   extraEnv: {{ components | component_env_vars("server") | tojson }}
   postgresql:
     primary:
       extraEnvVars: {{ components | component_env_vars("database") | tojson }}

   # After: nothing. Styrmin injects env vars into each component container.
   ```

3. **Move hard-coded env out of chart env lists instead of copying chart defaults.** If the
   template still sets a chart env list only to add your own fixed entries, that list still
   replaces the chart's defaults. Put fixed entries in a key the chart merges (a map, or a
   secondary env list), or drop them. Do not copy the chart's defaults into the template. The
   `infrahub` driver used to override the Prefect server's env list to set one flag:

   ```yaml
   # Before: replaces the chart's server.env defaults
   prefect-server:
     server:
       env:
         - name: PREFECT_SERVER_ANALYTICS_ENABLED
           value: "false"

   # After: the subchart merges global.prefect.env under its own server.env defaults
   prefect-server:
     global:
       prefect:
         env:
           - name: PREFECT_SERVER_ANALYTICS_ENABLED
             value: "false"
   ```

   Hard-coded entries the chart reads as a map (for example
   `infrahubServer.infrahubServer.env` in the infrahub chart) can stay as they are.

4. **Bump `spec.version` and load the driver.** Users then upgrade their deployments to it
   (see [If you run deployments](#if-you-run-deployments)).

5. **Check the result.** Deploy, set an env var that has the same name as a chart default,
   and read the live pod: the user value replaces the default, and every other chart entry is
   still there. Clear it and the chart default comes back.

`instance.config.env_vars` and `components.<name>.env_vars.config` are still readable in
`values.j2.yml`, for example to build a ConfigMap. Do not write them into a chart env key:
Styrmin already injects them, and the list replacement problem comes back.

### Behaviour changes to expect

- **Env vars reach the component container only.** Other containers in the pod, init
  containers, and chart `Job`s and `CronJob`s no longer receive user env vars, even if the
  chart fed the same Helm value into them. For example, a chart that passed its server env
  list to a database migration Job no longer gives that Job the user's env vars.
- **Only `Deployment` and `StatefulSet` workloads are patched.**
- **User entries come first.** In the container's env list, user env vars come before the
  chart's remaining entries, and the component container moves to the first position in the
  pod. A chart entry that references a user env var with `$(USER_VAR)` expands; a user value
  that references a chart entry with `$(CHART_VAR)` does not.
- **Component-scope env vars need a component container.** Adding or changing one on a
  component without a container fails with `COMPONENT_CONTAINER_NOT_DECLARED`; the error lists
  the components that accept env vars. Removing stored values is always allowed. Deployment-
  and environment-scope env vars skip such components without an error.
- **The UI follows the driver.** The deployment's Configuration editor hides the env var
  editor for a component without a container and shows any stored values read-only with a
  remove button. The driver's **Components** tab shows each component's container, or
  **None declared**.
- **Upgrades keep stored values.** If a driver upgrade drops a component's container, its
  stored component-scope env vars are kept and reported with `isApplicable: false` in the
  API; they are not injected until a driver version declares the container again.
- **A wrong container name fails the release.** The first time an env var (or an image
  override) is set on the component, the deployment fails with `COMPONENT_CONTAINER_NOT_FOUND`
  and a message naming the component and the container. Styrmin never adds a container.
- **Rolling Styrmin back stops injection.** After you load migrated drivers, an older Styrmin
  release does not inject env vars into them: it ignores `container`, and the migrated values
  templates no longer write env vars.

### Next

- [Creating a Driver](./creating-a-driver.md) — the full driver walkthrough, including the
  component container.
- [The Context](./context.md) — the env var fields that stay readable in templates.
