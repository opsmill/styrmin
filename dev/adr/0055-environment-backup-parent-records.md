# ADR-055: Environment backup/restore as parent records with derived status

**Status**: Accepted
**Date**: 2026-08-06
**Source**: specs/001-env-backup-restore/ (research.md D1-D11, data-model.md, spec.md)
**Related**: [ADR-012](0012-environment-config-fanout.md) (the fan-out convention this
replicates, and the umbrella-record rejection this deviates from),
[ADR-017](0017-authorization-model.md) (the role model the restore asymmetry follows),
[ADR-053](0053-driver-version-provenance-fingerprint.md) (the fingerprint the snapshot
records), [ADR-027](0027-environment-capabilities-computed-independently.md)
(capabilities recomputed, never captured), [ADR-001](0001-alembic-database-migrations.md)
(the revision this ships).

## Context

Backups were per-instance only. An operator wanting a coherent snapshot of a
whole environment triggered `createBackup` once per deployment and then tracked
by hand which N backups formed one logical snapshot — a spreadsheet problem the
platform created and refused to solve. Restoring meant replaying that list in
the right order, from memory. Issue #7 asked for both halves as single actions.

The mechanics were never the hard part: one constituent backup per eligible
deployment is a loop over the existing `create_backup` service, and
[ADR-012](0012-environment-config-fanout.md) already established exactly how an
environment-scope change fans out to deployments — per-item `try/except`
isolation, commit before dispatch, a structured audit line with outcome
counters, and its consequences section explicitly nominates that shape as "the
convention to replicate for any future environment-scope change".

Three questions were not answered by that precedent, and one of them puts this
feature in direct tension with it:

1. **Does the grouping get a record?** ADR-012 considered an umbrella row for
   its own fan-out and rejected it. Issue #7's entire premise is the grouping.
2. **If there is a parent, what is its status?** A snapshot of five deployments
   where four succeeded is neither "completed" nor "failed", and any answer
   stored alongside the children can contradict them.
3. **In what order does a restore revert config and restore data?** Both
   converge the same namespaces, and the naive ordering races them.

## Decision

### 1. A parent record — the justified deviation from ADR-012

`EnvironmentBackup` and `EnvironmentRestore` are first-class tables. Constituent
membership is a **nullable FK on the existing child** —
`Backup.environment_backup_id`, `Restore.environment_restore_id` — mirroring the
existing `Backup.schedule_id` precedent. A null FK is an ordinary standalone
backup; nothing about existing rows changes.

ADR-012's "Alternatives Considered" rejected a dedicated umbrella for its
fan-out, and that rejection has to be addressed rather than quietly stepped
over. Four reasons this is a genuine exception and not a reversal:

- **What ADR-012 rejected was a `Task` *type*, not a record.** The proposal
  there was a new member of the `Task` type enum for the umbrella event. That
  enum's rows track individual async operations, and adding a member per
  triggering source is the precedent ADR-012 correctly refused to set. This
  feature adds no `Task` type. Constituent backups remain ordinary `Backup`
  rows, driven by the ordinary `EXECUTE_BACKUP` flow, tracked by ordinary
  `Task` rows. The per-deployment work-item model is untouched.
- **ADR-012's reason was "no consumer needs it".** Its umbrella event was an
  audit fact about one mutation, and a structured log line served that fact
  completely. Here the grouping *is* the deliverable: operators list snapshots,
  inspect per-constituent outcomes, restore from a snapshot, and delete one
  with cascade. A log line cannot be queried, listed, restored from, or
  cascade-deleted. The requirement changed; the judgment did not.
- **Everything else about ADR-012 is replicated verbatim.** Fan-out lives in
  the service layer, not a new Prefect flow. Per-constituent `try/except`
  isolation: one conflicted constituent becomes a recorded error and its peers
  proceed. Commit before dispatch. A structured audit line with outcome
  counters (`env_backup_fanout_dispatched`, `env_restore_fanout_dispatched`)
  alongside `env_config_fanout_dispatched`. This extends the convention.
- **The narrow rule that generalises**: add an umbrella record when the
  grouping is itself a user-facing artifact with its own lifecycle — listable,
  inspectable, restorable-from, deletable-with-cascade. Keep the log line when
  the grouping is only an audit fact about a single mutation. ADR-012's case
  was the latter; this one is the former.

### 2. Parent status is derived on every read, never stored

Neither parent table has a status column. `EnvironmentOperationStatus` is
computed by a pure function from the constituents' own statuses plus the count
of recorded errors:

