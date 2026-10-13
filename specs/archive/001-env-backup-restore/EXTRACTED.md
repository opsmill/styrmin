# Extraction Record

**Extracted on**: 2026-10-13
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. [ADR-055](../../../dev/adr/0055-environment-backup-parent-records.md) was written during
implementation and already records research.md D1–D7.

## ADRs Amended

- [dev/adr/0055-environment-backup-parent-records.md](../../../dev/adr/0055-environment-backup-parent-records.md)
  - Status: narrowed by ADR-056.
  - New dated note: ADR-056 added an `IN_USE` refusal when deleting a snapshot, and a third (clone) case to the environment-level guard.
  - Alternatives, "Restores first, config afterwards": dated amendment saying that `redeploy_for_environment_update` now skips `RESTORING` deployments, and why the step-4 exclusion is still needed.
  - `Source` points at `specs/archive/001-env-backup-restore/`.

## Knowledge Updated

- `dev/knowledge/backend/backup-restore.md`
  - Environment Operations table
  - Data models: `DeploymentSnapshot` fields, FK columns without an index
  - Eligibility: corrected the ingress-controller statement
  - Concurrency guard
  - Fan-out
  - Restore ordering
  - Skip classification
  - Derived status
  - Cascade delete
  - Typed errors
- `dev/knowledge/backend/api.md` (Queries, Mutations, Enums: environment backup and restore operations)
- `dev/knowledge/backend/services.md` (directory tree, UnitOfWork interface, exception tree)
- `dev/knowledge/backend/e2e-testing.md` (`api_only` audit discipline: environment backup methods, location of the driver conformance test)
- `dev/knowledge/frontend/environment-backups.md` (new file: Backups tab)
- `CONTEXT.md` (Environment backup: deletion refused with `IN_USE` during a clone's capture)

## Guidelines Updated

- `dev/guidelines/backend/python.md`
  - Calculate a status that several writers change; do not store it: commit the parent row with its child rows
  - Join the caller's transaction when you reuse a service that commits
  - Set the row id before the INSERT when a unique name is built from it
  - Declare a mirror enum class for each GraphQL enum
  - Testing: put a test that needs no cluster under `tests/unit/`
- `dev/guidelines/cyclopts.md` (Exit 1 when an operation ends `PARTIAL`, not only when it ends `FAILED`)
- `dev/guides/pre-commit-hooks.md` (Troubleshooting: stage regenerated types before `invoke lint`)

## Other Changes

- `docs/docs/concepts-and-architecture/backups-and-restores.md`: deleting an environment backup is refused while a clone captures it; an environment has its own ingress controller only when `dedicated_ingress` is set.

## Already Documented Before Extraction

The implementation change itself wrote these, so the extraction did not repeat them:

- ADR-055
- `dev/knowledge/backend/backup-restore.md` ("Environment-Level Backup & Restore")
- `CONTEXT.md` (Environment backup, Environment restore)
- `docs/docs/concepts-and-architecture/backups-and-restores.md`, `docs/docs/reference/styrminctl.md`, `cli/README.md`

## spec.md Changes at Extraction

- `**Status**` set to `Extracted`.

## Archive

Spec directory moved to `specs/archive/001-env-backup-restore/` as a historical record.
