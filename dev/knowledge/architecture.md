# Styrmin Architecture

A high-level, descriptive view of how the Styrmin system is built today: the
relationship between the server and the agent, what the agent does, how
desired and current state are modelled, and how context binds them together.

This document is the **technical companion to the [constitution](../constitution.md)**.
The constitution is *prescriptive* — it defines the principles we commit to
("MUST", "SHOULD"). This document is *descriptive* — it explains how those
principles are realised in code today. When the two diverge, the constitution
wins and this document is what gets corrected.

**Audience.** Contributors and agents who want a single place to understand
how the pieces fit together before reading the per-component knowledge docs in
[`agent/`](agent/), [`backend/`](backend/), and [`frontend/`](frontend/).

---

## 1. The server and the agent

Styrmin runs as **two cooperating processes**, each with a clearly bounded
job. The server holds the database and exposes the public API; the agent
turns recorded intent into running Kubernetes resources.

### 1.1 Topology

| Process | What it is | What it owns |
|---------|------------|--------------|
| **Server** | FastAPI + GraphQL backend | The database, all GraphQL operations, task records, the SDK contract |
| **Agent** | One container running a Prefect worker, a kopf operator, **and** a status reporter in a single async event loop | Everything inside the target Kubernetes cluster: CRDs, HelmReleases, NetworkPolicies, Secrets, Services, Middlewares; plus reporting observed cluster state back to the server |

The Prefect worker and the kopf operator share one event loop via
`asyncio.gather()`. Graceful shutdown is coordinated through an
`asyncio.Event` so both halves stop together — see
[ADR-002](../adr/0002-shared-async-event-loop-kopf-prefect.md).

### 1.2 How the server directs the agent

The server never calls the agent directly. Direction flows through
**recorded intent** at three layers:

1. **GraphQL → service → Task.** A mutation reaches the service layer,
   which writes a `Task` record and submits a Prefect flow.
2. **Prefect flow → CRD.** The flow runs on the agent. It resolves the
   deployment's full configuration into a `GlobalContext` and writes (or
   updates) a `StyrminDeployment` CRD with that context embedded in its
   spec — see [ADR-004](../adr/0004-embed-context-in-deployment-crd.md)
   and [ADR-006](../adr/0006-prefect-crd-intent-declaration.md).
3. **CRD → operator → Kubernetes.** The kopf operator watches
   `StyrminDeployment` CRDs and reconciles the cluster on its own — no
   back-channel calls to the server are required.

Status flows back the other way: Prefect callbacks POST to the server's
internal GraphQL endpoint to update task and deployment status; the agent's
status reporter periodically writes pod and CRD snapshots to the database.
USER flows and driver actions record the steps of their task, backup or
restore through the `recordStep` mutation with the action token; server code
and INTERNAL flows call the step recorder directly. The server turns each
CRD snapshot of a rollout into the operator-phase steps of the newest task
that rolled out the reported instance (the CR's `status.instanceId`), and
each snapshot in the `Deleting` or `Deleted` phase into the steps of the
deployment's newest `delete_deployment` task — see
[ADR-060](../adr/0060-steps-and-derived-task-result.md).

Once a day, the server's task worker (the Prefect worker of
`styrmin-work-pool`) runs the INTERNAL flow `send_telemetry_report`, which
posts one anonymous report about the install to the telemetry endpoint unless
telemetry is turned off — see
[ADR-061](../adr/0061-server-anonymous-daily-telemetry.md).

### 1.3 What the agent does

The agent is a single process but fulfils several distinct functions:

- **Workflow orchestration.** The `PrefectManager` registers, schedules,
  and runs internal and user-defined workflows.
  → details: [`agent/overview.md`](agent/overview.md)
- **Context resolution and CRD authorship.** Orchestration flows resolve a
  full `GlobalContext` from the database and embed it in the
  `StyrminDeployment` CRD.
  → details: [`backend/orchestration-flows.md`](backend/orchestration-flows.md)
- **Helm rendering.** Tasks render `HelmRelease` specs from driver-supplied
  templates against the resolved context.
  → details: [`agent/overview.md`](agent/overview.md)
