# Data Model: Environment Clone

**Feature**: 010-environment-clone | **Date**: 2026-08-19

One new table, one Alembic revision (ADR-001). No changes to existing tables' columns;
`delete_environment_backup` and `create_restore` gain behaviour, not schema.

## New table: `EnvironmentClone`

Follows `StyrminModel` (`id: UUID` pk, `created_on`, `updated_on`).

| Field | Type | Constraints | Meaning |
|---|---|---|---|
| `name` | `str` | non-null | The requested target environment name (also the created environment's name once it exists). Not unique on this table — a failed clone must not block re-cloning under the same name (SC-005); uniqueness of the *environment* name stays on `Environment(name, cluster_id)`. |
| `source_environment_id` | `UUID \| None` | FK → `environment.id`, nullable | The environment that was cloned. Nullable so provenance survives source deletion: deleting the source nulls this on **terminal** clones (the record lives on as the created environment's provenance) and deletes **non-terminal** clone records outright (see Deletion semantics). |
| `source_environment_name` | `str` | non-null | The source's name at clone time, denormalised so provenance stays readable after the source is gone. |
| `environment_backup_id` | `UUID \| None` | FK → `environmentbackup.id`, nullable | The capture the clone is built from. Set in the same transaction that creates the capture; null only if registration itself failed. |
| `created_environment_id` | `UUID \| None` | FK → `environment.id`, nullable, `ON DELETE SET NULL` | The environment the clone created. Null until the capture succeeds and the environment materialises; reset to null when the created environment is deleted (which drives the clone terminal — D9). |
| `requested_deployment_ids` | `list \| None` | JSON, nullable | The explicit selection, verbatim; null = all eligible. Persisted for auditability of FR-003. |
| `config_override` | `dict \| None` | JSON, nullable | The override supplied at clone time (canonicalised `UpdateEnvironmentInput` dict), before merging. Persisted so the merge is reproducible/inspectable (FR-006). |
| `cleared_config_fields` | `list \| None` | JSON, nullable | The `clearConfigFields` names supplied at clone time (research D7); popped from the captured config before the override merge. |
| `deployment_results` | `list \| None` | JSON, nullable | Per-source-deployment attribution list (see below). Written by the mutation (skips known upfront) and updated by the clone flow as steps land. |
| `clone_errors` | `list \| None` | JSON, nullable | Operation-level events that occurred outside any single deployment (capture failed, name lost in the TOCTOU window, environment creation failed, scaffolding deleted). Each entry: `{"step": str, "error": str, "fatal": bool}` — `fatal: true` drives the derivation to `FAILED`; deletions that touch an already-terminal clone are recorded with `fatal: false` so history is kept without rewriting the outcome. |
| `created_by_user_id` | `UUID \| None` | FK → `user.id`, nullable | Who invoked the clone (matches `Deployment.created_by_user_id` convention). |

**Deliberately no status column** (FR-009, ADR-055 decision 2 — the docstring states
it, like `EnvironmentBackup`'s does).

### `deployment_results` entry shape

One entry per source deployment considered (SC-003: 100% accounted for):

```json
{
  "deployment_id": "<source deployment UUID>",
  "deployment_name": "postgres-main",
  "outcome": "cloned | skipped | failed | pending",
  "reason": "<free text; required for skipped/failed, null otherwise>",
  "counterpart_deployment_id": "<UUID | null>",
  "restore_id": "<UUID | null>"
}
```

- `outcome` values on the wire are free strings inside JSON (like
  `SkippedConstituent.reason` — ADR-055 decision 4: open vocabulary, zero silent
  skips), but the service writes only the four above.
- `pending` is the transient value between registration and the step landing; a
  terminal clone contains no `pending` entries (that is part of the derivation, below).
- `reason` examples: `"deployment has no active instance"` (skip),
  `"captured driver version no longer exists"` (failed),
  `"constituent backup failed at capture"` (failed).

## Derived status

`EnvironmentCloneStatus`: `PENDING / IN_PROGRESS / COMPLETED / PARTIAL / FAILED` —
same vocabulary as `EnvironmentOperationStatus` (`services/backup/environment.py:71-81`),
new pure function `derive_environment_clone_status(...)` because the inputs are
heterogeneous (capture status + environment existence + restore rows + results),
unlike the homogeneous child list `derive_environment_operation_status` folds.

Inputs: the backing environment backup's **derived** status (or absence),
`created_environment_id`, the constituent `Restore` rows reachable via
`deployment_results[].restore_id`, `deployment_results`, `clone_errors`.

Two resolution rules applied before deriving:

- **A missing derivation input is never re-interpreted.** A nulled
  `environment_backup_id` on a clone that already recorded counterpart work means the
  backup was cleaned up later, not that the clone failed; a `deployment_results`
  entry whose `restore_id` no longer resolves to a `Restore` row (cascade-deleted
  with the backup) keeps its **recorded outcome as final**. History is only rewritten
  through `clone_errors`, which every deletion path writes explicitly (research D9).
- **Every fatal event is an explicit `clone_errors` entry** written in the same
  transaction as the event: capture wholly failed, target name lost to TOCTOU,
  environment creation failed, backing backup deleted mid-clone
  (`environment_backup_deleted`), created environment deleted
  (`created_environment_deleted`). The bare `ON DELETE SET NULL` on
  `created_environment_id` is belt-and-braces only — the app-level cascade writes the
  marker the derivation keys on (a bare NULL is not computably distinguishable from
  "not yet created").

Derivation (first match wins):

1. `clone_errors` contains a **fatal** entry → **FAILED** (terminal; releases the D9
   guard). Per-deployment failures are not fatal entries — they live in
   `deployment_results`.
2. Capture in flight (`environment_backup_id` set, derived capture status `PENDING`)
   and nothing else recorded → **PENDING**.
3. Capture non-terminal (`IN_PROGRESS`), or capture terminal-restorable but
   `created_environment_id` still null with no fatal error (materialisation pending —
   this includes the dead-flow case, which stays `IN_PROGRESS` until an operator uses
   an escape hatch, research D9), or any `deployment_results` entry `pending`, or any
   **resolvable** referenced `Restore` row non-terminal → **IN_PROGRESS**.
4. All steps landed: every entry `cloned` (with its restore's final status
   `COMPLETED`) or `skipped` → **COMPLETED** (skips are not failures — FR-004; an
   all-skipped clone of an empty-but-valid selection is `COMPLETED`, matching
   `derive([], 0) == COMPLETED`).
5. Mixed outcomes — any `failed` entry, or a `cloned` entry whose restore ended
   `FAILED`/`PARTIAL`, alongside at least one success → **PARTIAL**. (A capture that
   ended `PARTIAL` feeds this rule: constituents that failed at capture are recorded
   as `failed` entries — FR-002.)
6. Every included entry `failed` → **FAILED**.

Terminal set: `{COMPLETED, PARTIAL, FAILED}` (mirrors
`TERMINAL_ENVIRONMENT_OPERATION_STATUSES`). Note for the D8/D9 guards: clone
terminality is **not expressible as a SQL EXISTS** (it folds capture status, restore
rows reachable only via JSON ids, and error entries) — guards load the candidate
clone rows and derive in Python; the candidate sets are tiny (clones of one
environment).

Coverage identity (tested, like ADR-055's count identity): for a terminal clone,
`len(deployment_results) == number of source deployments considered` and no entry is
`pending`.

## Changed behaviour on existing entities (no schema change)

- **`Backup` / `EnvironmentBackup`**: no column changes. A clone's capture is an
  ordinary `EnvironmentBackup` (auto-named, listable, TTL-governed). Its deletion
  gains the D9 guard, scoped to the capture window: a referencing clone whose
  *capture* is still non-terminal → `EnvironmentBackupInUseByCloneError` (`IN_USE`);
  afterwards deletion proceeds and updates referencing clones (research D9). The
  `DeploymentSnapshot` JSON shape gains `service_name_overrides: dict[str, str] |
  None` (additive; pre-existing snapshots read as `None` → driver-default names) so
  counterparts can reproduce overridden service names without re-reading the live
  source (FR-005 ∧ FR-007).
- **`Restore`**: unchanged schema. Cross-target restores set `target_namespace` to
  the counterpart's namespace and `target_instance_id` to the counterpart's active
  instance (the dormant field becomes load-bearing); `create_restore` gains
  `target_deployment_id` and applies its guards/`RESTORING` flip to the target.
- **`Environment`**: the created environment is an ordinary row (FK'd by
  `created_environment_id`); capabilities recomputed at creation (ADR-027), config =
  merge(captured, override) (D7).
- **`Deployment`**: counterparts are ordinary rows created via `deploy_application`
  (which gains `skip_initial_reconcile` — research D5) with a pinned
  `application_driver_version_id`, created in the `RESTORING` state so the existing
  restoring-deployment mutation guards protect them until their restore lands;
  `redeploy_for_environment_update` learns to skip `RESTORING` deployments (D8).

## Deletion semantics

All cascades are **app-level** (they must write derivation inputs in the same
transaction — see the resolution rules above); the DB-level `ON DELETE SET NULL` on
`created_environment_id` is a backstop only.

- **Delete created environment** → ordinary `delete_environment`, always allowed (the
  discard path). Clone-aware: nulls `created_environment_id` **and** appends the
  `clone_errors` entry `created_environment_deleted` → on a non-terminal clone the
  entry is `fatal: true` and the clone derives `FAILED`; on an already-terminal clone
  it is recorded `fatal: false` and the outcome stands. The clone *record* survives
  as history.
- **Delete source environment** → handles the source's clone records **before**
  cascading its environment backups, so the D9 guard cannot wedge the deletion:
  terminal clones survive with `source_environment_id` nulled (provenance for the
  created environment outlives the source; `source_environment_name` keeps it
  readable); non-terminal clones are deleted outright and the clone flow tolerates
  its row vanishing (mirrors `RestoreNotFoundError` handling in the restore flow).
  Then backups cascade as today. Created environments survive — they are ordinary
  independent environments.
- **Delete backing environment backup** → refused (`IN_USE`) only while a referencing
  clone's **capture** is in flight. Otherwise allowed: nulls `environment_backup_id`
  on referencing clones; on a **non-terminal** clone it also appends the fatal
  `environment_backup_deleted` entry (→ `FAILED`, the escape hatch for a stuck
  clone); on a **terminal** clone the outcome stands (routine TTL cleanup must not
  rewrite history). Constituent `Restore` rows cascade away with the backup as today
  — the clone's `deployment_results` outcomes remain final (resolution rule above).
- **Delete clone record** itself: not exposed in v1 (no mutation); records are
  history, removed only via the source-environment cascade for non-terminal clones.

## Alembic revision

One revision (after current head `c1d2e3f4a5b6`): create `environmentclone` with the
fields above; named FK constraints inside `op.batch_alter_table`-compatible DDL for
SQLite parity, per `dev/guides/database-migrations.md`. No new PG enum types (status
is derived, never stored).
