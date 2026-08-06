# Feature Specification: Environment Clone

**Feature Branch**: `fac/clone-restore-k93ia`

**Created**: 2026-08-06

**Status**: Draft

**Input**: User description: "Environment clone (issue #6) — clone a live environment into a new environment on the same cluster as a data-bearing copy, with selective deployment inclusion, automatic pre-clone environment backup as the transfer mechanism, clone-time environment-config override, first-class async tracking with derived status, and discard-and-retry recovery. Full grilled idea brief at https://github.com/opsmill/styrmin/issues/6#issuecomment-5208479529."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Clone an environment with its data (Priority: P1)

A platform operator clones a live environment (e.g. `prod`) into a new environment (e.g. `prod-rehearsal`) on the same cluster with a single operation. The clone comes up running with the source's application data as of clone time. The source environment is untouched throughout — the only source-side artefact is the environment backup the clone captures as its first step.

**Why this priority**: This is the entire value proposition — one operation replaces a manual, error-prone, per-deployment recreate-and-restore slog. Without it nothing else in this feature matters.

**Independent Test**: Can be fully tested by creating an environment with one data-bearing deployment, writing a marker into its data, invoking clone, and asserting the clone's deployment holds the marker while the source's config and declared state are unchanged.

**Acceptance Scenarios**:

1. **Given** a live environment with eligible deployments carrying application data, **When** the operator invokes clone with a new environment name, **Then** a fresh environment backup of the source is captured, a new environment and counterpart deployments are created entirely from that capture, each constituent backup is restored into its counterpart, and the clone finishes `COMPLETED`.
2. **Given** a completed clone, **When** the operator inspects the cloned deployments, **Then** each preserves the source deployment's configuration, parameters, and application driver version, and its application data matches the capture point.
3. **Given** a clone in progress, **When** the source environment is modified (deployment upgraded, deleted, or config changed) after the capture completes, **Then** the finished clone reflects capture-time state and none of the post-capture changes.
4. **Given** a clone in progress or completed, **When** the operator inspects the source environment, **Then** the source's config and every source deployment's declared state are identical to their pre-clone values.
5. **Given** the initial backup phase fails, **When** the clone is inspected, **Then** its status is `FAILED` and no new environment or deployments exist.
6. **Given** a running clone operation, **When** the operator queries its status on any surface, **Then** the reported status reflects the current state of its steps (derived on read, never stored) and attributes every source deployment as cloned, skipped (with reason), or failed (with reason).

---

### User Story 2 - Select which deployments are cloned (Priority: P2)

The operator narrows a clone to a subset of the source's deployments — for example cloning only the application under investigation and its database, excluding ancillary workloads. Omitting the selection clones all eligible deployments.

**Why this priority**: Cloning an entire large environment when only part of it is needed wastes cluster capacity and time. Selection is the issue's explicit acceptance criterion, but a clone without selection (US1) is already valuable.

**Independent Test**: Clone an environment containing two eligible deployments while selecting only one; assert the clone contains exactly the selected deployment and the other is attributed as excluded.

**Acceptance Scenarios**:

1. **Given** a source environment with several eligible deployments, **When** the operator invokes clone with a selection naming a subset, **Then** only the selected deployments are backed up and cloned.
2. **Given** a clone invocation with no selection, **When** the clone runs, **Then** all eligible deployments (non-tombstoned, non-internal, with an active instance) are included.
3. **Given** a source environment containing an ineligible deployment (e.g. never deployed, no active instance), **When** the clone runs, **Then** that deployment is skipped with an attributed name and reason — not an error — and the rest of the clone proceeds.

---

### User Story 3 - Override environment configuration at clone time (Priority: P2)

The operator supplies an environment-config override when invoking the clone. The override is merged over the source's captured environment config **before any cloned deployment comes up**, closing the window in which a clone of production could run with production settings (e.g. a live outbound mail relay or external endpoint configured at environment level).

**Why this priority**: A clone of production that comes up with production configuration can actively interfere with real systems. The environment-level override is the one safety lever available at clone time; without it every clone of production runs verbatim production config for at least a window.