- **Kubernetes resource reconciliation.** The kopf operator drives
  `StyrminDeployment` resources through ordered phases (prerequisites →
  HelmRelease → services), guaranteeing that dependencies exist before
  dependents — see [ADR-005](../adr/0005-ordered-phase-deployment-sub-handlers.md).
  → details: [`agent/operator.md`](agent/operator.md)
- **Drift detection and correction.** A timer handler re-checks managed
  resources on a fixed cadence and corrects anything that has drifted from
  the CRD spec.
  → details: [`agent/operator.md`](agent/operator.md)
- **Driver hook execution.** Pre / core / post hooks defined by an
  application driver run inside Prefect as part of the create, update, and
  upgrade flows.
  → details: [`backend/hooks-and-actions.md`](backend/hooks-and-actions.md)
- **Utility resource management.** Cluster-level utilities (ingress,
  service discovery) are managed by the same builders that produce
  application resources.
  → details: [`agent/overview.md`](agent/overview.md)
- **Status reporting.** A third coroutine in the shared event loop polls
  Kubernetes every ~5 s (configurable via
  `STYRMIN_AGENT_STATUS_POLL_INTERVAL`) for pod state and
  `StyrminDeployment` CRD status, then posts the snapshots back via
  `reportPodStatuses` and `reportDeploymentStatuses` GraphQL mutations.
  This is distinct from Prefect's flow-state callbacks: the reporter
  describes *what is running in the cluster*, not *what workflows are
  doing*. The CRD snapshot carries `status.instanceId`, the instance the
  operator acted on, which links it to the task whose operator-phase steps
  it moves.
  → details: [`agent/overview.md`](agent/overview.md) (Status Reporter section)

---

## 2. State and the declarative model

Styrmin is a declarative system: every change is expressed as "this is what
the world should look like", and the system is responsible for making the
world match. This is Constitution Principle I in code form.

### 2.1 Desired vs current

Two persistent records carry the state of any given application:

- **`Deployment`** — the *desired* state. A long-lived record holding the
  application version, configuration, environment reference, and driver
  version. Editing a Deployment expresses a new intent.
- **`Instance`** (`ApplicationInstance` in the database) — the *current*
  realised state. A frozen snapshot of what was actually deployed at a
  point in time, including the resolved context.

A Deployment owns at most one *active* Instance at a time. Reconciliation
generates a fresh Instance from the Deployment and asks: does the active
Instance already match? If yes, nothing happens. If no, the system plans
the work needed to converge.

### 2.2 The reconciliation loop

The loop has three steps and lives in
[`services/reconciliation/`](../../backend/styrmin_backend/services/reconciliation/):

1. **Generate** — `apply_state()` calls `generate_instance_from_deployment()`,
   which assembles a new `Instance` from the Deployment's current
   configuration.
2. **Compare** — a `Comparator` diffs the new Instance against the active
   Instance using DeepDiff, producing a typed `DiffReport`. Identity
   fields (`id`, `name`, `status`) are excluded; all context changes
   collapse into a single `ContextChange` entry.
3. **Remediate** — a `Remediator` maps the `DiffReport` to a `Remediation`
   that names the Prefect flow to run (`CREATE_INSTANCE`,
   `UPDATE_INSTANCE`, `UPGRADE_INSTANCE`, …) and the parameters to pass.

Possible diff outcomes:

| Current | New | Diff type | Typical remediation |
|---------|-----|-----------|---------------------|
| absent | present | `InstanceCreation` | `CREATE_INSTANCE` |
| present | present (different) | `InstanceUpdate` | `UPDATE_INSTANCE` or `UPGRADE_INSTANCE` |
| present | absent | `InstanceDeletion` | not yet implemented |
| equal | equal | no diff | no remediation |

### 2.3 Idempotence by structure

A converged system produces no diff, which means no remediation, which
means no flow submission. Re-running reconciliation on a system that is
already in the desired state is a no-op by construction — not by careful
guarding inside the flows. This is what Principle I means by "idempotent".

### 2.4 The same pattern, twice

The declarative model repeats at the Kubernetes layer. The agent declares
its desired Kubernetes state in a `StyrminDeployment` CRD, and kopf
reconciles the cluster to match. From there, FluxCD reconciles
`HelmRelease` resources into actual workloads. Three nested loops, each
running on its own cadence, each comparing desired against current.

