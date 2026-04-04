# Research: Environment-Level Backup and Restore

**Feature Branch**: `001-env-backup-restore`
**Date**: 2026-04-04

## Research Task 1: Concurrency Limiting for Constituent Backups

**Context**: FR-017 requires configurable max concurrency (default 5) for constituent backups within an environment backup. The existing codebase has no concurrency limiting patterns.

**Decision**: Use `asyncio.Semaphore` within a new Prefect INTERNAL flow (`execute_environment_backup_workflow`) to gate concurrent constituent backup dispatches.

**Rationale**: The existing backup dispatch pattern uses `PrefectManager.run_action()` which is non-blocking (timeout=0). The environment backup workflow will collect all eligible instances, then use `asyncio.gather()` with a semaphore to limit how many `PrefectAction.EXECUTE_BACKUP` actions run concurrently. This matches the existing `asyncio.gather()` pattern used for utility updates in orchestration.py (lines 235-247).

**Alternatives considered**:
- Prefect work pool concurrency limits: Too coarse — would affect all backups system-wide, not just within one environment backup operation.
- Prefect task concurrency limits: Require Prefect Cloud/Server concurrency API — adds external dependency.
- Queue-based approach: Unnecessary complexity; the semaphore within a single orchestrating flow is simpler and sufficient.

## Research Task 2: Parent Status Aggregation Strategy

**Context**: FR-003/FR-006 require deriving EnvironmentBackup/EnvironmentRestore status from constituent statuses. The spec says status is stored and updated via callback.

**Decision**: Store status as a persistent column on EnvironmentBackup/EnvironmentRestore. Update it in the environment backup orchestration flow after each constituent backup completes or fails, using the same UnitOfWork pattern.

**Rationale**: The existing backup status update pattern (`update_backup_status()` in service.py) uses direct DB updates within the INTERNAL flow. The environment-level flow will await each constituent's completion (via `arun_deployment` polling or flow run status checks), then recompute and persist the parent status. This avoids eventual consistency issues from computed-on-read approaches.

**Aggregation logic**:
- All PENDING → PENDING
- Any IN_PROGRESS → IN_PROGRESS
- All COMPLETED → COMPLETED
- Some COMPLETED + some FAILED → PARTIALLY_FAILED
- All FAILED → FAILED

**Alternatives considered**:
- Computed status (query-time aggregation): Simpler but slower for list queries and inconsistent with existing stored-status pattern for Backup/Restore.
- Event-driven (each constituent triggers parent update): Would require modifying existing backup service — violates SC-004 (no changes to existing backup behavior).

## Research Task 3: Orchestration Flow Architecture

**Context**: Need to determine whether environment backup orchestration should be a new Prefect INTERNAL flow or handled entirely at the service layer.

**Decision**: New Prefect INTERNAL flow (`execute_environment_backup_workflow`) registered as `PrefectAction.EXECUTE_ENV_BACKUP`. The GraphQL mutation creates the EnvironmentBackup + constituent Backup records, then dispatches the orchestration flow.

**Rationale**: Follows the existing two-tier pattern:
1. **Mutation** (synchronous): Creates all DB records (EnvironmentBackup + constituent Backups in PENDING state), returns EnvironmentBackup immediately.
2. **INTERNAL flow** (async): For each constituent Backup, dispatches `PrefectAction.EXECUTE_BACKUP` (reusing existing flow). Tracks completions, updates parent status.

This reuses the existing per-instance backup flow entirely (FR-014) and matches the existing `create_backup` mutation → `EXECUTE_BACKUP` flow pattern.

**Alternatives considered**:
- Service-layer-only orchestration: Would require long-running async tasks outside Prefect, losing observability and retry capabilities.
- Single monolithic flow: Would duplicate the Velero CRD building and status polling logic already in `execute_backup_workflow`.

## Research Task 4: Cascade Delete Implementation

**Context**: FR-009 requires deleting an EnvironmentBackup to cascade to all constituent Backups and their Restores.

**Decision**: Use SQLAlchemy cascade delete (`cascade="all, delete-orphan"`) on the EnvironmentBackup → Backup relationship. Additionally, the existing Backup → Restore relationship already has a `back_populates` link, so add cascade on Backup.restores as well.

