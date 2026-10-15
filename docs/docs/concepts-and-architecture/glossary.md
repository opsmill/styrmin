---
title: Glossary
sidebar_position: 3
description: Every term Styrmin uses, in one alphabetical list, with cross-references to the page that explains it in depth.
---

## Glossary

Single-line definitions for every Styrmin term that appears in the
docs, the GraphQL schema, the SDK, the CLI, and the UI. Use this page
when you encounter a word and want to know what it means in one
sentence. For the mental model and how the pieces fit together, read
[Core concepts](./core-concepts.md).

### A

**Action** — A Python function declared by an Application Driver that
runs inside a Prefect flow at a specific lifecycle **hook** and
**mode** (e.g. `setup` / `pre`). See [Lifecycle hooks and
actions](./hooks-and-actions.md).

**Active instance** — The single **Instance** currently considered
live for a **Deployment**. Reconciliation compares the newly generated
Instance against the active Instance.

**Agent** — The container Styrmin runs inside a target Kubernetes
cluster. Reconciles **recorded intent** into Kubernetes resources and
reports observed state back to the **server**. One per **cluster**.

**Application Driver** — A versioned, self-contained deployment
specification for one application. The unit of deployment in Styrmin.
See [What is an Application Driver?](./what-is-a-driver.md).

**Application Driver Version** — A specific revision of an
Application Driver, with its own Helm chart pin, components,
parameters, services, and actions. A **Deployment** points at one
Application Driver Version.

**Application Version** — The user-facing version of the application
itself (e.g. Infrahub `1.6.0`). Distinct from the Application Driver
Version that knows how to deploy it.

### B

