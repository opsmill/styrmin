# Research: CRD Status Reporting

## R1: CRD Access Pattern from the Agent

**Decision**: Use the existing `get_custom_resource()` primitive to read each StyrminDeployment CRD by name and namespace. List CRDs per namespace if the exact name is unknown.

**Rationale**: `get_custom_resource()` in `primitives.py` already handles reading namespaced custom resources with proper error handling (`CustomResourceNotFound` on 404). The CRD group/version/plural are defined as constants in `operator/config.py` (`styrmin.io`, `v1alpha1`, `styrmindeployments`). Reusing this avoids duplicating K8s API logic.

**Key detail**: The CRD name equals the `release_reference` (set in `crd/builder.py`), which is the same as the namespace: `styrmin-{deployment_id}`. The agent can derive both the namespace and CRD name from the deployment ID using `get_kubernetes_reference()`.

**Alternatives considered**:
- List all CRDs cluster-wide: Requires cluster-level RBAC and doesn't scope to managed namespaces.
- Use kopf watch from the reporter: Over-engineering; the reporter is a simple polling loop, not an operator.

## R2: CRD Status Extraction

**Decision**: Read `crd["status"]` dict from the custom resource response. Extract `phase` (string), `conditions` (list of dicts), and `managedResources` (dict of counts). Handle missing `status` field by defaulting to phase `Pending` with empty conditions.

**Rationale**: The CRD status is a standard K8s status subresource. The structure is defined in `operator/crd/status.py` and is stable. New CRDs may not have a status field yet (before the operator processes them), so the default is necessary.

## R3: Deployment Status Update from CRD Phase

**Decision**: Add a new service function `update_deployment_from_crd_phase()` that maps CRD phase to `DeploymentStatus` and persists via the existing UnitOfWork. The mapping follows FR-004: `Pending`/`Creating*` → `pending`, `Ready` → `running`, `Failed` → `failed`, `Deleting` → no change.

**Rationale**: This is additive to the existing task callback mechanism. Both can update Deployment status; the most recent write wins. This is acceptable because the CRD phase is the ground truth for cluster state — if the CRD says "Ready" but the task callback said "Failed" earlier, the CRD is correct (the operator recovered).

**Alternatives considered**:
- Replace task callback entirely: Too risky — the callback also updates Task and ApplicationInstance status.
- Add a priority/precedence system: Over-engineering for a polling-based system. Last-write-wins is simple and correct here.

## R4: Reporting Mechanism

**Decision**: Extend the existing `reportPodStatuses` mutation to also accept CRD status data per deployment, or add a companion `reportCrdStatuses` mutation. The latter is cleaner — separate concerns, separate payloads.

**Rationale**: A dedicated mutation keeps the pod status and CRD status reporting orthogonal. The agent can fail to collect one without affecting the other. The mutation can also handle the Deployment status update in the same transaction.

**Alternatives considered**:
- Bundle into `reportPodStatuses`: Conflates two different data types. Makes it harder to evolve independently.
- Direct DB access from agent: Breaks the layered architecture (agent must go through GraphQL API).

## R5: Data Storage

**Decision**: New `DeploymentCrdStatus` model with a one-to-one relationship to Deployment. Stores phase (string), conditions (JSON list), managed_resource_counts (JSON dict), message (string), and `last_polled_at`. Upsert semantics on `deployment_id` (unique).

**Rationale**: Mirrors the PodStatus pattern from the previous feature but is simpler — one record per deployment instead of one per pod. JSON for conditions and resource counts avoids schema complexity for nested structures that are read-only snapshots.

**Alternatives considered**:
- Store on Deployment model directly: Pollutes the Deployment model with K8s-specific fields.
- Separate conditions table: Over-normalized for read-only snapshot data.
