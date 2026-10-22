---
title: Migrate command and args overrides to component containers
sidebar_position: 6
description: Move drivers and deployments from the retired component_command and component_args template filters to the component container.
---

## Migrate command and args overrides to component containers

Styrmin now applies the container `command` and `args` overrides that users set on a deployment
after the Helm chart renders. It patches them into the **component container** that the driver
declares for each component, together with env vars and image overrides. The
`component_command` and `component_args` template filters, which drivers used to pass these
overrides to the chart, are retired, and `spec.container_overrides` is removed from
`driver.styrmin.yml`.

If you arrived here from an error like this one on a deployment:

```text
Failed to create HelmRelease: The 'component_args' template filter was removed: Styrmin now
applies container command and args overrides to each component's declared component
container. ...
```

the deployment uses a driver version whose `values.j2.yml` still calls a retired filter. Follow [If you run deployments](#if-you-run-deployments) to fix it, and
[If you write drivers](#if-you-write-drivers) to migrate a driver.

If you arrived here from an error while loading a driver:

```text
values.j2.yml line 12 calls the 'component_args' template filter, which was removed: ...
```

that driver version is not migrated yet, and Styrmin does not load it. Follow
[If you write drivers](#if-you-write-drivers).

### Why it changed

Before this change, a container override reached the pod only when the driver's
`values.j2.yml` passed it to a chart value. This had three effects:

- When a driver did not call the filters, Styrmin stored the override, never applied it and
  reported no error.
- A user could override only the fields the chart exposes as values. The infrahub chart has no
  `command` value, so the `server` and `task-worker` components of the `infrahub` and
  `infrahub-enterprise` drivers accepted `args` only.
- Each driver author wrote template code that matched how the chart reads the value, so that
  the chart's own `command` and `args` applied when no override was set: an empty list for
  `simple-app`, a `null` for the infrahub charts.

Now Styrmin renders the chart without changes, then replaces the `command` or `args` list of
the component container. The driver needs no template code, and a user can override
`command` and `args` whether or not the chart exposes them as values.

### If you run deployments

#### Before you upgrade Styrmin

After the upgrade, Styrmin applies the stored `command` and `args` of every component that
declares a component container, and any new render of a deployment applies them. A render
happens on a change to the deployment, and also on changes other users make: an env var edit
on the deployment's environment, or a cluster config update that changes its resolved config.
So remove the values you do not want while you still run the Styrmin release you have now.

This matters most for deployments of a driver whose template never called the filters, such
as the `slurpit`, `semaphore`, `infrahub-mcp` and `db-test` example drivers. Styrmin stored
their `command` and `args` but never applied them. After the upgrade, Styrmin applies them on
the next render, even if the deployment stays on its driver version.

1. **List the stored `command` and `args` of each deployment.** The `Config:` line of
   `styrminctl deployments get` shows `components`, and each component block shows its
   `command` and `args`:

   ```shell
   uv run styrminctl deployments get <deployment-id>
   ```

   Through the API, `Deployment.componentContainerOverrides` returns them for each component
   that stores one:

   ```graphql
   query {
     deployment(deploymentId: "<deployment-id>") {
       componentContainerOverrides { component command args isOrphaned }
     }
   }
   ```

2. **Remove the values you do not want, with the CLI or the API.** The **Edit configuration** drawer of
   releases before this one cannot submit a change that only removes `command` or `args`.
   `components` in the payload replaces every stored component block, so include the env vars,
   image, `command` and `args` of every component you keep:

   ```shell
   uv run styrminctl deployments update <deployment-id> --config @config.json
   ```

   ```json
   {
     "components": [
       { "name": "server", "envVars": [{ "name": "LOG_LEVEL", "value": "debug" }] },
       { "name": "worker", "args": ["--queue", "low"] }
     ]
   }
   ```

   If you manage the deployment with a manifest, remove the values from
   `spec.config.components` and run `styrminctl deployments apply` instead. Either way, Styrmin
   redeploys the deployment on its current driver version.

#### After you upgrade Styrmin

Do these steps in order. With `styrminctl deployments apply`, steps 2 and 3 are one apply: see
[Steps 2 and 3 with `styrminctl apply`](#steps-2-and-3-with-styrminctl-apply).

1. **Load driver versions that no longer call the retired filters.** The example drivers in
   the Styrmin image at `/styrmin/drivers/<name>` are already migrated: `simple-app` version 3,
   `infrahub` version 4 and `infrahub-enterprise` version 3. After you upgrade Styrmin, load
   each one you use again, for example:

   ```shell
   uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
   ```

   For your own drivers, load the migrated version from its git repository or directory (see
   [Load a driver](./loading-drivers.md)). If the driver is not migrated yet, its author must
   first follow [If you write drivers](#if-you-write-drivers).

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
     component with a component container. These deployments stay on their driver version, and
     Styrmin applies the values on their next render. If you did not remove the values you do not want
     [before you upgraded Styrmin](#before-you-upgrade-styrmin), remove them now.

   The **Component Overrides** card on the deployment's **Settings** tab lists the stored
   `command` and `args` of each component, with an **applied** or **not applied** badge. Users
   who cannot edit the deployment see the card too. Through the API,
   `Deployment.componentContainerOverrides` returns `command`, `args` and `isApplicable` for
   each component that stores an override.

   Remove the values you do not want in the same write that moves the deployment (step 3), so
   they never reach the pods.

3. **Move every deployment to the migrated driver version.** Run an upgrade to the
   deployment's current application version. Styrmin binds the deployment to the newest loaded
   driver version that supports that version (see
   [Selecting a driver version](./loading-drivers.md#selecting-a-driver-version-when-deploying-or-upgrading)):

   ```shell
   uv run styrminctl deployments update-version <deployment-id> <current-application-version>
   ```

   To remove container overrides in the same task, pass the new configuration with
   `--config` (see
   [`deployments update-version`](../reference/styrminctl.md#deployments-update-version)).
   `components` in that payload replaces every stored component block, so include the env
   vars, `command`, `args` and image of every component you keep.

   Do this **before** anything else changes the deployment. A deployment on a driver version
   that calls a retired filter fails its next render, even when it has no override set. Changes made elsewhere also render deployments again: an env var edit on an
   environment redeploys every deployment in it, and a cluster config update redeploys each
   deployment whose resolved config changes.

   The pods of a deployment whose render fails keep running. Styrmin does not apply a
   HelmRelease from a failed render, and it does not render a running deployment again until
   the deployment changes.

#### Steps 2 and 3 with `styrminctl apply`

Load the migrated driver version (step 1), then remove the `command` and `args` you do not want
from the manifest's `spec.config.components` and keep `spec.version` at the deployment's
application version. Every apply binds the deployment to the newest loaded driver version that
supports `spec.version`, so this apply moves the deployment to the migrated version (step 3).
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
   [Migrate env vars to component containers](./migrating-env-vars.md)), it already has them. Add `container`
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
   the chart keys that contained only the override, and any `{% if %}` block or `null` you wrote
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

   Both filters fail wherever they appear, even inside `{% if %}` and when no override is set.
   Styrmin rejects the driver version when you load it, with `RETIRED_TEMPLATE_FILTER` and the
   line of the first call. A driver version loaded before the upgrade stays loaded and fails
   when Styrmin renders a deployment of it. A fixed `command` or `args` that the template sets
   for its own reasons can stay: an override replaces it, and clearing the override restores
   it.

3. **Delete `spec.container_overrides` from `driver.styrmin.yml`.** A driver file that still
   contains the block fails to load:

   ```text
   - spec: spec.container_overrides was removed: Styrmin now applies container command and args
     overrides to each component's declared component container. Delete the block and declare
     components.<name>.container instead. Migration guide: ...
   ```

4. **Increase `spec.version` and load the driver.** Users then move their deployments to it (see
   [If you run deployments](#if-you-run-deployments)).

5. **Check the result.** Deploy, set `args` on a component whose chart renders a `command`,
   and read the live pod: the component container has your `args` and the chart's `command`,
   and the other containers are unchanged. Clear the override, and Styrmin restores the
   chart's `args`.

`components.<name>.container_override` stays readable in `values.j2.yml` as read-only data. Do
not write it into a chart key: Styrmin already applies it, and when no override is set the
chart key would no longer hold the chart's own value.

### Behavior changes

- **Styrmin applies container overrides only to the component container.** Other containers
  in the pod, init containers, and chart `Job`s and `CronJob`s do not receive them, even if the
  chart passed the same Helm value to them.
- **Only `Deployment` and `StatefulSet` workloads are patched.**
- **The component container moves to the first position.** When any override applies to a
  component, its component container is `containers[0]` in the pod. This changes the default
  container of `kubectl logs` for pods with several containers.
- **A set field replaces the whole list, and an unset field keeps the chart's value.** An
  `args`-only override replaces the chart's `args` and keeps the chart's `command`. Clearing an
  override restores the chart's `command` and `args`.
- **An empty list is still rejected.** `command: []` fails with `INVALID_CONTAINER_COMMAND` and
  `args: []` with `INVALID_CONTAINER_ARGS`, so an override cannot remove the chart's `command`
  to fall back to the image's entrypoint.
- **Container overrides need a component container.** Adding or changing `command` or `args`
  on a component without a container fails with `COMPONENT_CONTAINER_NOT_DECLARED`, with the
  `override` metadata set to `command` or `args`. Removing a stored value, or sending the same
  value again, is accepted.
- **The UI shows override editors only for components with a container.** For a component
  without a container, the deployment's **Edit configuration** drawer explains that the component
  accepts no overrides instead of offering **Add override**. It hides the Command and Args
  editors, and shows any stored values read-only, marked **not applied**, with a remove button.
- **Upgrades keep stored values.** If a driver upgrade removes a component's container, its
  stored `command` and `args` are kept and reported with `isApplicable: false` in the API.
  Styrmin does not apply them until a driver version declares the container again. For each
  component whose `command`, `args`, env vars or image override the manifest sets and the
  driver version does not apply, `styrminctl deployments apply` prints a warning on stderr. The
  warning names the component and the kinds of override, and says to remove them from the
  manifest or to load a driver version that declares a container for the component.
- **A wrong container name fails the release.** The first time any override applies to the
  component, including `command` or `args` alone, the deployment fails with
  `COMPONENT_CONTAINER_NOT_FOUND` and a message that names the component and the container.
  Styrmin never adds a container.
- **A rollback of Styrmin stops container overrides on migrated drivers.** An older Styrmin
  release applies `command` and `args` only through the filters, which the migrated templates
  no longer call. The stored values are kept.

### Next steps

- [Create a driver](./creating-a-driver.md) — how to write a driver, including the component
  container.
- [Migrate env vars to component containers](./migrating-env-vars.md) — the same migration for
  env vars.
- [The context](./context.md) — the fields that stay readable in templates.