For the full mechanism see [`backend/reconciliation.md`](backend/reconciliation.md);
for the data model see [`backend/data-models.md`](backend/data-models.md).

---

## 3. Context: the bridge between deployment and instance

The hardest part of a deployment platform is *which configuration applies
where*. Styrmin solves this with a single, hierarchical model called
`GlobalContext`. Context is what makes the agent autonomous and what makes
the declarative loop closable.

### 3.1 What context is

`GlobalContext` is a Pydantic model — not a separate database table, not a
separate CRD. It is the **resolved configuration snapshot** that both the
server (for bookkeeping) and the agent (for rendering and reconciliation)
need in order to act.

It is produced by `generate_context_from_deployment()`, which walks the
database and merges configuration from every relevant source: the cluster,
the environment, the deployment itself, the application driver, and the
Helm chart.

### 3.2 Composition

```text
GlobalContext
├── ClusterContext       (cluster config + capabilities)
├── EnvironmentContext   (environment config + capabilities; can override cluster)
├── DeploymentContext    (deployment config; can override environment)
├── InstanceContext      (the merged ResolvedConfig + namespace + release_reference)
├── ApplicationContext   (name, version, helm chart info)
├── ComponentsContext    (per-component config, optional)
└── utilities            (list of UtilityContext)
```

Each level can override the level above it. `InstanceContext.config` is
the final merged view that drivers and templates actually see.

### 3.3 How context relates Deployment and Instance

- The **Deployment** owns the *inputs* — its own config dict, its
  environment reference, its driver version. The Deployment's inputs may
  change over time as users edit it.
- At reconciliation time, those inputs are *resolved* into a
  `GlobalContext`.
- That `GlobalContext` is **embedded** in the new `Instance`'s `context`
  field **and** copied into the `StyrminDeployment` CRD spec.
- Once embedded, the context is **frozen** for the lifetime of that
  Instance. A new Instance means a new resolution and a new context.

In short: a Deployment's config is the *recipe*; an Instance's context is
the *meal* — what was actually plated, with every substitution and
override already applied.

### 3.4 Why context lives on the Instance, not on the Deployment

Because the agent must be able to render, reconcile, and recover *without
calling back to the server*. If the resolved context lived on the
Deployment, the agent would need to query the server every time it
reconciled — and would have to deal with the Deployment changing
mid-reconciliation. By snapshotting the context onto the Instance and the
CRD at submission time, the agent gets a stable, complete specification it
can act on autonomously. This is the core motivation in
[ADR-004](../adr/0004-embed-context-in-deployment-crd.md).

### 3.5 Why context is the unit of state

Any change to cluster, environment, deployment, or driver configuration
that affects rendering surfaces as a `ContextChange` diff entry, which
triggers an `UPDATE_INSTANCE` (or `UPGRADE_INSTANCE`) remediation. Context
is therefore the single thing that ties the entire declarative loop
together: edit a config field anywhere in the hierarchy, and reconciliation
will notice, plan a remediation, and converge.

Reconciliation runs per deployment, so a change above the deployment
reaches it only when something starts a reconciliation of that deployment.
An edit of a deployment reconciles that deployment. An edit of an
environment or a cluster config reaches the deployments through a **config
fan-out**, which redeploys each affected deployment at its current
application version and driver version:

- **Environment config fan-out** (`services/environments.py`,
  [ADR-012](../adr/0012-environment-config-fanout.md)). `update_environment`
  commits the environment row, then redeploys each live, non-internal
  deployment of the environment whose active instance stores a different
  environment config (`context.environment.config`).
- **Cluster config fan-out** (`services/cluster_config_fanout.py`,
  [ADR-065](../adr/0065-cluster-config-fanout.md)). `update_cluster` commits
  the cluster config and its recomputed capabilities, then
  `fan_out_cluster_config` evaluates every live, non-internal deployment of
  every environment of the cluster. It compares the resolved config computed
  now (`resolve_instance_config`: cluster, then environment, then deployment)
  with `context.instance.config` of the active instance, so a deployment in an
  environment that overrides the changed value is not redeployed. When an
  environment's effective `dedicated_ingress` changes, the fan-out creates or
  redeploys the environment's dedicated ingress controller and holds back the
  applications that would move onto it until the controller is `RUNNING` with
  the new values.

