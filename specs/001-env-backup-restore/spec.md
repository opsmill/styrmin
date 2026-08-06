# Feature Specification: Environment-Level Backup and Restore

**Feature Branch**: `fac/env-backup-restore-6jtfn`

**Created**: 2026-08-06

**Status**: Draft

**Input**: User description: "Environment-level backup and restore operations (GitHub issue #7). Add the ability to back up and restore an entire environment as a single coordinated operation, via a new EnvironmentBackup construct grouping per-instance Backup records, plus a symmetric EnvironmentRestore record." (Full grilled idea brief supplied; see issue [#7](https://github.com/opsmill/styrmin/issues/7).)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Coordinated environment backup in one action (Priority: P1)

A platform operator managing a multi-application environment (e.g., a full staging or production stack) backs up the entire environment with a single action. The system captures the environment's config as of that moment, the declared state of every eligible deployment, and initiates one constituent backup per eligible application instance — all grouped under a single environment backup record whose status is derived from its children.

**Why this priority**: This is the core pain from issue #7 — today operators trigger per-instance backups one by one and track by hand which backups form a logical snapshot. A coordinated, traceable snapshot delivers value even before restore ships: it removes manual orchestration and gives a single record answering "which backups belong together?".

**Independent Test**: Can be fully tested by creating an environment with several deployments, triggering one environment backup, and verifying that one constituent backup exists per eligible deployment, the environment config and per-deployment declared state are captured, and the parent status correctly derives from the children.

**Acceptance Scenarios**:

1. **Given** an environment with several running deployments and an assigned backup storage location, **When** the operator creates an environment backup, **Then** one constituent backup is initiated in parallel per eligible deployment (non-tombstoned, non-internal, with an active application instance), the environment's config and each eligible deployment's declared state are captured, and the environment backup reports a status derived from its children.
2. **Given** an environment where one deployment's instance already has a backup in progress, **When** the operator creates an environment backup, **Then** that constituent is recorded as failed with an attributable error, the remaining constituents proceed, and the environment backup ends `PARTIAL` (assuming at least one other constituent completes).
3. **Given** an environment with zero eligible deployments, **When** the operator creates an environment backup, **Then** a config-only environment backup is created and immediately reports `COMPLETED` with zero constituents.
4. **Given** an environment with an environment backup already in progress, **When** the operator requests another environment-level operation on that environment, **Then** the request is rejected with a typed, machine-readable error and the in-flight operation is unaffected.

---

### User Story 2 - Coordinated in-place environment restore (Priority: P2)

A platform operator restores an environment to a known-good state with a single action. The system reverts the environment's config to the captured value and restores each usable constituent backup into its still-existing deployment, in place. Constituents that cannot be restored are skipped and reported with the deployment name and reason — never silently.

**Why this priority**: Restore is the recovery half of the feature and the second success metric of issue #7. It depends on backups existing (User Story 1) but is independently testable against any existing environment backup and delivers its own value: one-action recovery instead of application-by-application restores.

**Independent Test**: Can be fully tested by taking an environment backup, mutating the environment config and application data, triggering one environment restore, and verifying config reversion, per-constituent restore outcomes, and skip reporting.

**Acceptance Scenarios**:

1. **Given** a `COMPLETED` environment backup and a since-modified environment config, **When** the operator restores the environment backup, **Then** the environment config is reverted to the captured value and every usable constituent backup is restored into its still-existing deployment without further operator input.
2. **Given** a `PARTIAL` environment backup (some constituents failed at backup time), **When** the operator restores it, **Then** the deployments with usable constituent backups are restored and every constituent that was not restored is reported with its deployment name and reason.
3. **Given** an environment backup containing a constituent whose deployment has since been deleted, **When** the operator restores the environment backup, **Then** that constituent is skipped and reported ("deployment no longer exists"), no deployment is created or deleted, and the remaining constituents restore normally.
4. **Given** an environment where a new deployment was created after the backup was taken, **When** the operator restores the environment backup, **Then** the newer deployment's data is left untouched (it still receives the reverted environment config through the existing config propagation behavior, which is the documented, correct outcome).
5. **Given** an environment backup whose constituents have all expired or been deleted, **When** the operator restores it, **Then** the environment config is still reverted, all constituents are reported as skipped with reasons, and the restore record reflects the outcome.

---

### User Story 3 - Snapshot visibility and lifecycle management (Priority: P3)

A platform operator inspects existing environment backups — seeing each snapshot's derived status and per-constituent outcomes (including gaps from expired or individually deleted constituents) — and deletes snapshots that are no longer needed, cleaning up all constituent backups in one action.

**Why this priority**: Visibility is what makes `PARTIAL` trustworthy — an operator staring at a half-green snapshot needs to see exactly which applications are covered before deciding to restore. Deletion with cascade keeps storage manageable without reintroducing the "which backups belong together?" tracking problem.

**Independent Test**: Can be fully tested by creating environment backups with mixed constituent outcomes, listing and inspecting them across the user surfaces, deleting one, and verifying its constituents (and their restores) are removed with it.

**Acceptance Scenarios**:

1. **Given** environment backups with mixed constituent outcomes, **When** the operator lists environment backups for an environment, **Then** each snapshot shows its derived status and, on inspection, the per-constituent outcomes with attributable errors for failures.
2. **Given** an environment backup, **When** the operator deletes it, **Then** its constituent backups (and any restores of those backups) are deleted with it.
3. **Given** an environment backup with one constituent individually deleted by an operator, **When** the snapshot is inspected, **Then** the parent still exists and the gap is visible.

---

### Edge Cases

- **Empty environment**: zero eligible deployments yields a config-only backup, immediately `COMPLETED` (supports the future "environment as template" clone case).
- **Constituent conflict at backup time**: an instance with a backup already in progress becomes a failed constituent with an attributable error; the environment operation never aborts or waits because of it.
- **No backup storage location assigned**: constituents fail exactly as individual backups do today; the environment backup ends `FAILED`. No new precondition is introduced.
- **Unusable constituents at restore time** (failed at backup, expired per retention TTL, constituent individually deleted, deployment deleted/tombstoned): uniform rule — restore what's usable, skip and report what isn't, naming the deployment and reason.
- **Topology drift**: restore never creates or deletes deployments. Deployments created after the backup keep their data; they do receive the reverted environment config via the existing config propagation behavior (documented as correct).
- **Concurrent environment-level operations**: at most one environment backup *or* environment restore in progress per environment; a second request receives a typed error. Different environments are fully independent. Per-instance guards are unchanged.
- **Piecewise expiry**: constituents expire individually per the existing deepest-wins backup retention TTL, so a snapshot decays piecewise; the parent record persists until explicitly deleted, even if all constituents have expired.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to create an environment backup with a single operation; it initiates constituent backups in parallel for every eligible deployment in the environment. Eligible means: non-tombstoned, non-internal, with an active application instance, regardless of current deployment state.
- **FR-002**: An environment backup MUST capture the environment's config as of backup time.
- **FR-003**: An environment backup MUST capture, for each eligible deployment, its declared state: driver, driver version with provenance fingerprint, application version, deployment config, and parameters — sufficient to recreate the deployment later (clone readiness).
- **FR-004**: The status of an environment backup and of an environment restore MUST be purely derived from their constituents: `COMPLETED` (all constituents completed), `PARTIAL` (at least one completed and at least one not), `FAILED` (all failed), plus `PENDING`/`IN_PROGRESS` while work is ongoing. A stored parent status that contradicts its constituents MUST NOT be possible.
- **FR-005**: A per-instance conflict at backup time (backup already in progress for that instance) MUST be recorded as a failed constituent with an attributable error and MUST NOT abort, block, or delay the rest of the environment backup.
- **FR-006**: Users MUST be able to restore a `COMPLETED` or `PARTIAL` environment backup with a single operation: the environment's captured config is reapplied and every usable constituent backup is restored in place into its still-existing deployment, without further operator input.
- **FR-007**: Every constituent that is not restored (failed at backup, expired, constituent deleted, deployment gone) MUST be reported with its deployment name and reason. Zero silent skips.
- **FR-008**: An environment restore MUST NOT create or delete deployments.
- **FR-009**: The system MUST reject a second concurrent environment-level operation (backup or restore) on the same environment with a typed, machine-readable error. Environment-level operations on different environments MUST NOT block each other, and per-instance operation guards remain unchanged.
- **FR-010**: Deleting an environment backup MUST delete its constituent backups and any restores of those backups. Constituent backups MUST remain individually deletable, with the parent surviving and the gap visible.
- **FR-011**: Backing up an environment with zero eligible deployments MUST yield a config-only environment backup that immediately reports `COMPLETED`.
- **FR-012**: Environment backup and restore MUST be available on all four user surfaces with equivalent capability: the programmatic API, the client SDK, the command-line client, and the web frontend (a backups section on the environment detail page: trigger backup, list snapshots with derived status, trigger restore, inspect per-constituent outcomes).
- **FR-013**: Users MUST be able to list environment backups per environment and inspect a single environment backup or environment restore, including per-constituent status and errors.
- **FR-014**: Constituent backups MUST behave as ordinary individual backups for retention: expiry stays per-constituent with the existing deepest-wins retention TTL resolution. The environment backup record persists until explicitly deleted, even when all constituents have expired.

### Key Entities

- **Environment backup**: A coordinated, near-consistent snapshot of an environment — its config as of backup time, the declared state of every eligible deployment, and one constituent backup per eligible application instance — grouped under a single record whose status is derived from its children. New entity.
- **Environment restore**: The record of one coordinated restore of an environment backup — derived status plus per-constituent outcomes, including skipped constituents with reasons. New entity.
- **Backup (constituent)**: Existing per-instance backup record; unchanged semantics. Gains membership in at most one environment backup. Children of an environment backup remain ordinary backups (individually listable, deletable, expiring).
- **Restore (constituent)**: Existing per-deployment restore record; unchanged semantics. Constituent restores of an environment restore are ordinary restores.
- **Environment**: Existing entity; source of the captured config and the scope of membership and concurrency rules.
- **Deployment**: Existing entity; contributes declared state to the snapshot and receives in-place restores.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator backs up an environment of N applications with one action (one API call, one command, or one click), for any N — versus N individual triggers plus manual tracking today.
- **SC-002**: An operator restores an environment with one action; every constituent with a usable backup is restored without further operator input.
- **SC-003**: For any combination of constituent outcomes, the parent status matches the derivation rule — no stored parent status can contradict its constituents.
- **SC-004**: 100% of non-restored constituents are attributed with deployment name and reason — zero silent skips.
- **SC-005**: After an in-place restore completes, the environment's config equals the config captured at backup time.
- **SC-006**: For an environment with 20 deployments, all constituent backups are enqueued within 60 seconds of the backup request being accepted.

## Assumptions

- **Near-consistent snapshot**: constituent backups are initiated together (in parallel), best-effort, with no quiescing — no stopping components and no write-freezing. A "stop-the-world consistent" variant is explicitly not this feature.
- **Parallel restore fan-out**: constituent restores run in parallel; there are no cross-application ordering or dependency semantics in v1.
- **Design constraint — full reuse**: constituent backup and restore fully reuse the existing per-instance machinery; no duplicated backup-strategy logic. (Carried from issue #7 as a design constraint rather than a success criterion.)
- **Capabilities are computed, never captured**: environment capabilities are recomputed after restore per the existing model (ADR-0027), not stored in the snapshot.
- **Storage model unchanged**: the backup-storage-location-per-environment model is untouched; constituents store to the environment's assigned location exactly as individual backups do today.
- **Config propagation**: reverting the environment config flows through the existing environment-config propagation behavior (ADR-0012), including to deployments created after the backup — documented as correct.
- **Authorization**: environment backup/restore operations follow the existing authorization model (ADR-0017); no new roles or permission concepts.

## Out of Scope (v1)

- **Clone** — restoring an environment backup into a **new** environment (planned P2 extension). v1 MUST, however, capture enough declared state that pre-clone backups remain clone-usable (FR-003). The clone input contract (target environment name, cluster binding, collision policy) is deferred to the P2 spec.
- **Topology reconstruction in place** — recreating deployments deleted since the backup, or removing deployments created after it.
- **Environment-level backup schedules** — schedules remain per-deployment.
- **Restoring into a different existing environment.**
- **Write-freeze / quiesced consistency.**