**Independent Test**: Clone an environment whose config carries a known key while supplying an override for that key; assert the clone's environment config and the first materialised deployment configuration reflect the override, and the source's config is unchanged.

**Acceptance Scenarios**:

1. **Given** a clone invocation with an environment-config override, **When** the clone creates the new environment, **Then** the override is merged over the captured config before any counterpart deployment materialises.
2. **Given** a clone with an override, **When** the source environment is inspected afterwards, **Then** the source's config is unchanged.

---

### User Story 4 - Understand and discard imperfect clones (Priority: P3)

When part of a clone fails, the operator can see exactly which deployments failed and why, and can discard the whole clone — whatever its state — through ordinary environment deletion, then retry under the same name.

**Why this priority**: Long multi-step operations fail partially in real life. Attribution plus discard-and-retry is the v1 recovery model; without it a partial clone is an undebuggable dead end. It is P3 because it only matters once US1 exists and exercises failure paths.

**Independent Test**: Induce a constituent restore failure mid-clone; assert the clone finishes `PARTIAL` with the failed deployment attributed, then delete the clone environment and re-clone under the same name successfully.

**Acceptance Scenarios**:

1. **Given** a clone where one deployment's data restore fails, **When** the clone finishes, **Then** its status is `PARTIAL`, the affected deployment is attributed with a reason, and the remaining deployments are cloned normally.
2. **Given** a clone in any state (`IN_PROGRESS`, `PARTIAL`, `FAILED`, `COMPLETED`), **When** the operator deletes the clone environment through ordinary environment deletion, **Then** the deletion succeeds and nothing blocks a subsequent clone under the same environment name.
3. **Given** an in-flight clone, **When** anyone attempts to delete the environment backup the clone depends on, **Then** the deletion is refused with a typed error naming the dependent clone.

---

### Edge Cases

- **Clone name already taken**: environment names are unique per cluster. The name is validated upfront, before the backup phase — a typed error with zero side effects. If the name is taken in the window between validation and environment creation, the clone finishes `FAILED` with that reason attributed; no auto-renaming.
- **Captured application driver version no longer exists** when the counterpart deployment is created (e.g. driver reloaded/removed mid-clone): that deployment is attributed as failed; the rest proceed (`PARTIAL`).
- **Clone of a clone**: allowed with no special casing — a clone is an ordinary environment the moment it exists.
- **Concurrent clones of the same source**: allowed — each captures its own independent environment backup; no source lock, no serialization.
- **Source environment deleted mid-clone**: harmless after capture — the clone is built entirely from the captured environment backup and never re-reads the live source.
- **When is a clone "done"**: clone status covers creation and data restoration only. Whether the cloned workloads subsequently become healthy (or sit pending for lack of cluster capacity) is the existing deployment-state machinery's concern, not the clone record's.
- **Backup phase fails**: the clone is `FAILED` and nothing materialised — no orphan environment, no cleanup burden.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to clone a live environment into a new environment on the same cluster in a single operation, and the clone MUST come up with the source's application data as of clone time.
- **FR-002**: The system MUST capture a fresh environment backup of the selected deployments as the clone's first step, and MUST NOT create the new environment or any deployment unless that backup succeeds.
- **FR-003**: Users MUST be able to select which eligible deployments are included in the clone; omitting the selection MUST include all eligible deployments. Eligibility is the environment-backup rule: non-tombstoned, non-internal, with an active instance.
- **FR-004**: The system MUST skip deployments that are ineligible for environment backup with an attributed deployment name and reason, without failing the clone.
- **FR-005**: The clone MUST preserve each included deployment's configuration, parameters, and application driver version, and MUST copy the source's environment config and backup storage location assignment to the new environment.
- **FR-006**: Users MUST be able to supply an environment-config override at clone time; the system MUST merge it over the copied environment config before any cloned deployment comes up.
- **FR-007**: The clone MUST be built entirely from the captured environment backup — configuration, declared deployment state, and data; the live source MUST NOT be re-read after capture, and no operation on the source after capture may alter or block the clone.
- **FR-008**: The system MUST refuse, with a typed error, to delete an environment backup that an in-flight clone depends on.
- **FR-009**: The clone operation MUST be asynchronous and tracked by a first-class record whose overall status is derived from the state of its steps on every read and never stored.
- **FR-010**: The clone record MUST account for 100% of the source's deployments — each attributed as cloned, skipped (with reason), or failed (with reason).
- **FR-011**: A failure in one deployment's counterpart creation or data restoration MUST NOT abort the remaining deployments; the clone finishes `PARTIAL` with the failures attributed.
- **FR-012**: The system MUST validate the new environment name upfront, before the backup phase, and reject a taken name with a typed error and zero side effects.
- **FR-013**: A clone environment in any state MUST be deletable through ordinary environment deletion, and its deletion MUST leave nothing that blocks a subsequent clone under the same name.
- **FR-014**: Only users with the `ADMIN` role MUST be able to invoke a clone (precedent: environment restore, whose privilege footprint clone strictly supersets).
- **FR-015**: Clone invocation and status tracking MUST be available on all four surfaces: frontend, CLI, SDK, and GraphQL API.

