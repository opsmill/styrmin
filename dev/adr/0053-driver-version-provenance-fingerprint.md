# ADR-053: Driver-version identity via provenance fingerprint; loads are non-destructive

**Status**: Accepted
**Date**: 2026-08-04
**Source**: specs/archive/013-driver-fingerprint/research.md (D-001 – D-007), data-model.md
**Related**: [ADR-001](0001-alembic-database-migrations.md) (which D-008 violated — see
Consequences), [ADR-028](0028-deployment-history-derived-from-existing-data.md) (the
timeline that depends on rows surviving), [`dev/guides/driver-iteration.md`](../guides/driver-iteration.md)
(the contributor-facing workflow).

## Context

Reloading an application driver from the same `(driver, source, version)`
coordinates used to **delete and recreate** the `ApplicationDriverVersion` row.
Two consequences followed. Editing a local driver without bumping its `version`
string produced no observable change — the platform could not tell the new bytes
from the old, so driver iteration meant either bumping a version label on every
save or believing a stale row. And the delete itself raised `IntegrityError`
against child `Action` rows, because the relationship had no cascade.

Worse, deleting the row destroyed history: deployments and application instances
hold FKs to the exact driver version they were deployed from, and rewriting that
row rewrote the past.

The platform needed to answer "are these the same driver bytes?" without trusting
a human-maintained version string.

## Decision

### 1. Two explicit fingerprint columns, discriminated by `source_type`

`ApplicationDriverVersion` gains `content_hash: str | None` (SHA-256 hex, 64
chars) and `source_commit_sha: str | None` (40-char git SHA). **Exactly one is
non-null per row**, selected by `source_type`; the invariant is enforced at the
service layer at load time.

Two names rather than one polymorphic `content_fingerprint` column: the commit
SHA is a property of the *source*, not a hash of loaded bytes, and calling it a
"content hash" would mislead at every query site. Distinct names also produce
distinct GraphQL fields, letting the frontend offer a git link for one and a
copy-hex affordance for the other. A discriminator column was rejected because it
would duplicate information `source_type` already carries.

### 2. The local content hash is length-framed over exactly the files the loader reads

```python
SHA-256(
    b"driver.styrmin.yml\x00" + len_be8(driver_spec)     + driver_spec
  + b"values_template\x00"    + len_be8(values_template) + values_template
  + (b"actions.py\x00"        + len_be8(actions_py)      + actions_py
     if spec.actions else b"")
)
```

Three properties are deliberate:

- **Only files the loader actually reads contribute.** Editing `README.md` or
  adding a screenshot must not mint a new driver version — that would astonish
  the author. `actions.py` is included **iff** `spec.actions` is non-empty,
  matching loader behaviour exactly.
- **Length-prefix framing**, so two distinct file triples cannot collide by
  shifting bytes across a boundary.
- **Raw bytes, no parsing or canonicalisation.** A whitespace or comment-only
  edit *is* a new version. Hashing the parsed Pydantic model would normalise
  those away and report "no change" after a real edit.

### 3. Git provenance is the resolved commit SHA — nothing is re-hashed

Git commits are already content-addressable. For `source_type = "git"` the
fingerprint is the SHA the provider resolved for the loaded ref, read from the
cloned repo's `HEAD`. `GitDriverProvider` had to be extended to surface it — it
previously cloned and yielded a temp directory without telling the caller what it
had checked out.

### 4. Identity widens; the delete branch is gone

Upsert looks up via a single `get_by_identity()` parameterised by `source_type`:

```text
(application_driver_id, source_type, source_repository,
 source_branch, source_path, version,
 content_hash | source_commit_sha)
```

- Same tuple → return the existing row. The load is an idempotent no-op.
- Same coordinates, different fingerprint → **a new row alongside the old one**.
- **No load operation deletes any `ApplicationDriverVersion` row.** This is the
  change that makes the feature non-destructive: existing deployments keep
  pointing at the bytes they were deployed from.

