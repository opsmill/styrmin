---
title: Migrating Container Overrides
sidebar_position: 6
description: Move drivers and deployments from the retired component_command and component_args template filters to the component container.
---

## Migrating Container Overrides

Styrmin now applies the container `command` and `args` overrides users set on a deployment by
itself, after the Helm chart renders. It patches them into the **component container** that the
driver declares for each component, together with env vars and image overrides. The
`component_command` and `component_args` template filters that drivers used to pass these
overrides to the chart are retired, and `spec.container_overrides` is removed from
`driver.styrmin.yml`.

If you arrived here from an error like this one on a deployment:

```text
Failed to create HelmRelease: The 'component_args' template filter was removed: Styrmin now
applies container command and args overrides to each component's declared component
container. ...
```

that deployment is pinned to a driver version whose `values.j2.yml` still calls a retired
filter. Follow [If you run deployments](#if-you-run-deployments) to fix it, and
[If you write drivers](#if-you-write-drivers) to migrate a driver.

### Why it changed

Under the old route, a container override reached the pod only when the driver's
`values.j2.yml` passed it to a chart value. This had three effects:

- When a driver did not call the filters, Styrmin stored the override, never applied it and
  reported no error.
- A user could override only the fields the chart exposes as values. The infrahub chart has no
  `command` value, so the `server` and `task-worker` components of the `infrahub` and
  `infrahub-enterprise` drivers accepted `args` only.
- Each driver author wrote template code that matched how the chart reads the value, so that
  the chart's own `command` and `args` applied when no override was set: an empty list for
  `simple-app`, a `null` for the infrahub charts.

Now the chart renders untouched, and Styrmin replaces the `command` or `args` list of the
component container afterwards. The driver needs no template code, and a user can override
`command` and `args` whether or not the chart exposes them as values.

### If you run deployments

Do these steps in order. With `styrminctl deployments apply`, steps 2 and 3 are one apply: see
[Steps 2 and 3 with `styrminctl apply`](#steps-2-and-3-with-styrminctl-apply).

1. **Load driver versions that no longer call the retired filters.** The example drivers that
   ship in the Styrmin image at `/styrmin/drivers/<name>` are already migrated: `simple-app`
   version 3, `infrahub` version 4 and `infrahub-enterprise` version 3. After upgrading Styrmin,
   reload each one you use, for example:

   ```shell
   uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
   ```

   For your own drivers, load the migrated version from its git repository or directory (see
   [Loading a Driver](./loading-drivers.md)). If the driver is not migrated yet, its author
   needs [If you write drivers](#if-you-write-drivers) first.

2. **Review the stored container overrides of each deployment before you move it.** Styrmin
   now applies a stored `command` or `args` to every component that declares a component
   container, so some stored values reach the pods for the first time:

   - `infrahub` and `infrahub-enterprise`: `command` on `server` and `task-worker`, and
     `command` or `args` on `database`, `cache`, `message-queue` and `task-manager-db`. The old
     templates passed only `args` on `server` and `task-worker`, and both fields on
     `task-manager`.
   - `simple-app`: `command` or `args` on `database`. The old template passed both fields on
     `server` only.
   - A driver whose template never called the filters, such as the `slurpit`, `semaphore`,
     `infrahub-mcp` and `db-test` example drivers: every stored `command` and `args` on a
     component with a component container. These deployments need no move: the values apply
     the next time Styrmin renders the deployment after you upgrade Styrmin. A change to the
     deployment renders it again, and so do an env var edit on its environment and a cluster
     config update that changes its resolved config. Remove the values you do not want before
     any of these happens.

   The **Component Overrides** card on the deployment's **Configuration** tab shows how many
   `command` and `args` entries each component stores. Click **Update Settings** and expand the
   component to view the values. Through the API, `Deployment.componentContainerOverrides`
   returns `command`, `args` and `isApplicable` for each component that stores an override.

   Remove the values you do not want in the same write that moves the deployment (step 3), so
   they never reach the pods.

3. **Move every deployment onto the migrated driver version.** Run an upgrade at the
   deployment's current application version; Styrmin binds it to the newest loaded driver
   version that supports that version (see
   [Selecting a driver version](./loading-drivers.md#selecting-a-driver-version-when-deploying-or-upgrading)):

   ```shell
   uv run styrminctl deployments update-version <deployment-id> <current-application-version>
   ```

   To remove container overrides in the same task, pass the new configuration with
   `--config` (see
   [`deployments update-version`](../reference/styrminctl.md#deployments-update-version)).
   `components` in that payload replaces every stored component block, so include the env
   vars, `command`, `args` and image of every component you keep.

   Do this **before** anything else changes the deployment. A deployment pinned to a driver
   version that calls a retired filter fails its next render, also when it has no override
   set. Changes made elsewhere also render deployments again: an env var edit on an
   environment redeploys every deployment in it, and a cluster config update redeploys each
   deployment whose resolved config changes.

   The pods of a deployment whose render fails keep running. Styrmin does not apply a
   HelmRelease from a failed render, and it does not render a running deployment again until
   something about it changes.

#### Steps 2 and 3 with `styrminctl apply`

Load the migrated driver version (step 1), then remove the `command` and `args` you do not want
from the manifest's `spec.config.components` and keep `spec.version` at the deployment's
application version. Every apply binds the deployment to the newest loaded driver version that
supports `spec.version`, so this apply moves the deployment onto the migrated version (step 3).
It writes `spec.config` together with that change and checks the container overrides against
the migrated version, so the removed values never reach the pods (step 2).

:::note Container overrides on a component without a component container

If the migrated driver version declares no component container for a component, an apply that
adds or changes `command` or `args` on that component is rejected with
`COMPONENT_CONTAINER_NOT_DECLARED`. Every component of the example drivers declares one.

:::

### If you write drivers

1. **Declare a component container on every component that should accept container
   overrides.** If you migrated your driver for env vars (see
   [Migrating Env Var Wiring](./migrating-env-vars.md)), it already has them. Add `container`
   next to the component's `identifier` in `driver.styrmin.yml`:

   ```yaml
   spec:
     components:
       server:
         container: my-app          # receives env vars, the image override, command and args
         identifier:
           label:
             app.kubernetes.io/name: my-app
   ```

   The name must exist in every `Deployment` and `StatefulSet` that the component's first
   identifier label selects. See
   [The component container](./creating-a-driver.md#the-component-container) for how to find
   it. A component without `container` accepts no `command` or `args` override.

2. **Remove every `component_command` and `component_args` call from `values.j2.yml`.** Delete
   the chart keys that only carried the override, and any `{% if %}` block or `null` you wrote
   around them:

   ```jinja
   {# Before, simple-app: the chart skips an empty list #}
   command: {{ components | component_command("server") | tojson }}
   args: {{ components | component_args("server") | tojson }}

   {# Before, infrahub: the chart renders args without a check #}
   infrahubServer:
     infrahubServer:
   {%- if components | component_args("server") %}
       args: {{ components | component_args("server") | tojson }}
   {%- else %}
       args: null
   {%- endif %}

   {# After: nothing. Styrmin patches command and args into each component container. #}
   ```

   Both filters fail the render wherever they appear, also inside `{% if %}` and when no
   override is set. A fixed `command` or `args` that the template sets for its own reasons can
   stay: an override replaces it, and clearing the override brings it back.

3. **Delete `spec.container_overrides` from `driver.styrmin.yml`.** A driver file that still
   contains the block fails to load, like a file with any other unknown key under `spec`:

   ```text
   - spec.container_overrides: Extra inputs are not permitted
   ```

4. **Bump `spec.version` and load the driver.** Users then move their deployments to it (see
   [If you run deployments](#if-you-run-deployments)).

5. **Check the result.** Deploy, set `args` on a component whose chart renders a `command`,
   and read the live pod: the component container has your `args` and the chart's `command`,
   and the other containers are unchanged. Clear the override and the chart's `args` come
   back.

`components.<name>.container_override` stays readable in `values.j2.yml` as read-only data. Do
not write it into a chart key: Styrmin already applies it, and when no override is set the
chart key would no longer hold the chart's own value.

### Behaviour changes to expect

- **Container overrides reach the component container only.** Other containers in the pod,
  init containers, and chart `Job`s and `CronJob`s do not receive them, even if the chart fed
  the same Helm value to them.
- **Only `Deployment` and `StatefulSet` workloads are patched.**
- **The component container moves to the first position.** Once any override applies to a
  component, its component container is `containers[0]` in the pod. This changes the default
  container of `kubectl logs` for pods with several containers.
- **A set field replaces the whole list, and an unset field keeps the chart's value.** An
  `args`-only override replaces the chart's `args` and keeps the chart's `command`. Clearing an
  override brings back the chart's `command` and `args`.
- **An empty list is still rejected.** `command: []` fails with `INVALID_CONTAINER_COMMAND` and
  `args: []` with `INVALID_CONTAINER_ARGS`, so an override cannot remove the chart's `command`
  to fall back to the image's entrypoint.
- **Container overrides need a component container.** Adding or changing `command` or `args`
  on a component without a container fails with `COMPONENT_CONTAINER_NOT_DECLARED`, with the
  `override` metadata set to `command` or `args`. Removing a stored value, or sending the same
  value again, is accepted.
- **The UI follows the driver.** The deployment's Configuration editor hides the Command and
  Args editors for a component without a container, and shows any stored values read-only,
  marked **not applied**, with a remove button.
- **Upgrades keep stored values.** If a driver upgrade drops a component's container, its
  stored `command` and `args` are kept and reported with `isApplicable: false` in the API; they
  are not applied until a driver version declares the container again. `styrminctl deployments
  apply` prints a warning on stderr for a component whose `command`, `args`, env vars or image
  override the manifest sets and the driver version does not apply.
- **A wrong container name fails the release.** The first time any override applies to the
  component, including `command` or `args` alone, the deployment fails with
  `COMPONENT_CONTAINER_NOT_FOUND` and a message naming the component and the container. Styrmin
  never adds a container.
- **Rolling Styrmin back stops container overrides on migrated drivers.** An older Styrmin
  release applies `command` and `args` only through the filters, which the migrated templates
  no longer call. The stored values are kept.

### Next

- [Creating a Driver](./creating-a-driver.md) — the full driver walkthrough, including the
  component container.
- [Migrating Env Var Wiring](./migrating-env-vars.md) — the same migration for env vars.
- [The Context](./context.md) — the fields that stay readable in templates.
