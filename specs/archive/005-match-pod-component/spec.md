# Feature Specification: Match Pod Statuses to Driver Components

**Feature Branch**: `005-match-pod-component`
**Created**: 2026-04-29
**Status**: Extracted
**Input**: GitHub issue [#133](https://github.com/opsmill/styrmin/issues/133) — "feat: Match pod statuses to driver components"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator sees which component owns each pod (Priority: P1)

When viewing the runtime status of a deployment, an operator needs to know which declared driver component each running pod belongs to. Today the platform reports a flat list of pods per deployment, with no link back to the component that defined them. For multi-component drivers — for example, a driver that declares an `api` component and a `worker` component — the operator cannot tell which pods are part of which component, cannot compute per-component health (e.g. "api: 3/3 ready, worker: 1/2 ready"), and cannot attribute a `CrashLoopBackOff` to the component that owns it.

**Why this priority**: This is a prerequisite for any per-component status UI and for downstream features such as component-level health rollups, component-scoped alerting, and component-aware troubleshooting. Without it, the platform's component model is invisible at runtime and operators must manually match pod names to driver intent.

**Independent Test**: Deploy a driver that declares two components, then query the deployment's pod statuses. Each pod's reported `component_name` matches the component whose workload definition produced it. The deployment can be deployed, the pods listed, and the attribution verified end-to-end without any other UI work — the value is delivered as soon as the data is exposed on the API.

**Acceptance Scenarios**:

1. **Given** a driver with components `api` and `worker` is deployed, **When** the agent reports pod statuses for the deployment, **Then** every pod created from the `api` component carries `component_name = "api"` and every pod from the `worker` component carries `component_name = "worker"` in the reported data and on the server-side record.
2. **Given** a deployment whose pods are reported with component names, **When** an API consumer queries pod statuses for that deployment, **Then** each pod's `component_name` is exposed alongside its existing fields (phase, ready, restart count, etc.).

---

### User Story 2 - Pods without a component label are still reported (Priority: P1)

Not every pod observed in a deployment's namespace was created by a declared component. System pods, sidecars from non-driver tooling, in-flight rollouts where labels haven't propagated yet, and pods deployed outside the component model can all appear. The platform must record these pods truthfully — neither dropping them silently nor fabricating a component to attach them to.

**Why this priority**: Silent drops would hide pods that operators need to see (a misbehaving sidecar is still a problem). Fabricating a fake component would corrupt the component model and mislead anything downstream that aggregates by component. The "unknown" case has to be representable.

**Independent Test**: Add a pod to a deployment's namespace that does not carry the `styrmin/component` label. The agent reports the pod and the server stores it; the pod is queryable on the API with `component_name = null` (or its language-equivalent absent value). No error is raised, no record is dropped.

**Acceptance Scenarios**:

1. **Given** a pod in a deployment's namespace has no `styrmin/component` label, **When** the agent reports pod statuses, **Then** the pod is reported with an explicitly absent component reference and the server persists the row with `component_name` set to its null/absent value.
2. **Given** a pod in a deployment's namespace has the `styrmin/component` label set to a blank/empty string, **When** the agent reports pod statuses, **Then** the pod is reported with an explicitly absent component reference (treated identically to missing label).
3. **Given** a pod carries `styrmin/component=ghost` where no component named `ghost` is declared on the deployment's driver, **When** the agent reports pod statuses, **Then** the pod is stored with `component_name = "ghost"` as observed — the server does not reject the record and does not coerce the value.

---

### Edge Cases

- A driver component is renamed between deployments; old pods (still rolling out) carry the old label while new pods carry the new label. Both must be reported with whatever label they carry.
- The `styrmin/component` label key is present but its value contains whitespace only (e.g. `"   "`). Treated as absent.
- A pod is reported multiple times across reporting cycles; the `component_name` recorded must reflect the most recent observation, not be appended to.
- A driver has zero declared components (legal but unusual). All observed pods will have `component_name = null` because no labelling has occurred — this is correctly representable.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When the agent collects pod data for a deployment, it MUST read the `styrmin/component` label from each pod's metadata and include the label's value as the pod's component reference in the reported status.
- **FR-002**: A pod whose `styrmin/component` label is missing, empty, or whitespace-only MUST be reported with an explicitly absent component reference (representable as null/None at every layer the value crosses).
- **FR-003**: The server MUST persist the reported component reference on each pod-status record, and MUST allow the value to be absent (nullable column).
- **FR-004**: The server MUST NOT reject a pod-status record because its component reference does not match a declared component on the deployment's driver. The reported value is stored as-is — drivers and components evolve independently and the server records observed state without gatekeeping it.
- **FR-005**: The component reference MUST be exposed on the public API representation of a pod status, alongside the existing pod-status fields.
- **FR-006**: When a previously reported pod is re-reported with a different component label (or with the label removed), the persisted component reference MUST be updated to reflect the latest observation.
- **FR-007**: The feature MUST be covered by automated tests at two levels: (a) unit tests for the agent's pod-data extraction covering pod-with-label, pod-without-label, and pod-with-unknown-label cases; (b) at least one end-to-end test deploying a driver with two or more components and asserting that each reported pod's component reference matches the component that owns it, and that a pod without the label is reported with an absent component reference.

### Key Entities *(include if feature involves data)*

- **Pod Status**: A periodically refreshed record of a single Kubernetes pod observed inside a deployment. Carries identifying fields (pod name, namespace), runtime fields (phase, ready, restart count, …), and — added by this feature — a reference to the declared driver component the pod belongs to. The reference may be absent.
- **Component**: An entity declared by a driver describing one piece of an application's deployment intent (e.g. `api`, `worker`). Pods produced from a component carry the `styrmin/component=<component-name>` label. Components are referenced by name from pod-status records, but the platform does not enforce referential integrity between observed pod labels and the deployment's currently declared component set.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For any deployment of a driver with multiple components, 100% of pods produced from a declared component are reported with a component reference matching that component's name.
- **SC-002**: For any pod observed in a deployment's namespace that does not carry the `styrmin/component` label, the corresponding pod-status record is persisted with an explicitly absent component reference; zero such pods are dropped or fail validation.
- **SC-003**: For any pod observed with a `styrmin/component` label whose value does not match a currently-declared component on the deployment's driver, the corresponding pod-status record is persisted with the observed value; zero such records are rejected.
- **SC-004**: An API consumer fetching pod statuses for a deployment receives a component reference alongside every pod's existing fields, with no additional queries required.
- **SC-005**: The component reference for a previously reported pod reflects the latest observation within one reporting cycle of any change to its label.

## Assumptions

- The agent already labels Kubernetes workloads it creates with `styrmin/component=<component-name>`; this feature consumes that label and does not change how it is set.
- Drivers and components evolve independently of observed runtime state. Drift between declared components and observed pod labels is expected and must be representable, not an error.
- The platform's existing pod-status reporting cycle is the right vehicle for delivering the component reference; no separate reporting path or new schedule is introduced.
- A nullable column on the existing pod-status table is acceptable; this requires a database migration but no rewrite of existing data — existing rows will be backfilled with absent component references and updated on the next reporting cycle.
- The frontend consumer of this data is out of scope for this spec; this feature exposes the data on the API and per-component UI is a separate piece of work.
