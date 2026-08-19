# Data Model: Environment Clone

**Feature**: 010-environment-clone | **Date**: 2026-08-19

One new table, one Alembic revision (ADR-001). No changes to existing tables' columns;
`delete_environment_backup` and `create_restore` gain behaviour, not schema.

## New table: `EnvironmentClone`

Follows `StyrminModel` (`id: UUID` pk, `created_on`, `updated_on`).

| Field | Type | Constraints | Meaning |
|---|---|---|---|
| `name` | `str` | non-null | The requested target environment name (also the created environment's name once it exists). Not unique on this table — a failed clone must not block re-cloning under the same name (SC-005); uniqueness of the *environment* name stays on `Environment(name, cluster_id)`. |
| `source_environment_id` | `UUID` | FK → `environment.id`, non-null | The environment that was cloned. Environment deletion cascades its clones-as-source records the same way it cascades its environment backups (a clone record is meaningless without its source row; see Deletion semantics). |
| `environment_backup_id` | `UUID \| None` | FK → `environmentbackup.id`, nullable | The capture the clone is built from. Set in the same transaction that creates the capture; null only if registration itself failed. |
| `created_environment_id` | `UUID \| None` | FK → `environment.id`, nullable, `ON DELETE SET NULL` | The environment the clone created. Null until the capture succeeds and the environment materialises; reset to null when the created environment is deleted (which drives the clone terminal — D9). |
| `requested_deployment_ids` | `list \| None` | JSON, nullable | The explicit selection, verbatim; null = all eligible. Persisted for auditability of FR-003. |
| `config_override` | `dict \| None` | JSON, nullable | The override supplied at clone time (canonicalised `UpdateEnvironmentInput` dict), before merging. Persisted so the merge is reproducible/inspectable (FR-006). |
| `deployment_results` | `list \| None` | JSON, nullable | Per-source-deployment attribution list (see below). Written by the mutation (skips known upfront) and updated by the clone flow as steps land. |
| `clone_errors` | `list \| None` | JSON, nullable | Operation-level errors that occurred outside any single deployment (capture failed, name lost in the TOCTOU window, environment creation failed). Each entry: `{"step": str, "error": str}`. |
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

Derivation (first match wins):

1. `environment_backup_id` is null **or** capture derived status = `FAILED` → **FAILED**
   (FR-002: nothing materialised).
2. `clone_errors` contains an operation-level error and no counterpart work is in
   flight → **FAILED** (e.g. name lost to TOCTOU, environment creation failed).
3. Capture derived status = `PENDING` and nothing else has happened → **PENDING**.
4. Capture non-terminal, or `created_environment_id` null, or any `deployment_results`
   entry `pending`, or any referenced `Restore` row non-terminal → **IN_PROGRESS**.
   Exception: `created_environment_id` null because it was **reset** (created
   environment deleted mid-flight) → **FAILED** (terminal; releases the D9 guard).
5. All steps landed: every entry `cloned` (with its restore `COMPLETED`) or `skipped`
   → **COMPLETED** (skips are not failures — FR-004; an all-skipped clone of an
   empty-but-valid selection is `COMPLETED`, matching `derive([], 0) == COMPLETED`).
6. Mixed `cloned`/`failed` (or a `cloned` entry whose restore ended
   `FAILED`/`PARTIAL`) → **PARTIAL**.
7. Every included entry `failed` → **FAILED**.

Terminal set: `{COMPLETED, PARTIAL, FAILED}` (mirrors
`TERMINAL_ENVIRONMENT_OPERATION_STATUSES`).

Coverage identity (tested, like ADR-055's count identity): for a terminal clone,
`len(deployment_results) == number of source deployments considered` and no entry is
`pending`.

## Changed behaviour on existing entities (no schema change)

- **`Backup` / `EnvironmentBackup`**: unchanged. A clone's capture is an ordinary
  `EnvironmentBackup` (auto-named, listable, TTL-governed). Its deletion gains the D9
  guard: non-terminal referencing clone → `EnvironmentBackupInUseByCloneError`
  (`IN_USE`).
- **`Restore`**: unchanged schema. Cross-target restores set `target_namespace` to
  the counterpart's namespace and `target_instance_id` to the counterpart's active
  instance (the dormant field becomes load-bearing); `create_restore` gains
  `target_deployment_id` and applies its guards/`RESTORING` flip to the target.
- **`Environment`**: the created environment is an ordinary row (FK'd by
  `created_environment_id`); capabilities recomputed at creation (ADR-027), config =
  merge(captured, override) (D7).
- **`Deployment`**: counterparts are ordinary rows created via `deploy_application`
  with a pinned `application_driver_version_id`; initial reconcile deferred (D5).

## Deletion semantics

- **Delete created environment** → ordinary `delete_environment`;
  `created_environment_id` set null → clone derives `FAILED`/stays terminal; the
  clone *record* survives as history on the source.
- **Delete source environment** → cascades environment backups (existing) and this
  feature extends the cascade to the source's clone records
  (`source_environment_id` is non-nullable, same reasoning as the
  `environmentbackup.environment_id` cascade). The *created* environments survive —
  they are ordinary independent environments.
- **Delete backing environment backup** → allowed unless a referencing clone is
  non-terminal (D9). After clone terminality the capture is deletable as usual; the
  clone record keeps a dangling-by-design `environment_backup_id`? No — deletion of
  the parent cascades hard today. The clone's FK is nullable: the cascade in
  `delete_environment_backup` nulls `environment_backup_id` on **terminal** clones
  rather than deleting the clone record (clone history outlives its scaffolding).
- **Delete clone record** itself: not exposed in v1 (no mutation); records are
  history, removed only via the source-environment cascade.

## Alembic revision

One revision (after current head `c1d2e3f4a5b6`): create `environmentclone` with the
fields above; named FK constraints inside `op.batch_alter_table`-compatible DDL for
SQLite parity, per `dev/guides/database-migrations.md`. No new PG enum types (status
is derived, never stored).
