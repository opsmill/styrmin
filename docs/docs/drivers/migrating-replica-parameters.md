---
title: Migrate the infrahub replica parameters
sidebar_position: 7
description: Move infrahub deployments from the replicas_server and replicas_task_worker parameters to replica overrides.
---

## Migrate the infrahub replica parameters

`infrahub` driver version 5 and `infrahub-enterprise` driver version 4 no longer declare the
`replicas_server` and `replicas_task_worker` parameters. The replica counts of the `server` and
`task-worker` components are now driver defaults. To run a different count, set a
**replica override** on the component of your deployment.

If you arrived here from an error like this one when you changed a deployment's driver version:

```text
Parameter 'replicas_task_worker' is not declared by driver infrahub version 5 (application
version 1.7.3), and this deployment sets it to 4 (default 2). Remove the parameter or reset it
to its default, then change the driver version again. See
https://styrmin.pages.dev/docs/drivers/changing-driver-versions. If it set a replica count,
carry the value over as a replica override on the component first:
https://styrmin.pages.dev/docs/drivers/migrating-replica-parameters
```

the deployment sets a replica parameter to a value other than its default. Follow
[Deployments with a changed value](#deployments-with-a-changed-value). The deployment is still
on its old driver version, and no pod count changed.

A deployment created from the earlier `examples/deployments/infrahub.yml` manifest is in this
case: see
[Deployments created from the earlier example manifest](#deployments-created-from-the-earlier-example-manifest).

### Changes in `infrahub` 5 and `infrahub-enterprise` 4

The two driver versions make the same changes:

| Component | `infrahub` 4 and `infrahub-enterprise` 3 | `infrahub` 5 and `infrahub-enterprise` 4 |
|-----------|------------------------------------------|------------------------------------------|
| `server` | `replicas_server` parameter, default `1` | driver default `replicas: 1` |
| `task-worker` | `replicas_task_worker` parameter, default `2` | driver default `replicas: 2` |
| `database`, `task-manager-db`, `cache` | the chart's count, 1 pod | singleton component, fixed at 1 pod |
| `message-queue`, `task-manager` | the chart's count | the chart's count (no change) |

The `values.j2.yml` of the new versions no longer passes a count to the chart. Styrmin sets
`spec.replicas` of each component's `Deployment` and `StatefulSet` after the chart renders,
from the replica override or, when there is none, from the driver default. The other
parameters, `database_storage_size` and `enable_analytics`, keep their defaults.

No pod count changes when a deployment moves to the new version with the default values: the
driver defaults are the old parameter defaults, and the charts already run 1 pod of each
singleton component.

### How Styrmin handles the removed parameters

When a deployment changes to the new driver versions, Styrmin applies the rule for
[parameters the target driver version no longer declares](./changing-driver-versions.md#parameters-the-target-driver-version-no-longer-declares):

- A stored or submitted `replicas_server: 1` or `replicas_task_worker: 2`, the old defaults, is
  dropped, and the change continues.
- Any other value rejects the change with `RETIRED_PARAMETER_VALUE` before any task starts. When
  both parameters hold a changed value, the error names `replicas_server` first; move both
  values to replica overrides in the same request.

The rule applies to the stored values together with the parameters sent in the same request.

### Deployments that kept the default values

No manual step is needed. Load the new driver version, then upgrade the deployment as usual:

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
uv run styrminctl deployments update-version <deployment-id> <application-version>
```

The upgrade drops `replicas_server: 1` and `replicas_task_worker: 2`. `server` runs 1 pod and
`task-worker` runs 2 pods, as before. The **Upgrade** button on the deployment page works the
same way.

### Deployments created from the earlier example manifest

Earlier versions of
[`examples/deployments/infrahub.yml`](https://github.com/opsmill/styrmin/blob/develop/examples/deployments/infrahub.yml)
set `replicas_task_worker: 1`, which is not the old default of `2`. A deployment created from
that manifest stores `replicas_task_worker: 1`, so its change to `infrahub` 5 is rejected with
`RETIRED_PARAMETER_VALUE`. Move the value to a replica override as described in
[Deployments with a changed value](#deployments-with-a-changed-value), with `replicas: 1` on
`task-worker`. With `styrminctl deployments apply`, the first apply after you load the new
driver version needs both lines:

```yaml
spec:
  parameters:
    replicas_task_worker: 2   # the old default, so the driver version change drops it
  config:
    components:
      - name: task-worker
        replicas: 1
```

The `replicas_server: 1` of the earlier manifest is the old default, so Styrmin drops it.

### Deployments with a changed value

Move the parameter value to a replica override on the component, and reset the
parameter to its default or remove it, in the same request as the driver version change. The
API, the SDK and `styrminctl` do this in one request. The UI does it in two steps. No pod count
changes in either case: a replica override applies on the old driver version too, because
Styrmin sets the count after the chart renders, so the override replaces the count that the
parameter passed to the chart.

The examples below use a deployment whose stored `replicas_task_worker` is `4`.

#### In one request with GraphQL

Send the override in `input.components` and the parameter at its old default in
`input.parameters`:

```graphql
mutation {
  updateDeploymentVersion(
    deploymentId: "<deployment-id>"
    version: "<application-version>"
    input: {
      components: [{ name: "task-worker", replicas: 4 }]
      parameters: [{ name: "replicas_task_worker", value: 2 }]
    }
  ) {
    id
  }
}
```

- `input.parameters` is merged on top of the stored values, so `replicas_task_worker` holds its
  default and Styrmin drops it. You can instead pass the top-level `parameters` argument, which
  replaces every stored value, without `replicas_task_worker`.
- `input.components` replaces every stored component block. Include the env vars, image,
  `command`, `args` and replica override of every component you keep.
- Without `driverVersionId`, Styrmin binds the deployment to the newest loaded driver version
  that supports the application version. Pass `driverVersionId` to choose the driver version.

#### In one request with the Python SDK

```python
from styrmin_sdk import StyrminClient
from styrmin_sdk.models import (
    ComponentConfigInput,
    ParameterValueInput,
    UpdateDeploymentInput,
)

async with StyrminClient(server_address="https://styrmin.example") as client:
    await client.deployments.update_version(
        deployment_id,
        application_version,
        input=UpdateDeploymentInput(
            components=[ComponentConfigInput(name="task-worker", replicas=4)],
            parameters=[ParameterValueInput(name="replicas_task_worker", value=2)],
        ),
    )
```

The same notes as for GraphQL apply.

#### In one request with `styrminctl deployments update-version`

```shell
uv run styrminctl deployments update-version <deployment-id> <application-version> \
  --config '{"components": [{"name": "task-worker", "replicas": 4}],
             "parameters": [{"name": "replicas_task_worker", "value": 2}]}'
```

`--config` takes the same `UpdateDeploymentInput` payload as `input` in GraphQL (see
[`deployments update-version`](../reference/styrminctl.md#deployments-update-version)).

#### In one request with `styrminctl deployments apply`

In the manifest, add the override under `spec.config.components` and set the parameter to its
old default under `spec.parameters`:

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: infrahub-prod
spec:
  driver: infrahub
  version: 1.7.3
  parameters:
    replicas_task_worker: 2   # the old default, so the driver version change drops it
  config:
    components:
      - name: task-worker
        replicas: 4
```

Then load the new driver version and apply the manifest. The apply binds the deployment to the
newest loaded driver version that supports `spec.version`, drops the parameter and stores the
override, in one task.

- Deleting the parameter from the manifest is not enough. `spec.parameters` is merged on top of
  the stored values, so the stored `4` stays and the apply is rejected.
- After this apply, remove `replicas_task_worker` from the manifest. The deployment's driver
  version no longer declares it, so the next apply fails with
  `Unknown parameter: 'replicas_task_worker'`, and the error links to
  [Change a deployment's driver version](./changing-driver-versions.md#a-request-or-manifest-that-still-lists-a-retired-parameter).
  This also applies to a manifest that lists `replicas_server: 1` or `replicas_task_worker: 2`:
  the first apply after you load the new driver version drops them, and the next apply rejects
  them.
- `components` replaces every stored component block, as in GraphQL.

#### In the UI, in two steps

The **Upgrade Deployment** dialog sends only the application version and the driver version, so
it cannot send a replica override. When it shows the `RETIRED_PARAMETER_VALUE` error, it lists
the steps below, links to this guide and offers **Open the Settings tab**. Make the change on the
old driver version first:

1. On the deployment's **Settings** tab, click **Update Settings**. In the
   **Edit configuration** drawer:

   - Under **Components**, set **Replicas** of `task-worker` to the value of the parameter,
     for example `4`.
   - Under **Driver Parameters**, set **Number of task worker replicas** back to its default,
     `2`.

   Click **Review & apply**. `task-worker` keeps 4 pods: the replica override now sets the
   count, and the parameter holds its default.

2. Click **Upgrade**. In **Upgrade Deployment**, enter the application version in
   **New Version**, for example the current one, choose the new driver version and click
   **Upgrade**. The **Upgrade** button stays disabled until **New Version** has a value.
   Styrmin drops the parameter, because it holds its default, and `task-worker` keeps 4 pods.

For a changed `replicas_server`, do the same with **Replicas** of `server` and
**Number of server replicas**, whose default is `1`.

### Singleton components

`database`, `task-manager-db` and `cache` are singleton components in the new driver versions.
`task-manager-db` (PostgreSQL) and `cache` (Redis) run in standalone mode, where a second pod
is a separate primary with its own volume, not a replica. Styrmin sets the count of each
singleton component to 1 and rejects a replica override greater than 1 with the error code
`SINGLETON_REPLICA_OVERRIDE`:

```text
Component 'database' is a singleton component in driver infrahub version 5 (application
version 1.7.3) and runs exactly 1 replica; the requested count is 2. Set the override to 1 or
clear it.
```

An override of exactly 1 is accepted. The old driver versions do not mark these components as
singleton, so a deployment can store an override greater than 1 on one of them. Such a
deployment cannot change to the new driver version until the same request lowers the override
to 1 or clears it.

During a rolling update, the chart's update strategy can run 2 pods of a singleton component
for a short time. The singleton flag limits the replica count, not the number of pods during a
rolling update.

`message-queue` and `task-manager` are not singleton components: they accept a replica
override, and without one they run the chart's count.

### Scaling `server` above 1 pod

The infrahub drivers mount a volume with the `ReadWriteOnce` access mode in the `server` pods
(`infrahubServer.persistence.accessMode` in `values.j2.yml`). Only one node at a time can
attach a `ReadWriteOnce` volume. When a `server` replica override is greater than 1 and
Kubernetes places an extra pod on another node, that pod cannot attach the volume and stays in
the `Pending` phase. The update task then fails when its wait limit runs out. This limit
existed with `replicas_server` too.

### Retire a replica parameter in your own driver

To retire a parameter that set a replica count in your own driver:

1. Remove the parameter from `spec.parameters` in `driver.styrmin.yml`, and remove the line
   that passes it to the chart from `values.j2.yml`.
2. Declare the parameter's default as `replicas` on the component in `spec.components`. Mark a
   component that must run 1 pod with `singleton: true`.
3. Increase `spec.version` and load the driver.

Deployments that kept the parameter's default then change to the new driver version without a
manual step, and deployments with another value follow
[Deployments with a changed value](#deployments-with-a-changed-value). A parameter without a
default cannot be dropped this way; see
[A retired parameter that has no default](./changing-driver-versions.md#a-retired-parameter-that-has-no-default).

Users can set a replica override on any component of any driver version as soon as Styrmin is
upgraded, even on a driver version loaded before this release. Mark each component that must run
a single pod, such as a database in standalone mode, with `singleton: true` in a new driver
version before you upgrade Styrmin, and move your deployments onto it.

### Next steps

- [Load a driver](./loading-drivers.md): load the new driver versions.
- [Create a driver](./creating-a-driver.md): how to write a driver.
- [`styrminctl` reference](../reference/styrminctl.md): `deployments update-version` and
  `deployments apply`.