**Backup history** — The backups of every **Instance** a **Deployment**
has had, newest first. Backups taken before an upgrade, a config edit or
an environment config change stay in it, and a deleted deployment keeps
it. The Backups tab and `styrminctl backups list` show it. See [Backup
history of a
deployment](backups-and-restores.md#backup-history-of-a-deployment).

**Backup Storage Location (BSL)** — An S3-compatible object store
registered as a destination for Velero backups. Assigned to an
**Environment**; all deployments in that environment back up there.

### C

**CLI / styrminctl** — The Cyclopts-based command-line client. Thin
wrapper over the GraphQL API.

**Cluster** — A Kubernetes cluster registered with Styrmin.
Cluster-level settings are inherited by every Environment and
Deployment on it. One **agent** runs per Cluster.

**Component** — A logical sub-part of an application (e.g. `server`,
`task-worker`) declared by the Application Driver and identified by a
Kubernetes label selector. Lifecycle controls (start/stop, restart) act
on the Component as a unit. Its replica count comes from a **Replica
override**, the driver default or the Helm chart.

**Component container** — The one container in a Component's pod
that the Application Driver names (`components.<name>.container`) to
receive the overrides users set on a Deployment: env vars, the **Image
override**, and container `command` and `args`. Styrmin applies them
after the Helm chart renders: env vars merge in by name, so the chart's
own env entries survive, and a `command` or `args` override replaces
that whole list. A component without one accepts none of these
component-scope overrides (`COMPONENT_CONTAINER_NOT_DECLARED`). A
declared name the chart does not render fails the deployment with
`COMPONENT_CONTAINER_NOT_FOUND` once any override targets the
component; Styrmin never adds a container. See [Creating a
Driver](../drivers/creating-a-driver.md#the-component-container).

**Component overrides** — The mechanism by which a Deployment
overrides the Application Driver Version's default Component config:
per-component env vars, **Image override**, container `command` and
`args`, and **Replica override**. Styrmin applies all of them after the
Helm chart renders; the driver's values template does not pass them to
the chart. Env vars, the image override, `command` and `args` go to the
**Component container**; the replica override goes to the component's
`Deployment` and `StatefulSet` workloads and needs no component
container. See [Migrating container
overrides](../drivers/migrating-container-overrides.md).

**Constituent backup / constituent restore** — An ordinary
per-deployment backup (or restore) that belongs to an **Environment
backup** (or **Environment restore**). Constituents stay individually
listable, deletable, and subject to per-backup retention. See [Backups
and restores](./backups-and-restores.md#backing-up-a-whole-environment).

**Context (GlobalContext)** — The resolved configuration snapshot
both the **server** and the **agent** act on. Embedded in both the
**Instance**'s `context` field and the **StyrminDeployment** CRD spec.
Frozen for the lifetime of an Instance. See [the Context
page](../drivers/context.md).

### D

**Deployment** — The long-lived record carrying the desired state of
one application in one Environment: which Application Driver Version,
which Application Version, and the user's config. Editing it triggers
**reconciliation**.

**DeploymentStatus** — The latest `StyrminDeployment` CRD `.status`
snapshot per deployment. Distinct from the **Deployment state** enum.

**Deployment state** — The enum on `Deployment.status`: `PENDING`,
`DEPLOYING`, `RUNNING`, `RESTORING`, `FAILED`, `DELETING`, `DELETED`.

**Dual-entrypoint E2E** — E2E tests that run twice, once driven
through the SDK and once through Playwright, so both the API surface
and the UI surface stay in sync.

### E

**E2E (test tier)** — End-to-end test against a real vcluster with
FluxCD, Prefect, and supporting services — no mocks.

**Environment** — A logical deployment target inside a **Cluster** —
`dev`, `staging`, `prod`, etc. Groups Deployments that share a
lifecycle and a Backup Storage Location.

**Environment backup** — A coordinated, near-consistent snapshot of one
Environment: its config as of backup time, the declared state of every
eligible Deployment, and one **constituent backup** per eligible
Deployment, grouped under a single record whose status is derived from
its constituents. Deleting it cascades to its constituents. See [Backups
and restores](./backups-and-restores.md#backing-up-a-whole-environment).

**Environment restore** — The coordinated operation that reapplies an
Environment backup's captured config and restores every usable
constituent backup **in place**, into the Deployment it came from.
Reports every constituent it could not restore with a deployment name
and reason; never creates or deletes Deployments. Requires the
administrator role.

### F

**Flow / Prefect flow** — A unit of orchestration (`CREATE_INSTANCE`,
`UPDATE_INSTANCE`, `UPGRADE_INSTANCE`, ...) submitted by the server
and executed on the agent's Prefect worker.

**Frontend** — The React 19 + Vite single-page app that consumes the
GraphQL API.

### G

**Generator** — The server component that builds a fresh **Instance**
from a **Deployment**, resolving the **Context** as part of the build.

**GlobalContext** — See **Context**.

**GraphQL operation** — A query or mutation defined in a `.graphql`
file. Inline GraphQL strings in Python are not allowed.

### H

**HelmRelease** — The FluxCD v2 CRD declaring desired Helm chart
state. Created and updated by the **operator** based on the resolved
Context.

**Hook** — A lifecycle slot at which Actions run. Currently `setup`
(during create) and `upgrade` (during upgrade). Each Hook has three
**Modes**.

### I

**Image override** — The image reference a user sets on one Component
of one Deployment, applied to its **Component container** after the
Helm chart renders. A full reference with an explicit tag or digest; a
`{{ app.version }}` token follows the Application Version, and a literal
tag pins the image. See [Image overrides](./image-overrides.md).

**Instance (ApplicationInstance)** — A frozen snapshot of what was
deployed at a point in time. Generated from a Deployment at
reconciliation time. A Deployment owns at most one **active
instance** at a time.

### M

**Mode** — The execution phase within a **Hook**: `pre`, `core`, or
`post`. Ordering across modes is strict; ordering inside a mode is
unspecified.

### O

**Observed state** — What the agent actually sees in the cluster, as
opposed to declared state. Captured in `PodStatus` and
`DeploymentStatus`. Drift between observed and declared is expected.

**Operator** — The kopf-based controller running inside the agent
that watches **StyrminDeployment** CRDs and reconciles them into
Kubernetes resources. See [The operator and
`StyrminDeployment`](./operator-and-crds.md).

### P

**Parameter** — A user-configurable input declared by the Application
Driver. Surfaced through the GraphQL API and frontend forms. When a
Deployment changes to a driver version that no longer declares a
parameter, Styrmin drops the parameter's value if it equals the
parameter's default in the current driver version, and otherwise rejects
the change (`RETIRED_PARAMETER_VALUE`). See [Migrating Replica
Parameters](../drivers/migrating-replica-parameters.md).

**PodStatus** — Per-pod observed-state record (one row per
`(deployment_id, pod_name)`).

**Prefect** — The workflow engine Styrmin uses to orchestrate Flows
on the agent.

### R

**Reconciliation** — The act of comparing the Deployment's newly
generated Instance against the active Instance and planning the
convergence work. The core loop of Styrmin. See
[Reconciliation](./reconciliation.md).

**Recorded intent** — The flow of direction from server to agent
through database rows and CRDs, not direct RPC. The server never
calls the agent directly.

**Remediator** — The server service that maps the diff between a
newly generated Instance and the active Instance to a Prefect flow.

**Replica override** — The replica count a user sets on one Component of
one Deployment, a whole number of 1 or more. Styrmin applies it after the
Helm chart renders, to `spec.replicas` of every `Deployment` and
`StatefulSet` that matches the component's label selector. Order of
precedence: the replica override, then the driver default
(`components.<name>.replicas`, or 1 for a **Singleton component**), then
the chart's count, which Styrmin does not change. A stopped component
runs 0 pods and keeps its override. See [Replica
overrides](./replica-overrides.md).

### S

**SDK / styrmin-sdk** — The async Python client SDK that wraps
GraphQL operations as typed Pydantic models.

**Server** — The Styrmin backend process. Owns the database, exposes
the GraphQL API. The single source of truth for what should be
running.

**Service (deployed service)** — A network-addressable endpoint
declared by the Application Driver and materialised as a Kubernetes
`Service` object.

**Singleton component** — A Component that the Application Driver
Version marks `singleton: true`. Styrmin sets its replica count to 1 and
rejects a **Replica override** greater than 1
(`SINGLETON_REPLICA_OVERRIDE`). The flag limits the replica count, not
the number of pods that run at the same time during a rolling update.
See [Replica overrides](./replica-overrides.md#singleton-components).

**Status reporter** — The coroutine inside the agent that polls
Kubernetes and posts `PodStatus` / `DeploymentStatus` snapshots back
to the server. See [Status reporting](./status-reporting.md).

**Step** — One unit of work inside a Task, a backup or a restore,
recorded so users can view it: its name, status (`PENDING`, `RUNNING`,
`SUCCEEDED`, `FAILED` or `SUPERSEDED`), start and end time, number of
attempts, the error of each failed attempt, and the end of a failed
command's output. One run of a Hook's Mode is one step (for example "Run
the upgrade pre-hook"); each operator phase is one step (for example
"Install or upgrade the HelmRelease"). See [Status
reporting](./status-reporting.md#steps-from-status-reports) and
[Lifecycle hooks and actions](./hooks-and-actions.md#steps-of-a-hook).

**StyrminDeployment (CRD)** — Styrmin's primary Custom Resource
Definition. Carries the embedded Context in `spec`; watched by the
**operator**.

### T

**Task (database record)** — A row tracking one asynchronous
operation, with `status`, `type` (for example `create_instance`,
`update_instance`, `upgrade_instance`, `stop_components`,
`start_components`, `run_job` or `delete_deployment`), and the Prefect
flow run id. Its `status` follows only the Prefect flow run. Not to be
confused with Prefect's in-process `task` primitive.

**Task result** — The result of a Task as users view it, calculated
from its Steps and its `status` on every read and never stored. It covers the task and
every task that its hook steps started, at any depth. The first rule
that matches wins: `RUNNING` while the flow of one of these tasks runs,
or a step of these tasks runs or has not started (a step that waits
behind a failed step of its own task does not count); `FAILED` when the
flow or a step of one of these tasks failed; `SUPERSEDED` when a task
outside them interrupted the operator phases of one of them; `SUCCEEDED`
otherwise. A task without steps takes its result from its `status`.

**Tombstone / tombstoned deployment** — A Deployment row whose
cluster-side workload has been torn down but whose record is retained
for timeline, backups, and audit.

### U

**Utility** — A cluster-level resource (ingress controller, service
discovery, ...) managed by the same builders that produce application
resources. Internal to Styrmin; not user-facing in normal use.

### V

**vcluster** — The virtual Kubernetes cluster used as the E2E test
target and the local-demo runtime. Bundled with the Styrmin repo's
Quickstart workflow.