The cluster config fan-out continues in the status reporter
(`report_deployment_statuses` in `services/deployment_status.py`), on a state
change only and inside a savepoint. An internal deployment that reaches
`RUNNING` runs `continue_environment_fan_out` for its environment, which
redeploys the applications that waited. An internal deployment that reaches
`FAILED`, and an application that reaches `RUNNING` or `FAILED`, run
`tear_down_unused_ingress_controller`, which removes the controller once the
environment's effective `dedicated_ingress` is off and every application has
been redeployed without it. Both fan-outs compare per deployment, so a
resubmission of the same config is a no-op except for the deployments that an
earlier fan-out could not redeploy.

For the full field list see [`backend/data-models.md`](backend/data-models.md).

---

## 4. Relationship to the constitution

This document describes the implementation of several constitutional
principles. The mapping:

| Section | Constitution principle |
|---------|------------------------|
| §1 The server and the agent | III. Layered Architecture |
| §2 State and the declarative model | I. Declarative State Reconciliation |
| §3 Context | I. Declarative State Reconciliation (its enabling mechanism) |
| (driver model, referenced throughout) | II. Driver-Based Deployment |

The constitution is the source of truth for what we commit to. This
document is the source of truth for what currently exists. If reality
drifts from the constitution, the fix is to either change the code or
amend the constitution — and update this document accordingly.

---

## 5. Glossary

- **Agent** — single container running the Prefect worker and the kopf
  operator. Reconciles intent into Kubernetes resources. See
  [`agent/overview.md`](agent/overview.md).
- **ApplicationDriver** — versioned spec defining how an application is
  deployed (helm chart, components, hooks). See the `driver/` directory.
- **Comparator** — service that diffs two Instances and produces a
  `DiffReport`. See [`backend/reconciliation.md`](backend/reconciliation.md).
- **Context / GlobalContext** — hierarchical Pydantic model holding the
  resolved configuration for an Instance. Embedded in both the database
  Instance row and the `StyrminDeployment` CRD spec.
- **CRD** — Kubernetes Custom Resource Definition. Styrmin's primary CRD
  is `StyrminDeployment`.
- **Deployment** — desired-state record: which application version with
  which configuration in which environment.
- **DiffReport** — typed result of comparing two Instances:
  `InstanceCreation`, `InstanceUpdate`, or `InstanceDeletion`.
- **HelmRelease** — FluxCD v2 CRD declaring desired Helm chart state.
  Created and updated by the operator.
- **Instance** (`ApplicationInstance`) — current-state snapshot generated
  from a Deployment, carrying a frozen `GlobalContext`.
- **Operator** — the kopf-based controller running inside the agent that
  watches `StyrminDeployment` CRDs. See [`agent/operator.md`](agent/operator.md).
- **Phase-based deployment** — kopf sub-handler ordering that guarantees
  prerequisites land before HelmReleases and services. See
  [ADR-005](../adr/0005-ordered-phase-deployment-sub-handlers.md).
- **PrefectManager** — service wrapping the Prefect SDK. Submits flows,
  manages work pools, registers user actions.
- **Reconciliation** — the act of comparing desired (new Instance) against
  current (active Instance) and planning convergence work.
- **Remediation** — plan object identifying which Prefect flow to run and
  with which parameters to apply a diff.
- **Remediator** — service that maps a `DiffReport` to a `Remediation`.
- **Server** — the FastAPI + GraphQL backend. Owns the database and the
  public API.
- **Step** — one unit of work inside a task, a backup or a restore (a hook
  mode, the CRD write, an operator phase, a restore stage, one component of
  a backup), with its status, times, attempts and errors. Written only
  through the step recorder.
- **StyrminDeployment** — the operator's CRD. Carries the embedded
  `GlobalContext` and is the agent's single source of truth about what
  should be running.
- **Task** — database record tracking an asynchronous operation
  (`CREATE_INSTANCE`, `UPDATE_INSTANCE`, `UPGRADE_INSTANCE`, …) and its
  Prefect flow run. `Task.status` follows only the flow run.
- **Task result** — the result users view for a task (`RUNNING`, `FAILED`,
  `SUCCEEDED`, `SUPERSEDED`). Calculated on every read from the steps and
  `Task.status` of the task and of the tasks its hook steps started, and
  never stored.
