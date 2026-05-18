# Research: Agent Status Reporting

## R1: Periodic Polling Loop Architecture

**Decision**: Add a third async task to `asyncio.gather()` in `combined.py`, alongside the Kopf operator and Prefect worker.

**Rationale**: Pod status collection is a cluster-wide concern (polling all managed namespaces), not a per-CRD concern. A Kopf timer fires per-resource and is designed for reconciliation of individual StyrminDeployment CRDs. A standalone async loop in the entrypoint is the correct pattern for a global polling task that iterates over all managed namespaces. The existing `_shutdown` event and `critical_service_loop` patterns provide graceful shutdown and resilient polling with backoff.

**Alternatives considered**:
- Kopf timer on StyrminDeployment CRD: Wrong scope — fires per CRD, not cluster-wide. Would duplicate work and miss cleanup of stale data across deployments.
- Prefect scheduled flow: Overhead of flow orchestration for a simple polling loop. Prefect flows are designed for deployment workflows, not continuous monitoring.
- Separate sidecar container: Over-engineering for a lightweight polling task. Adds deployment complexity without benefit.

## R2: Namespace Discovery

**Decision**: The agent queries the backend API to get all active (non-internal) deployments, then derives namespaces as `styrmin-{deployment_id}` using the existing `get_kubernetes_reference()` utility.

**Rationale**: Namespaces in Styrmin are derived from deployment IDs (`styrmin-{uuid}`). The backend's deployment list is the canonical source of truth. Additionally, namespaces carry labels like `styrmin/environment_id` which help associate pods back to their deployment context.

**Alternatives considered**:
- Label-based namespace discovery via K8s API: Simpler but introduces coupling to label conventions and could miss unlabeled namespaces.
- Query StyrminDeployment CRDs: Possible but adds coupling to the CRD. The backend API is authoritative for deployment state.

## R3: Status Data Model

**Decision**: Single `PodStatus` model with upsert semantics on `(deployment_id, pod_name)`, linked to `Deployment` via FK.

**Rationale**: The spec requires storing only the latest snapshot per pod. Upsert ensures no historical rows accumulate. Linking to `Deployment` (not `ApplicationInstance`) is natural since the namespace is derived from the deployment ID.

**Alternatives considered**:
- Link to ApplicationInstance: More precise but adds complexity. A deployment's active instance can change, and pods belong to the namespace (deployment), not the instance abstraction.
- JSON blob on Deployment: Simpler storage but loses queryability and makes per-pod filtering impossible.
- Separate time-series table: Out of scope per spec — no historical data.

## R4: Agent-to-Backend Communication

**Decision**: Add a dedicated `reportPodStatuses` mutation to the GraphQL API, following the existing `callback()` mutation pattern. The mutation accepts a batch of pod statuses per deployment to minimize HTTP round-trips.

**Rationale**: The existing `callback()` mutation handles task state updates. A new dedicated mutation keeps concerns separate (task lifecycle vs. workload health) and avoids overloading the callback with unrelated data.

**Alternatives considered**:
- Extend `callback()` mutation: Conflates task lifecycle with workload monitoring. Different cadences and concerns.
- REST endpoint: Would work but breaks the pattern of using GraphQL for all API operations.
- gRPC streaming: Over-engineering for a 60-second polling interval.

## R5: Configuration

**Decision**: Add `STYRMIN_AGENT_STATUS_POLL_INTERVAL` as a module-level constant with `os.environ.get()`, following the operator config pattern (`RECONCILIATION_INTERVAL_SECONDS` in `operator/config.py`).

**Rationale**: The existing operator config uses simple module-level `os.environ.get()` with defaults. This is the simplest approach for a single config value. The Pydantic `BaseSettings` approach is used for more complex config groups, which is unnecessary here.

**Alternatives considered**:
- Pydantic BaseSettings class: More structured but overkill for a single integer value.

## R6: Stale Data Cleanup

**Decision**: Two-pronged cleanup: (1) each poll cycle deletes PodStatus records for pods that no longer exist in the cluster, and (2) cascade-delete PodStatus records when a Deployment is deleted from the database.

**Rationale**: Pod-level cleanup handles the common case of pods being replaced (rolling updates, scaling). Deployment-level cascade handles the structural case of entire deployments being removed.

**Alternatives considered**:
- TTL-based expiry: Adds complexity and doesn't handle the deployment deletion case cleanly.
- Cleanup only on deployment deletion: Would leave stale pod records between poll cycles.