**Rationale**: The codebase already uses SQLAlchemy cascade for DeployedService cleanup (models.py line 229). Using the same pattern ensures consistency. The service layer `delete_environment_backup()` function will check for in-progress operations (FR-010) before issuing the delete.

**Alternatives considered**:
- Manual cascade in service layer: Error-prone, requires explicit delete of each constituent. DB-level cascade is more reliable.
- Soft delete: Not used anywhere in the codebase; would add unnecessary complexity.

## Research Task 5: Relationship Design — EnvironmentBackup to Backup

**Context**: Need to link constituent Backups to their parent EnvironmentBackup without modifying the existing Backup model in a breaking way.

**Decision**: Add a nullable FK `environment_backup_id` on the existing `Backup` model pointing to `EnvironmentBackup`. Individual backups (not part of an env backup) will have this field as NULL. Add a corresponding `environment_restore_id` FK on `Restore`.

**Rationale**: This is the simplest relational approach. The FK is nullable, so existing backup creation code doesn't need to change (SC-004). The EnvironmentBackup can access its constituents via `backups: list[Backup] = Relationship(back_populates="environment_backup")`. Queries for "backups belonging to env backup X" are efficient index lookups.

**Alternatives considered**:
- Junction table: Unnecessary for a simple one-to-many relationship.
- JSON array of backup IDs on EnvironmentBackup: Loses referential integrity and makes cascade delete harder.
- Separate "EnvironmentBackupConstituent" model: Over-engineering for a direct parent-child relationship.

## Research Task 6: Environment Backup Timeout Handling

**Context**: FR-018 requires a configurable overall timeout. If exceeded, the EnvironmentBackup transitions to FAILED and running constituent backups are cancelled.

**Decision**: The orchestration flow will track elapsed time. On timeout, it marks remaining in-progress constituents as FAILED (with timeout error message) and sets the parent to FAILED. Cancellation of Prefect flow runs uses the Prefect client's `cancel_flow_run()` API.

**Rationale**: The existing per-instance backup has its own timeout (3600s default). The environment-level timeout provides an overall ceiling. Using Prefect's `cancel_flow_run()` is the cleanest way to stop running constituent workflows without modifying existing flow logic.

**Alternatives considered**:
- Let constituent timeouts handle everything: Doesn't provide an overall time bound for the environment operation.
- Velero-level cancellation: Would require K8s API access from the INTERNAL flow, breaking the two-tier separation.

## Research Task 7: Frontend Integration Pattern

**Context**: FR-016 requires frontend UI for environment backup/restore on the environment detail page.

**Decision**: Add a "Backups" section to the Environment detail page, following the same pattern as the Deployment detail page's backup section. Use urql queries/mutations with auto-generated types from graphql-codegen.

**Rationale**: The existing DeploymentDetailPage.tsx provides a proven pattern: query hooks with `refetchInterval` for auto-refresh, mutation hooks for create/delete/restore operations, dialog confirmations, and status badges. The environment backup UI will follow this exact pattern.

**Alternatives considered**:
- Separate page for environment backups: Unnecessary indirection; the backup section belongs contextually on the environment detail page.
- Real-time subscriptions: urql subscription support exists but no GraphQL subscriptions are used in the project; polling with refetchInterval is the established pattern.

## Research Task 8: CLI Command Structure

**Context**: FR-016 requires CLI commands (`styrmin env backup` / `styrmin env restore`).

**Decision**: The CLI currently has no backup commands. Since the spec mentions `styrmin env backup` / `styrmin env restore`, these will be added as subcommands under a new `env` command group, using Cyclopts (the CLI framework used by the project). CLI commands will call the GraphQL API via the styrmin-sdk.

**Rationale**: The CLI is a thin client over the GraphQL API. CLI commands will invoke the same mutations used by the frontend. The styrmin-sdk already provides a GraphQL client, so CLI commands just need to construct the right queries.

**Alternatives considered**:
- Direct service layer calls from CLI: Would bypass the API layer, violating the layered architecture (Constitution Principle III).
