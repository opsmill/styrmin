# Styrmin Agent

The agent is the in-cluster process responsible for everything that happens inside the target Kubernetes cluster. A single container runs three coroutines on a shared async event loop:

- **Kopf operator** — watches `StyrminDeployment` CRDs and drives Kubernetes resources to match. See [operator.md](operator.md).
- **Prefect worker** — a Prefect `ProcessWorker` that polls `user-work-pool` (`styrmin agent start --work-pool user-work-pool`) and runs each USER flow run as a process in the agent pod: the remediation flows `create_instance_crd`, `update_instance_crd` and `upgrade_instance_crd`, `run_job_command`, the other USER flows, and the driver actions. The INTERNAL flows that start them (`apply_state`, `run_job`) run on `styrmin-work-pool`, which the server chart's `task-worker` polls. The flow definitions live under `agent/tasks/` but the catalogue, manager API, and callback wiring belong to the orchestration layer (see [`../backend/orchestration-flows.md`](../backend/orchestration-flows.md)).
- **Status reporter** — periodically observes pod and CRD state and reports it back to the server. See [Status Reporter](#status-reporter).

[ADR-002](../../adr/0002-shared-async-event-loop-kopf-prefect.md) covers the shared event loop. ADR-004, ADR-005, and ADR-006 cover the operator's responsibility split with Prefect.

## Where Prefect lives

Prefect spans both processes. The split is:

- The **server** registers workflow definitions, submits flow runs through `PrefectManager`, and tracks task state in the database.
- The server chart's **task-worker** (`prefect worker start --pool styrmin-work-pool`) picks up the INTERNAL flow runs, such as `apply_state` and `run_job`, and runs each as a process in the task-worker pod.
- The **agent** runs the Prefect `ProcessWorker` that picks up the USER flow runs from `user-work-pool` and runs each as a process in the agent pod. The definitions of the orchestration flows live in `backend/styrmin_backend/agent/tasks/` — physically agent-side code, but conceptually part of the orchestration layer documented in [`../backend/orchestration-flows.md`](../backend/orchestration-flows.md).
- **User actions** (driver-defined hooks) are USER flow runs too: the agent's worker runs each as a process in the agent pod, not as a Kubernetes Job, so an action's `image` has no effect today. See [`../backend/hooks-and-actions.md`](../backend/hooks-and-actions.md#work-pools).

In short: the agent's Prefect worker is what *runs* USER flows and driver actions; everything else about Prefect (catalogue, manager, models, work-pool topology) is documented under `backend/`.

## Directory structure (agent-side code)

```text
backend/styrmin_backend/
├── agent/
│   ├── tasks/                  # Prefect flow definitions (INTERNAL and USER flows)
│   │   ├── core.py             # Rendering tasks
│   │   ├── application.py      # Application-specific (create/update HelmRelease)
│   │   ├── orchestration.py    # apply_state, create_instance, update_instance, upgrade_instance, run_job, run_job_command
│   │   ├── extra.py            # Utility install/update
│   │   ├── service_aliases.py  # "Apply service aliases" flow: write, skip and delete ExternalName aliases
│   │   ├── environment_services.py # Reads an environment's services from the server (alias step, #503)
│   │   ├── list_environment_services.graphql
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
│           ├── service_alias_rules.py # Alias labels and rules shared by the alias flow and the operator; no Prefect import
│           ├── styrmin_deployment.py  # read_styrmin_deployment: the CR, or None on 404
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

### Post-render patches and the Helm hooks they reach

<!-- Extracted from specs/025-helm-v4-defaults on 2026-10-16 -->

`ApplicationHelmReleaseBuilder.build()` writes the patches below into the HelmRelease's `spec.postRenderers`, in this order. helm-controller runs with Helm v4 defaults (`postRenderStrategy: combined`), so Helm runs the post-renderers once on the chart's templates and Helm hooks together, and every patch whose target matches a Helm hook applies to it ([ADR-072](../../adr/0072-helm-v4-defaults-releases-keep-apply-method.md)). "Selector" is a component's identifier label selector, which kustomize matches against the resource's own `metadata.labels`.

| Patch (builder) | Target | Form | Reaches a Helm hook when |
| --- | --- | --- | --- |
| Ingress annotations (`AnnotationPatch`, `IngressUtility`) | `Ingress` | JSON6902 `add` under `/metadata/annotations/` | the hook is an `Ingress` |
| Ingress class: `SpecPatch` on `ingressClassName`, or `IngressClassNameRemovalPatch` with a dedicated ingress controller (`IngressUtility`) | `Ingress` | JSON6902 `add`, or strategic merge `null` | the hook is an `Ingress` and the deployment sets an ingress class or a dedicated ingress controller |
| Styrmin labels (`MetadataLabelsMergePatch`, `build_target_for_label_patches`) | every name (`.*`) | strategic merge | always, including a resource without `metadata.labels` |
| Styrmin pod template labels (`TemplateLabelPatch`) | `Deployment`, `StatefulSet` | JSON6902 `add` under `/spec/template/metadata/labels/` | the hook is a `Deployment` or `StatefulSet` |
| Component label (`MetadataLabelsMergePatch`, `build_target_for_component_labels`) | selector | strategic merge | the hook carries a component's identifier label |
| Component pod template label (`TemplateLabelPatch`) | `Deployment`, `StatefulSet` with the selector | JSON6902 `add` | the hook is a `Deployment` or `StatefulSet` that carries a component's identifier label |
| Replica count (`SpecPatch` on `replicas`, `build_component_replica_patches`) | `Deployment`, `StatefulSet` with the selector | JSON6902 `add` on `/spec/replicas` | the hook is a matching `Deployment` or `StatefulSet`, and an override, a driver default or a stopped component sets the count |
| Backup volumes annotation (`TemplateAnnotationPatch`, `build_backup_annotation_patches`) | `Deployment`, `StatefulSet` with the selector of a component that has a `backup` setting | strategic merge | the hook is a matching `Deployment` or `StatefulSet` |
| Scheduling (`AffinityPatch`, `TolerationsPatch`, `TopologySpreadPatch`, `NodeAffinityPatch`, `RuntimeClassPatch`, `ResourcesPatch`; `build_scheduling_post_rendering_patches`) | `Deployment`, `StatefulSet`, `DaemonSet`, `Job`, `CronJob`, `ReplicaSet`; with the selector of each component that has scheduling settings when the driver declares components | strategic merge; `ResourcesPatch` is a JSON6902 `replace` on `containers/0/resources` | the hook has one of these kinds and, for a driver that declares components, carries the identifier label of a component with scheduling settings |
| Component container overrides (`ContainerMergePatch`) and the guard (`ComponentContainerPatch`; `build_component_container_patches`) | `Deployment`, `StatefulSet` with the selector of a component that has a component container and an override that applies | strategic merge, then JSON6902 guard | the hook is a matching `Deployment` or `StatefulSet`; when it does not render the component container, the guard fails the install or upgrade with `COMPONENT_CONTAINER_NOT_FOUND` |

A Helm hook `Job` or `CronJob` gets the scheduling settings and the labels, but no override and no replica count. When you add a post-render patch, add it to this table.

## Combined process

The kopf operator, the Prefect worker, and the status reporter run in a single async process and share one event loop via `asyncio.gather()` (see [ADR-002](../../adr/0002-shared-async-event-loop-kopf-prefect.md)).

Graceful shutdown is coordinated through a single `asyncio.Event`: kopf's `@kopf.on.cleanup()` handler signals the event, and both the Prefect worker and the status reporter exit cleanly.

## Status Reporter

The status reporter is the mechanism by which the database reflects what is actually running in the cluster — separate from Prefect's flow-state callbacks, which only describe *workflow* progress.

### What it does

Every poll cycle, the reporter:

1. Calls the `listDeploymentsForStatus` GraphQL query against the server to discover every live deployment grouped by environment. The query passes `includeInternal: true`, because `Environment.deployments` leaves internal deployments out by default. The server needs the status of the ingress controller: it rejects new deployments while the controller is `FAILED`, and the terminal `Deleted` report tombstones a controller torn down after its environment's last app was deleted.
2. For each deployment, in its namespace:
   - Lists pods via `kr8s` and extracts phase, readiness, restart count, container statuses, node, start time, and the `styrmin/component` label (recorded as-is — see [ADR-007](../../adr/0007-pod-status-records-observed-state-not-declared-state.md)). Pods without the component label are reported with `component_name = None` rather than dropped. `containerStatuses` holds, in this order, a `pod` entry while the `PodScheduled` condition is `False` (its reason and the scheduler's message), one `init` entry per init container and one `container` entry per container; each entry carries the kubelet's `message` of a waiting container, except for `PostStartHookError`, whose message quotes the hook's output. The pod's restart count follows `kubectl get pods`: init container restarts while the pod is not `Initialized`, then container and sidecar restarts ([ADR-088](../../adr/0088-pod-status-entries-for-init-containers-and-scheduling.md)).
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
- **Failures.** Phase `Failed` or `displayState: Error` fails the first unfinished rollout step with the CR message. For the HelmRelease step and "Wait for the deployment to be ready", the error also lists up to five pods that have not finished, read from the stored pod statuses, with their causes: the scheduler's reason and message for a pod that is not scheduled, each container or init container that waits or ended with a reason other than `ContainerCreating`, `PodInitializing` or `Completed` (with the kubelet's message, except for `CrashLoopBackOff`), each one that is not ready and runs again after restarts, and each init container that is still running without restarts (`still running`). Messages are cut to 300 characters ([ADR-088](../../adr/0088-pod-status-entries-for-init-containers-and-scheduling.md)).
- **Attempts and FluxCD.** A failed step starts a new attempt when a later report shows the operator working on it again, and succeeds with a new attempt when a later phase is reported. On the HelmRelease step, FluxCD's reason and message are kept as the step's detail, each new FluxCD reason ending in `Failed` adds an error, and `HelmReleaseRemediated` records the rollback time and message. The operator reads FluxCD every 60 seconds, so FluxCD attempts that fail faster than that count as one.

The phase history runs in a savepoint (`session.begin_nested()`) of the report's transaction. When it raises, its own writes roll back, the error is logged, and the snapshot and the `Deployment.status` change still commit.

`reportDeploymentStatuses` is on the unauthenticated allow-list (issue [#396](https://github.com/opsmill/styrmin/issues/396)), so a caller who can reach the API can also move operator-phase steps through it.

### Cluster config fan-out after a state change

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

When a report changes `Deployment.status`, `report_deployment_statuses` calls `_run_cluster_config_fanout_hook` in a second savepoint of the report's transaction. A report that does not change the status runs nothing. The hook does one of two things:

- When an internal deployment, such as the dedicated ingress controller, reaches `RUNNING`, it calls `continue_environment_fan_out`, which redeploys the applications that were waiting for that controller.
- When an application reaches `RUNNING`, `FAILED` or `DELETED`, or the controller reaches `FAILED`, it calls `tear_down_unused_ingress_controller`, which requests the deletion of the environment's controller once no application depends on it.

When the hook raises, its own writes roll back, the error is logged as `cluster_config_fanout_hook_error`, and the rest of the report still commits. See [ADR-066](../../adr/0066-cluster-config-fanout.md) §2 and §3, and the cluster config fan-out in [`../backend/services.md`](../backend/services.md).

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

### Readiness polls of the Helm release flows

<!-- Extracted from specs/023-per-component-replicas on 2026-10-16 -->

The agent flows `create_helm_release` and `update_helm_release` (`agent/tasks/application.py`,
registered in `workflows/catalogue.py`) apply the HelmRelease directly instead of through the
operator. After the apply, they run three Prefect tasks from `agent/tasks/shared.py` in order:

1. `poll_helm_release_status`: waits until FluxCD has observed the HelmRelease's current generation
   and its `Ready` condition is `True`. It returns a `Failed` state when the condition is `False`
   or the HelmRelease does not exist.
2. `poll_kubernetes_deployments_status`: for each `Deployment` in the namespace.
3. `poll_kubernetes_stateful_sets_status`: for each `StatefulSet` in the namespace.

Each workload poll raises, so Prefect retries it (`STYRMIN_AGENT_POLL_*`), until all of these hold
against `spec.replicas` (1 when the field is not set):

- `status.observedGeneration` is at least `metadata.generation`;
- `status.replicas` is not above `spec.replicas`, so a scale-down, a stopped component and a
  rolling update complete only after the extra pods are gone;
- the updated and ready counts, and for a `Deployment` the available count, reach `spec.replicas`.

The second check was added after the PR #483 review (item 20). Before it, a scale-down passed as
soon as the remaining pods were ready. The replica count that the polls wait for is the
post-rendered one, so it includes the replica override or driver default
([ADR-070](../../adr/0070-replica-overrides-and-retired-parameters.md) §4).

## Key files

| File | Purpose |
|------|---------|
| [agent/tasks/orchestration.py](../../../backend/styrmin_backend/agent/tasks/orchestration.py) | Orchestration flow definitions: `apply_state` and `run_job` run on the task-worker, the CRD flows and `run_job_command` on the agent's Prefect worker |
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
| [agent/tasks/service_aliases.py](backend/styrmin_backend/agent/tasks/service_aliases.py) | "Apply service aliases" flow; see [Service aliases](../backend/orchestration-flows.md#service-aliases) |
| [agent/tasks/environment_services.py](backend/styrmin_backend/agent/tasks/environment_services.py) | `read_environment_services`: the environment's services from the server, with the flow's action token |
| [agent/service/kubernetes/service_alias_rules.py](backend/styrmin_backend/agent/service/kubernetes/service_alias_rules.py) | `is_alias_of_deployment`, `teardown_deletes_aliases`: the rules that the alias flow and the operator's teardown share |
| [agent/service/kubernetes/styrmin_deployment.py](backend/styrmin_backend/agent/service/kubernetes/styrmin_deployment.py) | `read_styrmin_deployment` |
| [entrypoint/combined.py](backend/styrmin_backend/entrypoint/combined.py) | Shared event loop: kopf + Prefect worker + status reporter |
