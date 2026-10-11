# Extraction Record

**Extracted on**: 2026-10-10
**Extracted by**: speckit.opsmill.extract

## ADRs Created

- [dev/adr/0062-backup-history-derived-through-instances.md](../../../dev/adr/0062-backup-history-derived-through-instances.md) (from R1, R3, R4, R5, R6 and commit `d81320c2`)
- [dev/adr/0063-restore-of-earlier-instance-backup.md](../../../dev/adr/0063-restore-of-earlier-instance-backup.md) (from spec.md Assumptions and FR-008, and commits `d81320c2`, `1d8b0c3b`, `68da40c8`)

## Knowledge Updated

- `dev/knowledge/backend/api.md` (Queries table, `backups` row)
- `dev/knowledge/backend/backup-restore.md` (Service Functions → `get_backups` row: missing index on `applicationinstance.deployment_id`)
- `dev/knowledge/backend/backup-restore.md` (Restore Lifecycle → new "Restoring a backup of an earlier instance")
- `dev/knowledge/backend/e2e-testing.md` (Ref type surface → `BackupRef`; `api_only` audit discipline → `list_backups`)

## Guidelines Updated

- `dev/guidelines/cyclopts.md` (new "Confirm before acting on a target the operator did not name")
- `dev/guidelines/backend/python.md` (Repository Pattern → new "Break timestamp ties by id when a client picks "the latest"")
- `dev/guides/graphql-propagation-tests.md` (Common mistakes → asserting only `VALIDATION_ERROR`)

## Already Documented Before Extraction

The implementation change itself updated these, so the extraction did not repeat them:

- `CONTEXT.md` (Backup history)
- `dev/knowledge/backend/backup-restore.md` (`get_backups` row, `backups(...)` signature, refusal of a restore into a tombstoned deployment)
- `docs/docs/concepts-and-architecture/backups-and-restores.md`, `docs/docs/reference/styrminctl.md`, `cli/README.md`

## spec.md Changes at Extraction

- `**Status**` set to `Extracted`.
- A note under FR-008 records that the review round superseded "no check and no confirmation" (ADR-063). The Edge Cases and Out of Scope sections still state the original decision.

## Archive

Spec directory moved to `specs/archive/011-deployment-backup-history/` as a historical record.
