# Extraction Record

**Extracted on**: 2026-08-04
**Extracted by**: speckit.opsmill.extract

## ADRs Created

- `dev/adr/0053-driver-version-provenance-fingerprint.md` (from D-001 – D-007)

## Knowledge Updated

None new — the knowledge tree was already current for this feature:
`dev/knowledge/backend/services.md` (identity-aware loading, `get_by_identity`),
`dev/knowledge/backend/data-models.md`, `dev/guides/driver-iteration.md`, and the
`CONTEXT.md` "Provenance fingerprint" entry all describe the shipped behaviour.

## Guidelines Updated

None.

## Also updated

- `dev/guides/driver-iteration.md` — repointed the two spec links into the archive and
  added the ADR-053 cross-reference

## Two research decisions recorded as superseded, not extracted

**D-008 ("no migration; `metadata.create_all()` will add the columns") was wrong.** The
premise — no production deployments, so nullable columns need no revision — ignores that
`create_all()` only builds a *fresh* database. Every already-existing database was left
without `content_hash`, `source_commit_sha`, `container_overrides`, or the
`uq_application_driver_version_identity` index. Revision
`a8b9c0d1e2f3_add_driver_fingerprint_and_container_overrides` backfills all four and had
to double as a **merge revision**, because by the time the omission surfaced two other
revisions had branched from the same parent and left the chain with two heads — making
`styrmin db init` / `db migrate` fail outright. ADR-053 records this as a consequence and
restates that [ADR-001](../../../dev/adr/0001-alembic-database-migrations.md) is not
waivable by "we have no production yet"; a green test suite proves nothing, because tests
build their schema with `create_all()`.

**D-006's "no NULL-fingerprint display fallback" also did not hold.**
`services/driver/labels.py::format_driver_version_label` falls back to the bare version
string and logs a warning, because dev databases predating the backfill contain such
rows. The warning is deliberate — on rows created by the spec-013 load path both columns
are always populated.

Also note D-004 deferred the identity unique index "to implementation discretion"; it
**was** shipped as `uq_application_driver_version_identity`.

## Follow-up left open

D-007: `styrminctl driver prune` (admin-driven deletion of unreferenced
`ApplicationDriverVersion` rows). The cascade added by D-005 is what will make it clean.

## Archive

Spec directory moved to `specs/archive/013-driver-fingerprint/` as a historical record.
