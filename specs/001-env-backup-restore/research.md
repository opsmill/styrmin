# Research: Environment-Level Backup and Restore

**Feature**: `specs/001-env-backup-restore` | **Date**: 2026-08-06

All unknowns from the Technical Context are resolved below. Each decision is grounded in the existing mechanisms mapped from the codebase.

## D1 — Fan-out orchestration lives in the service layer, not a new Prefect flow

**Decision**: `create_environment_backup` is a service-layer function that snapshots config + declared state, then loops over eligible deployments calling the existing `create_backup` service per active instance and dispatching the existing `EXECUTE_BACKUP` Prefect flow per constituent. No new Prefect flows are introduced. Same shape for restore (`EXECUTE_RESTORE` per constituent).

**Rationale**: This is exactly the ADR-0012 environment-config fan-out pattern (`services/environments.py:333-389`): per-item `try/except` isolation, aggregate outcome, dispatch failures never abort the loop. ADR-0012's consequences section explicitly names this the convention to replicate for "any future environment-scope change fans out to deployments". A wrapper Prefect flow would add a new orchestration layer for no benefit — each constituent already has its own flow, and SC-006 (20 constituents enqueued < 60s) is trivially met by a loop of `arun_deployment` fire-and-forget calls (~100ms each).

**Alternatives considered**: (a) A new `EXECUTE_ENVIRONMENT_BACKUP` INTERNAL flow doing the fan-out — rejected: moves the eligibility/snapshot logic out of the service layer (Constitution §III), duplicates the mutation-side component-config resolution, and makes the typed concurrency error unreachable synchronously (the caller could no longer get `ALREADY_IN_PROGRESS` at request time). (b) `asyncio.gather` parallel dispatch — unnecessary; sequential dispatch of N fire-and-forget submissions is fast enough and keeps ADR-0012's per-item isolation semantics simple.

**Amendment (critique E5)**: both fan-outs emit the ADR-0012-style structured audit log line with outcome counters — `env_backup_fanout_dispatched environment_id=… evaluated=… dispatched=… conflict=… dispatch_failed=…` and `env_restore_fanout_dispatched … restored=… skipped=…` — for parity with `env_config_fanout_dispatched`.

**Amendment (implementation review)**: the capture is **atomic up to the dispatch**. The parent row, every constituent row and every recorded `ConstituentError` / late `SkippedConstituent` are created and committed in *one* transaction; the dispatch loop then consumes a list of already-committed ids. Committing the parent on its own first left a window in which a snapshot had zero children and zero errors and therefore derived `COMPLETED` (D2): a `CancelledError` (client disconnect, request timeout) escapes the per-constituent `except Exception` and published that state permanently, and D6's guard — an `EXISTS` over non-terminal *children* — did not hold the environment while the window was open, so a second `createEnvironmentBackup` passed it (FR-009). Reusing `create_backup` / `create_restore` inside that transaction requires `_SharedTransaction`, a `UnitOfWork` view whose `commit`/`rollback` are no-ops, so the reused service joins the caller's transaction instead of publishing a half-built capture — and so `UnitOfWork.__aexit__` cannot roll the parent back because one constituent's instance was busy, which would invert FR-005's per-constituent isolation. Both services also generate their row id up front, so the unique auto-generated name is final before the `INSERT` (two sentinel rows in one transaction violate the index).

## D2 — Parent status is derived at read time; no stored status column

**Decision**: `EnvironmentBackup` and `EnvironmentRestore` have **no status column**. Status is computed by a pure service function from (a) the statuses of linked constituent rows and (b) the recorded constituent errors/skips: any non-terminal child → `IN_PROGRESS` (all-`PENDING` → `PENDING`); otherwise all completed and no errors → `COMPLETED`; at least one completed → `PARTIAL`; else `FAILED`. Zero children and zero errors → `COMPLETED` (config-only backup). Exposed as a GraphQL field resolver.

**Rationale**: FR-004/SC-003 demand that "a stored parent status that contradicts its constituents MUST NOT be possible" — the only way to make contradiction structurally impossible is to never store the parent status. The children's own statuses are already maintained by the existing flows (`update_backup_status` from inside `execute_backup_workflow`), so the parent needs no writer at all — which also means **zero changes to the existing Prefect flows**. The closest existing precedent is `update_backup_component_status` (`services/backup/service.py:208-258`), which derives a parent status from a child-status map — but it *stores* the result and collapses mixed outcomes to `FAILED`; we lift the derivation, add `PARTIAL`, and drop the storage.

