# Extraction Record

**Extracted on**: 2026-08-04
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. The design is almost entirely an *application* of decisions already recorded:
[ADR-029](../../../dev/adr/0029-config-additions-via-baseconfigsection-no-migration.md)
(policy knobs go on `BaseConfigSection`, riding existing JSON columns with no migration),
[ADR-025](../../../dev/adr/0025-capabilities-as-extensible-json-column.md)/[026](../../../dev/adr/0026-capabilities-recalculation-in-service-layer.md)/[027](../../../dev/adr/0027-environment-capabilities-computed-independently.md)
(capabilities are *derived* and recomputed, so policy must not live there), and
[ADR-014](../../../dev/adr/0014-schema-walking-input-propagation-tests.md) (the schema-walk
guard at `test_environment_update_propagation.py:507` mechanically forced the FR-005 input
field the moment `backup_ttl` landed on the shared base).

## Knowledge Updated

None new — `dev/knowledge/backend/backup-restore.md` was updated in the same change and
already carries the full picture: the `## Retention TTL (services/backup/ttl.py)` section
with its validation surface, resolution precedence, and `status.expiration` plumbing, plus
`### Retention fields on Backup`. `CONTEXT.md` has the **Backup retention TTL** entry,
explicitly distinguished from `BackupSchedule.retention_count`.

## Guidelines Updated

Two repo-wide correctness rules that this feature surfaced and that no guideline stated:

- `dev/guidelines/backend/python.md` (Database Models — **new subsection** "Plain `JSON`
  columns are not change-tracked — reassign, never mutate", from R5 / critique M2). A
  `Column(JSON)` has no `MutableDict`, so `obj.col[k] = v` is silently dropped at commit.
  Includes the merge-not-replace and `None`-handling details, the case for a typed payload
  over a bare `dict`, and the requirement to verify through a fresh session rather than
  the in-memory object.
- `dev/guidelines/backend/python.md` (Error Handling — **new subsection** "Never add new
  logic inside a swallow-and-proceed block", from the R3 caveat). The existing BSL block
  catches broadly and continues; putting TTL resolution inside it would have made a
  config-read failure an invisible fallback. Generalised to: a fallback is only acceptable
  when it is observable.

## Not extracted

R1 (field placement — ADR-029), R2 (Go-duration validation rule — recorded in
`backup-restore.md` and the model), R4 (builder pass-through), R6 (GraphQL surface),
R7 (frontend surface, including the `deployment-input.ts` / `config-diff.ts` round-trip
additions FR-005 forced), R8 (CLI surface), R9 (test mapping), R10 (documentation set),
R11 (out-of-scope confirmations).

## Follow-ups left open (from R11)

- No cluster-**update** mutation exists, so cluster-scope TTL stays set-at-create.
- `ttlSource` is not exposed in GraphQL — provenance lives in `metadata.ttl_source` and
  the workflow logs.
- No retro-patching of existing Velero backups; no per-backup or per-schedule TTL
  override; no `30d` sugar; no expired-backup drift reconciliation (documented warning
  instead, adjacent to #304).
- `BackupSchedule.retention_count` remains semantically distinct and currently unenforced.

## Also updated

- `AGENTS.md` — removed the stale speckit-injected line pointing at this spec's `plan.md`
  as "the current plan".

## Archive

Spec directory moved to `specs/archive/016-backup-retention-ttl/` as a historical record.