### Key Entities

- **Environment clone** (new): the first-class record of one clone operation — linking the source environment, the backing environment backup, and the created environment; carrying the operator's inputs (new name, selection, config override) and per-deployment attribution; status derived on read from its steps.
- **Environment backup** (existing): the capture-time snapshot the clone is built from — environment config, declared deployment state, and one constituent backup per included deployment. Gains a protection: undeletable while an in-flight clone depends on it.
- **Environment** (existing): the clone creates a new one from captured config plus the operator's override; the new environment is ordinary in every respect (deletable, backupable, re-clonable).
- **Deployment** (existing): counterpart deployments are created in the new environment from captured declared state, preserving configuration, parameters, and application driver version binding.
- **Constituent backup / constituent restore** (existing): each included deployment's constituent backup is restored into its counterpart deployment — a restore into a *different* deployment than the one captured from, which the shipped in-place restore contract does not cover today.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator produces a running, data-bearing copy of an environment through a single operation — zero manual per-deployment steps — on every surface (frontend, CLI, SDK, GraphQL).
- **SC-002**: Cloning never mutates the source: the source environment's config and every source deployment's declared state are identical before and after a clone; the only source-side artefact is the environment backup itself.
- **SC-003**: 100% of the source's deployments are accounted for on the clone record — each one cloned, skipped with a reason, or failed with a reason. No silent omissions.
- **SC-004**: For every successfully cloned deployment, application data in the clone matches the capture point: a marker written before cloning is present in the clone; a mutation made to the source after capture is not.
- **SC-005**: A clone in any state — in-flight, partial, failed — can be fully discarded via ordinary environment deletion, leaving nothing that blocks re-cloning under the same name.

## Assumptions

- The platform remains single-cluster (ADR-0039); "clone to a different cluster" is unreachable until that ADR is revisited.
- The environment-backup eligibility rule and the derived-parent-status pattern (ADR-0055, feature 001-env-backup-restore) are stable foundations this feature composes on.
- The existing per-deployment backup strategies can restore into a different target deployment than the one they were captured from; confirming feasibility per strategy belongs to the plan phase.
- Cluster capacity for the doubled footprint is the operator's concern; the clone record does not track workload health (existing deployment-state machinery does).
- The `CONTEXT.md` glossary entry **Environment clone** (added alongside this spec) is the canonical vocabulary for this feature.

## Out of Scope (v1)

- Cross-cluster clone (structurally blocked by ADR-0039).
- Network isolation for cloned environments — deferred as its own slice, modelled as an environment-level property, with its own spec.
- Point-in-time clone from an existing environment backup (the clone mechanism should not preclude it later).
- Per-deployment config/parameter overrides at clone time (environment-level override only).
- Config-only clone mode (every clone is a data clone; ineligible deployments are skipped, not config-cloned).
- Per-deployment repair or retry of a partial clone (recovery is discard-and-retry via environment deletion).
- Automatic rollback of a failed clone.
