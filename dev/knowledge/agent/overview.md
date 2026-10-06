# Styrmin Agent

The agent is the in-cluster process responsible for everything that happens inside the target Kubernetes cluster. A single container runs three coroutines on a shared async event loop:

- **Kopf operator** — watches `StyrminDeployment` CRDs and drives Kubernetes resources to match. See [operator.md](operator.md).
- **Prefect worker** — executes the internal orchestration flows that the server submits (`apply_state`, `create_instance`, `update_instance`, `upgrade_instance`, `run_job`). The USER flows that these start (the remediation flows `create_instance_crd`, `update_instance_crd` and `upgrade_instance_crd`, and `run_job_command`) run as Kubernetes Jobs in the user work pool. The flow definitions live under `agent/tasks/` but the catalogue, manager API, and callback wiring belong to the orchestration layer (see [`../backend/orchestration-flows.md`](../backend/orchestration-flows.md)).
- **Status reporter** — periodically observes pod and CRD state and reports it back to the server. See [Status Reporter](#status-reporter).

[ADR-002](../../adr/0002-shared-async-event-loop-kopf-prefect.md) covers the shared event loop. ADR-004, ADR-005, and ADR-006 cover the operator's responsibility split with Prefect.

## Where Prefect lives

Prefect spans both processes. The split is:

- The **server** registers workflow definitions, submits flow runs through `PrefectManager`, and tracks task state in the database.
- The **agent** runs the Prefect *worker* that picks up internal flow runs and executes them. The flow definitions for those internal flows live in `backend/styrmin_backend/agent/tasks/` — physically agent-side code, but conceptually part of the orchestration layer documented in [`../backend/orchestration-flows.md`](../backend/orchestration-flows.md).
- **User actions** (driver-defined hooks) run as separate Kubernetes Jobs in the user work pool, *not* on the agent's worker. See [`../backend/hooks-and-actions.md`](../backend/hooks-and-actions.md).

In short: the agent's Prefect worker is what *runs* internal flows; everything else about Prefect (catalogue, manager, models, work-pool topology) is documented under `backend/`.

## Directory structure (agent-side code)

```text
backend/styrmin_backend/
├── agent/
│   ├── tasks/                  # Prefect flow definitions executed by the agent's worker
│   │   ├── core.py             # Rendering tasks
│   │   ├── application.py      # Application-specific (create/update HelmRelease)
│   │   ├── orchestration.py    # apply_state, create_instance, update_instance, upgrade_instance, run_job, run_job_command
│   │   ├── extra.py            # Utility install/update
│   │   └── shared.py           # Shared task utilities
│   │
│   ├── status/                 # Periodic status reporter (see "Status Reporter")
│   │   ├── reporter.py         # Polling loop, GraphQL mutations
│   │   ├── models.py           # Wire-format DTOs
│   │   ├── queries.py          # load_query() helper
│   │   └── *.graphql           # list_deployments_for_status, report_pod_statuses, report_deployment_statuses
│   │
│   ├── steps/                  # Step writes from USER flows and driver actions (spec 019)
│   │   ├── reporter.py         # StepReporter: recordStep calls with the action token
│   │   ├── backup_components.py # One step per component of a Velero backup
│   │   ├── queries.py          # load_query() helper
│   │   └── record_step.graphql
│   │
│   └── service/                # Kubernetes service layer
│       ├── exceptions.py
│       └── kubernetes/
│           ├── primitives.py   # Low-level K8s ops (apply, delete, list, get_custom_resource)
│           ├── job_logs.py     # End of a failed Job's output (read_job_output_tail)
│           ├── utils.py        # Reference helpers (namespace, release_reference)
│           └── resources/      # Resource builders
│               ├── custom_resource.py     # HelmRelease CRD
│               ├── blocks/                # Modular building blocks (metadata, spec, patches)
│               ├── builders/              # High-level builders (application, utility, backup)
│               └── utilities/             # Utility implementations (ingress, environment)
│
├── operator/                   # Kopf handlers, CRD schema, restore recovery (see operator.md)
│
└── entrypoint/
    └── combined.py             # asyncio.gather(kopf, prefect_worker, status_reporter)
```

The Prefect manager, workflow catalogue, and `WorkflowDefinition` types are *not* listed here — they live under `backend/styrmin_backend/workflows/` and are the server's concern.

## Kubernetes resource building

The agent assembles Kubernetes manifests from the resolved `GlobalContext` and the application driver's templates. The output is a FluxCD v2 `HelmRelease` plus optional NetworkPolicies, Secrets, Services, and Middlewares — all created and managed by the operator (see [operator.md](operator.md) for phase ordering).

### HelmRelease

```python
# resources/custom_resource.py
class HelmRelease:
    api_version: str = "helm.toolkit.fluxcd.io/v2"
    kind: str = "HelmRelease"
    metadata: HelmReleaseMetadata
    spec: HelmReleaseSpec
```

### Resource blocks

Modular building blocks compose into final resource manifests:

| Block | Purpose |
|-------|---------|
| `MetadataBlock` | Name, namespace, labels, annotations |
| `SpecBlock` | HelmRelease spec (chart, values) |
| `PatchesBlock` | Strategic merge patches |

### Builders

| Builder | Purpose |
|---------|---------|
| `ApplicationHelmReleaseBuilder` | HelmRelease for application deployments |
| `UtilityHelmReleaseBuilder` | HelmRelease for utility deployments (ingress, etc.) |

### Utilities

`UtilityFactory` produces utility implementations (`IngressUtility`, `EnvironmentUtility`) for cluster-level infrastructure.

## Combined process

The kopf operator, the Prefect worker, and the status reporter run in a single async process and share one event loop via `asyncio.gather()` (see [ADR-002](../../adr/0002-shared-async-event-loop-kopf-prefect.md)).

Graceful shutdown is coordinated through a single `asyncio.Event`: kopf's `@kopf.on.cleanup()` handler signals the event, and both the Prefect worker and the status reporter exit cleanly.

## Status Reporter

The status reporter is the mechanism by which the database reflects what is actually running in the cluster — separate from Prefect's flow-state callbacks, which only describe *workflow* progress.

### What it does

Every poll cycle, the reporter:

1. Calls the `listDeploymentsForStatus` GraphQL query against the server to discover all non-internal deployments grouped by environment, plus internal deployments in `deleting` (an ingress controller being torn down after its environment's last app was deleted), so their terminal `Deleted` report reaches the server.
2. For each deployment, in its namespace:
   - Lists pods via `kr8s` and extracts phase, readiness, restart count, container statuses, node, start time, and the `styrmin/component` label (recorded as-is — see [ADR-007](../../adr/0007-pod-status-records-observed-state-not-declared-state.md)). Pods without the component label are reported with `component_name = None` rather than dropped.
   - Fetches the `StyrminDeployment` CRD (`styrmin.io/v1alpha1`) and reads `status.instanceId`, `status.phase`, `status.displayState`, `status.message`, `status.conditions`, and `status.managedResources`. A missing CRD is not an error — that deployment is simply skipped this cycle.
   - Sends `status.instanceId` as the report's `instanceId`: the instance whose spec the operator last handled (see [operator.md](operator.md#status)). A CR that no operator handler has touched since the agent was upgraded has no `status.instanceId`; the reporter then sends `spec.instanceId`. Before, the reporter always sent `spec.instanceId`, so right after a flow wrote a new spec a report could pair the new instance with the previous rollout's `Ready` phase.
3. Posts two independent GraphQL mutations to the server's `/graphql` endpoint:
   - `reportPodStatuses(reports: [DeploymentPodStatusReport!]!)` — server upserts pod rows and deletes stale ones (handled by `services/pod_status.py::report_pod_statuses`).
   - `reportDeploymentStatuses(reports: [DeploymentStatusReportInput!]!)` — server snapshots CRD status, runs the [phase history](#phase-history) for the report, and, when `displayState` maps to a known `DeploymentState`, updates `Deployment.status` (subject to the instance-mismatch guard described in [`../backend/reconciliation.md`](../backend/reconciliation.md) and `services/deployment_status.py`, and to the in-flight restore guard described in [`../backend/backup-restore.md`](../backend/backup-restore.md#display-state-mapping)).

Pod and CRD collection are wrapped in independent `try` blocks: a failure in one does not block reporting of the other.

### Phase history

<!-- Extracted from specs/019-task-steps on 2026-10-06 -->

For each deployment report, after it upserts the `DeploymentStatus` snapshot, `report_deployment_statuses` calls `services/steps/operator_history.py::apply_operator_report`. The phase history turns the report into changes of the task's operator-phase steps ([ADR-060](../../adr/0060-steps-and-derived-task-result.md)):

- **Finding the task.** A report in the `Deleting` or `Deleted` phase goes to the newest `delete_deployment` task of the deployment. Any other report goes to the task whose `instance_id` equals the report's `instanceId`, when that task belongs to the reporting deployment. A report that finds no task, or a task whose operator-phase steps are all `succeeded` or `superseded`, changes nothing and locks no row. A report outside `Deleting` and `Deleted` also changes nothing, and locks no row, once a newer task of the deployment has a succeeded `resource:styrmindeployment` or `resource:delete-request` step: the operator no longer works on that instance, and a late `Ready` must not succeed a failed step that superseding left `failed`. Until that newer write, reports for the instance still move the task's steps.
- **Moving forward.** `CreatingPrerequisites`, `CreatingHelmRelease`, `CreatingServices` and `Ready` succeed the earlier rollout steps and start the step of that phase. A step ends at the transition time of its CR condition (`NetworkPoliciesReady` and `SecretsReady`, `HelmReleaseReady`, `ServicesReady`, `Ready`) when the condition is `True`, else at the report time. `Deleting` starts the teardown step and `Deleted` succeeds it.
- **Failures.** Phase `Failed` or `displayState: Error` fails the first unfinished rollout step with the CR message. For the HelmRelease step and "Wait for the deployment to be ready", the error also lists up to five pods that have not finished and whose containers wait or ended with a reason such as `ImagePullBackOff` or `CrashLoopBackOff`, read from the stored pod statuses.
- **Attempts and FluxCD.** A failed step starts a new attempt when a later report shows the operator working on it again, and succeeds with a new attempt when a later phase is reported. On the HelmRelease step, FluxCD's reason and message are kept as the step's detail, each new FluxCD reason ending in `Failed` adds an error, and `HelmReleaseRemediated` records the rollback time and message. The operator reads FluxCD every 60 seconds, so FluxCD attempts that fail faster than that count as one.

The phase history runs in a savepoint (`session.begin_nested()`) of the report's transaction. When it raises, its own writes roll back, the error is logged, and the snapshot and the `Deployment.status` change still commit.

`reportDeploymentStatuses` is on the unauthenticated allow-list (issue [#396](https://github.com/opsmill/styrmin/issues/396)), so a caller who can reach the API can also move operator-phase steps through it.

### Cadence and lifecycle

- **Cadence**: configurable via `STYRMIN_AGENT_STATUS_POLL_INTERVAL` (seconds, default `5`).
- **Backend address**: `STYRMIN_URL_API` (default `http://localhost:8000`); the reporter posts to `${STYRMIN_URL_API}/graphql`.
- **Connection failures**: backend unreachable → log at `debug` and retry next cycle; never fatal.
- **Shutdown**: `run_status_reporter(shutdown_event, graphql_url, interval)` shares the same `asyncio.Event` as the Prefect worker. When kopf signals shutdown, the reporter exits its loop cleanly.

Entry point wiring lives in `entrypoint/combined.py`, where `asyncio.gather()` runs `kopf.operator(...)`, the Prefect worker, and `run_status_reporter(...)` together. `main()` takes the `Settings` that `styrmin agent start` loaded and passes the reporter its GraphQL URL and interval from them.

### Why polling, not watching

The reporter polls rather than streaming Kubernetes watches because the design favours coalesced, deployment-scoped reports over per-event delivery: one network round-trip per deployment per cycle, with the server doing batch upserts and stale-row pruning. ADR-007 documents the related decision that observed state is *recorded as observed* and not validated against declared state.

## Kubernetes integration

### Primitives (`kubernetes/primitives.py`)

Low-level Kubernetes operations:

```python
def apply_resource(resource: dict) -> None:
    """Apply a K8s resource"""

def delete_resource(name: str, namespace: str, kind: str) -> None:
    """Delete a K8s resource"""
```

### Utils (`kubernetes/utils.py`)

Reference generation helpers:

```python
def generate_namespace_reference(context: GlobalContext) -> str:
    """Generate namespace name from context"""

def generate_release_reference(context: GlobalContext) -> str:
    """Generate HelmRelease name from context"""
```

## Key files

| File | Purpose |
|------|---------|
| [agent/tasks/orchestration.py](backend/styrmin_backend/agent/tasks/orchestration.py) | Internal flow definitions executed on the agent's Prefect worker |
| [agent/tasks/application.py](backend/styrmin_backend/agent/tasks/application.py) | `create_helm_release`, `update_helm_release` |
| [agent/tasks/core.py](backend/styrmin_backend/agent/tasks/core.py) | Core rendering tasks |
| [agent/service/kubernetes/resources/custom_resource.py](backend/styrmin_backend/agent/service/kubernetes/resources/custom_resource.py) | HelmRelease CRD |
| [agent/service/kubernetes/resources/builders/application.py](backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py) | Application HelmRelease builder |
| [agent/status/reporter.py](backend/styrmin_backend/agent/status/reporter.py) | Periodic pod + CRD status reporter (`run_status_reporter`) |
| [agent/status/models.py](backend/styrmin_backend/agent/status/models.py) | Wire-format DTOs for the status reporter |
| [services/pod_status.py](backend/styrmin_backend/services/pod_status.py) | Server-side handler for `reportPodStatuses` (upsert + `delete_stale`) |
| [services/deployment_status.py](backend/styrmin_backend/services/deployment_status.py) | Server-side handler for `reportDeploymentStatuses` (snapshot + `displayState` → `Deployment.status`, then the phase history) |
| [services/steps/operator_history.py](backend/styrmin_backend/services/steps/operator_history.py) | Phase history: turns each status report into operator-phase step changes |
| [agent/steps/reporter.py](backend/styrmin_backend/agent/steps/reporter.py) | Flow step reporter: `recordStep` calls from USER flows and driver actions |
| [agent/service/kubernetes/job_logs.py](backend/styrmin_backend/agent/service/kubernetes/job_logs.py) | Reads the end of a failed Job's output |
| [entrypoint/combined.py](backend/styrmin_backend/entrypoint/combined.py) | Shared event loop: kopf + Prefect worker + status reporter |