**Alternatives considered**: Stored status updated by child-flow callbacks — rejected: requires modifying `execute_backup_workflow`/`execute_restore_workflow` (violating the no-touch reuse constraint), introduces a race between concurrent child completions, and can contradict children after a crash between child update and parent update.

**Amendment (implementation review)**: `derive([], 0) == COMPLETED` stays correct and is still required for the FR-011 config-only case, but it is no longer reachable from a half-built capture (see D1's amendment). A fresh snapshot with eligible deployments derives `PENDING`/`IN_PROGRESS`; one whose every constituent was blocked at creation derives `FAILED` (zero children, `error_count > 0`). Coverage is a count, not a status: the capture commits `len(backups) + len(constituent_errors) == len(deployment_snapshots)`, and a later shortfall against that identity is exactly the gap left by an individually deleted constituent (FR-014 / US3) — comparing linked backups alone against `deployment_snapshots` is not the check, because a constituent that failed at creation never got a row.

## D3 — Snapshot capture as JSON on the parent row

**Decision**: `EnvironmentBackup` carries two JSON columns: `environment_config` (verbatim copy of `Environment.config` at backup time) and `deployment_snapshots` (a list, one entry per eligible deployment: `deployment_id`, `deployment_name`, `driver_name`, `driver_version`, `driver_fingerprint` (content hash or commit SHA per source type), `application_version`, `config`, `parameters`, `instance_id`). A Pydantic model in the service layer defines the snapshot shape; the DB stores plain JSON. Constituent-creation failures are recorded in a third JSON column `constituent_errors` (list of `{deployment_id, deployment_name, error}`).

**Rationale**: Snapshots are immutable point-in-time captures — never queried relationally, never updated — which is exactly what the codebase already uses JSON columns for (`Backup.component_statuses`, `Backup.metadata_`, `ApplicationInstance.context`). ADR-0025 (capabilities as extensible JSON) establishes the convention. The snapshot must be self-contained for the P2 clone case: it records the driver *fingerprint* (ADR-0053), not just the version string, so a future clone can detect whether the same driver content is still loaded. `constituent_errors` covers constituents that never got a `Backup` row (e.g. `BackupAlreadyInProgressError` raised before row creation) without duplicating `create_backup`'s row-creation logic.

**Alternatives considered**: Creating a `FAILED` `Backup` row for conflicted constituents — rejected: `create_backup` raises before creating the row, so the environment service would have to hand-craft `Backup` rows, duplicating naming/metadata logic and polluting the per-instance backup list with rows that never had a Velero attempt.

## D4 — Restore ordering: constituent data restores converge restored deployments; config fan-out covers only the rest

**Decision**: `restore_environment_backup` executes in this order, in one service function:
1. Guard concurrency (D6) and restorability (derived status must be `COMPLETED` or `PARTIAL`).
2. Classify constituents: usable (backup `COMPLETED`, row still exists, deployment alive) vs skipped (with reason) — recorded on the `EnvironmentRestore` row at creation.
3. Revert `Environment.config` to the captured value, recompute capabilities, create one constituent `Restore` row per usable constituent via the existing `create_restore` service (which flips each deployment to `RESTORING`), record any late skip discovered while doing so, and **commit all of it once, before any dispatch** (ADR-0012 rule, made atomic — see D1's amendment).
4. Dispatch the existing per-deployment config fan-out (`redeploy_for_environment_update`) **only for eligible deployments NOT receiving a constituent restore** (including deployments created after the backup — documented as correct per the spec).
5. Dispatch `EXECUTE_RESTORE` per created constituent restore.

**Rationale**: A deployment receiving a Velero data restore is brought back to its backup-time state — its restored in-cluster resources already correspond to the captured environment config (they were captured in the same near-consistent snapshot). Redeploying it via config fan-out *and* restoring it concurrently would race apply-state against the Velero restore on the same namespace. Excluding restored deployments from the fan-out removes the race by construction while still converging every deployment: restored ones via Velero, unrestored ones via the standard fan-out. Committing config before dispatch preserves the ADR-0012 recovery property (a re-submitted operation converges laggards).

**Alternatives considered**: (a) Full fan-out then restores — rejected: apply-state redeploy racing Velero restore in the same namespace has undefined outcome. (b) Restores first, config later — rejected: `redeploy_for_environment_update` doesn't check `RESTORING` status, same race from the other side, plus a window where restored data runs under wrong env config. (c) Sequential wait-for-fanout-then-restore — rejected: fan-out completion is not observable synchronously without new polling machinery; violates the no-new-machinery reuse constraint.

**Amendment (critique E3)**: the config revert must NOT delegate to `update_environment` — that service treats `config is None` as an idempotent no-op (`services/environments.py:296-302`), which would make a captured `None` config unrestorable. The restore service sets `Environment.config` directly (including `None`), recomputes capabilities, commits, then runs the exclusion-aware fan-out loop itself, reusing `redeploy_for_environment_update` per non-restored deployment.

**Amendment (critique P2)**: constituents whose deployment is already mid-restore at classification time (`RestoreAlreadyInProgressError` from an individual restore) are classified as skipped with reason "deployment busy with another restore" — the uniform skip rule, never an abort.

## D5 — Cascade delete reuses `delete_backup` per constituent

**Decision**: `delete_environment_backup` loops constituents calling the existing `delete_backup` service (which already deletes each backup's restores), deletes `EnvironmentRestore` rows referencing the parent, then deletes the parent row. The `Backup.environment_backup_id` FK is nullable; individually deleting a child backup leaves the parent with a visible gap (spec US3).

**Rationale**: Full reuse; `delete_backup`'s semantics (DB-row deletion; Velero object lifecycle governed by TTL) carry over unchanged, keeping FR-014's "constituents behave as ordinary backups" true for deletion too.

**Amendments (critique E1, E2)**: (1) Deletion is legal **regardless of derived status** — no in-progress guard — because it is the escape hatch for an environment backup pinned in progress by a stuck-`PENDING` constituent (fire-and-forget dispatch means no janitor will rescue it; ADR-0024 cleanup covers observed-state tables only). (2) `delete_environment` (`services/environments.py:396-405`) gains the same cascade: deleting an environment deletes its environment backups (and their environment restores) before deleting the row, otherwise the new `environmentbackup.environment_id` FK turns environment deletion into an FK violation masked as `INTERNAL_ERROR` (spec FR-015).

## D6 — Concurrency guard: repository EXISTS query over non-terminal constituents

**Decision**: One environment-level operation per environment, enforced in the service layer by a repository query: an environment backup is in progress iff it has a linked `Backup` row in `PENDING`/`IN_PROGRESS`; an environment restore is in progress iff it has a linked `Restore` row in `PENDING`/`IN_PROGRESS`. New typed error `EnvironmentOperationInProgressError` (`error_code = "ALREADY_IN_PROGRESS"`, metadata carrying the in-flight operation's id and kind), added to `services/exceptions.py` alongside `BackupAlreadyInProgressError`.

**Rationale**: Reuses the derived-state philosophy of D2 — "in progress" is a fact about the children, so the guard can never disagree with reality (no lock row to leak if a process dies). Mirrors the existing `has_in_progress_backup` guard shape. `ALREADY_IN_PROGRESS` already exists in `ErrorCode` (`api/errors.py`), so no new error-code surface.

**Known limitation (accepted)**: two racing create calls can both pass the EXISTS check; the per-instance `has_in_progress_backup` guard then turns the loser's constituents into recorded conflicts (`PARTIAL` outcome) rather than corrupting anything. Documented; a DB-level advisory lock was rejected as new machinery disproportionate to the race window.

## D7 — GraphQL surface and authorization

**Decision**: Mutations `createEnvironmentBackup(environmentId, name)` (READ_WRITE), `restoreEnvironmentBackup(environmentBackupId)` (**ADMIN**), `deleteEnvironmentBackup(environmentBackupId)` (READ_WRITE). Queries `environmentBackup(id)`, `environmentBackups(environmentId)`, `environmentRestore(id)`, `environmentRestores(environmentBackupId)`. Full contract in `contracts/graphql.md`.

**Rationale**: `createBackup`/`deleteBackup` are READ_WRITE today — creating/deleting environment backups is the same class of operation at wider scope. `restoreEnvironmentBackup` reverts `Environment.config`, which is exactly what `updateEnvironment` does, and that mutation requires ADMIN — granting config-mutation-by-restore to READ_WRITE would create a privilege bypass. This follows ADR-0017's existing role model with no new concepts (spec assumption).

## D8 — CLI shape: a new `env-backups` command group

**Decision**: New Cyclopts sub-app `environment_backups.py` registered as `env-backups` in `cli_commands.py`, with commands `create`, `list`, `get`, `delete`, `restore`, `restore-get`, `restore-list` mirroring `backups.py`'s shape (same option aliases, `styrmin_error_handler`, `print_table`/`print_success` rendering, `--wait/--max-wait/--interval` polling via new SDK `wait_for_environment_backup`). Environment resolution mirrors `environments.py get`: positional name or `--id`, with `--cluster`/`--cluster-id` disambiguation (ADR-0031 dual-identifier resolution, server-side).

**Rationale**: Keeping environment backups out of the `backups` group avoids overloading its instance-scoped options (`--deployment`, `--instance-id`); a dedicated group matches the CLI's existing one-namespace-per-resource layout (`backups`, `backup-locations`, `environments`).

## D9 — E2E strategy: extend the `shard_backup` scenario, dual-entrypoint, re-enable the ui/backup CI cell

**Decision**: One new dual-entrypoint E2E test in `backend/tests/e2e/test_backup_restore.py` (existing `shard_backup` module) covering: env backup over ≥2 deployments (reusing `deployed_simple_app` + one additional deployment with `service_name_overrides`), constituent verification, config mutation, environment restore, config-revert + data-restore assertions, and cascade delete. New `ScenarioDriver` protocol methods (`create_environment_backup`, `get_environment_backup`, `wait_for_environment_backup`, `restore_environment_backup`, `wait_for_environment_restore`, `delete_environment_backup`) implemented in both drivers + conformance test + a new environment-backups-tab page object. **`.github/workflows/ci.yml` line ~240: remove the `{entrypoint: ui, shard: backup}` matrix exclusion** — the exclusion comment explicitly says to re-enable when a dual-entrypoint test is added, which this is.

**Rationale**: Constitution §V "reuse before you boot" — the backup shard already boots Velero + MinIO + simple-app; the new scenario adds one light deployment rather than a new heavy node. Dual-entrypoint is mandatory because the feature ships a UI flow (spec FR-012) and the scenario driver methods are dual-entrypoint by definition. The CI matrix edit is the pre-authorized re-enable path written into the exclusion's own comment.

## D10 — Alembic revision shape

**Decision**: One revision on head `b9c0d1e2f3a4`: create `environmentbackup` (id, timestamps, `name` unique, `environment_id` FK, `environment_config` JSON nullable, `deployment_snapshots` JSON nullable, `constituent_errors` JSON nullable), create `environmentrestore` (id, timestamps, `environment_backup_id` FK, `skipped_constituents` JSON nullable), add nullable FK columns `backup.environment_backup_id` and `restore.environment_restore_id`. **No new DB enums** (status is derived, not stored — D2), so the Postgres enum-creation ceremony from `dev/guides/database-migrations.md` does not apply. Tables created in FK-dependency order; downgrade drops columns then tables.

**Rationale**: Follows ADR-0001 and the migration guide's portability rules; avoiding stored enums removes the riskiest part of multi-dialect migrations. Nullable FKs mirror the existing `Backup.schedule_id` precedent.

## D11 — Documentation set

**Decision**: Update `docs/docs/concepts-and-architecture/backups-and-restores.md` (new environment-level section — the page's "Why one BSL per environment?" section already sets up the concept), `docs/docs/alpha-status.md` (remove the "Backup of a full environment — coming before beta" bullet, lines 30-32), `docs/docs/reference/styrminctl.md` (new `env-backups` group), `docs/docs/concepts-and-architecture/glossary.md` (two entries), `dev/knowledge/backend/backup-restore.md` (architecture), and a new ADR documenting the parent-record + derived-status design — explicitly recording the justified deviation from ADR-0012 §"no umbrella record" (that ADR rejected an umbrella row for config fan-out; this feature's traceability requirement is precisely what changed). `CONTEXT.md` glossary entries already landed with the spec commit.

**Rationale**: Constitution §VII enumerates exactly these surfaces; the alpha-status page names issue #7 directly, so shipping without editing it would leave the docs factually wrong.
