---
title: Status reporting
sidebar_position: 8
description: How the Styrmin UI shows the state of the cluster.
---

## Status reporting

When the UI shows a deployment as `RUNNING` with three healthy pods, the
agent read that state from the cluster and sent it to the server.

### Why the agent has a separate reporter

The server does not connect to the cluster (see
[Architecture](./architecture.md)). The agent reports the cluster state
to it.

The agent runs a third coroutine, the **status reporter**, next to the
Prefect worker and the operator. The reporter does only this:

1. Every 5 seconds or so, read the cluster.
2. Collect the state of every pod and `StyrminDeployment`.
3. Send the snapshot to the server through GraphQL.

The server writes it into its `PodStatus` and `DeploymentStatus` tables,
and the UI reads those tables.

```text
                 every ~5 seconds
   ┌─────────┐  ◄────────────────────  ┌─────────────┐
   │ Agent's │   pod & deployment      │ Kubernetes  │
   │ status  │   state (read-only)     │     API     │
   │reporter │                         └─────────────┘
   └────┬────┘
        │
        │  reportPodStatuses / reportDeploymentStatuses
        │  (GraphQL mutations)
        ▼
   ┌─────────┐
   │ Server  │  → DB → UI
   └─────────┘
```

### Why polling, not watching

Kubernetes can _push_ events when objects change ("watches"). The
reporter polls instead, for two reasons:

- **Fewer failure modes.** Polling needs no long-lived connections and no
  resync logic, and it cannot miss an event.
- **The same result at this interval.** Five seconds is shorter than the
  time a user needs to react, so event-driven reporting adds no
  operational benefit here.

### Observed state and declared state

- **Declared state** is what _should_ run. Styrmin stores it in the
  deployment row and in the `StyrminDeployment` resource.
- **Observed state** is what _does_ run. The status reporter sends it,
  and the UI shows it.

The two can differ for a short time in normal operation: after you roll
out an update, while the pods start. The UI shows `DEPLOYING` until the
observed state matches the declared state.

The two can also differ because something is wrong: a pod is in
`CrashLoopBackOff`, an image pull failed, or a node went down. The UI
shows that difference.

### Removing stale state

Pods and deployments are created and deleted. The reporter does not only
add rows: it sends the full current state in every cycle, and the server
deletes the rows of objects that no longer exist in the cluster. When you
delete a deployment, its pods stop reporting and disappear from the UI
within a few seconds.

### Which instance a report is about

Each `StyrminDeployment` report contains an `instanceId`: the application
instance whose spec the operator last handled. The reporter reads it from
the `status.instanceId` of the `StyrminDeployment`, which the operator
writes when it starts working on a new spec. A `StyrminDeployment` that
no operator handler has processed since Styrmin was upgraded has no
`status.instanceId`, so the reporter sends `spec.instanceId` instead.

Right after a flow writes a new spec, the `StyrminDeployment` still shows
the phase of the previous rollout. Because `status.instanceId` changes only when the
operator acts on the new spec, the server never reads the previous
rollout's `Ready` phase as the result of the new instance.

### When a deployment becomes RUNNING

A report with `displayState: Running` sets the deployment to `RUNNING`
only when the task that rolled out the reported instance has finished.
When a hook step of another task started that task, the starting task
must have finished too.

This matters for upgrades whose driver hook calls `stop_components` and
`start_components`. Each call rolls out its own instance while the upgrade
task is still running. Without the check, the operator's `Running` report
for the stopped instance would set the deployment to `RUNNING` in the
middle of the upgrade, and `styrminctl deployments apply --wait` would
return at that point. The first report after the upgrade task finishes sets
`RUNNING`, within one reporting cycle.

### Waiting for a change from a script

Each SDK call that changes a deployment returns a task: `create()`,
`update()`, `scale()`, `update_version()`, `delete()`,
`start_components()`, `stop_components()` and `run_job()`. The task
status `success` means that the flow has ended, not that the deployment
is running. `start_components()` and `stop_components()` do not change
the deployment status until their flow starts, so a `RUNNING` status read
right after the call is the status from before the change.

`client.deployments.wait_for_task()` waits until the change has finished:

1. It waits until the task result is no longer `RUNNING`. The task result
   covers the task, the tasks that its hook steps started, and the
   operator-phase steps of the rollout.
2. When the task result is `SUCCEEDED`, it waits until the deployment
   status is `running`, `failed` or `deleted`.