```text
any child PENDING/IN_PROGRESS  -> IN_PROGRESS
                                  (PENDING when every child is PENDING
                                   and no errors are recorded)
all children terminal:
    no failures                -> COMPLETED
    some completed, some not   -> PARTIAL
    nothing completed          -> FAILED
    no children, no errors     -> COMPLETED   (config-only snapshot)
```

The requirement was that a parent status contradicting its constituents be
**impossible**, not merely unlikely. The only structural way to get that is to
have nothing to contradict. Storing it would need a writer, and a writer means
modifying `execute_backup_workflow` / `execute_restore_workflow` (breaking the
zero-touch reuse constraint), a race between concurrent child completions, and
a window after a crash between the child update and the parent update where the
two disagree permanently. Deriving it means the parent needs **no writer at
all**, which is why this feature changed no existing flow.

`PARTIAL` is new. The closest prior art,
`update_backup_component_status`, also derives a parent status from a child map
— but stores the result and collapses every mixed outcome to `FAILED`. This
lifts the derivation, adds the mixed state as a first-class outcome, and drops
the storage.

The derivation only ever sees a *complete* capture, which is why the whole
capture — parent row, every constituent row, every recorded error — commits in
**one transaction** before any dispatch (decision 4). The first draft committed
the parent on its own and its children afterwards, which opened a window where
a committed snapshot had zero children and zero errors and therefore derived
`COMPLETED`: a cancelled request (`CancelledError` escapes the per-constituent
`except Exception`) published that state permanently, and the D6 guard of
decision 5 — an `EXISTS` over non-terminal *children* — did not hold the
environment while it was open. Committing once removes both by construction.

Two honest costs remain, documented rather than engineered away:

- **Terminal status is still not proof of convergence.** For a restore, the
  constituent data restores can be done while the reverted config is still
  propagating to the deployments that did not receive one; and a snapshot whose
  constituents were individually deleted afterwards legitimately reads
  `COMPLETED` with fewer children than `deployment_snapshots` (FR-014). The
  constituent count against `deployment_snapshots`, not the status, is what
  says whether the snapshot still covers the whole environment.
- **Status is O(children) per read.** Acceptable at tens of deployments per
  environment; the derivation is a list comprehension over already-loaded
  relationship rows.

### 3. Snapshot capture as JSON on the parent row

Three JSON columns on `EnvironmentBackup`: `environment_config` (a verbatim copy
of `Environment.config` at backup time), `deployment_snapshots` (one
`DeploymentSnapshot` per eligible deployment), and `constituent_errors`. One on
`EnvironmentRestore`: `skipped_constituents`. Pydantic models in the service
layer define the shapes; the database stores plain JSON.

Snapshots are immutable point-in-time captures, never queried relationally and
never updated — which is what the codebase already uses JSON columns for
(`Backup.component_statuses`, `Backup.metadata_`,
`ApplicationInstance.context`), per ADR-025's convention.

`deployment_snapshots` records the driver **fingerprint** (ADR-053), not just
the version string, so the planned clone extension can tell whether the same
driver content is still loaded. This is the one piece of v1 scope that exists
purely for a future feature; capturing it later is impossible, which is why it
is captured now.

`constituent_errors` exists because `create_backup` raises
`BackupAlreadyInProgressError` *before* it creates a row. The alternative —
hand-crafting a `FAILED` `Backup` row for each conflicted constituent — would
duplicate the naming and metadata logic and pollute the per-instance backup
list with rows that never had a Velero attempt.

Environment capabilities are deliberately **not** captured. They are recomputed
after the config revert per ADR-027.

### 4. Restore ordering: restored deployments converge via Velero, everyone else via the config fan-out

`restore_environment_backup` runs five steps in one service function:

1. Guard restorability (derived status must be `COMPLETED` or `PARTIAL`) and
   environment-level concurrency.
2. Classify every captured constituent as usable or skipped; persist the skips
   on the `EnvironmentRestore` row at creation.
3. Revert `Environment.config` to the captured value, recompute capabilities,
   create one constituent `Restore` per usable constituent (recording any late
   skip found while doing so), and **commit all of it once, before any
   dispatch**.
4. Run the config fan-out (`redeploy_for_environment_update`) for eligible
   deployments **not** receiving a constituent restore.
5. Dispatch one `EXECUTE_RESTORE` per created constituent restore.

Steps 2, 3 and step 5's row creation share one transaction for the same reason
`createEnvironmentBackup`'s capture does (decision 2): a cancellation between
the parent's commit and the constituent rows would otherwise publish a restore
that silently dropped its late skips and did not hold the environment.
Reusing `create_backup` / `create_restore` inside that shared transaction needs
one accommodation — a `UnitOfWork` view whose `commit`/`rollback` are no-ops, so
those services join the caller's transaction instead of committing a half-built
capture or rolling the parent back when one constituent's instance is busy.

