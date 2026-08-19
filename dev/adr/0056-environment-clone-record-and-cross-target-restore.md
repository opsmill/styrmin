# ADR-056: Environment clone as a first-class record, built on a cross-target restore

**Status**: Accepted
**Date**: 2026-08-19
**Source**: specs/010-environment-clone/ (research.md D2-D10, data-model.md, spec.md)
**Related**: [ADR-055](0055-environment-backup-parent-records.md) (the parent-record and
derived-status pattern this reuses, and the deletion-escape-hatch decision this narrows),
[ADR-012](0012-environment-config-fanout.md) (per-item isolation, commit-before-dispatch,
and the per-field replacement granularity the override merge adopts),
[ADR-027](0027-environment-capabilities-computed-independently.md) (capabilities
recomputed for the cloned environment, never copied),
[ADR-031](0031-dual-identifier-resolution-service-layer.md) (source resolution),
[ADR-039](0039-single-cluster-platform-scope.md) (why the clone lands on the same
cluster), [ADR-053](0053-driver-version-provenance-fingerprint.md) (the fingerprint the
counterpart's driver version is pinned from),
[ADR-017](0017-authorization-model.md) (the role model the ADMIN gate follows),
[ADR-001](0001-alembic-database-migrations.md) (the revision this ships)

## Context

An operator who wanted a data-bearing copy of an environment had to create a target
environment by hand, recreate every deployment in it with the right driver version and
configuration, take a backup per source deployment, and restore each one into the
matching new deployment — then remember which of the N restores belonged to that
exercise. [Issue #6](https://github.com/opsmill/styrmin/issues/6) asked for the whole
thing as one operation.

[ADR-055](0055-environment-backup-parent-records.md) had already shipped most of the raw
material: a coordinated environment capture (config plus one `DeploymentSnapshot` and one
constituent `Backup` per eligible deployment), a derived parent status with a first-class
`PARTIAL`, and an environment-level concurrency guard. It even captured the ADR-053
driver fingerprint *explicitly for a future clone*.

Three things it did not answer, and one shipped invariant that stood directly in the way:

1. **Does a clone get its own record, and what is on it?** A clone spans **two**
   environments. Neither existing parent's shape fits: an `EnvironmentRestore` reaches
   its environment *through* its backup, and its vocabulary is in-place.
2. **Can a constituent backup be restored into a *different* deployment?** The shipped
   restore contract is in-place by construction, not by Velero limitation — six distinct
   coupling points, all in code we own (research D2).
3. **How is a clone discarded?** A partial or failed clone has to be fully removable, and
   must not block re-cloning under the same name.

The invariant in the way: `create_restore` refused a second restore when the target
deployment was already `RESTORING`, while a clone deliberately *parks* each counterpart
in `RESTORING` so nothing reconciles it before its data lands.

## Decision

### 1. A new `EnvironmentClone` record, derived status, name deliberately not unique

`EnvironmentClone` is a first-class table linking `source_environment_id`, the
`environment_backup_id` it was built from, and the `created_environment_id` it produced,
carrying the requested target name, the selection, the override, one attribution entry
per source deployment considered, and a flat list of operation-level events.

It follows ADR-055's derived-status decision exactly: **there is no status column.**
`derive_environment_clone_status` computes `PENDING` / `IN_PROGRESS` / `COMPLETED` /
`PARTIAL` / `FAILED` on every read from four inputs — the capture's own derived status,
whether the created environment exists, the per-deployment attribution, and the recorded
events (plus the referenced `Restore` rows). A stored status could contradict any of
them.

Two shapes are specific to clone rather than inherited:

- **`name` is not unique.** Uniqueness of an environment name belongs on
  `Environment(name, cluster_id)`, where it already lives. Putting it on the clone record
  too would mean a discarded clone permanently burned its name — the opposite of the
  discard-and-retry recovery model (spec SC-005).
- **Both environment FKs are nullable, and every deletion writes a marker.** Deleting the
  source nulls `source_environment_id` on a terminal clone (the denormalised
  `source_environment_name` keeps it readable); deleting the created environment nulls
  `created_environment_id`. A bare `NULL` is indistinguishable from "not created yet", so
  each cascade *also* appends a `{"step", "error", "fatal"}` entry. `fatal: true` drives
  the derivation to `FAILED`; a deletion that touches an already-terminal clone is
  recorded `fatal: false` so history is kept without rewriting the outcome.

A first read can therefore legitimately be `IN_PROGRESS` rather than `PENDING`: an
upfront skip is recorded with the clone row, and recorded progress is progress. Nothing
in the platform may assume `PENDING` comes first.

### 2. Extend the restore contract to a cross-target restore, rather than add a second one

`create_restore` gains an optional explicit target: when set, the guards and the
`RESTORING` flip apply to the **target** deployment, and the long-persisted-but-unread
`Restore.target_instance_id` is finally honoured for attribution. The restore flow splits
source identity (namespace derivation) from the status-write target. Velero's native
`namespaceMapping` — already wired in our builder — does the actual redirection; no new
dependency, and no second restore code path to keep in step with the first.

Counterparts are created through the ordinary `deploy_application` service with
`driver_version_id` pinned from the snapshot's ADR-053 fingerprint (Constitution §II — no
ad-hoc deploy logic), with two deliberate deviations: the **initial reconcile is
deferred**, and the deployment is created in `RESTORING` rather than `PENDING`.
Reconciling first would only create resources the restore flow immediately deletes, and
`RESTORING` is what makes the existing restoring-deployment guards protect a counterpart
until its data lands.

### 3. The counterpart adopts the source's Helm release identity

This is the least obvious decision and the one with a visible operator consequence.

A counterpart keeps its **own** `StyrminDeployment` CR identity (CR name = namespace =
`styrmin-<counterpart_id>`) but pins its **Helm release name to the source's**
(`styrmin-<source_deployment_id>`). Velero restores the source-named `HelmRelease` and
the source's Helm release-storage secret into the counterpart's namespace, and every
restored chart object carries the source's `meta.helm.sh/release-name`. Re-rendering the
release under a counterpart name would be a fresh Helm *install* over objects Helm
already owns, and would fail its ownership check outright; matching the source name makes
it an *upgrade*, which rewrites the ownership annotations consistently.

To keep that pin from being silently undone, release-reference resolution became sticky:
explicit override → the value the active instance already carries → the computed default.
A later configuration fan-out can no longer rename a live release.

Cross-target recovery replaces the restored source-named CR with the counterpart's own CR
body, carries kopf's state annotations over, re-runs prerequisites → HelmRelease →
services against the counterpart's spec, and **clears and verifies finalizers before
deleting the restored CR** — deleting it with kopf's finalizer intact would fire the
delete handler and tear down the very HelmRelease keeping the just-restored data alive.

**Consequence we accept and document:** `helm list -n styrmin-<counterpart>` shows a
release named after the *source* deployment. That is correct, not drift. (It assumes
Helm's default secret storage driver.)

### 4. The restore concurrency guard gates on a `Restore` row, not on `deployment.status`

`RestoreAlreadyInProgressError` is now raised when a **non-terminal `Restore` row**
(`PENDING` or `IN_PROGRESS`) already targets the deployment, or when one already replays
the same backup — never because `deployment.status == RESTORING`.

The old check conflated a *state* with an *operation*. A counterpart parked in `RESTORING`
is the **precondition** of its first cross-target restore, not a conflict with it. The
change is strictly better for in-place restores too: a deployment left `RESTORING` by a
restore whose flow died is restorable again instead of permanently wedged. `PENDING`
counts as in flight, so nothing that was refused before is accepted now on the strength
of a not-yet-started restore.

### 5. The `IN_USE` guard is scoped to the capture window — a narrowing of ADR-055 decision 6

FR-008 wanted the backing capture protected while a clone depends on it; ADR-055 decision
6 had deliberately left snapshot deletion *unguarded* because it is the escape hatch for
an operation pinned non-terminal. Guarding "while any clone is non-terminal" would have
recreated exactly the wedge that decision was engineered to avoid: a clone whose flow died
after a successful capture but before the environment materialised would sit
`IN_PROGRESS` forever, with an undeletable backup and no environment to delete.

So `delete_environment_backup` refuses with `IN_USE` **only while a referencing clone's
capture is itself still in flight** — the one window in which deletion strands
unattributable work. Afterwards deletion is allowed and *is* the escape hatch: on a
non-terminal clone it nulls the link and appends a fatal `environment_backup_deleted`
entry (the clone derives `FAILED`, attributed); on a terminal clone the recorded outcome
stands, because backups are TTL-governed and routine cleanup must not rewrite history.

Two honest deviations from the naive reading of that guard, both deliberate:

- the guard additionally requires the clone itself to be non-terminal, so a finished clone
  never blocks cleanup of its capture;
- **terminality is snapshotted at the guard rather than re-derived after the cascade.**
  The cascade deletes `Backup` and `Restore` rows that are themselves inputs to the
  derivation, so re-deriving afterwards would read a status computed from rows the
  operation just removed. The pre-cascade reading is the one that reflects what the
  operator asked about.

### 6. Read access is ungated — a conscious parity decision, not an inheritance

`cloneEnvironment` requires `ADMIN` (it writes environment configuration, exactly as
`updateEnvironment` and `restoreEnvironmentBackup` do, and strictly supersets their
footprint). The read surface — `environmentClone`, `environmentClones`,
`Environment.clonedFrom` — is **ungated**, matching `environmentBackup` /
`environmentBackups`.

This is recorded as a decision because it deserved an argument rather than a shrug. A
clone record exposes the same value class an environment backup already exposes ungated:
the captured environment configuration, here as the `configOverride` echoed back. Gating
clone reads while backup reads stay open would be inconsistent without being protective —
the same values remain readable one query away. If environment-level read gating is ever
introduced, it must cover both surfaces in one change; neither is a precedent for leaving
the other open.

### 7. Config override: top-level-field replacement, plus explicit field clearing

The cloned environment's configuration is the captured configuration with the override
applied as a **top-level-field replacement merge** — a field present in the override
replaces the captured field wholesale; absent fields keep their captured values. Both
sides are canonicalised through `EnvironmentConfig` validation first, the merged result is
validated before the environment is created, and capabilities are recomputed rather than
copied (ADR-027).

ADR-012 rejected deep/PATCH merge for `updateEnvironment`; per-field replacement is the
platform's established granularity, so the clone override adopts the same semantics one
level up.

Replacement alone cannot express *removal*, because the shared input-to-dict conversion
omits `None`-valued fields — yet removing production-only settings is the whole motive for
the override (US3). Hence a companion `clearConfigFields`, validated against
`EnvironmentConfig`'s top-level field names, whose keys are popped from the captured
configuration **before** the merge. A field both cleared and overridden takes the override
value. A cleared field is *absent* from the created environment's configuration — not
null, not defaulted — and resolves to `None` in an instance context.

The merge happens before the environment is created, so the counterparts' very first
instance contexts observe the merged configuration. There is no window in which cloned
workloads run under the source's configuration.

### 8. Internal deployments are omitted from attribution entirely

Eligibility is ADR-055's rule verbatim: non-tombstoned, non-internal, with an active
application instance. Clone adds one refinement: an **internal** deployment (an
environment's ingress controller, for instance) is not attributed at all unless it was
explicitly named in the selection — the cloned environment gets its own fresh ingress
controller as part of ordinary environment setup, so reporting the source's as "skipped"
would be noise, not information.

This is a recorded drift from the spec's SC-003 wording ("100% of source deployments are
accounted for"), which FR-003's own eligibility rule already contradicted. The
implemented, documented contract is: **every source deployment a caller could have
selected is accounted for** — cloned, skipped with a reason, or failed with a reason.
User-facing documentation states it that way rather than repeating the "100%" phrasing.

### 9. Discard is ordinary environment deletion — which now cascades deployments

The supported way to throw a clone away, in any state, is to delete the created
environment. It records `created_environment_deleted` and the clone derives `FAILED` —
a legitimate *discarded* state, not an unexpected error, and the surfaces render it as
such. Because the clone name is not unique and the environment name is freed, re-cloning
under the same name immediately afterwards works.

Making that path real exposed a pre-existing gap: `delete_environment` never cascaded its
deployments, so the ORM nulled a non-nullable FK. Every prior caller swallowed the failure
in cleanup handling, so it had never surfaced. Environment deletion now asks each
deployment to tear its cluster resources down and then removes its rows, in FK order,
detaching (rather than deleting) cross-target restores so a clone's attribution stays
resolvable.

## Consequences

- **A clone is honest about partial outcomes.** `PARTIAL` is a first-class result:
  usable constituents are cloned, an unresolvable pinned driver version or a
  capture-failed constituent is attributed by deployment name and reason, and the
  operation does not abort. An all-skipped clone — and a clone of an empty selection —
  is `COMPLETED`: an environment-only copy is a real, useful outcome.
- **The capture serialises on the source; nothing else does.** A second clone of the same
  source during the first's capture window is refused with the existing
  `ALREADY_IN_PROGRESS`; afterwards, clones proceed independently. A non-terminal clone
  additionally occupies its *created* environment, so configuration updates and
  environment-level operations on an under-construction clone are refused — deletion
  excepted, because deletion is the discard path.
- **In-place restore inherits an improvement.** The `Restore`-row guard un-wedges
  deployments left `RESTORING` by a dead restore, independently of cloning.
- **`helm list` in a counterpart's namespace shows a source-named release.** Documented,
  intentional, and load-bearing for Helm ownership consistency.
- **Non-interference is configuration-level only.** The override neutralises what lives
  in the environment configuration. Credentials, webhook URLs, API endpoints and licence
  keys stored **inside the restored application data** are copied verbatim, so a clone can
  still reach systems the source pointed at. Additionally, a driver that *generates*
  credentials at install/upgrade time can mint fresh credentials over restored data,
  because a counterpart's Helm values are re-rendered while its data comes from the
  source. Both are stated plainly in the user documentation rather than implied away.
- **The cloned environment starts without a backup storage location.** Capabilities are
  recomputed, not copied, and the location is an environment assignment rather than
  configuration — so a clone cannot take its *own* backups until one is assigned.
  Restoring the capture into it is unaffected.
- **One more Alembic revision and one more Prefect flow.** `EXECUTE_ENVIRONMENT_CLONE` is
  the platform's first orchestration that has to *wait* (for the capture to reach a
  restorable terminal status) instead of being fire-and-forget.

## Alternatives Considered

- **Reuse `EnvironmentRestore` with a nullable "target environment"**: rejected. It
  overloads an in-place contract and its status vocabulary with a two-environment
  operation, and every reader of either would have to learn which mode a row is in.
- **A stored clone status**: rejected for ADR-055's reasons, which apply with more force
  here — a clone's status depends on a capture, an environment, N attribution entries and
  N restores, so a stored copy has four ways to fall out of step.
- **A second, clone-only restore path**: rejected. It would duplicate the Velero builders,
  the hooks and the flow, and guarantee the two drift. Extending `create_restore` with an
  explicit target keeps one contract with one extra parameter.
- **Give the counterpart its own Helm release name**: rejected — a fresh install over
  objects Helm already owns fails its ownership check, and rewriting every restored
  object's ownership annotations by hand is strictly worse than matching the name.
- **Keep gating the restore guard on `deployment.status`**: rejected. It conflates state
  with operation, makes a parked counterpart un-restorable, and leaves in-place
  deployments permanently wedged after a dead restore.
- **Guard backup deletion while *any* referencing clone is non-terminal** (the literal
  reading of FR-008): rejected — it reintroduces the permanent wedge ADR-055 decision 6
  exists to prevent. See decision 5.
- **Re-derive clone terminality after the deletion cascade**: rejected — the cascade
  removes rows the derivation reads, so the post-cascade answer describes a record that no
  longer has its inputs.
- **Reserve the target environment name at validation time**: rejected. Reserving it
  needs a placeholder environment row, and FR-002 forbids anything materialising before
  the capture succeeds. The race is accepted and attributed where it lands, as a fatal
  `target_name_taken`.
- **Fully reconcile the counterpart, then restore data over it**: rejected — it collides
  with the restore flow's namespace delete-and-wait and would lay source volume objects
  over live pods.
- **Deep recursive merge for the config override**: rejected — no platform precedent
  (ADR-012 settled this) and ambiguous for list-valued fields. **Whole-config
  replacement** was rejected from the other side: an operator overriding one environment
  variable would silently drop everything else.
- **A `configOverride` shape that rejects unknown keys**: not achieved in v1, and recorded
  as a known caveat rather than claimed. The generated input model tolerates extra keys,
  so a *misspelled* override field is dropped silently and the captured value stays in
  place. Only an unknown `clearConfigFields` *name* is a validation error.
- **Cross-cluster clone**: out of scope, blocked by
  [ADR-039](0039-single-cluster-platform-scope.md).
- **Point-in-time clone from an existing environment backup**: deferred. v1 always
  captures fresh; nothing in the record's shape precludes adding it, since the capture is
  already a plain FK.
