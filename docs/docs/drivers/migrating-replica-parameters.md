---
title: Migrating Replica Parameters
sidebar_position: 7
description: Move infrahub deployments from the replicas_server and replicas_task_worker parameters to replica overrides.
---

## Migrating Replica Parameters

`infrahub` driver version 5 and `infrahub-enterprise` driver version 4 no longer declare the
`replicas_server` and `replicas_task_worker` parameters. The replica counts of the `server` and
`task-worker` components are now driver defaults. To run a different count, you set a
**replica override** on the component of your deployment.

If you arrived here from an error like this one when you changed a deployment's driver version:

```text
Parameter 'replicas_task_worker' is not declared by driver infrahub version 5 (application
version 1.7.3), and this deployment sets it to 4 (default 2). Remove the parameter or reset it
to its default, then change the driver version again. If it set a replica count, carry the
value over as a replica override on the component first. See
https://styrmin.pages.dev/docs/drivers/migrating-replica-parameters
```

the deployment sets a replica parameter to a value other than its default. Follow
[Deployments with a changed value](#deployments-with-a-changed-value). The deployment is still
on its old driver version, and no pod count changed.

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

### The rule for parameters a new driver version no longer declares

When a deployment changes to another driver version, Styrmin checks each parameter that the
current driver version declares and the target driver version does not:

- If the value equals the parameter's default in the current driver version, Styrmin drops the
  value and the change continues.
- Otherwise, Styrmin rejects the change with the error code `RETIRED_PARAMETER_VALUE` before any
  task starts. The deployment stays on its current driver version, and no pod count changes.

The rule applies to the stored values together with the parameters sent in the same request.
A value must have the same type as the default to be equal: the string `"2"` does not equal
the integer default `2`. The error carries the parameter name (`parameter_name`), its value
(`value`), its default in the current driver version (`default`) and the target driver
version (`checked_against`). When both parameters hold a changed value, the error names
`replicas_server` first; carry both values over in the same request.

The rule applies to any driver version that removes a parameter, not only to the infrahub
drivers.

### Deployments that kept the default values

No manual step is needed. Load the new driver version, then upgrade the deployment as usual:

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
uv run styrminctl deployments update-version <deployment-id> <application-version>
```

The upgrade drops `replicas_server: 1` and `replicas_task_worker: 2`. `server` runs 1 pod and
`task-worker` runs 2 pods, as before. The **Upgrade** button on the deployment page works the
same way.

### Deployments with a changed value

Carry the parameter value over as a replica override on the component, and reset the
parameter to its default or remove it, in the same request as the driver version change. The
API, the SDK and `styrminctl` do this in one request. The UI does it in two steps. No pod count
changes in either case: a replica override also applies on the old driver version, because
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

- Do not only delete the parameter from the manifest. `spec.parameters` is merged on top of
  the stored values, so the stored `4` stays and the apply is rejected.
- After this apply, remove `replicas_task_worker` from the manifest. The deployment's driver
  version no longer declares it, so the next apply would fail with
  `Unknown parameter: 'replicas_task_worker'`. This also applies to a manifest that lists
  `replicas_server: 1` or `replicas_task_worker: 2`: the first apply after you load the new
  driver version drops them, and the next apply rejects them.
- `components` replaces every stored component block, as in GraphQL.

#### In the UI, in two steps

The **Upgrade Deployment** dialog sends only the application version and the driver version, so
it cannot send a replica override. Make the change on the old driver version first:

1. On the deployment's **Settings** tab, click **Update Settings**. In the
   **Edit configuration** drawer:

   - Under **Components**, set **Replicas** of `task-worker` to the value of the parameter,
     for example `4`.
   - Under **Driver Parameters**, set **Number of task worker replicas** back to its default,
     `2`.

   Click **Review & apply**. `task-worker` keeps 4 pods: the replica override now sets the
   count, and the parameter holds its default.

2. Click **Upgrade**, choose the new driver version in **Upgrade Deployment** and click
   **Upgrade**. Styrmin drops the parameter, because it holds its default, and `task-worker`
   keeps 4 pods.

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

### If you write drivers

To retire a parameter that set a replica count in your own driver:

1. Remove the parameter from `spec.parameters` in `driver.styrmin.yml`, and remove the line
   that passes it to the chart from `values.j2.yml`.
2. Declare the parameter's default as `replicas` on the component in `spec.components`. Mark a
   component that must run 1 pod with `singleton: true`.
3. Increase `spec.version` and load the driver.

Deployments that kept the parameter's default then change to the new driver version without a
manual step, and deployments with another value follow
[Deployments with a changed value](#deployments-with-a-changed-value).

### Next

- [Loading a Driver](./loading-drivers.md): load the new driver versions.
- [Creating a Driver](./creating-a-driver.md): the full driver walkthrough.
- [`styrminctl` reference](../reference/styrminctl.md): `deployments update-version` and
  `deployments apply`.
