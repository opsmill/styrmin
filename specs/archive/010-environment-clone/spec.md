# Feature Specification: Environment Clone

**Feature Branch**: `010-environment-clone`

**Created**: 2026-08-19

**Status**: Extracted

**Input**: User description: "Environment Clone — clone a live environment into a new environment on the same cluster, built from a fresh environment backup, with selective deployment inclusion. Idea brief from [issue #6](https://github.com/opsmill/styrmin/issues/6#issuecomment-5208479529)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Clone an environment with its data (Priority: P1)

A platform operator clones environment `prod` into a new environment `prod-rehearsal` on the same cluster with a single operation. The clone comes up running with the source's application data as of clone time. The source environment is untouched throughout — its config and declared state are byte-identical before and after, and the only source-side artefact is the environment backup that was captured to build the clone.

**Why this priority**: This is the entire value proposition — one operation yields a running, data-bearing copy without touching the source, replacing a manual per-deployment recreate-and-restore slog. Without it nothing else in this feature matters.

**Independent Test**: Clone an environment containing a stateful deployment; assert the clone's counterpart deployment is running and holds the source's data as of capture time, and that the source environment's config and declared state are unchanged.

**Acceptance Scenarios**:

1. **Given** an environment with eligible deployments carrying application data, **When** the operator invokes clone with a new environment name, **Then** a fresh environment backup of the source is captured, a new environment and counterpart deployments are created entirely from that capture, each constituent backup is restored into its counterpart, and the clone record reports every source deployment as cloned, skipped (with reason), or failed (with reason).
2. **Given** a clone operation completed, **When** the operator inspects the source environment, **Then** its config and declared state are identical to before the clone, and the only new source-side artefact is the environment backup.
3. **Given** a clone operation in progress, **When** data is written to a source deployment after the backup capture completed, **Then** the finished clone holds the data as of capture time, not the post-capture write.
4. **Given** an environment containing a deployment that is ineligible for environment backup (e.g. never deployed), **When** the operator invokes clone, **Then** that deployment is skipped with an attributed name and reason, the rest are cloned, and the operation does not error out.
5. **Given** the initial environment backup capture fails, **When** the clone operation reports its outcome, **Then** no new environment or deployments have materialised.

---

### User Story 2 - Select which deployments to include (Priority: P2)

The operator clones an environment but includes only a subset of its deployments — for example, excluding a heavyweight analytics deployment that is irrelevant to the rehearsal. Omitting the selection includes all eligible deployments.

**Why this priority**: Selection makes clones cheaper and faster for the common case where only part of an environment matters, but a full clone (US1) is already valuable without it.

**Independent Test**: Clone an environment with two eligible deployments while selecting only one; assert the clone contains exactly the selected deployment's counterpart and the clone record accounts for the other as not included.

**Acceptance Scenarios**:

1. **Given** an environment with multiple eligible deployments, **When** the operator invokes clone with an explicit deployment selection, **Then** only the selected deployments are captured and cloned, and the clone record accounts for every source deployment.
2. **Given** an environment with multiple eligible deployments, **When** the operator invokes clone without a selection, **Then** all eligible deployments are included.

---

### User Story 3 - Override the environment config at clone time (Priority: P2)

The operator supplies an environment-config override when invoking the clone, so the clone comes up with safe, non-production settings (e.g. disabled outbound email, sandbox webhook endpoints) merged over the copied source config — before any cloned deployment comes up. This is the non-interference motive: a clone of production left with production configuration may actively interfere with real systems.

**Why this priority**: Without an override path, a production clone starts with production configuration, which can send real emails, hit real webhooks, and touch shared external services. Operators need this at clone time, not as a post-hoc edit racing against starting workloads.

**Independent Test**: Clone an environment with a config override; assert the clone's environment config equals the source's captured config with the override merged over it, and that the first started counterpart instances observe the merged config.

**Acceptance Scenarios**:

1. **Given** a source environment with config, **When** the operator invokes clone with an environment-config override, **Then** the clone's environment config is the captured source config with the override merged over it, applied before any cloned deployment comes up.
2. **Given** a clone invoked without an override, **When** the clone materialises, **Then** its environment config equals the captured source config.
3. **Given** a source environment with a production-only config field set (e.g. an external DNS integration), **When** the operator invokes clone naming that field as cleared, **Then** the clone's environment config does not contain the field at all.

---

### User Story 4 - Track, and if needed discard, a clone (Priority: P3)

The clone runs asynchronously. The operator watches its progress through a first-class clone record whose status is derived from its steps, sees exactly which source deployments were cloned, skipped, or failed and why, and can fully discard a clone in any state (including partial or failed) via ordinary environment deletion — leaving nothing that blocks re-cloning under the same name.

**Why this priority**: Cloning real environments takes real time and can partially fail; without honest tracking and a clean discard path the operator is back to spreadsheet archaeology. Still, tracking is meaningless before US1 exists.

