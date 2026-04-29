# Phase 0 Research: Match Pod Statuses to Driver Components

## 1. Where to read the `styrmin/component` label

**Decision**: Read the label inside `_extract_pod_data(pod)` in `backend/styrmin_backend/agent/status/reporter.py`, from `pod.metadata.labels`.

**Rationale**:

- The `V1Pod` object is already in scope at that call site — `_collect_pod_statuses()` runs `list_pods(namespace=namespace)` and feeds each item to `_extract_pod_data()`. The label is metadata that arrives free of charge with the list call.
- Adding a separate "lookup component for this pod" round-trip (e.g., re-querying the workload that owns the pod, or fetching the deployment's component list from the backend) would be slower, more failure-prone, and would re-implement information that the platform already encodes in the label itself.
- `get_component_labels()` in `kubernetes/primitives.py:394` is a different helper — it pulls labels from a workload's pod template by selector. It's not appropriate here: we already have an actual pod object, and we want labels that ended up on the running pod, not what the template says.

**Alternatives considered**:

- *Server-side join*: agent reports pod name only; server resolves component by listing the deployment's components and finding one whose selector matches. Rejected — requires the server to know about Kubernetes label semantics, requires storing per-deployment selectors on the server, and creates a join that breaks any time a driver edits selectors or rolls a workload.
- *Backend-issued lookup table*: agent fetches a deployment-id → component-name → selector map on each cycle. Rejected — adds a query per cycle, is duplicative of what the label already encodes, and gets stale during rollouts.

## 2. Server-side validation of `component_name`

**Decision**: The server stores the reported value as-is. It does **not** check that `component_name` matches a declared `Component` for the deployment.

**Rationale**:

- **Drift is a feature, not a bug.** Drivers and components evolve independently of observed runtime state. During a rollout, the new component name and the old one can both legally be present on running pods. After a rename, old pods carry the old name. Rejecting either would manufacture an outage.
- **The server records observation, not intent.** The point of pod-status reporting is "what we saw in the cluster." Coercing observed values to match declared intent collapses two distinct things (observed vs declared) into one and erases the diagnostic value of the report.
- **Cost of validation**: every `report_pod_statuses` would need to hit the deployments/components tables to validate, adding contention and latency to a hot path that runs every ~5 s.
- **Cost of coercion** (e.g. mapping unknown values to `None`): silently destroys information operators need.

**Alternatives considered**:

- *Strict validation*: reject reports whose component does not match a declared component. Rejected — turns expected drift into an error. The agent has no recovery path other than dropping the row, which violates the "don't silently drop pods" requirement.
- *Lenient coercion*: store `None` when the value doesn't match. Rejected — loses the actual observed label, which is exactly the data an operator needs when diagnosing a misconfigured workload.
- *Foreign key to `Component.id`*: rejected — components are scoped per-deployment and can be deleted/renamed; foreign-keying observed runtime state to mutable declared state is a recipe for cascade-delete bugs and migration pain.

## 3. Treatment of empty/whitespace label values

**Decision**: Empty string and whitespace-only values are normalized to `None` at the agent boundary, before the wire model is built.

**Rationale**:

- The k8s label-validation rules technically allow only specific characters, so a whitespace-only label "shouldn't happen". But `None` and `""` carry the same semantic ("unknown component") and downstream consumers shouldn't have to guard against both.
- The agent is the natural place to do this normalization — it owns the bridge between Kubernetes data and platform data. Doing it in the reporter keeps the server simple (one absent representation, not three).

**Alternatives considered**:

- *Pass through verbatim*: reject — forces every consumer to write the same `if not value or not value.strip()` guard.
- *Normalize on the server*: rejected — duplicates work and means the database can grow values like `""` from older agent releases.

## 4. Migration strategy

**Decision**: Single Alembic revision adding `component_name VARCHAR NULL` to the `podstatus` table. No backfill — existing rows get `NULL` and the next reporting cycle (every ~5 s) populates them.

**Rationale**:

- Pod statuses are ephemeral — they're rewritten every poll cycle and stale rows are deleted. There is no value in backfilling rows that will be rewritten within seconds.
- A nullable column with no default is the simplest possible migration; downgrade just drops the column.

**Alternatives considered**:

- *Backfill from declared components*: rejected — would require resolving each pod to a component at migration time, which the server has no clean way to do (and would replicate the validation logic we're explicitly avoiding, see §2).

## 5. SDK query updates

**Decision**: Add `componentName` to the two read queries (`get_pod_statuses.graphql`, `get_deployment_pod_statuses.graphql`). Do not change `report_pod_statuses.graphql` — the mutation's response shape doesn't include pod fields. The mutation's *input* (the `PodStatusInput` shape) is regenerated automatically from the schema.

**Rationale**:

- The agent's wire model (`PodStatusData`) writes `componentName` via Pydantic alias. The mutation accepts it through the `PodStatusInput` schema definition, regenerated by `uv run invoke generate`. No `.graphql` mutation file edits needed.
- Read queries explicitly select fields, so they need the new field added or downstream consumers won't see it.