The exclusion in step 4 is the load-bearing part. A deployment receiving a
Velero data restore is being returned to its backup-time state, and its restored
in-cluster resources already correspond to the captured config — both came out
of the same near-consistent snapshot. Redeploying it through the config fan-out
*while* Velero restores the same namespace races apply-state against the restore
with an undefined outcome. Excluding restored deployments removes the race by
construction while still converging every deployment: the restored ones via
Velero, the rest via the standard fan-out. Committing the config before any
dispatch preserves ADR-012's recovery property — a re-submitted operation picks
up laggards.

Two sharp edges pinned here because both are silent when got wrong:

- **The revert assigns `Environment.config` directly** and does not delegate to
  `update_environment`, which treats `config is None` as an idempotent no-op.
  Delegating would make a captured `None` config permanently unrestorable, and
  the failure mode is a successful-looking restore that changed nothing.
- **Expiry is derived, not read.** Velero garbage-collects expired backup data
  cluster-side but never updates the row, so an expired constituent still reads
  `COMPLETED`. Classification computes `expires_at < now` from the recorded TTL
  metadata — the same derivation `Backup.expiresAt` uses — so an expired
  constituent becomes an honest skip instead of a Velero-stage failure.

Every constituent that is not restored is recorded with its deployment name and
a reason. The reasons are stored as free strings, not a DB enum: the set will
grow, and a wire-level closed vocabulary would force a schema change (and break
older clients) each time it does. Restore never creates or deletes deployments —
topology drift is reported, never repaired.

### 5. Concurrency: one environment-level operation per environment, also derived