**Independent Test**: Invoke a clone, poll its record until terminal, and assert every source deployment is accounted for; delete the created environment and assert re-cloning under the same name succeeds.

**Acceptance Scenarios**:

1. **Given** a clone in progress, **When** the operator reads the clone record, **Then** its status reflects the current state of its steps (derived on every read, never stored) and lists per-deployment outcomes.
2. **Given** a clone where one deployment failed to materialise (e.g. its captured application driver version vanished mid-clone), **When** the remaining deployments finish, **Then** the clone reports a partial outcome with the failure attributed by deployment name and reason, and the successfully cloned deployments are running.
3. **Given** a partial or failed clone, **When** the operator deletes the created environment through ordinary environment deletion, **Then** nothing remains that blocks a new clone of the same source under the same name.

### Edge Cases

- **Clone name already taken**: rejected upfront with a typed validation error and zero side effects. If the name is lost in the window between validation and creation (TOCTOU), the clone ends `FAILED` with the conflict attributed.
- **Captured application driver version vanishes mid-clone**: that deployment is attributed as failed; the remaining deployments proceed; the clone ends `PARTIAL`.
- **Clone of a clone**: allowed; no special casing.
- **Concurrent clones of one source**: allowed, each built from its own independent environment backup; there is no lock spanning a whole clone. Refinement from planning: the capture window counts as an environment-level operation on the source (same rule as environment backup/restore), so a second clone started while the first is still *capturing* is rejected upfront with a typed busy error; once the capture completes, further clones may start while earlier ones are still building their environments.
- **Deleting the backing environment backup**: refused with a typed error while the clone's *capture* is in flight and the clone could still be waiting for it; allowed afterwards — on a still-running clone it drives the clone to a failed terminal state with the deletion attributed (this is the escape hatch for a clone stuck before its environment materialised), and on a finished clone the recorded outcome stands.
- **Partially successful capture**: constituents that failed at capture are attributed as failed; the clone proceeds with the usable ones and ends partially successful (mirrors what environment restore accepts as restorable).
- **Mutating the clone's new environment while it is still being built**: environment-level config updates and further environment-level operations (backup/restore/clone) on the under-construction environment are refused with a typed busy error until the clone is terminal; counterpart deployments are in a restoring state, so ordinary deployment mutations are refused by the existing restoring-deployment rules. Deleting the under-construction environment remains allowed (it is the discard path) and drives the clone to a failed terminal state.
- **Deleting the source environment mid-clone**: allowed. The source's clone records are handled before its backups cascade — a clone that already created an environment survives as that environment's provenance (with the source reference cleared, and attributed as failed if it was still building); only a clone that materialised nothing has its record removed, and its work aborts quietly. Environments already created by earlier clones are ordinary environments and survive.
- **Clone status boundary**: the clone record covers environment/deployment creation and data restoration only; ongoing workload health remains the existing deployment-state machinery's job.
- **Recovery from `PARTIAL`/`FAILED`/stuck clones**: discard-and-retry — delete the created environment when it exists; for a clone stuck before the environment materialised, delete the backing environment backup (see above). No per-deployment repair in v1.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to clone a live environment into a new environment on the same cluster; the clone MUST come up running with the source's data as of clone time. *(Verify: E2E — clone an environment with a stateful deployment, assert data present.)*
- **FR-002**: System MUST capture a fresh environment backup of the selected deployments as the clone's first step, and nothing MUST materialise (no environment, no deployments) unless that capture reaches a restorable terminal status — fully or partially successful, matching what environment restore accepts. Constituents whose capture failed are attributed as failed and the clone may end partially successful; a wholly failed capture materialises nothing. *(Verify: force full backup failure, assert no environment created; force one constituent failure, assert the rest clone and the failure is attributed.)*
- **FR-003**: Users MUST be able to select which eligible deployments are included; omitting the selection includes all eligible. Eligibility is the environment-backup rule: non-tombstoned, non-internal, with an active application instance. *(Verify: propagation + E2E with an exclusion.)*
- **FR-004**: System MUST skip ineligible deployments with an attributed name and reason, not an error. *(Verify: clone an environment containing a never-deployed deployment.)*
- **FR-005**: Clone MUST preserve each included deployment's configuration, parameters, and application driver version. *(Verify: propagation test comparing source vs clone records.)*
- **FR-006**: Users MUST be able to supply an environment-config override at clone time, merged over the copied config before any cloned deployment comes up — including the ability to **clear** a copied config field entirely (not just replace its value), so production-only settings such as real DNS or outbound integrations can be removed, not merely changed. *(Verify: propagation — override visible in the clone's config and its first instances' contexts; a cleared field absent from the clone's config.)*
- **FR-007**: The clone MUST be built entirely from the captured environment backup; the live source is never re-read after capture. *(Verify: mutate source after capture, assert clone reflects capture-time state.)*
- **FR-008**: System MUST refuse to delete an environment backup while a clone's capture of it is still in flight (the only window where deletion strands unattributable work), for as long as the clone could still be waiting for that capture. Once the capture is terminal — or that wait budget is exhausted, which is what a capture whose constituent work was never picked up eventually does — deleting the backup is allowed and is the documented escape hatch for a stuck clone: it drives a non-terminal clone to a failed terminal state with the deletion attributed, and leaves a finished clone's recorded outcome untouched. The escape hatch MUST therefore always become reachable; a clone can never be pinned non-terminal with no recovery. *(Verify: unit tests — typed error during capture; attributed failure on post-capture deletion of a non-terminal clone; unchanged outcome on a terminal one; escape hatch open for a capture that can no longer terminalise.)*
- **FR-009**: Clone MUST be asynchronous and tracked by a first-class record whose status is derived from its steps on every read, never stored. *(Verify: derived-status unit tests, mirroring the environment-backup pattern of ADR-055.)*
- **FR-010**: Only `ADMIN` users MUST be able to clone. *(Verify: auth propagation test.)*
- **FR-011**: System MUST reject a clone whose target environment name is already taken with an upfront typed validation error and zero side effects; a name lost between validation and creation resolves to a `FAILED` clone with the conflict attributed. *(Verify: unit test for the upfront rejection; attributed-failure test for the race.)*
- **FR-012**: The clone operation and its status MUST be available on every user surface (UI, CLI, SDK, GraphQL). *(Verify: surface parity checks per surface.)*

### Key Entities

- **Environment clone** *(new)*: first-class record of one clone operation, linking the source environment, the backing environment backup it was built from, and the environment it created; carries per-source-deployment outcomes (cloned / skipped + reason / failed + reason) and a status derived from its steps on every read.
- **Environment** *(existing)*: the source of a clone, and the kind of thing a clone creates; the created environment is an ordinary environment, deletable through ordinary environment deletion.
- **Environment backup / constituent backup** *(existing)*: the capture a clone is built from; one constituent backup per eligible included deployment. The clone introduces one new demand on this machinery: restoring a constituent backup into a *different* deployment than it was captured from (cross-target restore) — the shipped restore contract is in-place only.
- **Deployment / application instance / application driver version** *(existing)*: each included source deployment gets a counterpart deployment in the clone, bound to the captured driver version, that reconciles like any ordinary deployment.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator obtains a running, data-bearing copy of an environment from a **single operation**, with zero manual per-deployment steps, on every surface (UI, CLI, SDK, GraphQL).
- **SC-002**: Cloning never mutates the source: source environment config and declared state are byte-identical before and after the clone; the only source-side artefact is the environment backup.
- **SC-003**: 100% of source deployments are accounted for on the clone record — each one reported as cloned, skipped with reason, or failed with reason.
- **SC-004**: Cloned data matches the capture point: in a marker-write test, the clone holds the marker written before capture and not the mutation written after capture.
- **SC-005**: A clone in any state (including partial and failed) can be fully discarded via ordinary environment deletion, leaving nothing that blocks re-cloning the same source under the same name.

## Assumptions

- **Single-cluster platform scope stands (ADR-039)**: clone targets the same cluster; "different cluster" from issue #6's original description is unreachable until that ADR is revisited.
- **The environment-backup foundation is stable**: the eligibility rule and the derived-status pattern (ADR-055) from the environment backup/restore feature are the foundations this composes on.
- **Existing backup strategies can restore into a different target**: disk, postgres, neo4j, and action strategies are assumed adaptable to cross-target restore; feasibility detail belongs to the plan phase.
- **Auth precedent**: clone requires the `ADMIN` role, following environment restore, whose privilege footprint clone strictly supersets.
- **No new external dependency is expected**; to be revisited at plan time if cross-target restore demands one.
- **Scope of the non-interference mitigation**: the clone-time config override (including field clearing) mitigates *configuration-level* interference only. Credentials, webhook URLs, and endpoints stored **inside the cloned application data** are copied verbatim and remain the operator's responsibility to neutralise; the documentation states this plainly.

## Out of Scope (v1)

- **Cross-cluster clone** — blocked by ADR-039 (single-cluster platform scope).
- **Network isolation mode** — its own slice (P2 in the idea brief), modelled as an environment-level property, to be specified separately; not a clone-only flag.
- **Point-in-time clone from an existing environment backup** — v1 always captures fresh; the mechanism should not preclude adding this later.
- **Per-deployment config/parameter overrides at clone time** — only the environment-level config override is in scope.
- **Config-only clone mode** (clone without data).
- **Per-deployment repair or retry of a partial clone**; recovery is discard-and-retry.
- **Automatic rollback of a failed clone**.