```python
from styrmin_sdk import StyrminClient

async with StyrminClient(server_address="https://styrmin.example") as client:
    task = await client.deployments.stop_components(deployment_id, ["server"])
    waited = await client.deployments.wait_for_task(task.id, max_wait=300)
    if not waited.succeeded:
        raise SystemExit(waited.failure_reason)
```

`waited.succeeded` is true when the deployment status is `running`, or
`deleted` after `delete()`. Otherwise `failure_reason` gives the reason,
and the call does not raise:

- `step "<name>" failed: <error>` names the failed step of the task or of
  a task that one of its hook steps started.
- `task <id> failed: <message>` gives the task's message when the flow
  failed between two steps.
- `task <id> was superseded by a later task of the deployment` means that
  a later task of the deployment interrupted the rollout.
- `deployment status is <status>, expected <status>` means that the task
  succeeded and the deployment ended in another status.
- `wait timeout` means that `max_wait` elapsed first, and `timed_out` is
  true. The change can still finish after that.

`wait_for_task()` reads the task and the deployment every 10 seconds, for
at most `max_wait` seconds (600 by default). `update()`, `scale()` and
`update_version()` return `None` when nothing changes, and there is no
task to wait for.

### Steps from status reports

The operator's work appears on the deployment page as the steps of the
task that rolled out the instance. For each report, the server finds that
task by the reported `instanceId` and moves its four operator-phase steps
forward:

- `CreatingPrerequisites`: "Create network policies and secrets" runs.
- `CreatingHelmRelease`: "Install or upgrade the HelmRelease" runs.
- `CreatingServices`: "Create services and middlewares" runs.
- `Ready`: every step succeeds, including "Wait for the deployment to be
  ready".

A report can skip phases between two polls; the steps in between then
succeed. A step ends at the time its condition on the `StyrminDeployment` became
`True` when the report contains that condition, and at the time of the
report otherwise.

Reports in the `Deleting` and `Deleted` phases go to the newest delete
task of the deployment instead: its step "Remove the deployment's
resources and namespace" runs during `Deleting` and succeeds at
`Deleted`.

Once a newer task has written the `StyrminDeployment` or requested the
deletion, the operator no longer works on the earlier instance. Reports
that still name the earlier instance then change none of the earlier
task's steps, so a step that failed keeps its failure. Until then,
reports for the earlier instance still move the earlier task's steps.

When a report shows the phase `Failed` or the display state `Error`, the
first unfinished step fails with the message of the `StyrminDeployment`. For the HelmRelease
step and the ready step, the error also names up to five pods from the
stored pod statuses, after `Pods not ready:`. For each pod, it gives:

- why the pod is not scheduled, with the scheduler's reason and message,
  for example
  `Unschedulable: 0/2 nodes are available: pod has unbound immediate PersistentVolumeClaims.`;
- each container or init container that waits or ended with a reason,
  such as `ImagePullBackOff`, `CrashLoopBackOff` or
  `CreateContainerConfigError`, and the kubelet's message for that
  reason. The reasons `ContainerCreating`, `PodInitializing` and
  `Completed` are left out, because the container is starting or has done
  its work, and so is the message of `CrashLoopBackOff`, which only gives
  the delay before the next start;
- each container or init container that is not ready and runs again after
  restarts, for example `init container admin: running after 7 restarts`;
- each init container that is still running and has not restarted, for
  example one that waits for a database: `init container wait-for-db: still running`.
  The pod cannot start its containers until its init containers end.

Each message is cut to 300 characters; the **Pods** tab shows it whole.
The error does not name a pod without such a cause, for example a pod
that fails its readiness probe, or a pod that has finished. It does not
contain container logs or Kubernetes events: a volume claim that names a
missing storage class shows as an unbound volume claim, and the name of
the class is only in the claim's events.

When a later report shows the operator working on the step
again, the step runs again as a new attempt; when a later phase is
reported, the failed step succeeds.

The reporter also reports internal deployments, such as the
per-environment ingress controller, so their status stays current. Their
tasks have no operator-phase steps.

