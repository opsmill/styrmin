---
title: Glossary
sidebar_position: 3
description: Every Styrmin term in one alphabetical list, with a link to the page that explains it.
---

## Glossary

One-sentence definitions of the Styrmin terms used in the docs, the
GraphQL schema, the SDK, the CLI, and the UI. For how the terms relate,
see [Core concepts](./core-concepts.md).

### A

**Action**: A Python function, declared by an application driver, that
runs inside a Prefect flow at a lifecycle **hook** and **mode** (for
example, `setup` / `pre`). See [Lifecycle hooks and
actions](./hooks-and-actions.md).

**Active instance**: The one **instance** of a **deployment** that is
currently live. Reconciliation compares the newly generated instance with
the active instance.

**Agent**: The container that Styrmin runs inside a target Kubernetes
cluster. It reconciles **recorded intent** into Kubernetes resources and
reports the observed state to the **server**. There is one per
**cluster**.

**Application driver**: A versioned, self-contained deployment
specification for one application. The unit of deployment in Styrmin.
See [What is an application driver?](./what-is-a-driver.md).

**Application driver version**: A revision of an application driver,
with its own Helm chart version, components, parameters, services, and
actions. A **deployment** uses one application driver version.

**Application version**: The version of the application itself (for
example, Infrahub `1.6.0`). Different from the application driver
version that deploys it.

### B

