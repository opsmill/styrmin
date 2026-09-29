# Driver iteration — the no-bump loop

**Status**: shipped in feature 013 (`specs/archive/013-driver-fingerprint/spec.md`).
Design rationale: [ADR-053](../adr/0053-driver-version-provenance-fingerprint.md).

Iterating on an application driver no longer requires bumping the
`spec.version` field in `driver.styrmin.yml`. Reload the driver as often
as you like; Styrmin uses a **provenance fingerprint** to decide whether
the new bytes are the same driver version it already knows or a new
revision worth recording.

See [`CONTEXT.md`](../../CONTEXT.md) for the canonical glossary entry
("Provenance fingerprint") and the related "Driver version" definition.

## tl;dr

- Edit `driver.styrmin.yml`, the values template, or `actions.py`,
  re-run `styrminctl drivers load-local-version <path>`, and Styrmin
  records a new `ApplicationDriverVersion` row.
- Re-run the same command on **unchanged** files and nothing happens —
  the load is idempotent.
- Every label that mentions a driver version now reads
  `<version>@<short-fingerprint>` (the first 7 hex chars of either the
  content hash or the resolved git commit SHA).

## How identity works

An `ApplicationDriverVersion` row is identified by the tuple:

```
(application_driver_id, source_type, source_repository, source_branch,
 source_path, version, content_hash, source_commit_sha)
```

Exactly one of `content_hash` / `source_commit_sha` is non-null per row,
and the discriminator is `source_type`:

| `source_type` | Fingerprint column | Computed from |
|---------------|--------------------|---------------|
| `"local"` | `content_hash` | SHA-256 of the canonical concatenation of the three hashed files (see below). |
| `"git"` | `source_commit_sha` | The HEAD commit SHA of the cloned working tree, resolved by `dulwich`. |

A reload that matches every column of the identity tuple is a no-op
(the existing row is returned). A reload that differs in any column —
including the fingerprint — creates a new row.

The tuple is also enforced as a `UNIQUE` composite index in Postgres,
using `IS NOT DISTINCT FROM` nullability semantics so that the two
fingerprint columns can each be NULL on the "other" source type without
breaking uniqueness. See `backend/styrmin_backend/db/models.py`
(`ApplicationDriverVersion.__table_args__`) for the live definition.

## What the platform considers "different content"

For local drivers, three files contribute to the content hash:

1. `driver.styrmin.yml` — the driver spec.
2. The values template referenced by `spec.helm.main.values_template`
   (e.g. `values.j2.yml`).
3. `actions.py`, **only when** `spec.actions` is non-empty. When the
   spec declares no actions, the file is omitted from the hash even if
   it exists on disk.

The three byte streams are length-framed (`<u32 LE length><bytes>`)
before concatenation, so a byte that moves between files cannot collide
across boundaries. The helper lives in
`backend/styrmin_backend/services/driver/hash.py` and is exercised by
`backend/tests/unit/services/driver/test_hash.py`.

## What it does **not** track

Anything outside the three hashed files is invisible to the fingerprint:

- `README.md`, screenshots, license files, examples
- Build artefacts, lockfiles, `.gitignore`
- Anything in a sub-directory the spec doesn't reference

Editing those files and reloading is a no-op — the row count stays the
same. Conversely, editing a comment in `driver.styrmin.yml` does
produce a new row because every byte of those three files counts.

## Git-sourced drivers

For `source_type = "git"`, Styrmin clones the requested
`(repository, branch)` into a tempdir and asks `dulwich` for the HEAD
commit SHA. That SHA is the fingerprint — the bytes of the working tree
are not re-hashed. Two implications:

- Re-running `drivers load-version` on the same commit is a no-op.
- A new commit pushed to the same branch produces a new row on the next
  load, even if the diff is whitespace-only.

The provider lives in
`backend/styrmin_backend/services/driver/provider.py`
(`GitDriverProvider.get_resolved_commit_sha`). Unit coverage:
`backend/tests/unit/services/driver/test_provider_commit_sha.py`.

The SHA is also what the driver's actions run: each action's Prefect
deployment pins `commit_sha` to the row's `source_commit_sha`, and its name
carries the short fingerprint (`User Action: <name>@<short>`) so a reload at
a newer commit registers alongside the earlier version. A push to the branch
never changes what an existing deployment runs — load the new commit and
upgrade the deployment to move it. Rows loaded before this shipped keep
following the branch tip until a new commit is loaded.

## Row accumulation

Loads create rows; nothing removes them. Two consequences worth
internalising while iterating:

- The driver list will accumulate rows over a long iteration session.
  This is intentional — every row is an addressable identity that an
  existing deployment might be pinned to, so they cannot be silently
  garbage-collected.
- A future `styrminctl drivers prune` command will let operators
  collapse rows that no deployment references. Until that ships, drop
  the dev database (or delete rows manually through the GraphQL API) to
  reset.

If you're iterating against a fresh local dev stack, the simplest reset
is to recreate it — Styrmin runs `metadata.create_all()` on startup, so
a fresh DB just gets the new schema directly.

## What you'll see in the UI / CLI / SDK

Every surface that renders a driver version now uses the
`format_driver_version_label` helper:

- Backend / SDK / CLI: `backend/styrmin_backend/services/driver/labels.py`
- Frontend: `frontend/src/lib/driverVersion.ts`

Both return `<version>@<short>` (7-character fingerprint) when the row
has a fingerprint, and the bare `version` string as a legacy fallback
when both fingerprint columns are NULL. Detail surfaces show the full
64-hex content hash or the full 40-char commit SHA next to a
copy-to-clipboard control.

Example CLI output after two reloads with one edit between them:

```text
Application driver version '1.0.0@a1b2c3d' loaded (id: 1)
  Content hash: a1b2c3d4e5f6...                       # full 64 chars
  ...
Application driver version '1.0.0@e9f0a1b' loaded (id: 2)
  Content hash: e9f0a1b2c3d4...                       # full 64 chars
```

## Migration / backfill

Both fingerprint columns are nullable, so no backfill is required.

The schema is versioned with **Alembic** — every model change ships a
revision in `backend/styrmin_backend/db/migrations/versions/`, applied
via `styrmin db migrate` (see
[ADR-001](../adr/0001-alembic-database-migrations.md) and
[`dev/guides/database-migrations.md`](database-migrations.md)).
`metadata.create_all()` only builds a *fresh* database at startup and in
test fixtures; it never evolves an existing one, so a green test suite is
not evidence that a revision is unnecessary.

Legacy rows in pre-013 dev databases keep `content_hash = NULL` /
`source_commit_sha = NULL` and fall through to the legacy label (bare
`version`); reloading any such driver produces a new row with the
fingerprint populated. Operators who want clean labels everywhere should
reload each driver once.

## Related work

- ADR: [`0053-driver-version-provenance-fingerprint.md`](../adr/0053-driver-version-provenance-fingerprint.md)
- Spec: [`specs/archive/013-driver-fingerprint/spec.md`](../../specs/archive/013-driver-fingerprint/spec.md)
- Issue: [opsmill/styrmin#262](https://github.com/opsmill/styrmin/issues/262)
- Glossary: [`CONTEXT.md`](../../CONTEXT.md) — "Provenance fingerprint"
- Future: `styrminctl drivers prune` (planned)
