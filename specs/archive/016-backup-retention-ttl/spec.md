# Feature Specification: Configurable Backup Retention TTL

**Feature Branch**: `fac/fix-backup-ttl-npf7g`

**Created**: 2026-08-03

**Status**: Extracted

**Input**: User description: "PRD: Configurable backup retention TTL — an optional `backup_ttl` config field at cluster/environment/deployment scopes (deepest wins, default 720h), validation of Go-duration h/m/s syntax with typed errors, recording applied TTL + Velero expiration on the backup record, GraphQL `Backup.ttl`/`expiresAt` fields, typed environment-update and deployment-config inputs carrying `backup_ttl`, web UI expiry column, and `styrminctl backups list` Expires column." (Full PRD sourced from a grilled idea-brief session on issue #305.)

## Problem Statement

Every backup Styrmin creates is retained for a fixed 30 days (Velero TTL `720h`). Operators cannot change this at any scope — not per deployment, not per environment, not globally. Compliance-driven organisations that must retain backups for 90 days or a year have no knob, and cost-sensitive setups that want shorter retention are equally stuck. The only workaround is editing Velero resources out-of-band, which Styrmin will not reconcile — and nobody can even see when a backup will expire without cluster access.

Backup retention becomes a first-class, optional config policy: a `backup_ttl` field settable at **cluster**, **environment**, or **deployment** scope, with the deepest scope winning and an unchanged built-in default of `720h`. Every backup created after a policy change carries the resolved retention, and every backup's expiry date is visible where backups are listed — in the web UI and in the `styrminctl` backup list — with the applied TTL recorded on the backup for audit.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Environment retention policy (Priority: P1)

A platform engineer sets `backup_ttl` on an environment; every subsequent backup of any deployment in that environment is created with that retention, the applied TTL is recorded on the backup for audit, and the expiry date is visible in the backup list.

**Why this priority**: This is the core value of the feature — aligning Styrmin's backup lifecycle with an organisation's retention policy at the scope where policy naturally lives (the environment). Without it nothing else matters; with it alone, the feature is already a viable MVP.

**Independent Test**: Can be fully tested by updating an environment's config with `backup_ttl: "2160h"`, creating a backup of a deployment in that environment, and asserting the created Velero Backup carries a 2160h TTL, the backup record stores the applied TTL, and the backup list shows the matching expiry date.

**Acceptance Scenarios**:

1. **Given** an environment with a backup storage location assigned and a running deployment, **When** the operator updates the environment config with `backup_ttl: "2160h"` and then creates a backup, **Then** the Velero Backup carries a 2160h TTL, the backup record stores the applied TTL, and the backup list shows the matching expiry date.
2. **Given** no `backup_ttl` configured at any scope, **When** a backup is created, **Then** the backup carries the built-in `720h` TTL and the backup spec is byte-identical to today's behaviour.
3. **Given** an operator debugging retention, **When** a backup is created, **Then** the backup workflow logs the resolved TTL and the scope it came from (deployment, environment, cluster, or built-in default).

---

### User Story 2 - Deployment-scope override (Priority: P2)

A platform engineer overrides retention for a single critical deployment so that it keeps backups longer than its environment's default; sibling deployments in the same environment keep following the environment policy (deepest scope wins).

**Why this priority**: Overrides matter only once the base policy exists. This delivers the "critical system retains longer" story and proves the precedence chain end to end.

**Independent Test**: Can be tested by setting `backup_ttl: "720h"` on an environment and `backup_ttl: "8760h"` on one deployment in it, backing up both that deployment and a sibling, and asserting the respective TTLs (8760h vs 720h).

**Acceptance Scenarios**:

1. **Given** an environment with `backup_ttl: "720h"` and one deployment in it with `backup_ttl: "8760h"`, **When** each is backed up, **Then** the critical deployment's backup carries 8760h and a sibling deployment's carries 720h (deepest scope wins).
2. **Given** a cluster created with `backup_ttl` in its config and an environment with no `backup_ttl`, **When** a deployment in that environment is backed up, **Then** the backup carries the cluster-scope TTL (cluster acts as the org-wide baseline).

---

### User Story 3 - Invalid value rejected loudly (Priority: P3)

An operator typos `30d`; the mutation fails immediately with a typed validation error naming the field and hinting correct `720h`-style syntax. Nothing is persisted, and backup behaviour is unchanged.

**Why this priority**: Validation guards the two higher-priority stories from silent misconfiguration, but it has no standalone value without them.

**Independent Test**: Can be tested by submitting `backup_ttl: "30d"` (and other malformed values) through each config surface and asserting the typed error and that the stored config is unchanged.

**Acceptance Scenarios**:

1. **Given** any config surface (cluster create, environment create/update, deployment config create/update), **When** `backup_ttl: "30d"` is submitted, **Then** the mutation returns a typed validation error naming the field and suggesting `720h`-style syntax, and the stored config is unchanged.
2. **Given** any config surface, **When** `0h`, `-24h`, `720` (bare integer), or `""` is submitted as `backup_ttl`, **Then** each is rejected with the same typed, field-naming validation error.

---

### User Story 4 - Expiry visible in the web UI and CLI (Priority: P2)

An application owner sees when each backup expires in the web UI backup list (with the applied TTL in the detail/tooltip); a CLI user sees an `expires_at` column in `styrminctl backups list`. Neither needs cluster access or calendar math.

**Why this priority**: Visibility is what makes retention trustworthy — operators can verify a restore point is still available before they need it. It rides on the recorded metadata from User Story 1.

**Independent Test**: Can be tested by rendering the backup list (UI component test / CLI unit test) with backups that have and lack expiry metadata and asserting the expiry date and "—" fallback respectively.

**Acceptance Scenarios**:

1. **Given** a backup with recorded TTL and expiration, **When** the user opens the web UI backup list, **Then** the expiry date is shown in the list and the applied TTL is available in the detail/tooltip.
2. **Given** a pre-existing backup with no recorded TTL/expiration (or a Failed/PartiallyFailed backup with no reported expiration), **When** the backup list is rendered in the web UI or via `styrminctl backups list`, **Then** the expiry renders as "—".
3. **Given** backups with recorded expiry, **When** the CLI user runs `styrminctl backups list`, **Then** an `expires_at` column shows the expiry, "—" when null.

---

### Edge Cases

- **Very short TTL** (e.g. `1h`): accepted as deliberate operator policy — no minimum bound; the visible expiry date is the mitigation.
- **Restore from an expired backup**: Velero has garbage-collected the backup but Styrmin's record remains; the restore fails. Pre-existing drift that shorter TTLs surface sooner — out of scope, documented warning, cross-referenced to #304.
- **Backup created while an environment update is mid-fanout**: config is read at backup-build time; last committed value wins. Same semantics as today's storage-location resolution; no locking.
- **Failed / PartiallyFailed backup**: Velero reports no expiration; `expiresAt` stays null; UI and CLI render "—".
- **Cluster scope is set-at-create only** (no cluster-update mutation exists): documented; operators who need to change a broad default use environment scope.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept an optional `backup_ttl` at cluster, environment, and deployment config scopes, resolved deepest-wins (deployment → environment → cluster → built-in default). *(verify: unit test per precedence hop)*
- **FR-002**: System MUST create every Velero Backup with a TTL equal to the resolved `backup_ttl`. *(verify: unit test on workflow resolution + E2E assertion on the created Velero Backup)*
- **FR-003**: When `backup_ttl` is unset at every scope, the system MUST produce a `720h` TTL and a backup spec byte-identical to today's. *(verify: regression test)*
- **FR-004**: System MUST reject any `backup_ttl` that is not a strictly positive Go-duration string in `h`/`m`/`s` units, at every input surface, with a typed error naming the field and hinting the syntax (no day unit; no bare integers). *(verify: parametrised validator tests — `30d`, `0h`, `-24h`, `720`, `""`)*
- **FR-005**: The typed environment-update and deployment-config inputs MUST carry `backup_ttl`, so full-replacement updates cannot silently wipe a stored value; every first-party client that assembles a full-replacement update from persisted config (the web UI's environment and deployment input builders) MUST round-trip the field. *(verify: propagation test — set via create-config, update with and without the field; frontend preservation test on the full-replacement builders)*
- **FR-006**: The backup workflow MUST record the applied TTL and Velero's reported expiration on the backup record, and log the resolved value with its source scope. *(verify: unit test on recorded metadata; log assertion)*
- **FR-007**: Users MUST be able to read `ttl` and `expiresAt` on the GraphQL `Backup` type; both nullable for pre-existing backups. *(verify: GraphQL propagation test)*
- **FR-008**: Users MUST see the expiry date in the web UI backup list, with the applied TTL in the detail/tooltip; null renders as "—". *(verify: frontend component test)*
- **FR-009**: A `backup_ttl` change MUST apply only to backups created afterwards; the system MUST NOT attempt to modify existing Velero backups' expiration. *(verify: documented limitation + the E2E naturally proves the "next backup" half)*
- **FR-010**: `styrminctl backups list` MUST display an `expires_at` column, "—" when null. The header is the snake_case field name, matching the sibling timestamp columns in that same table (`started_at`, `completed_at`) — every column in `backups list` is named after its field, so a prose label like "Expires" would be the odd one out. Do not "fix" it back. *(verify: CLI unit test asserting the `expires_at` header)*

### Key Entities

- **Cluster / Environment / Deployment**: each config gains the optional `backup_ttl` field on the shared config base (per ADR-029); no new columns, existing JSON config storage.
- **Backup**: gains recorded applied-TTL and expiration in its existing metadata, surfaced as two new nullable GraphQL fields. No schema migration.
- **Instance**: unchanged in shape; a `backup_ttl` change propagates through the standard config-update flow (new instance version), like every other config field.
- **Backup retention TTL** *(new concept, not a new entity)*: glossary entry to be added to `CONTEXT.md` in the implementation change — explicitly distinct from `BackupSchedule.retention_count` (count-based, currently unenforced).
- Explicitly untouched: **BackupSchedule** and the derived **capabilities** JSON (recomputed, would be overwritten — see ADR-025/026/027).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Aligning Styrmin's backup retention with an organisation's policy requires zero out-of-band edits to cluster resources.
- **SC-002**: 100 % of backups created after a retention change carry the configured value, verifiable from the backup's own record without cluster access.
- **SC-003**: Zero invalid retention values reach the backup system asynchronously — every malformed value is rejected at submission.
- **SC-004**: With no retention configured, behaviour is byte-identical to today; the existing test suite passes with no assertion changes beyond relocating the pinned default.
- **SC-005**: A user can answer "when does this backup disappear?" directly from the backup list — web UI or CLI — with no cluster access and no calendar math.

## Assumptions

- Velero honours the backup TTL and garbage-collects expired backups (its documented behaviour).
- The single-cluster limit remains; cluster scope stays a set-at-create global default (no cluster-update mutation exists).
- Scheduled backups remain non-executing in v1 (their execution wiring does not exist yet); once implemented they flow through the same workflow and inherit TTL resolution for free.
- Cluster/environment creation accepts the `backup_ttl` key through the existing `config: JSON` argument with no schema change (ADR-029 pattern); typed inputs are extended only where they already exist (environment update, deployment config create/update).

## Out of Scope

- Per-backup TTL override on the create-backup mutation (policy-level needs are covered; revisit if "keep this one backup longer" demand appears).
- Per-schedule TTL (scheduled backups do not execute today — would be dead code).
- A deploy-time settings/env-var global (cluster scope plays that role).
- Day-unit sugar (`30d`) — Go duration syntax only.
- Expired-backup drift reconciliation (backup listed but no longer restorable) — documented warning instead; adjacent to #304.
- Retro-patching the expiration of already-created Velero backups (not reliably possible).
- A cluster-update mutation.
- Enforcement of `BackupSchedule.retention_count` (pre-existing, unrelated gap).

## Further Notes

- Related issues: #305 (source), #304 (backup history disappears after upgrade — expired-backup drift is adjacent), #263 (infrahub backup PartiallyFailed — null-expiration handling overlaps).
- Related ADRs: ADR-029 (config additions via the shared config base, no migration — the load-bearing pattern here), ADR-025/026/027 (capabilities are derived, hence not a home for this knob), ADR-018 (typed update inputs).
- Related specs: `specs/009-environment-update` (typed full-replacement input + redeploy fanout this feature rides), `specs/014-deployment-update-noop` (no-op detection semantics), `specs/002-single-cluster-limit` (why cluster scope ≈ global default).
- Glossary: a **Backup retention TTL** entry is added to `CONTEXT.md` in the implementation change.