**Backup history**: The backups of every **instance** that a
**deployment** has had, newest first. Backups taken before an upgrade, a
config edit, or an environment config change stay in it, and a deleted
deployment keeps it. The Backups tab and `styrminctl backups list` show
it. See [Backup history of a
deployment](backups-and-restores.md#backup-history-of-a-deployment).

**Backup storage location (BSL)**: An S3-compatible object store
registered as a destination for Velero backups. You assign it to an
**environment**, and every deployment in that environment stores its
backups there.

### C

**CLI / styrminctl**: The Cyclopts-based command-line client. It calls
the GraphQL API.

**Cluster**: A Kubernetes cluster registered with Styrmin. Every
environment and deployment on it uses the cluster-level settings. One
**agent** runs per cluster.

**Component**: A logical part of an application (for example, `server`
or `task-worker`), declared by the application driver and identified by
a Kubernetes label selector. Lifecycle operations (start, stop, restart)
apply to the component as a unit. Its replica count comes from a
**replica override**, the driver default, or the Helm chart.

**Component container**: The one container in a component's pod that
the application driver names (`components.<name>.container`) to receive
the overrides that users set on a deployment: env vars, the **image
override**, and the container `command` and `args`. Styrmin applies them
after the Helm chart renders. Env vars merge in by name, so the chart's
own env entries stay, and a `command` or `args` override replaces the
whole list. A component without a component container accepts none of
these component-scope overrides (`COMPONENT_CONTAINER_NOT_DECLARED`). A
declared name that the chart does not render fails the deployment with
`COMPONENT_CONTAINER_NOT_FOUND` as soon as an override applies to the
component; Styrmin never adds a container. See [Create a
driver](../drivers/creating-a-driver.md#the-component-container).

**Component overrides**: The values with which a deployment overrides
the default component configuration of its application driver version:
per-component env vars, the **image override**, the container `command`
and `args`, and the **replica override**. Styrmin applies all of them
after the Helm chart renders; the driver's values template does not pass
them to the chart. Env vars, the image override, `command`, and `args`
go to the **component container**. The replica override goes to the
component's `Deployment` and `StatefulSet` workloads and needs no
component container. See [Migrate command and args overrides to
component containers](../drivers/migrating-container-overrides.md).

**Constituent backup / constituent restore**: An ordinary
per-deployment backup (or restore) that belongs to an **environment
backup** (or **environment restore**). You can still list, delete, and
expire each constituent on its own. See [Backups and
restores](./backups-and-restores.md#backing-up-a-whole-environment).

**Context (GlobalContext)**: The resolved configuration that both the
**server** and the **agent** use. Embedded in the `context` field of the
**instance** and in the `spec` of the **StyrminDeployment** resource.
It does not change during the lifetime of an instance. See [The context
(GlobalContext)](../drivers/context.md).

**Cross-target restore**: The restore of a **constituent backup** of
one deployment into another deployment: the deployment that an
environment clone creates for it in the new environment, in that
deployment's own namespace. Only an environment clone makes one. See
[Cloning an environment](./backups-and-restores.md#cloning-an-environment).

### D

**Deployment**: The long-lived record of the desired state of one
application in one environment: which application driver version, which
application version, and the user's configuration. Editing it starts a
**reconciliation**.

**DeploymentStatus**: The latest `.status` of a deployment's
`StyrminDeployment` resource, stored for each deployment. Different from
the **deployment state** enum.

**Deployment state**: The enum on `Deployment.status`: `PENDING`,
`DEPLOYING`, `RUNNING`, `RESTORING`, `FAILED`, `DELETING`, `DELETED`.

### E

**Environment**: A logical deployment target in one **cluster**, such as
`dev`, `staging`, or `prod`. It groups deployments that share a
lifecycle and a backup storage location.

**Environment backup**: A snapshot of one environment, taken in one
operation: its configuration at backup time, the declared state of every
eligible deployment, and one **constituent backup** per eligible
deployment. Styrmin records them as one record and computes its status
from its constituents. Deleting it also deletes its constituents. See
[Backups and restores](./backups-and-restores.md#backing-up-a-whole-environment).

**Environment restore**: The operation that applies the configuration
captured in an environment backup again and restores every usable
constituent backup **in place**, into the deployment it came from. It
reports every constituent it could not restore, with a deployment name
and a reason, and never creates or deletes deployments. Requires the
administrator role.

### F

**Flow / Prefect flow**: A unit of orchestration (`CREATE_INSTANCE`,
`UPDATE_INSTANCE`, `UPGRADE_INSTANCE`, …) that the server submits. The
internal flows, such as `apply_state` and the backup and restore flows,
run on the `task-worker` of the server's Helm chart, which polls the
work pool `styrmin-work-pool`. The flows that these start to act on the
cluster, such as `create_instance_crd`, and the driver actions run on
the agent's Prefect worker, which polls the work pool `user-work-pool`.

**Frontend**: The React 19 + Vite single-page app that uses the GraphQL
API.

### G

**Generator**: The server component that builds a new **instance** from a
**deployment** and resolves the **context** as part of the build.

**GlobalContext**: See **Context**.

### H

**HelmRelease**: The FluxCD v2 custom resource that declares a Helm
chart, its version, and its values. The **operator** creates and updates
it from the resolved context.

**Hook**: A point in the deployment lifecycle at which actions run:
`setup` (during create) and `upgrade` (during upgrade). Each hook has
three **modes**.

### I

**Image override**: The image reference that a user sets on one
component of one deployment. Styrmin applies it to the **component
container** after the Helm chart renders. It is a full reference with an
explicit tag or digest; a `{{ app.version }}` token follows the
application version, and a literal tag pins the image. See [Image
overrides](./image-overrides.md).

**In-place restore**: The restore of a backup into the deployment it was
taken of, in that deployment's namespace `styrmin-<deployment id>`,
whichever **instance** of the deployment the backup belongs to. You
start it from the Backups tab, `styrminctl backups restore`, the Python
SDK, GraphQL, or an **environment restore**, and you name only the
backup. The restore does not change the deployment's **active
instance**. See [What happens when you
restore](./backups-and-restores.md#what-happens-when-you-restore).

**Instance (ApplicationInstance)**: A fixed record of what was deployed
at one point in time. Styrmin generates it from a deployment at
reconciliation time. A deployment has at most one **active instance** at
a time.

### M

**Mode**: The phase within a **hook**: `pre`, `core`, or `post`. The
modes run in this order; the order of the actions inside one mode is not
defined.

### O

**Observed state**: The state that the agent reads from the cluster, as
opposed to the declared state. Stored in `PodStatus` and
`DeploymentStatus`. The observed and the declared state can differ.

**Operator**: The kopf-based controller inside the agent that watches
**StyrminDeployment** resources and reconciles them into Kubernetes
resources. See [The operator and
`StyrminDeployment`](./operator-and-crds.md).

### P

**Parameter**: A user-configurable input declared by the application
driver. The GraphQL API and the frontend forms show it. When a
deployment changes to a driver version that no longer declares a
parameter, Styrmin drops the parameter's value if it equals the
parameter's default in the current driver version, and otherwise rejects
the change (`RETIRED_PARAMETER_VALUE`). See [Migrate the infrahub
replica parameters](../drivers/migrating-replica-parameters.md).

**PodStatus**: The observed state of one pod (one row per
`(deployment_id, pod_name)`).

**Prefect**: The workflow engine that Styrmin uses to run flows on the
agent.

### R

**Reconciliation**: Comparing a deployment's newly generated instance
with its active instance and listing the changes to apply. Styrmin runs
it for each change. See [Reconciliation](./reconciliation.md).

**Recorded intent**: The server records the intended state in database
rows and custom resources, and the agent reads it. The server does not
call the agent.

**Remediator**: The server service that maps the difference between a
newly generated instance and the active instance to a Prefect flow.

**Replica override**: The replica count that a user sets on one
component of one deployment: a whole number of 1 or more. Styrmin
applies it after the Helm chart renders, to `spec.replicas` of every
`Deployment` and `StatefulSet` that matches the component's label
selector. Order of precedence: the replica override, then the driver
default (`components.<name>.replicas`, or 1 for a **singleton
component**), then the chart's count, which Styrmin does not change. A
stopped component runs 0 pods and keeps its override. See [Replica
overrides](./replica-overrides.md).

### S

**SDK / styrmin-sdk**: The async Python client SDK that wraps the
GraphQL operations as typed Pydantic models.

**Server**: The Styrmin backend process. It owns the database, exposes
the GraphQL API, and stores what should run.

**Service (deployed service)**: A network endpoint that the application
driver declares and that Styrmin creates as a Kubernetes `Service`.

**Service ingress override**: The ingress class, the FQDN suffix, or
both, that a deployment sets for one external service of its application
driver version. It replaces the resolved class and suffix for that
service only. You set it in a manifest (`spec.config.services`), through
the API, or in the Configuration tab and the deploy form. Styrmin refuses
an override on a service that is not `scope: external`. See [Service
ingress overrides](./service-ingress-overrides.md).

**Singleton component**: A component that the application driver
version marks `singleton: true`. Styrmin sets its replica count to 1 and
rejects a **replica override** greater than 1
(`SINGLETON_REPLICA_OVERRIDE`). The flag limits the replica count, not
the number of pods that run at the same time during a rolling update.
See [Replica overrides](./replica-overrides.md#singleton-components).

**Status reporter**: The coroutine inside the agent that polls
Kubernetes and sends `PodStatus` and `DeploymentStatus` snapshots to the
server. See [Status reporting](./status-reporting.md).

**Styrmin-built Ingress**: The Ingress that Styrmin builds for a service
that its application driver declares `scope: external`. The driver's
chart renders no Ingress for that service. Styrmin builds it from the
resolved ingress class and FQDN suffix, or from a **service ingress
override**. See [The Ingress that Styrmin builds for an external
service](./ingress-and-networking.md#the-ingress-that-styrmin-builds-for-an-external-service).

**Step**: One unit of work inside a task, a backup, or a restore,
recorded so that users can view it: its name, status (`PENDING`,
`RUNNING`, `SUCCEEDED`, `FAILED`, or `SUPERSEDED`), start and end time,
number of attempts, the error of each failed attempt, and the end of a
failed command's output. One run of a hook's mode is one step (for
example, "Run the upgrade pre-hook"); each operator phase is one step
(for example, "Install or upgrade the HelmRelease"). See [Status
reporting](./status-reporting.md#steps-from-status-reports) and
[Lifecycle hooks and actions](./hooks-and-actions.md#steps-of-a-hook).

**StyrminDeployment**: The custom resource that the **operator**
reconciles, one per deployment. Its `spec` contains the embedded
context. The `StyrminDeployment` CRD defines its type.

### T

**Task (database record)**: A row that tracks one asynchronous
operation, with `status`, `type` (for example, `create_instance`,
`update_instance`, `upgrade_instance`, `stop_components`,
`start_components`, `run_job`, or `delete_deployment`), and the Prefect
flow run id. Its `status` follows only the Prefect flow run. Not the
same as Prefect's in-process `task` primitive.

**Task result**: The result of a task as users view it, calculated from
its steps and its `status` on every read and never stored. It covers the
task and every task that its hook steps started, at any depth. The first
rule that matches applies: `RUNNING` while the flow of one of these
tasks runs, or a step of these tasks runs or has not started (a step
that waits behind a failed step of its own task does not count);
`FAILED` when the flow or a step of one of these tasks failed;
`SUPERSEDED` when a task outside them interrupted the operator phases of
one of them; `SUCCEEDED` otherwise. A task without steps takes its
result from its `status`.

**Tombstone / tombstoned deployment**: A deployment record whose
workload has been deleted from the cluster, but which Styrmin keeps for
the timeline, backups, and auditing.

### U

**Utility**: A cluster-level resource (ingress controller, service
discovery, …) that Styrmin creates with the same code as application
resources.
Internal to Styrmin; users do not manage it.

### V

**vCluster**: The virtual Kubernetes cluster that the local demo runs
on. The [Quickstart](../installation/quickstart.md) creates one.
