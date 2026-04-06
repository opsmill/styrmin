# Research: Kubernetes Operator for Deployment Reconciliation

**Branch**: `001-k8s-operator` | **Date**: 2026-04-05

## R1: Kopf + Prefect Async Coexistence

**Decision**: Use `asyncio.gather(kopf.operator(...), run_prefect_worker())` in a shared event loop.

**Rationale**: kopf's `operator()` is a plain `async def` coroutine (not an async context manager). At startup, it snapshots all existing asyncio tasks via `aiotasks.all_tasks()` and adds them to an `ignored` set. During shutdown, `run_tasks()` only cancels tasks kopf itself created, leaving pre-existing tasks (like the Prefect worker) untouched. This makes shared-loop embedding safe.

**Alternatives considered**:
- **Separate threads (Pattern B)**: kopf's official embedding example uses `threading.Thread` + `asyncio.new_event_loop()` per thread. Rejected because it adds thread-safety complexity and contradicts the spec's requirement for a shared async event loop.
- **kopf.spawn_tasks() / kopf.run_tasks()**: Lower-level API that gives more control over task lifecycle. Viable but unnecessary given `operator()` already handles the task snapshot pattern.

**Key findings**:
- `kopf.operator()` supports `stop_flag` parameter (accepts `asyncio.Event`, `asyncio.Future`, `threading.Event`, or `concurrent.futures.Future`)
- kopf registers SIGTERM/SIGINT handlers in `spawn_tasks()` if running in main thread, overwriting any previously registered handlers
- `@kopf.on.cleanup()` runs during shutdown, providing a reliable bridge to signal Prefect worker termination

## R2: Prefect Worker Async Interface

**Decision**: Run Prefect worker internals (`get_and_submit_flow_runs`, `sync_with_backend`) as anyio task group, racing against a shutdown event.

**Rationale**: Prefect's `BaseWorker.start()` is a blocking async method that uses `anyio.create_task_group()` internally. Rather than calling `start()` directly (which would block until completion), we replicate its internal loop structure and add a cancellation mechanism via a shared `asyncio.Event`.

**Alternatives considered**:
- **Calling `worker.start()` directly**: Blocks the coroutine with no clean cancellation mechanism. Would require wrapping in a task and cancelling it, which is less graceful.
- **Using `run_once=True` in a loop**: Adds polling overhead and loses Prefect's built-in heartbeat/backoff logic.

**Key findings**:
- `BaseWorker` is an async context manager (`__aenter__` calls `setup()`, `__aexit__` calls `teardown()`)
- Internal loops use `prefect.workers.utilities.critical_service_loop` with configurable interval, jitter, and backoff
- `anyio` task groups (used by Prefect) are compatible with asyncio event loops

## R3: Kopf Leader Election (Peering)

**Decision**: Use kopf's built-in peering mechanism with `ClusterKopfPeering` CRD.

**Rationale**: kopf provides a priority-based conflict resolution system where the highest-priority operator instance runs while others pause. This satisfies the "only one active reconciliation instance" requirement without implementing custom leader election.

**Alternatives considered**:
- **Kubernetes Lease-based leader election**: Standard K8s pattern but requires custom implementation. kopf's peering is built-in and well-tested.
- **`standalone=True` (no peering)**: Simplest option but unsafe with multiple replicas.

**Key findings**:
- Requires deploying `ClusterKopfPeering` CRD and creating a peering object
- Operators with lower priority pause when they detect a higher-priority operator
- Peer records expire after configurable `lifetime` seconds (default 60s)
- This is priority-based pause/resume, not true leader election - the highest priority operator wins
- Configure via `@kopf.on.startup()` handler: `settings.peering.name`, `settings.peering.mandatory`, `settings.peering.priority`

## R4: Desired State Resolution via REST API

**Decision**: Operator calls `GET /deployments/{deployment_id}/context` to obtain GlobalContext.

**Rationale**: This endpoint already exists at `/backend/styrmin_backend/api/rest/deployments.py`. It returns a fully-built GlobalContext with all configs merged (cluster → environment → deployment). The existing agent tasks use the same endpoint via `get_context()` in `agent/tasks/shared.py` with httpx.

**Alternatives considered**:
- **Direct database access**: Violates Constitution Principle III (Layered Architecture). The operator would bypass the service layer.
- **Store desired state as annotations/ConfigMap on HelmRelease**: Would require Prefect to serialize the full utility spec during deployment. Adds complexity and data staleness risk.
- **GraphQL query**: More complex than REST for a simple context fetch. The REST endpoint already exists and returns the exact model needed.

**Key findings**:
- Endpoint: `GET /deployments/{deployment_id}/context`
- Returns: `GlobalContext` JSON (includes `utilities: list[UtilityContext]`)
- Agent tasks use `STYRMIN_URL_API` environment variable for base URL
- Context includes all info needed to build utility resources via `UtilityResourceBuilder`

## R5: Existing Label/Annotation Scheme

**Decision**: Extend existing labels with `styrmin.io/operator-managed: "true"` for forward-only adoption.

**Rationale**: The existing `UtilityResourceBuilder` already applies three labels to all utility resources:
1. `app.kubernetes.io/managed-by: styrmin`
2. `styrmin.io/utility-kind: <kind>` (e.g., "ingress", "service-discovery")
3. `styrmin.io/release-reference: <release_reference>`

These are sufficient for the operator to identify and filter managed resources. Adding `styrmin.io/operator-managed: "true"` to the HelmRelease distinguishes new deployments from pre-existing ones.

**Key findings**:
- Labels added in `UtilityResourceBuilder.build()` at `builders/utility.py`
- `release_reference` maps to `get_kubernetes_reference(deployment.id)` - a deterministic function of deployment UUID
- The operator can use `release_reference` to look up the deployment ID for API calls
- NetworkPolicy names follow pattern: `{release_reference}-{netpol_name}` (e.g., `abc123-default-deny-egress`)

## R6: Conflict Avoidance Mechanism

**Decision**: Use an annotation `styrmin.io/deployment-in-progress: "true"` on HelmRelease as a lightweight mutex.

**Rationale**: Prefect flows already modify the HelmRelease during deployment operations. Adding an annotation before modifying utility resources and removing it after completion is a minimal change. The operator checks this annotation before reconciling and skips resources for in-progress deployments.

**Alternatives considered**:
- **Distributed lock (Redis/etcd)**: Over-engineered for this use case. Both components can read K8s annotations.
- **Timestamp-based conflict detection**: More complex to implement correctly and harder to debug.
- **No conflict avoidance (let last-write-win)**: Risky - could cause flapping between operator and Prefect during deployments.

## R7: NetworkPolicy Generation Pipeline

**Decision**: Reuse existing `IngressUtility.build_resources()` and `UtilityResourceBuilder.build()` for generating desired NetworkPolicy specs.

**Rationale**: The ingress utility already generates NetworkPolicies from a Jinja2 template (`ingress-controller-chart-values.j2.yaml`) using GlobalContext. The builder adds ownership labels. Reusing this pipeline ensures the operator produces identical resources to what Prefect would have created.

**Key findings**:
- `IngressUtility.build_resources(context, release_reference, namespace)` generates Secrets, NetworkPolicies, and Middlewares
- 5 NetworkPolicies generated: default-deny-egress, default-deny-ingress, allow-traefik-ingress, traefik-netpolicy-egress, prefect-netpolicy-egress (plus app-specific)
- Resources are raw `dict[str, Any]` Kubernetes manifests
- `UtilityResourceBuilder.build()` adds labels to each resource
- The operator can call `build_resources()` → `builder.build()` to get the desired state, then compare with actual cluster state