At most one environment backup *or* restore in flight per environment, enforced
in the service layer by repository `EXISTS` queries over linked children in
`PENDING`/`IN_PROGRESS`. A second request gets
`EnvironmentOperationInProgressError` (`ALREADY_IN_PROGRESS`, carrying the
in-flight operation's id and kind). Different environments never interact, and
the per-instance guards are unchanged.

This reuses decision 2's philosophy: "in progress" is a fact about the children,
so the guard can never disagree with reality and there is no lock row to leak if
a process dies. Two accepted limitations:

- **Two racing create calls can both pass the check.** The per-instance
  `has_in_progress_backup` guard then turns the loser's constituents into
  recorded errors — a `PARTIAL` outcome, not corruption. A DB advisory lock was
  rejected as disproportionate machinery for the window.
- **A stuck constituent pins the environment.** Dispatch is fire-and-forget, so
  a constituent whose flow never ran stays `PENDING` forever, its parent stays
  non-terminal, and the guard blocks every new operation. Decision 6 is the
  escape hatch.

### 6. Cascade delete reuses `delete_backup`, and has no status guard

`delete_environment_backup` loops constituents calling the existing
`delete_backup` (which already deletes each backup's restores), then deletes the
snapshot's `EnvironmentRestore` rows, then the parent. Full reuse keeps
"constituents behave as ordinary backups" true for deletion too: the row goes,
the Velero object's lifecycle stays governed by its TTL. Deleting a constituent
individually leaves the parent alive with a visible gap, which is a feature — a
snapshot that can only restore three of five applications must say so.

**Deletion is legal regardless of derived status.** This is deliberate and is
the escape hatch for decision 5's stuck-constituent case: no janitor will
rescue a fire-and-forget dispatch that never landed (ADR-024's cleanup covers
observed-state tables only), so deletion is the only way to release the
environment. A guard here would convert a stuck constituent into a permanently
wedged environment.

`delete_environment` gains the same cascade, run before the environment row is
deleted: `environmentbackup.environment_id` is a non-nullable FK, so without it
environment deletion becomes a constraint violation surfacing as an opaque
`INTERNAL_ERROR`. In v1 snapshots do not outlive their environment.

### 7. Restoring requires `ADMIN`; creating and deleting require `READ_WRITE`

`createEnvironmentBackup` and `deleteEnvironmentBackup` are `READ_WRITE`,
matching per-instance `createBackup` / `deleteBackup`.
`restoreEnvironmentBackup` is **`ADMIN`**.

The asymmetry is deliberate and is privilege parity, not caution:
`restoreEnvironmentBackup` rewrites `Environment.config`, which is exactly what
`updateEnvironment` does, and that mutation is `ADMIN`. Leaving the restore at
`READ_WRITE` would hand any `READ_WRITE` caller a way to mutate an
environment's config through the back door. No new roles or permission concepts
(ADR-017); the user surfaces gate the restore action accordingly.

## Consequences

- **Easier**: one action backs up or restores an environment of any size, and
  the "which backups belong together?" bookkeeping is the platform's problem
  now. The snapshot is a queryable artifact with its own lifecycle.
- **Easier**: no existing backup/restore code changed. No new Prefect flows, no
  strategy changes, no writer for the parent status, no modification to
  `execute_backup_workflow` / `execute_restore_workflow`. Constituents are
  ordinary backups for retention, listing, and deletion.
- **Easier**: `PARTIAL` makes a half-covered snapshot legible instead of
  rounding it to success or failure, and every non-restored constituent is
  attributed with a deployment name and reason. There are no silent skips to
  discover later, during a recovery.
- **Convention set**: an umbrella record is justified when the grouping is a
  user-facing artifact with its own lifecycle; a structured log line remains
  the answer when it is an audit fact about one mutation. Future
  environment-scope features should still start from ADR-012's fan-out shape
  and add a record only against this test.
- **Harder**: terminal parent status is not proof of convergence, in two
  directions — a just-created snapshot reads `COMPLETED` before its
  constituents exist, and a terminal restore leaves the reverted config still
  propagating to non-restored deployments. Both are documented on the user
  surfaces and in `dev/knowledge/backend/backup-restore.md`; neither is
  fixable without the stored status decision 2 exists to avoid.
- **Harder**: status and in-progress checks cost O(children) per read, and the
  constituent-outcome projection joins `deployment_snapshots` against linked
  backups on every query. Fine at tens of deployments; a very large environment
  would want the projection memoised.
- **Harder**: skip reasons are free strings, so clients must render them as
  text rather than switch on them. The trade is deliberate — a wire-level
  closed vocabulary would break older clients every time the set grows.
- **Harder**: two racing create calls can both pass the concurrency guard, and
  the loser's constituents surface as recorded conflicts. Accepted; the
  outcome is `PARTIAL`, never corruption.

## Alternatives Considered

- **No parent record; a structured log line as the umbrella** (ADR-012's
  answer for its own fan-out): rejected here. The grouping is the feature —
  operators must list, inspect, restore from, and cascade-delete it, and a log
  line supports none of those. See decision 1.
- **A stored parent status updated by child-flow callbacks**: rejected.
  Requires modifying the existing backup/restore workflows, races between
  concurrent child completions, and can contradict its children permanently
  after a crash between the child and parent writes. The requirement was
  structural impossibility, not low probability.
- **A new `EXECUTE_ENVIRONMENT_BACKUP` Prefect flow doing the fan-out**:
  rejected. Moves eligibility and snapshot logic out of the service layer
  (Constitution §III), duplicates the mutation-side component-config
  resolution, and makes the typed concurrency error unreachable synchronously —
  the caller could no longer receive `ALREADY_IN_PROGRESS` at request time.
- **`asyncio.gather` for parallel dispatch**: unnecessary. N fire-and-forget
  submissions at ~100ms each clear the 60-second enqueue budget for 20
  deployments with room to spare, and sequential dispatch keeps ADR-012's
  per-item isolation semantics simple.
- **Hand-crafted `FAILED` `Backup` rows for conflicted constituents** instead
  of `constituent_errors`: rejected. `create_backup` raises before creating a
  row, so the environment service would have to duplicate its naming and
  metadata logic, and the per-instance backup list would fill with rows that
  never had a Velero attempt.
- **Full config fan-out followed by constituent restores**: rejected —
  apply-state redeploy racing a Velero restore in the same namespace has an
  undefined outcome. **Restores first, config afterwards** was rejected for the
  same race from the other side (`redeploy_for_environment_update` does not
  check `RESTORING`), plus a window where restored data runs under the wrong
  environment config. **Waiting for the fan-out, then restoring** was rejected
  because fan-out completion is not synchronously observable without new
  polling machinery.
- **Delegating the config revert to `update_environment`**: rejected. Its
  `config is None` no-op guard would make a captured `None` config
  unrestorable, and silently so.
- **An in-progress guard on deletion**: rejected. It would turn a stuck
  constituent into a permanently wedged environment, since nothing else
  releases a fire-and-forget dispatch that never landed.
- **A DB advisory lock for the environment-level concurrency guard**: rejected
  as new machinery disproportionate to the race window, whose worst outcome is
  a `PARTIAL` snapshot.
- **A stored DB enum for skip reasons**: rejected. The set is expected to grow,
  and each addition would force a migration and a client-visible schema change
  for what is a human-readable explanation.
- **Restore at `READ_WRITE`**: rejected — it reverts `Environment.config`,
  which `updateEnvironment` requires `ADMIN` for, so it would be a privilege
  bypass.