`reportDeploymentStatuses`, the mutation the reporter calls, accepts calls
without credentials
([issue #396](https://github.com/opsmill/styrmin/issues/396) tracks
adding authentication). Anyone who can reach the server's API can
therefore change a deployment's state and its operator-phase steps.

### When the agent stops reporting

While an operator-phase step is running, the server checks when the
agent last reported the deployment. When that was more than 60
seconds ago (or, without any report, when the step started more than 60
seconds ago), the step shows "No report from the agent since" followed
by that time. The notice disappears with the next report. It shows
whether the agent stopped or the phase is slow.

The deployment page reloads its data every 10 seconds. With the 5-second
report interval, a change of an operator-phase step appears on the page
within about 15 seconds.

### What this means in practice

- The UI is _eventually consistent_, with a delay of about 5 seconds. A
  pod that crashed half a second ago shows as healthy until the next poll.
- If the agent is unhealthy, status updates stop. The UI keeps showing
  the last known state, and a running operator-phase step shows "No
  report from the agent since" and the time of the last report after 60
  seconds without one.
- The GraphQL API returns the same data in the `podStatuses` and
  `deploymentStatuses` fields, so external dashboards can read it too.
  The Python SDK reads the pod statuses as described in
  [Reading pod statuses from a script](#reading-pod-statuses-from-a-script).

### Reading pod statuses from a script

The Python SDK reads the stored pod statuses of:

- one deployment, with `deployments.get_pod_statuses(deployment_id)`;
- every deployment of an environment, with
  `environments.get_pod_statuses()`;
- every deployment of every environment of a cluster, with
  `clusters.get_pod_statuses()`.

Each pod status has a `containerStatuses` list. Each entry has a `kind`:

- `pod`: the pod is not scheduled. `name` is `PodScheduled`, `state` is
  `waiting:<reason>`, for example `waiting:Unschedulable`, and `message`
  is the scheduler's message. The list has this entry only while the pod
  is not scheduled, and it comes first.
- `init`: an init container.
- `container`: a container.

An `init` or `container` entry has `name`, `image`, `ready`,
`restart_count`, `started_at`, `state` (`running`, `waiting:<reason>`,
`terminated:<reason>` or `unknown`) and `message`, the kubelet's message
of a waiting container. Styrmin does not store the message of a
terminated container, because the container writes it, nor the message
of `PostStartHookError`, which quotes the output of the container's
`postStart` hook. The pod's
`restartCount` counts the restarts of its init containers while it
initializes, and of its containers after that, as `kubectl get pods`
does. An entry without `kind` comes from an older agent and is a
container.

The **Pods** tab of a deployment shows the same data: when you expand a
pod, it shows why the pod is not scheduled above its containers, marks
init containers with `init`, and shows each message under its container.

`environments.get_pod_statuses()` takes the environment's ID, or its name
with the ID or name of its cluster, as `environments.get()` does.
`clusters.get_pod_statuses()` takes the cluster's ID or name. Both read
the environment or the cluster first, so an unknown ID or name raises
`ResourceNotFoundError`.

```python
from styrmin_sdk import StyrminClient
from styrmin_sdk.models import PodPhase

async with StyrminClient(server_address="https://styrmin.example") as client:
    pods = await client.environments.get_pod_statuses(
        environment_name="staging", cluster_name="local"
    )
    serving = [pod for pod in pods if pod.phase is not PodPhase.SUCCEEDED]
    if not serving or not all(pod.ready for pod in serving):
        raise SystemExit("a pod is not ready, or no pod is reported yet")
```

The example leaves out the pods in the `SUCCEEDED` phase, such as the pod
of a finished job, because such a pod is never ready. `all()` is true for
an empty list, so the example also checks that the list is not empty.

The environment and cluster reads:

- include the internal deployments, such as the ingress controller of a
  dedicated ingress. `deployments.list()` leaves these deployments out
  unless you pass `include_internal=True`;
- leave out the deleted deployments;
- return the pods in no fixed order;
- return the pods of the last report, which can be about 5 seconds old.
  A pod that started after that report is not in the list yet, so a new
  environment, such as a clone right after its restore, can return an
  empty list.

`clusters.get_pod_statuses()` returns every pod of the cluster in one
response, without paging, so its size grows with the number of pods.
`environments.get_pod_statuses()` reads one environment at a time.

Each item is a `PodStatus` from `styrmin_sdk.models`. Its `deployment_id`
names the deployment of the pod, and its `phase` is a `PodPhase`.
`deployments.get_pod_statuses()` returns the same fields, except
`deployment_id`.

### Next steps

- [**The operator and `StyrminDeployment`**](./operator-and-crds.md):
  what the reporter observes.
- [**Architecture**](./architecture.md): how the reporter connects to the
  other components.