A `uq_application_driver_version_identity` unique index over the identity columns
backs the lookup. Registration of Prefect actions is keyed on the fingerprint's
short prefix, so a historical deployment resolves its actions to the bytes it
shipped with rather than to whatever currently occupies that version label.
For git rows this holds end to end (#375): the action deployment's pull step
pins `commit_sha` to `source_commit_sha`, and the short fingerprint is part of
the Prefect deployment *name* — Prefect upserts on `(flow, name)`, so a shared
name would let a reload overwrite the earlier version's deployment. Rows
registered before #375 keep their branch-tip deployment: a repeated load is a
no-op, so nothing re-registers them.

### 5. Cascade on children, deliberately not on deployments

`actions` and `component_configs` get
`sa_relationship_kwargs={"cascade": "all, delete-orphan"}`, mirroring
`Deployment.components`. This fixes the `IntegrityError` and makes a future prune
possible.

**`deployments` is intentionally NOT cascaded.** A deployment outlives its driver
version — its lifetime is the application's, not the driver's. `ApplicationInstance`
and `Deployment` FKs preserve provenance across instance regeneration, and
cascading from a driver version would delete live deployments.

### 6. Labels always show `<version>@<short7>`

Every surface that names a driver version renders `<version>@<short>` where
`<short>` is the fingerprint's first 7 characters — **unconditionally**, even when
only one row exists for that version. Detail views show the full hex with a copy
affordance.

Showing the suffix only "when ambiguous" makes labels flicker
(`1.2.3` → `1.2.3@a1b2c3d`) the moment a second row appears; stability matters
more than brevity. 7 chars is git's own convention and reads as a fingerprint to
any developer. `format_driver_version_label()` in
`services/driver/labels.py` is the single source of truth, duplicated in
`cli/src/styrminctl/labels.py` only because the CLI is a separate package.

### 7. No automatic garbage collection

v1 never prunes unreferenced rows. Rows are a few KB; thousands are operationally
irrelevant. A correct "safe to delete" rule has to check `Deployment` **and**
`ApplicationInstance` FKs and account for tombstoned deployments — getting it
wrong corrupts the timeline. That logic belongs in an explicit admin operation
(`styrminctl driver prune`, filed as a follow-up), not a background job. The
cascade from §5 is what will make it clean when it arrives.

## Consequences

- **Driver iteration works without version bumps.** Save a file, reload, get a
  new row with a new short fingerprint. Documented in
  [`dev/guides/driver-iteration.md`](../guides/driver-iteration.md).
- **History is immutable.** No load rewrites a row a deployment or instance
  points at, so the timeline and the "which bytes ran?" question stay answerable.
- **Rows accumulate.** Every distinct set of driver bytes is a permanent row
  until a prune command exists. Accepted.
- **A misspelled or unbumped `version` no longer hides a change, but it does
  produce siblings.** Several rows can share a `version` string; the fingerprint
  suffix is what distinguishes them, which is exactly why §6 shows it always.
- **⚠ D-008 ("no migration; `metadata.create_all()` will add the columns") was
  wrong and cost a broken migration chain.** The research phase reasoned that
  because Styrmin was not yet deployed, new nullable columns needed no Alembic
  revision. `create_all()` only ever builds a *fresh* database, so every
  already-existing database was left without `content_hash`,
  `source_commit_sha`, `container_overrides`, or the identity index. Revision
  `a8b9c0d1e2f3` backfills all four — and had to double as a **merge revision**,
  because by the time the omission was noticed two other revisions had branched
  from the same parent and left the chain with two heads, making `styrmin db
  init` / `db migrate` fail outright with "Multiple head revisions are present".
  **The rule in [ADR-001](0001-alembic-database-migrations.md) and AGENTS.md is
  not waivable by "we have no production yet"** — a green test suite proves
  nothing here, because tests build their schema with `create_all()`.
- **The display rule needed a fallback the spec said it would not need.** D-006
  specified no NULL-fingerprint fallback, on the same "no legacy rows" premise.
  `format_driver_version_label()` in fact falls back to the bare `version` and
  logs a warning, because dev databases predating the backfill do contain such
  rows. The warning is deliberate: on rows created by the spec-013 load path both
  columns are always populated, so it firing means a loader regression, a manual
  insert, or a missed backfill — never normal operation.

## Alternatives Considered

- **A single polymorphic `content_fingerprint` column.** Rejected: loses the
  type-of-fingerprint signal at every query site and misdescribes the git case.
- **`content_fingerprint` + `content_fingerprint_kind` discriminator.** Rejected:
  two columns either way, and the discriminator duplicates `source_type`.
- **Hashing the parsed `ApplicationDriver` model instead of raw bytes.** Rejected:
  canonicalises away whitespace and comments, so a real edit reports as no change.
- **Hashing a tar of the driver directory.** Rejected: includes files the loader
  never reads and is non-deterministic across filesystems (mtime, ownership).
- **Fingerprint as primary key.** Rejected: the UUID PK is unchanged; the
  fingerprint is a content-addressable *secondary* identity.
- **Two repository methods (`get_by_local_identity` / `get_by_git_identity`).**
  Rejected: identical logic, split for no reason.
- **Making `Action.application_driver_version_id` nullable instead of cascading.**
  Rejected: an action is meaningless outside a driver version; a nullable FK would
  model a state that must never exist.
- **Sequence numbering (`1.2.3 #2`) instead of a fingerprint suffix.** Rejected:
  recomputed across siblings, so it changes if rows are ever pruned — not stable.
- **Automatic GC of unreferenced rows.** Rejected for v1: the correctness rule is
  subtle and getting it wrong is unrecoverable.
