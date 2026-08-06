# Data Model: Environment Clone

**Feature**: `specs/002-env-clone` | **Date**: 2026-08-06

One new table + one new nullable FK column, shipped as one Alembic revision on head `c1d2e3f4a5b6` (research.md D11). All tables extend `StyrminModel` (UUID `id`, tz-aware `created_on`/`updated_on`). Status is **never stored** (research.md D5).

## New table: `EnvironmentClone`

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| `source_environment_id` | `UUID \| None` | FK → `environment.id`, nullable, `ON DELETE SET NULL` | Source environment; survives source deletion (spec edge: source deleted mid-clone is harmless) |
| `source_environment_name` | `str` | not null | Copied at creation; attribution stays readable after source deletion |
| `environment_backup_id` | `UUID \| None` | FK → `environmentbackup.id`, nullable, `ON DELETE SET NULL` | The backing capture (FR-007); nullable so the record survives later backup deletion |
| `created_environment_id` | `UUID \| None` | FK → `environment.id`, nullable, `ON DELETE SET NULL` | The clone environment; null until created (FR-002) and after its deletion (FR-013) |
| `new_environment_name` | `str` | not null | Operator input; validated upfront (FR-012) |
| `selected_deployment_ids` | `list \| None` | JSON | Operator selection; `null` = all eligible (FR-003) |
| `environment_config_override` | `dict \| None` | JSON | Operator override, merged top-level-shallow over captured config (FR-006) |
| `deployment_results` | `list \| None` | JSON | Attribution events, one `DeploymentCloneResult` per selected snapshot (FR-010) |
| `finished_at` | `datetime \| None` | nullable | Event stamped once by the flow on exit — the terminal/non-terminal pivot for derivation |
| `created_by_user_id` | `UUID` | FK → `user.id`, not null | Caller attribution, threaded into `deploy_application` |

Relationships: `source_environment` / `created_environment` (many-to-one, both optional); `environment_backup` (many-to-one, optional); `restores` (one-to-many via new nullable FK on `Restore`).

### `DeploymentCloneResult` (service-layer Pydantic model, stored as JSON)

| Field | Type | Notes |
|---|---|---|
| `deployment_id` | UUID | Source deployment (from the snapshot) |
| `deployment_name` | str | Stable even if the source is later tombstoned |
| `counterpart_deployment_id` | UUID \| None | Set once the counterpart exists |
| `outcome` | `cloned \| skipped \| failed` | `skipped` = ineligible/backup-failed constituent carried from the capture; `failed` = counterpart creation or data restore failed |
| `reason` | str \| None | Required for `skipped`/`failed`; open text ("render it, do not switch on it") |
| `fingerprint_fallback` | bool | True when the driver version was re-resolved by name+version because the fingerprint no longer matched (research.md D3) |

## Modified table: `Restore`

| Column | Change |
|---|---|
| `environment_clone_id` | **New**, `UUID \| None`, FK → `environmentclone.id`, nullable — mirrors `environment_restore_id`. Null for standalone and environment restores. |

**Behavioural change (no schema change)**: `create_restore` resolves *two* deployments — source from `backup.instance_id` (provenance), target from `target_instance_id` (already a column, currently written but never read). The `internal` check, the `RESTORING` concurrency guard, the `deployment.status = RESTORING` flip, and the completion status update all move to the **target**; absent `target_instance_id` keeps today's in-place behaviour exactly (target = source).

## Derived status (not a column)

Pure service-layer function `derive_environment_clone_status`:

```
inputs: backup_status (derived, or MISSING if backup deleted),
        finished_at, deployment_results, linked Restore statuses

finished_at is None:
  backup_status in {PENDING}                       -> PENDING
  otherwise                                        -> IN_PROGRESS
finished_at set (results are final):
  every result outcome == cloned AND no linked
    restore FAILED                                 -> COMPLETED
  at least one cloned                              -> PARTIAL
  zero cloned                                      -> FAILED
```

- The flow appends `deployment_results` progressively and stamps `finished_at` exactly once, in a `finally` — including on flow crash paths it can still reach. A flow killed hard leaves the record `IN_PROGRESS` forever; the escape hatch is `deleteEnvironmentClone` (legal regardless of status), which also releases the FR-008 backup-deletion guard.
- Deleted linked rows degrade gracefully, ADR-0055-style: a `cloned` result whose `Restore` row was later deleted stays `cloned` (the event is the record); the count identity `len(deployment_results) == len(selected snapshots)` holds from the moment `finished_at` is stamped.

## State transitions

- `EnvironmentClone` rows are written by the flow only: `deployment_results` appended per step, `created_environment_id` set once, `finished_at` stamped once. Never updated after `finished_at`.
- Counterpart `Deployment` rows follow the ordinary lifecycle (`PENDING → DEPLOYING → RUNNING`), then `RESTORING → RUNNING` during the constituent data restore — no new states.
- The backing `EnvironmentBackup` and its constituents keep their existing lifecycles untouched.

## Validation rules (service layer)

- **Clone create (synchronous, zero side effects on failure — FR-012)**: source environment exists (`EnvironmentNotFoundError`); `new_environment_name` free in the cluster (`EnvironmentAlreadyExistsError`); every selected id is an eligible deployment of the source (`EnvironmentCloneSelectionError`, `VALIDATION_ERROR`); no environment-level operation in progress on the source (`EnvironmentOperationInProgressError`, `ALREADY_IN_PROGRESS` — research.md D4 amendment); merged config passes `validate_environment_config`.
- **Backup deletion guard (FR-008)**: `delete_environment_backup` raises `EnvironmentBackupInUseError` (`OPERATION_DENIED`) when a linked `EnvironmentClone` has `finished_at IS NULL`; the same guard surfaces through `deleteEnvironment`'s cascade on the source.
- **Clone record deletion**: legal regardless of derived status; deletes the record only — never the clone environment, the backup, or any constituent (they have their own lifecycles).
- **Eligibility**: exactly the environment-backup rule (`is_eligible_for_environment_backup`) — non-tombstoned, non-internal, active instance (FR-003).
