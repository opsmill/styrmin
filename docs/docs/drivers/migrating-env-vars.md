---
title: Migrate env vars to component containers
sidebar_position: 5
description: Move drivers and deployments from the removed component_env_vars template filter to component containers.
---

## Migrate env vars to component containers

Styrmin now adds the env vars that users set on a deployment after the Helm chart renders. Each
driver names one **component container** per component, and Styrmin merges the env vars into
that container by env var name. The `component_env_vars` template filter, which drivers used to
write env vars into their Helm values, is removed.

If you arrived here from an error like this one on a deployment:

```text
Failed to create HelmRelease: The 'component_env_vars' template filter was removed: Styrmin
now injects env vars into each component's declared component container. ...
```

the deployment uses a driver version that still calls the removed filter. Follow
[If you run deployments](#if-you-run-deployments) to fix it, and
[If you write drivers](#if-you-write-drivers) to migrate a driver.

### Why it changed

Before this change, a driver's `values.j2.yml` wrote user env vars into the chart's env key.
When a chart defines env as a list, Helm replaces the whole list, so the chart's default env
vars were removed. The `infrahub` task manager lost `PROMETHEUS_MULTIPROC_DIR` and
`PREFECT_UI_SERVE_BASE` this way, and its pods restarted repeatedly (`CrashLoopBackOff`).

Now Styrmin renders the chart without changes, then merges user env vars into the component
container. The chart's env entries stay. A user env var with the same name as a chart entry
replaces it, including a chart entry that uses `valueFrom`.

### If you run deployments

Do these steps in order. With `styrminctl deployments apply`, steps 2 and 3 are one apply:
see [Steps 2 and 3 with `styrminctl apply`](#steps-2-and-3-with-styrminctl-apply).

1. **Load driver versions that declare component containers.** The example drivers in the
   Styrmin image at `/styrmin/drivers/<name>` are already migrated. After you upgrade Styrmin,
   load each one you use again, for example:

   ```shell
   uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
   ```

   For your own drivers, load the migrated version from its git repository or directory (see
   [Load a driver](./loading-drivers.md)). If the driver is not migrated yet, its author must
   first follow [If you write drivers](#if-you-write-drivers).

2. **Upgrade every deployment to the migrated driver version.** Run an upgrade to the
   deployment's current application version. Styrmin binds the deployment to the newest
   matching driver version (see
   [Selecting a driver version](./loading-drivers.md#selecting-a-driver-version-when-deploying-or-upgrading)):

   ```shell
   uv run styrminctl deployments update-version <deployment-id> <current-application-version>
   ```

   Do this **before** you edit env vars on an environment. An env var edit on an environment
   redeploys every deployment in that environment, and each deployment that still uses an old
   driver version fails to render. A running deployment on an old driver version keeps running:
   Styrmin does not render it again until the deployment changes.

3. **Then set or edit env vars.** On its first reconciliation on the migrated version, a
   deployment removes the env entries that the old template wrote into its Helm values, so
   clearing an env var later restores the chart default.

#### Steps 2 and 3 with `styrminctl apply`

Load the migrated driver version (step 1), then add the component env vars to the manifest and
keep `spec.version` at the deployment's application version. Every apply binds the deployment
to the newest loaded driver version that supports `spec.version`, so this apply moves the
deployment onto the migrated version (step 2). It writes `spec.config` together with that
change and checks the env vars against the migrated version, so it sets them in the same
reconciliation (step 3).

Upgrade before an environment env var edit, as in step 2: apply every manifest of the
environment before you edit its env vars.

:::note Env vars on a component that the migrated version removes

If the migrated driver version removes or renames a component, an apply that still sets env
vars on that component is rejected with `UNKNOWN_COMPONENT_ENV_VAR`. Remove them from the
manifest in the same change.

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

   In `rendered.yaml`, find the `Deployment` or `StatefulSet` whose `metadata.labels` include
   the identifier label, and read the application container's name under
   `spec.template.spec.containers`.

   A component without `container` accepts no component-scope env vars, and Styrmin does not
   apply deployment-scope or environment-scope env vars to it.

2. **Remove every `component_env_vars` call from `values.j2.yml`.** Delete the keys that
   contained only user env vars, such as `extraEnv` or `extraEnvVars`:

   ```yaml
   # Before
   extraEnv: {{ components | component_env_vars("server") | tojson }}
   postgresql:
     primary:
       extraEnvVars: {{ components | component_env_vars("database") | tojson }}

   # After: nothing. Styrmin adds env vars to each component container.
   ```

3. **Move fixed env entries out of chart env lists.** If the template still sets a chart env
   list only to add your own fixed entries, that list still replaces the chart's defaults. Put
   fixed entries in a key that the chart merges (a map, or a secondary env list), or remove
   them. Do not copy the chart's defaults into the template. The
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

   Fixed entries that the chart reads as a map (for example
   `infrahubServer.infrahubServer.env` in the infrahub chart) can stay as they are.

4. **Increase `spec.version` and load the driver.** Users then upgrade their deployments to it
   (see [If you run deployments](#if-you-run-deployments)).

5. **Check the result.** Deploy, set an env var that has the same name as a chart default,
   and read the live pod: the user value replaces the default, and every other chart entry is
   still there. Clear it, and Styrmin restores the chart default.

`instance.config.env_vars` and `components.<name>.env_vars.config` are still readable in
`values.j2.yml`, for example to build a ConfigMap. Do not write them into a chart env key:
Styrmin already adds them, and Helm would replace the chart's env list again.

### Behavior changes

- **Styrmin adds env vars only to the component container.** Other containers in the pod, init
  containers, and chart `Job`s and `CronJob`s no longer receive user env vars, even if the
  chart passed the same Helm value to them. For example, a chart that passed its server env
  list to a database migration Job no longer gives that Job the user's env vars.
- **Only `Deployment` and `StatefulSet` workloads are patched.**
- **User entries come first.** In the container's env list, user env vars come before the
  chart's remaining entries, and the component container moves to the first position in the
  pod. A chart entry that references a user env var with `$(USER_VAR)` expands; a user value
  that references a chart entry with `$(CHART_VAR)` does not.
- **Component-scope env vars need a component container.** Adding or changing one on a
  component without a container fails with `COMPONENT_CONTAINER_NOT_DECLARED`; the error lists
  the components that accept env vars. Removing stored values is always allowed. Styrmin does
  not apply deployment-scope and environment-scope env vars to such components, and reports no
  error.
- **The UI shows env var editors only for components with a container.** For a component
  without a container, the deployment's **Edit configuration** drawer hides the env var editor and
  shows any stored values read-only, with a remove button. The driver's **Components** tab shows each component's container, or
  **None declared**.
- **Upgrades keep stored values.** If a driver upgrade removes a component's container, its
  stored component-scope env vars are kept and reported with `isApplicable: false` in the
  API. Styrmin does not add them until a driver version declares the container again.
- **A wrong container name fails the release.** The first time an env var (or an image
  override) is set on the component, the deployment fails with `COMPONENT_CONTAINER_NOT_FOUND`
  and a message that names the component and the container. Styrmin never adds a container.
- **A rollback of Styrmin stops adding env vars.** After you load migrated drivers, an older
  Styrmin release does not add env vars to their containers: it ignores `container`, and the
  migrated values templates no longer write env vars.

### Next steps

- [Create a driver](./creating-a-driver.md) — how to write a driver, including the component
  container.
- [The context](./context.md) — the env var fields that stay readable in templates.
