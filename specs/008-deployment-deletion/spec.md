# Feature Specification: Deployment Deletion

**Feature Branch**: `008-deployment-deletion`
**Created**: 2026-05-01
**Status**: Draft
**Input**: PRD comment on issue #94 (https://github.com/opsmill/styrmin/issues/94#issuecomment-4360661060)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Delete a running deployment end-to-end (Priority: P1)

An operator decides to retire a deployment that is currently running on a managed cluster. They open the deployment, trigger a delete action (either through the UI or through the platform's API client), and the platform tears down every resource it created on the cluster — services, the application release, network policies, secrets, and finally the namespace — without any manual `kubectl` work. The deployment record itself remains in the platform's history so the audit trail and any associated backups stay queryable.

**Why this priority**: This is the core capability the feature exists to deliver. Without it, operators continue to retire deployments manually, leaving orphaned platform records and risking incomplete cleanup. Every other story in this spec is either a refinement of this flow or a guard against its misuse.

**Independent Test**: Deploy a sample application through the platform, wait for it to reach a running state, trigger the delete action, then verify (a) the namespace `styrmin-{id}` no longer exists on the cluster, (b) the deployment's status has progressed through "deleting" to "deleted", and (c) the deployment record is still resolvable by id with a recorded deletion timestamp.

**Acceptance Scenarios**:

1. **Given** a deployment in the running state, **When** the operator triggers delete, **Then** the deployment status transitions to "deleting" within seconds, the cluster namespace is removed within the cluster's normal teardown window, and the status finally settles on "deleted" only after the namespace is fully gone.
2. **Given** a deployment in a stuck/failed state, **When** the operator triggers delete, **Then** teardown still proceeds and any owned resources are removed; the operator is not blocked from cleanup by the deployment having never reached running.
3. **Given** a deleted deployment, **When** the operator queries it by id, **Then** the platform returns the tombstoned record (deletion timestamp populated) and any associated backups still resolve.
4. **Given** a deployment is being deleted, **When** the platform records the action in the deployment's timeline, **Then** the timeline entry identifies who triggered the deletion and when.

---

### User Story 2 - Confirm before destroying (Priority: P1)

Before the platform actually deletes anything, the operator is forced through a confirmation step that cannot be passed by a careless click. The confirmation requires the operator to type the exact deployment name; only then does the destructive action become available.

**Why this priority**: Deletion is irreversible at the cluster level (workload is gone), and the platform cannot rely on a generic "Are you sure?" prompt for production-grade safety. Bundling this with US1 keeps the safety guardrail inseparable from the destructive action — shipping the action without the guard is not acceptable.

**Independent Test**: Open the delete dialog for a deployment, attempt to confirm with an empty input, with a wrong name, with a name that differs only in case, and finally with the exact deployment name. The confirm control is enabled only in the last case.

**Acceptance Scenarios**:

1. **Given** the delete dialog is open, **When** the operator has typed nothing, the wrong name, or the right name with a case mismatch, **Then** the destructive confirm button remains disabled.
2. **Given** the delete dialog is open, **When** the operator types the deployment name exactly (case-sensitive), **Then** the destructive confirm button becomes enabled.
3. **Given** the dialog body, **When** the operator reads it, **Then** they see a clear summary that workload and namespace will be torn down, that backups are retained, and that the deployment will appear in a deleted view for the forensic retention window.
4. **Given** the operator confirms, **When** the action completes, **Then** the dialog closes and the operator is taken back to the deployment list, where the row remains visible with a "Deleting..." badge until the platform reports the deployment as fully deleted.

---

### User Story 3 - See deletion progress and find deleted deployments later (Priority: P2)

While a deployment is being torn down, the operator should see live progress on the list view, not a stale snapshot. Once a deployment is fully deleted, it should disappear from the default day-to-day view but remain findable through an explicit "Show deleted" toggle, so retired records do not clutter the working list but can still be audited.

**Why this priority**: Without progress visibility, long-running namespace teardown looks like a hung UI; without filtering, retired deployments accumulate in the default list and degrade the day-to-day experience.

**Independent Test**: Trigger a deletion and observe the row in the deployment list throughout teardown — it must show a "Deleting..." indicator until the deployment reaches the deleted state, then disappear from the default list. Toggle "Show deleted" and verify the same row reappears, visually de-emphasised, with a relative-time deletion timestamp.

**Acceptance Scenarios**:

1. **Given** a deployment is mid-teardown, **When** the operator views the list with default filters, **Then** the row remains visible with a "Deleting..." indicator.
2. **Given** a deployment is fully deleted, **When** the operator views the list with default filters, **Then** the row is hidden.
3. **Given** the "Show deleted" toggle is on, **When** the operator views the list, **Then** deleted rows appear visually de-emphasised with a relative deletion timestamp and no inline action menu.

---

### User Story 4 - Inspect a deleted deployment forever (Priority: P2)

After a deployment is deleted, its detail page must still be reachable by direct link or id so the operator can review what happened, when, and to which resources, and so any associated backups remain visible for restore-recovery flows. The detail page is read-only and signals this state unambiguously.

**Why this priority**: The audit trail and backup chain are the only artefacts that survive deletion. They are useless if the operator cannot navigate to them. Making the deleted-state detail page a first-class read-only experience also prevents the operator from accidentally invoking lifecycle actions on a retired deployment.

**Independent Test**: Open a deleted deployment by direct id (URL or API), confirm the page renders with a clear "Deleted at ..." indicator, confirm every lifecycle action button is disabled and explains why, confirm the timeline still shows the full lifecycle including the delete event, and confirm associated backups still appear.

**Acceptance Scenarios**:

1. **Given** a deleted deployment id, **When** the operator opens the detail page, **Then** the page loads, shows a banner indicating deletion and when it occurred, and presents the full historical timeline.
2. **Given** the detail page of a deleted deployment, **When** the operator looks at the action area, **Then** every lifecycle action (delete, upgrade, redeploy, etc.) is disabled with a tooltip explaining the deployment is retired.
3. **Given** a deleted deployment with previously-created backups, **When** the operator views its detail page, **Then** the backup list is still rendered.

---

### User Story 5 - Automate deletion safely from a script (Priority: P3)

An operator running automation (CI scripts, test harnesses, scheduled cleanups) needs to delete deployments programmatically. The automation must (a) return immediately rather than blocking on long namespace finalizers, (b) be safe to retry on transient errors without surfacing spurious failures, and (c) treat already-gone deployments as a no-op rather than an error.

**Why this priority**: Test harnesses and short-lived experiments are the primary driver for adopting deletion in the first place; if scripts hang for minutes per cleanup or fail noisily on retries, operators will keep working around the platform. This story can ship after US1 since most of its semantics are state-guard refinements on top of the same delete action.

**Independent Test**: From a script: trigger delete on a running deployment and confirm the call returns within a small bounded time. Trigger delete a second time on the same in-flight deletion and confirm the call succeeds idempotently. Trigger delete on an already-deleted id and confirm the script gets a clean "not found" outcome it can treat as success. Poll the deployment status until it settles on the deleted terminal state.

**Acceptance Scenarios**:

1. **Given** a running deployment, **When** the script issues a delete call, **Then** the call returns promptly without waiting for cluster teardown to complete, and the deployment status is observable as "deleting".
2. **Given** a deployment already being deleted, **When** the script issues a second delete call, **Then** the call succeeds and references the existing in-flight deletion (no duplicate side effects).
3. **Given** a deployment that has already reached the deleted terminal state, **When** the script issues a delete call, **Then** the script receives a clear "not found" outcome rather than a server error.
4. **Given** a deployment in the middle of a restore operation, **When** the script issues a delete call, **Then** the call is rejected with a clear reason (data-integrity guard) rather than allowed through.

---

### User Story 6 - Forensic retention of cluster-side state (Priority: P3)

After a deployment is reported as deleted to the platform, its cluster-side record should linger long enough that an operator can inspect what happened on the cluster (final conditions, last events) before automatic cleanup removes it. Platform engineers need this retention window to be configurable per environment so dev and prod clusters can use different forensic horizons.

**Why this priority**: This is a quality-of-life improvement for incident response, not a blocker for shipping deletion. Default retention applied uniformly is the MVP; environment-specific tuning is a follow-on enabler.

**Independent Test**: Delete a deployment, confirm the cluster-side record persists immediately after the deployment is reported deleted, fast-forward the retention clock (or run with a small configured value), and confirm the cluster-side record is automatically garbage-collected. Repeat with a different configured retention value and confirm the window changes accordingly.

**Acceptance Scenarios**:

1. **Given** a deployment that has just been reported as deleted, **When** an operator inspects the cluster directly, **Then** the cluster-side record is still present and shows the final state.
2. **Given** retention is configured to N hours, **When** more than N hours have elapsed since a deployment reached the deleted state, **Then** the cluster-side record is removed automatically.
3. **Given** a cluster-side record stuck in "deleting" (teardown failed), **When** the retention timer would otherwise apply, **Then** the record is **not** garbage-collected — only fully-deleted records are reaped, so failed teardowns remain visible for human intervention.

---

### Edge Cases

- **Deletion during a restore**: The platform must refuse deletion while a restore is in progress, with a clear reason. Allowing the delete would corrupt backup-storage state mid-recovery.
- **Stuck deployment (failed or never-finished deploy)**: Deletion must still succeed and tear down whatever resources were created. The operator must not be blocked from cleanup just because the deploy itself never reached running.
- **Repeated delete calls**: Two delete calls on the same deployment, including from concurrent clients, must converge to a single deletion (idempotent). The second call references the first; it does not duplicate work or surface as an error.
- **Delete on already-deleted record**: Clearly distinguishable from "we have no idea what id that is" — automation needs a stable signal it can treat as success.
- **Manual cluster-side deletion**: An operator running `kubectl delete` on the cluster-side record (bypassing the platform) must still result in cluster resources being torn down through the existing safety-net handler. This out-of-band path does **not** create a platform-side tombstone; reconciling such cases is explicitly out of scope.
- **Long-running namespace finalisers**: Teardown can take minutes if Kubernetes finalisers run slowly. The deployment status must not flip to "deleted" until the namespace is actually gone, even if every other resource has been removed.
- **Race between the action and visibility**: An operator who has just confirmed deletion must see the row reflect "deleting" without needing to refresh the list manually.
- **Reverting deletion**: Once a deletion has been requested, it cannot be cancelled or reversed. The cluster-side trigger is monotonic.
- **Deleted deployment URL navigation**: Direct links to a deleted deployment must always resolve to its read-only detail page, not 404. This is the primary forensic interface.

## Requirements *(mandatory)*

### Functional Requirements

#### Deletion lifecycle

- **FR-001**: Operators MUST be able to trigger deletion of any deployment that is in a non-restoring lifecycle state (including pending, deploying, running, and failed states).
- **FR-002**: When deletion is triggered, the platform MUST tear down every resource it provisioned for that deployment, in dependency-safe order, ending with the deployment's namespace.
- **FR-003**: The platform MUST NOT mark a deployment as deleted until cluster-side teardown is fully complete (in particular, the namespace must be gone).
- **FR-004**: When teardown is in progress but not yet complete, the deployment's status MUST be observable as "deleting".
- **FR-005**: When teardown has completed, the deployment's status MUST be observable as "deleted" and a deletion timestamp MUST be recorded against the deployment.
- **FR-006**: When teardown fails, the deployment MUST remain in the "deleting" state with a human-readable reason surfaced; the platform MUST NOT introduce a separate "deletion failed" terminal state.
- **FR-007**: A request to delete a deployment that is currently restoring MUST be rejected with a clear reason citing data-integrity protection.
- **FR-008**: A delete request issued against a deployment that is already being deleted MUST succeed idempotently, referencing the in-flight deletion record without producing a new one or duplicating side effects.
- **FR-009**: A delete request issued against a deployment that is already deleted MUST surface a clear "not found" outcome distinct from a generic error.
- **FR-010**: Once deletion has been requested for a deployment, it MUST NOT be cancellable or reversible.

#### Audit and forensics

- **FR-011**: Every successful deletion request MUST produce an entry on the deployment's timeline that captures who triggered it and when.
- **FR-012**: Deletion of a deployment MUST NOT remove its historical record, its timeline entries, or any backups associated with it.
- **FR-013**: The platform MUST retain the cluster-side record of a deleted deployment for a configurable retention window so operators can inspect cluster-side state after the fact.
- **FR-014**: After the retention window has elapsed for a deployment that reached the "deleted" state, the platform MUST automatically remove the cluster-side record.
- **FR-015**: The platform MUST NOT automatically remove cluster-side records that are stuck in "deleting"; these MUST remain visible until human action resolves them.
- **FR-016**: The retention window duration MUST be configurable per environment (cluster) without code changes.

#### Safety and protection

- **FR-017**: A manual cluster-side deletion bypassing the platform MUST still result in the platform's existing teardown handler running so cluster resources are removed; reconciling such out-of-band deletions back into a platform-side tombstone is out of scope (FR-011 audit guarantees do not apply to this path).
- **FR-018**: The cluster-side trigger that requests deletion MUST be monotonic: once set, it cannot be unset.

#### API and SDK

- **FR-019**: The platform MUST expose a delete operation over its API that returns immediately and does not block on cluster teardown.
- **FR-020**: The platform MUST expose a high-level delete operation in its client library so automation can call it idiomatically.
- **FR-021**: The platform MUST allow API consumers to filter the deployment list by whether deleted records are included.
- **FR-022**: The platform MUST allow direct lookup of a deployment by id regardless of whether it has been deleted.
- **FR-023**: The platform MUST expose the deletion timestamp of a deleted deployment as a queryable field.

#### UI

- **FR-024**: The deployment detail page MUST present a "Delete" action alongside other lifecycle actions (such as upgrade and redeploy) when the deployment is in a deletable state.
- **FR-025**: The "Delete" action MUST require an explicit confirmation in which the operator types the deployment name exactly (case-sensitive) before the destructive control becomes enabled.
- **FR-026**: The confirmation dialog MUST clearly describe what is about to happen: workload and namespace teardown, retention of backups, and forensic visibility under a "Show deleted" view.
- **FR-027**: After the operator confirms deletion, the UI MUST navigate them back to the deployment list.
- **FR-028**: While a deployment is mid-teardown, its row in the deployment list MUST remain visible with a "Deleting..." indicator.
- **FR-029**: After a deployment reaches the "deleted" state, its row MUST be hidden from the default list view.
- **FR-030**: The deployment list view MUST offer a "Show deleted" toggle that reveals deleted rows.
- **FR-031**: Deleted rows in the list MUST render visually de-emphasised, must show a relative-time deletion indicator, and MUST NOT offer inline action affordances.
- **FR-032**: The detail page of a deleted deployment MUST be reachable by direct id forever and MUST display a clear banner indicating deletion and when it occurred.
- **FR-033**: On the detail page of a deployment in the "deleting" or "deleted" state, every lifecycle action button MUST be disabled with an explanatory tooltip.

### Key Entities

- **Deployment**: An operator-managed application instance on a managed cluster. Gains a deletion timestamp when retired; this timestamp distinguishes "live" from "tombstoned" records and is the basis for default-list filtering.
- **Deployment lifecycle state**: The deployment's coarse status. Adds two new values for this feature — "deleting" (cluster teardown in progress) and "deleted" (terminal, set only once the namespace is gone). "Deleted" is irreversible.
- **Deployment record (cluster-side)**: The operator-side custom resource that mirrors the deployment on the cluster. Gains an immutable "deletion requested" flag that, once set, drives teardown and cannot be reset. Lingers in a "deleted" phase for the configured forensic window before being garbage-collected.
- **Timeline event**: A log of deployment lifecycle activity. Gains a new event type representing deletion requests, capturing actor and timestamp.
- **Backup**: A snapshot associated with a deployment. Survives the deployment's deletion so recovery into a new deployment remains possible.
- **Cluster retention configuration**: The forensic window in hours for cluster-side records of deleted deployments. Per-cluster (per environment), with a sensible default; not per-deployment.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can fully retire a deployment (workload gone from the cluster, record tombstoned, audit preserved) without running any `kubectl` or other out-of-platform commands.
- **SC-002**: Triggering deletion is acknowledged within 2 seconds; the deployment becomes observable in the "deleting" state immediately on the next list refresh.
- **SC-003**: For a deployment whose namespace teardown completes within the cluster's normal finaliser timeline, the deployment reaches the "deleted" state within that same window — the platform itself adds no significant latency on top of the cluster.
- **SC-004**: An operator cannot complete a destructive deletion through the UI without typing the deployment's exact name; the confirm control remains disabled until the input matches exactly.
- **SC-005**: After a deployment is deleted, its detail page remains reachable by direct id with 100% success and shows a clear banner identifying it as deleted along with the deletion timestamp.
- **SC-006**: After a deployment is deleted, its associated backups remain queryable against its (tombstoned) record with no data loss.
- **SC-007**: Repeated delete calls (from concurrent clients or retries) on the same deployment produce exactly one deletion outcome — duplicates do not surface as errors and do not create duplicate audit entries.
- **SC-008**: A delete call against an already-deleted deployment returns a "not found" outcome that is programmatically distinguishable from "id does not exist" and from a generic error.
- **SC-009**: A delete call against a restoring deployment is refused with a reason an operator can act on, and the restore is unaffected.
- **SC-010**: Cluster-side records of deleted deployments are automatically removed within one operator reconciliation tick after the configured retention window elapses; records stuck in "deleting" are never removed automatically.
- **SC-011**: The retention window can be reconfigured per environment by an operator with cluster admin access without redeploying the platform's source code.
- **SC-012**: Default deployment-list views exclude deleted records; toggling "Show deleted" reveals them, and toggling it back hides them again, with no page reload required.

## Assumptions

- The cluster-side teardown handler that already runs on manual `kubectl delete` of a deployment record continues to function and is the same mechanism reused on the platform-driven delete path. Out-of-band deletions go through this handler but do **not** produce a platform-side tombstone.
- The platform's existing reconciliation cadence (cluster state → database) is fast enough to surface "deleting" → "deleted" transitions without introducing a dedicated long-running orchestration task.
- The backup retention strategy is unchanged by this feature: backups attached to a deleted deployment are retained as long as backups attached to live deployments. A separate backup TTL/lifecycle policy is a follow-up.
- The forensic retention window applies cluster-wide (per managed cluster); a per-deployment override is explicitly out of scope as premature flexibility.
- The Kubernetes baseline of the managed clusters supports server-side validation of immutable transitions on custom resource fields. (This is the mechanism used to make "deletion requested" monotonic; if a cluster falls below the baseline, the field is still honoured but loses its server-enforced one-way guarantee.)
- Restore-into-a-new-deployment workflows from a deleted deployment's backups are not introduced here. The data model permits them; the user-visible flow is a follow-up.
- Bulk/multi-select deletion is not introduced here. All deletion is single-deployment.
- The operator role required to trigger deletion is the same as the role required to upgrade or redeploy a deployment today; no new permissions are introduced.

## Out of Scope

- A backup-storage retention/TTL policy distinct from this feature (lifecycle of backup objects beyond "retained against tombstoned deployments").
- Reconciling out-of-band cluster-side deletions back into platform-side tombstones (the safety-net path is preserved, but it does not produce a tombstone).
- Restore-into-a-new-deployment user-visible flow from a deleted deployment's backups.
- Bulk delete and multi-select deletion.
- Per-deployment retention overrides on the cluster-side record.
- A separate "deletion failed" terminal state — failures stay visible through the in-progress state's surfaced reason.
