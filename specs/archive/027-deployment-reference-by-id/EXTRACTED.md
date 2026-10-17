# Extraction Record

**Extracted on**: 2026-10-17
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. [ADR-075](../../../dev/adr/0075-deployment-references-stored-by-id.md) was written during
the implementation and records R-001 to R-010 and R-014. Its links now point to this archive
directory.

## Knowledge Updated

- `dev/knowledge/backend/api.md` (Deployment references in config inputs)
- `dev/knowledge/backend/backup-restore.md` (Affinity terms in a clone: link to research R-008
  points to this archive directory)

Written during the implementation, not changed here: `dev/knowledge/backend/services.md`,
`dev/knowledge/backend/data-models.md`, `dev/knowledge/backend/backup-restore.md`,
`CONTEXT.md` and `dev/guides/pod-scheduling.md`.

## Guidelines Updated

- `dev/guidelines/backend/python.md` (Validate before any step that starts a flow run: a service
  that commits in phases runs every check before its first commit)
- `dev/guidelines/backend/python.md` (Set the row id before the INSERT when a unique name is built
  from it: choose the ids first when configs name records created in the same operation)
- `dev/guidelines/backend/python.md` (Store a reference to another record by its id; look up a
  name only during the write: new)
- `dev/guidelines/backend/python.md` (Normalize a stored JSON config by walking the dict, not by a
  model round-trip: new)
- `dev/guidelines/backend/python.md` (Per-target failure isolation in fanout writes: the
  environment restore's redeploy loop follows the rule)

## Archive

Spec directory moved to `specs/archive/027-deployment-reference-by-id/` as a historical record.
