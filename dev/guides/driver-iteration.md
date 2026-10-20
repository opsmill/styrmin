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
- Re-run the same command on **unchanged** files and Styrmin returns the
  existing row instead of creating a new one. The one write it can make
  to the row: a row stored before Styrmin kept the driver's logo,
  description and links (`spec.info`, spec `020-driver-info-display`)
  gets those three values from the file. The load also registers in
  Prefect the declared actions that hooks cannot resolve.
  See [How identity works](#how-identity-works).
- After editing `actions.py` on the dev stack, load the driver again and
  use the new driver version. No `docker compose build` is needed. See
  [Iterating on the actions of a local driver](#iterating-on-the-actions-of-a-local-driver).
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

A reload that matches every column of the identity tuple returns the
existing row. A reload that differs in any column — including the
fingerprint — creates a new row.

Before it returns the existing row, the load compares the `icon`,
`description` and `links` it parsed from `spec.info` with the stored
values. When any of them differs, it writes all three and commits; no
other column changes. Because the identity tuple pins the file content,
this changes only rows stored before these columns existed (spec
`020-driver-info-display`, research R5).

Before it returns the existing row, the load also registers the declared
actions that hooks cannot resolve (spec `029-local-driver-actions`,
FR-006): `ensure_action_registrations` looks up each declared hook and
mode with the lookup that hooks use, and registers the actions of each
pair that has no registered flow, for example after their Prefect
deployments were deleted. A pair that the lookup finds is left as it is,
so a repeated load of a driver whose actions are all registered makes no
Prefect write. See `load_application_driver_from_object` in
`backend/styrmin_backend/services/applications.py` and
[ADR-081](../adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md).

The tuple is also enforced as a `UNIQUE` composite index in Postgres,
using `IS NOT DISTINCT FROM` nullability semantics so that the two
fingerprint columns can each be NULL on the "other" source type without
breaking uniqueness. See `backend/styrmin_backend/db/models.py`
(`ApplicationDriverVersion.__table_args__`) for the live definition.

## What the platform considers "different content"

For local drivers, three files contribute to the content hash:

1. `driver.styrmin.yml` — the driver spec.
2. The values template, whose file name comes from the server setting
   `STYRMIN_DRIVER_VALUES_TEMPLATE` (default `values.j2.yml`). A missing
   values template is hashed as empty bytes.
3. `actions.py`, **only when** `spec.actions` is non-empty. When the
   spec declares no actions, the file is omitted from the hash even if
   it exists on disk.

Each part is framed as its name (`driver.styrmin.yml`,
`values_template` or `actions.py`), a zero byte, and the length of its
bytes as an 8-byte big-endian integer, followed by the bytes. The framed
parts are concatenated and hashed with SHA-256, so a byte that moves
between files cannot give the same hash. The helpers live in
`backend/styrmin_backend/services/driver/hash.py`
(`compute_driver_content_hash`, and `compute_driver_directory_fingerprint`,
which reads the files of a driver directory) and are exercised by
`backend/tests/unit/services/driver/test_hash.py`. The loader and the
check that runs before each action of a local driver version both call
`compute_driver_directory_fingerprint`.

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

- Re-running `drivers load-version` on the same commit returns the
  existing row (see [How identity works](#how-identity-works) for the
  one write it can make).
- A new commit pushed to the same branch produces a new row on the next
  load, even if the diff is whitespace-only.

The provider lives in
`backend/styrmin_backend/services/driver/provider.py`
(`GitDriverProvider.get_resolved_commit_sha`). Unit coverage:
`backend/tests/unit/services/driver/test_provider_commit_sha.py`.

The SHA is also what the driver's actions run: each action's Prefect
deployment pins `commit_sha` to the row's `source_commit_sha`, and its name
carries the driver and the short fingerprint
(`User Action: <name> (<driver>@<short>)`) so a reload at a newer commit, or
another driver declaring the same action, registers alongside it. A push to the branch
never changes what an existing deployment runs — load the new commit and
upgrade the deployment to move it. Rows loaded before this shipped keep
following the branch tip until a new commit is loaded.

## Iterating on the actions of a local driver

Each action of a local driver version runs the `actions.py` at the
driver version's path (`source_path`), in the Styrmin agent, after a
check that the files at that path have the driver version's
`content_hash`
([ADR-081](../adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md)).
The agent runs each action as a process in its own container, with a
Prefect `ProcessWorker` (`backend/styrmin_backend/entrypoint/combined.py`),
so it reads the driver from its own file system at the same path as the
server.

On the dev stack (`docker compose up`, which `uv run invoke dev` runs),
the `server` and `agent-operator` services of `docker-compose.yml` both
bind-mount `./driver/examples` at `/styrmin/drivers` (read-only) and
`./backend` at `/source/backend`. After you edit an action:

1. Load the driver again, for example
   `uv run styrminctl drivers load-local-version /styrmin/drivers/my-app`.
   The edit changes the fingerprint, so the load creates a new driver
   version and registers its actions.
2. Create or upgrade a deployment with the new driver version.

You do not need `docker compose build`: the agent reads the edited file
through the bind mount. A driver version loaded before the edit fails
the check when one of its actions runs, because the files at its path
are no longer its files. Its hook step shows the fingerprint error ("The
driver files at … are not the files of this driver version").

A driver at a path that only the `server` service mounts is not in the
agent container, and its actions fail with the missing-files error ("The
driver files are not at …"). Mount such a driver at the same path into
both services.

On the local demo and in any other Helm install, the server and the
agent read the driver from their image. After an edit, rebuild the
image, roll out the server and the agent, then load the driver again.

The errors name the host where the action ran: "the Styrmin agent pod
<host name>". On the dev stack, that host name is the container id of
the `agent-operator` container, which `docker ps` lists. An action's
`image:` has no effect today.

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
