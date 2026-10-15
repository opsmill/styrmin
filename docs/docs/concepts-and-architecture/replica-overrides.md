---
title: Replica overrides
sidebar_position: 8
description: Set how many pods one component of a deployment runs, without a driver parameter.
---

## Replica overrides

The number of pods that a component runs (its replica count) comes from
the Helm chart bundled with the deployment's driver version, or from a
default that the driver declares. A **replica override** sets the replica
count of one component of one deployment. Styrmin applies it after the
chart renders: it sets `spec.replicas` of every `Deployment` and
`StatefulSet` that matches the component's label selector. The component
needs no component container, and the driver needs no parameter or
template code for it.

### Order of precedence

Styrmin takes each component's replica count from the first of these
sources that is set:

1. **The replica override** on the deployment.
2. **The driver default**: `components.<name>.replicas` in the driver
   version, or 1 for a [singleton component](#singleton-components) that
   declares no `replicas`.
3. **The chart's count.** Styrmin does not change `spec.replicas`, so the
   count that the chart renders applies. Styrmin does not read this count,
   so the UI and `styrminctl` show the source without a number.

Each source shows up differently in the API, the UI and the CLI:

| Source | GraphQL `ComponentReplicas.source` | **Component Overrides** card | `styrminctl deployments get` |
|--------|------------------------------------|------------------------------|------------------------------|
| Replica override of 3 | `OVERRIDE` | `3 (override)` | `3 (override)` |
| Driver default of 2 | `DRIVER_DEFAULT` | `2 (driver default)` | `2 (driver default)` |
| Singleton component without an override | `DRIVER_DEFAULT` | `1 (driver default, singleton)` | `1 (driver default, singleton)` |
| The chart's count | `CHART` | `set by the chart` | `chart` |

When you clear an override, the component returns to the next source in
this order.

### Before you start

- **Only `Deployment` and `StatefulSet` workloads change.** Styrmin sets
  `spec.replicas` on every `Deployment` and `StatefulSet` that the
  component's label selector matches. It does not change `Job`, `CronJob`
  or `DaemonSet` workloads. When the selector matches no `Deployment` and
  no `StatefulSet`, the override changes nothing and the deployment does
  not fail.
- **The count is a whole number from 1 to 2147483647.** A count of 0 or
  less is rejected with `INVALID_REPLICA_COUNT`. To run no pods, stop the
  component instead (see [Stopped components](#stopped-components)).
- **Component scope only.** There is no environment-wide or
  deployment-wide replica count, and no layering.
- **The cluster must have room for the new pods.** Styrmin does not check
  the cluster's capacity before it scales a component. Pods that the
  cluster cannot place stay in the `Pending` phase, and the update task
  fails when its wait limit runs out.
- **Permissions** are the same as for any other deployment config edit.

### When the update task completes

A change to a replica count starts an update task, as any other config
edit does. The task completes after the component's workloads report the
new count as their updated, ready and available pods. This applies to a
scale-down as well as to a scale-up, so a completed task means that the
change of count is done.

### Singleton components

A driver marks a component that must run exactly one pod with
`singleton: true`, for example a database that runs as a single primary.
For a singleton component:

- Styrmin sets the count to 1, also when the chart renders more pods and
  the driver declares no `replicas`.
- A replica override of exactly 1 is accepted.
- A replica override greater than 1 is rejected with
  `SINGLETON_REPLICA_OVERRIDE` before any task starts, when you create the
  deployment, update it, change its driver version, or run
  `styrminctl deployments apply`.
- When you change a deployment to a driver version that marks a component
  as singleton, and the deployment stores an override greater than 1 on
  that component, the change is rejected. Lower the override to 1 or
  clear it in the same request.

The singleton flag limits the replica count, not the number of pods that
run at the same time. During a rolling update, the chart's update
strategy can run a second pod of a singleton component for a short time,
for example when a `Deployment` uses the `RollingUpdate` strategy with
`maxSurge` above 0.

The driver version page shows which components are singleton components:
see [On the driver version page](#on-the-driver-version-page).

### Stopped components

Stopping a component and setting its replica count are separate
operations. A stopped component runs 0 pods whatever its replica count
is, and its override stays stored. When you start the component again, it
returns to the count from the [order of precedence](#order-of-precedence).

Components are stopped and started with the `stopComponents` and
`startComponents` GraphQL mutations, with
`styrminctl deployments stop-components` and `start-components`, and by
driver actions through the `stop_components` and `start_components`
primitives.

While a component is stopped:

- `Deployment.componentReplicas` reports the count that the component
  returns to when it starts, and `Deployment.components[].enabled` is
  `false`.
- The **Component Overrides** card adds `stopped: 0 pods` to the
  component's replica line.
- `styrminctl deployments get` adds `, stopped: 0 pods` to the
  component's replica cell, for example `3 (override), stopped: 0 pods`.

### Overrides on a component that the driver version no longer declares

When you change a deployment to a driver version that no longer declares a
component, Styrmin keeps that component's replica override and does not
apply it. The override is then orphaned:

- `Deployment.componentReplicas` has a row for the component with
  `isOrphaned: true`, `isApplicable: false` and `count: null`. `override`
  holds the stored value.
- The **Component Overrides** card shows the override in the row of the
  component that the driver no longer declares, with a **not applied**
  badge.
- `styrminctl deployments get` adds a row to the Components table, for
  example `3 (override, not applied: no longer declared)`.

Adding or changing an override on a component that the driver version does
not declare is rejected with `UNKNOWN_COMPONENT_REPLICA_OVERRIDE`. The
error lists the components that the driver version declares. Sending the
stored value again unchanged is accepted, so an update that keeps the
other component blocks does not fail. Removing the override always works.

### In the UI

To set or clear an override on an existing deployment:

1. Open the deployment, go to the **Settings** tab, and click **Update
   Settings**.
2. In the **Edit configuration** drawer, under **Components**, expand the
   component.
3. Type the count in **Replicas**. When the field is empty, its placeholder
   shows the count that applies without an override, for example
   `2 (driver default)`, or `set by the chart`. Under a count below 1, the
   drawer shows "Must be 1 or more. To run no pods, stop the component.",
   and the server rejects such a count.
4. Click **Review & apply** and confirm.

To clear the override, empty the **Replicas** field and apply.

A singleton component shows a read-only **Replicas** field with the value
`1 (singleton)`. If such a component stores an override greater than 1,
the drawer shows the stored value with a **not applied** badge and a
button that removes it.

To set counts when you create a deployment, use the **Component replicas**
section of the **Deploy** form. It lists the components of the selected
driver version with the same **Replicas** field. Leave a field empty to
use the driver default or the chart's count.

The **Component Overrides** card on the **Settings** tab shows a replica
line for every component: the count and its source, an **applied** or
**not applied** badge when an override is stored, and `stopped: 0 pods`
for a stopped component.

#### On the driver version page

On the driver's page, the **Components** tab shows, for each component of
the selected driver version, a **Replicas** row (the driver default, or
`not set`) and a **Singleton** row (`yes` or `no`).

### With `styrminctl apply`

Set `replicas` on the component's entry in `spec.config.components`:

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: my-app
spec:
  driver: acme/my-driver
  version: "1.4.2"
  environment: production
  config:
    components:
      - name: server
        replicas: 3
```

Applying the same manifest again changes nothing. `spec.config` is
replaced on every apply, so removing the `replicas` key (or the
component's entry) and applying again clears the override. An omitted or
empty `spec.config` is the exception: it keeps the stored configuration.
When the override you remove is the only setting left, write
`components: []` instead of deleting `spec.config`. See
[the `styrminctl` reference](../reference/styrminctl.md#manifest-specconfig-shape).

When the manifest keeps a replica override on a component that the driver
version no longer declares, `apply` stores it, does not apply it, and
prints a warning on stderr. The exit code does not change:

```text
warning: my-app: replica override is stored on worker but not applied: the driver version does not declare worker. Remove it from the manifest, or load a driver version that declares components.worker and apply again
```

### With the Python SDK or GraphQL

The override is `ComponentConfigInput.replicas` on `deploy`,
`updateDeployment` and `updateDeploymentVersion` (in `input`). It is read
back from `Deployment.componentReplicas`, which has one row per component
that the driver version declares and one row per orphaned override, sorted
by component name. Each row has `component`, `count`, `source`,
`override`, `singleton`, `isOrphaned` and `isApplicable`.

```python
from styrmin_sdk import StyrminClient
from styrmin_sdk.models import ComponentConfigInput, UpdateDeploymentInput

# The client reads its token from STYRMIN_TOKEN, or takes token=... explicitly.
async with StyrminClient(server_address="https://styrmin.example") as client:
    await client.deployments.update(
        deployment_id,
        input=UpdateDeploymentInput(
            components=[ComponentConfigInput(name="server", replicas=3)],
        ),
    )

    deployment = await client.deployments.get(deployment_id)
    for row in deployment.component_replicas:
        print(row.component, row.count, row.source, row.is_applicable)
```

`components` replaces every stored component block, and leaving
`replicas` out of a block clears it. Resubmit the env vars, `command`,
`args`, image and replica override of every component you want to keep.

`styrminctl deployments update` and `deployments update-version --config`
take the same payload as JSON:

```shell
uv run styrminctl deployments update <deployment-id> \
  --config '{"components": [{"name": "server", "replicas": 3}]}'
```

The driver version's defaults are on `ComponentConfig.replicas` and
`ComponentConfig.singleton` (`ApplicationDriverVersion.componentConfigs`).

### Scaling a component whose pods share a `ReadWriteOnce` volume

A volume with the `ReadWriteOnce` access mode can be attached to one node
at a time. When the pods of a component mount one shared
`PersistentVolumeClaim` with this access mode, a pod that Kubernetes
places on another node cannot attach the volume and stays in the
`Pending` phase. The update task then fails when its wait limit runs out.
The `server` component of the `infrahub` drivers mounts such a volume:
see
[Scaling `server` above 1 pod](../drivers/migrating-replica-parameters.md#scaling-server-above-1-pod).

### Replica counts that a driver parameter sets

Before replica overrides, a driver could expose a replica count only as a
parameter that its `values.j2.yml` passes to the chart. A replica override
also applies on such a driver version: Styrmin sets `spec.replicas` after
the chart renders, so the override replaces the count that the parameter
passed to the chart.

`infrahub` driver version 5 and `infrahub-enterprise` driver version 4
replace their `replicas_server` and `replicas_task_worker` parameters with
driver defaults. A deployment that changed one of these parameters must
carry the value over as a replica override before it changes driver
version. See
[Migrating Replica Parameters](../drivers/migrating-replica-parameters.md).

### When something goes wrong

| What you see | Why | What to do |
|--------------|-----|------------|
| The write fails with `INVALID_REPLICA_COUNT` | The count is below 1, above 2147483647, or not a whole number | Fix the count. To run no pods, stop the component |
| The write fails with `UNKNOWN_COMPONENT_REPLICA_OVERRIDE` | The driver version does not declare that component | Check the component name against the components listed in the error |
| The write fails with `SINGLETON_REPLICA_OVERRIDE` | The driver version marks the component as a singleton component | Set the override to 1 or clear it |
| A driver version change fails with `RETIRED_PARAMETER_VALUE` | The target driver version no longer declares a parameter that the deployment sets to a value other than its default | Follow [Migrating Replica Parameters](../drivers/migrating-replica-parameters.md#deployments-with-a-changed-value) |
| Pods stay in the `Pending` phase and the update task fails | The cluster cannot place the new pods, or the pods share a `ReadWriteOnce` volume | Open the deployment's **Pods** tab to read the reason, then lower the count or add capacity |
| A component does not run the count of its override | The override is orphaned, or the component is stopped | Check the replica line on the **Component Overrides** card |

### Upgrading and rolling back Styrmin

- **Upgrade the agent chart together with the server.** An agent from an
  earlier release rejects a deployment context that carries a replica
  override.
- **A driver version loaded before this release that already sets
  `components.<name>.replicas`** to a whole number starts to apply it as
  the driver default. No example driver set this key before this release.
  A stored `replicas` or `singleton` value that is not valid is ignored,
  and Styrmin logs a warning that names the driver version and the
  component.
- **Clear every replica override before you roll Styrmin back** below the
  release that added them: earlier releases reject a deployment config
  that carries a `replicas` key.

### Limits

- **No autoscaling.** Styrmin does not detect a `HorizontalPodAutoscaler`
  that a chart ships, and does not work with one.
- **No default at environment or cluster level.**
- **No separate scale action.** Change the count by editing the
  deployment config.
- **One pod at a time is not guaranteed** for a singleton component during
  a rolling update.

### Related

- [Creating a Driver](../drivers/creating-a-driver.md#replica-counts-replicas-and-singleton) —
  declaring `replicas` and `singleton` on a component.
- [Migrating Replica Parameters](../drivers/migrating-replica-parameters.md) —
  the `infrahub` drivers and the rule for parameters that a new driver
  version no longer declares.
- [`styrminctl` reference](../reference/styrminctl.md#manifest-specconfig-shape) —
  the manifest `spec.config` shape.
- [Image overrides](./image-overrides.md) — the other per-component
  override applied after the chart renders.
