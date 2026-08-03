# Research: Configurable Backup Retention TTL

**Feature**: 016-backup-retention-ttl | **Date**: 2026-08-03

All Technical Context unknowns resolved. Research was performed against the live codebase (file/line references verified on branch `fac/fix-backup-ttl-npf7g`) plus ADRs 014, 018, 025–027, 029 and the root-cause analysis for issue #305 (`.bug-analysis-305-backup-retention-ttl.md`, local artifact).

## R1. Where the `backup_ttl` field lives

**Decision**: Add `backup_ttl: str | None = None` to `BaseConfigSection` (`backend/styrmin_backend/context/models/config.py:376`), the shared Pydantic config base inherited by `ClusterConfig`, `EnvironmentConfig`, and `DeploymentConfig`.

**Rationale**: ADR-029 prescribes exactly this for new config policy knobs: one field definition covers all three scopes, config columns are already JSON (no migration), `extra="forbid"` catches typos, and cluster/environment create mutations already accept `config: JSON` (no schema change on the create path). The generic deepest-wins merge in `_resolve_instance_config` (`context/resolvers.py:66-109`) spreads scalars via `model_dump(exclude_none=True)`, so a plain scalar needs **zero merge changes**.

**Alternatives considered**:
- *Capabilities JSON (ADR-025/026/027)* — rejected: capabilities are derived and recomputed synchronously on every triggering write; a policy stored there would be silently overwritten.
- *New DB column per scope* — rejected: needs an Alembic revision (Alembic is in use — 17 revisions — despite the stale AGENTS.md note) and violates the ADR-029 pattern for no benefit.
- *Deploy-time settings/env-var global (`WorkflowSettings`-style)* — rejected by the PRD (out of scope): cluster scope plays the global-default role.

## R2. Validation rule and error surface

**Decision**: A Pydantic field validator on `BaseConfigSection` restricted to strictly positive Go-duration strings in `h`/`m`/`s` units: regex `^(\d+(\.\d+)?(h|m|s))+$` plus a strict-positivity check (reject all-zero values like `0h` / `0h0m0s`). Rejects `30d`, `0h`, `-24h`, `720` (bare integer), `""`. The error message names the field and hints the syntax (e.g. `backup_ttl must be a positive Go duration using h/m/s units, e.g. "720h"`). The regex + a `validate_backup_ttl` helper and `DEFAULT_BACKUP_TTL = "720h"` constant live in `backend/styrmin_backend/services/backup/ttl.py`; the config model imports the helper so there is a single home for the rule.

**Rationale**: FR-004 requires rejection at every input surface with a field-naming, syntax-hinting error. All five input surfaces (cluster create, environment create/update, deploy, deployment update) funnel through `validate_cluster_config` / `validate_environment_config` / `validate_deployment_config` (`context/validators.py`), which wrap Pydantic `ValidationError` into `InvalidClusterContextError` / `InvalidEnvironmentContextError` / `InvalidDeploymentContextError` — existing `ServiceError` subclasses that `StructuredErrorExtension` projects to `extensions.code` with field-level detail. One validator in the shared base covers everything; nothing is persisted on failure because validation happens before any write.

**Alternatives considered**:
- *Dedicated `ServiceError` subclass (e.g. `InvalidBackupTtlError` via the `mode="before"` pattern in `config.py:513-529`)* — deferred, per the PRD's plan-time call: the existing config-validation error shape already names the field and carries a machine-readable code. Introduce only if a distinct error code is later demanded by a client.
- *Full Go `time.ParseDuration` semantics (ns/us/ms, signs)* — rejected: PRD explicitly limits to h/m/s, no day unit, no bare integers; sub-second retention is meaningless for backups. Decimals (e.g. `1.5h`) and compounds (e.g. `1h30m`) are accepted — they are valid Go durations Velero parses, and excluding them would need extra rules for no user benefit.
- *Accepting `30d` sugar* — rejected by the PRD (out of scope); Velero/Go has no day unit.

## R3. TTL resolution point and mechanics

**Decision**: Resolve in `execute_backup_workflow` (`workflows/templates/backup.py:306`), where the deployment and environment rows are already loaded for BSL resolution (lines 344-364). Add a pure function `resolve_backup_ttl(deployment_config, environment_config, cluster_config) -> tuple[str, str]` in `services/backup/ttl.py` returning `(ttl, source_scope)` with `source_scope ∈ {"deployment", "environment", "cluster", "default"}`. The workflow loads `deployment.config`, `env.config`, and the cluster config (via the environment's cluster relationship / repository) in the same UnitOfWork block, calls the resolver, and logs `Resolved backup TTL <ttl> from <scope> scope for backup <id>`.

**Rationale**: FR-001/FR-006 require deepest-wins resolution with source-scope logging; the workflow is the single place every backup (ad-hoc today, scheduled later) passes through — scheduled backups inherit resolution for free once their execution wiring exists. A pure helper is unit-testable per precedence hop without Prefect. Config is read at backup-build time (last committed value wins), mirroring today's storage-location semantics — no locking, per the spec's edge case.

**Caveat carried into design**: the existing BSL block swallows all exceptions with a warning and proceeds. TTL resolution MUST NOT silently fall back inside that try — resolve in its own step so a config-read failure is logged with the fallback value and source `default`, never invisibly.

**Alternatives considered**:
- *Resolve in `create_backup` service at mutation time* — rejected: the value could go stale between record creation and workflow execution, and scheduled backups (future) would bypass it.
- *Resolve in the agent/builder* — rejected: violates §III layering (builders are pure renderers) and the PRD's explicit "builder becomes a pure pass-through".
- *Use `ResolvedConfig` from `_resolve_instance_config`* — considered; rejected for v1 because the instance-resolution path is deployment-creation-time machinery, while FR-006 needs the *source scope* (which the merged output discards). The three-hop explicit resolver is smaller and reports provenance.

## R4. Builder pass-through

**Decision**: Make `ttl` a required parameter with no default on both `build_velero_backup` (`agent/service/kubernetes/resources/builders/backup.py:18`) and the `VeleroBackup` dataclass (`agent/service/kubernetes/velero/resources.py:52`), deleting both `"720h"` literals. The workflow passes the resolved TTL explicitly at the existing call site (`workflows/templates/backup.py:379-387`).

**Rationale**: FR-002/FR-003 and the PRD: the builder must not own policy. Grep confirms exactly two source literals (plus two test assertions); removing both eliminates silent divergence. `VeleroBackup.render()` already writes `spec["ttl"]` unconditionally (resources.py:60), so the rendered shape is unchanged — byte-identical output when the resolved value is the default `720h` (SC-004).

**Alternatives considered**: keeping a default on the dataclass "for safety" — rejected: a hidden default is exactly the bug class this feature removes; the two existing unit suites are updated to supply an explicit TTL and the pinned default assertion relocates to the resolver's unit tests.

## R5. Recording applied TTL and expiration (no migration)

**Decision**: Store on the existing `Backup.metadata_` JSON column (`db/models.py:504`, column name `metadata`, currently `{"timeout": <int>}`):
- `ttl` (str) + `ttl_source` (str) — written when the workflow resolves the TTL, before the Velero object is built;
- `expires_at` (ISO 8601 str) — written on completion from Velero's `status.expiration`.

Plumbing: extend the `Variable.set` payload in `execute_velero_backup_flow` (`workflows/templates/backup.py:132-146`) to include `expiration` (available from `poll_backup_status`, `velero/client.py:243`), and extend `update_backup_status` (`services/backup/service.py:149`) with an optional `metadata_updates: dict | None` parameter that merges into `metadata_` (never replaces — preserves `timeout`).

**Rationale**: FR-006/FR-007 with zero schema migration, exactly the PRD's "existing metadata" decision; the `timeout` key already proves the read/write pattern. Failed/PartiallyFailed backups simply never get `expires_at` → GraphQL null → "—" in UI/CLI (spec edge case, overlaps issue #263).

**Alternatives considered**: dedicated columns (`ttl`, `expires_at`) — rejected: Alembic revision + crosses the DB governance gate for two audit fields; the analysis for #305 explicitly recommends against it.

## R6. GraphQL surface

**Decision** (contract in `contracts/graphql-delta.md`):
- `Backup.ttl: String` (nullable) and `Backup.expiresAt: DateTime` (nullable) as `@strawberry.field` resolvers on the `Backup` type (`api/definitions/backup/backup.py:28`) reading `self.db_model.metadata_` — same pattern as the existing `component_statuses` field (line 52-65). `expiresAt` parses the stored ISO string to `datetime`; absent/unparseable → null.
- `backup_ttl: str | None = None` on `UpdateEnvironmentInput` (`api/definitions/environment/inputs.py:69`) and on `DeploymentConfigInput` (`api/definitions/deployment/inputs.py:135` — shared by `deploy` and `updateDeployment`, so one edit covers create + update). The generic `_convert_value` converter handles a plain scalar; no converter changes.
- Cluster/environment **create** accept the key through the existing `config: JSON` argument (ADR-029) — no schema change on those paths.

**Rationale**: FR-005/FR-007. The schema-walking guard `test_update_environment_input_covers_every_environment_config_field` (`tests/functional/graphql/test_environment_update_propagation.py:507`) fails the moment `backup_ttl` lands on `BaseConfigSection` without the input field — the codebase mechanically enforces the FR-005 half of this design. Regeneration: `uv run styrmin export graphql-schema schema.graphql` + `uv run invoke generate` (regenerates SDK `_generated/` and `frontend/src/generated/graphql.ts`).

**Alternatives considered**: exposing `ttlSource` in GraphQL — deferred: audit provenance is in the record (`metadata.ttl_source`) and workflow logs; no user story demands it in the API. Adding a `Backup.ttl` DB column — rejected (see R5).

## R7. Frontend surface

**Decision**:
- `frontend/src/graphql/list_backups.graphql`: select `ttl expiresAt`.
- Backups tab in `DeploymentDetailPage.tsx` (lines 580-652): add an "Expires" column to the header row and an expiry cell in `BackupRow` (line 993) rendering the localized date, with the applied TTL shown in a tooltip/title on the cell; null → "—". Date formatting follows the file's existing inline `new Date(x).toLocaleDateString()` convention.
- FR-005 round-trip: map `backup_ttl` ↔ `backupTtl` in `deploymentConfigToInput` (`frontend/src/lib/deployment-input.ts:355`) so UI-driven full-replacement deployment updates preserve a stored value, and register `backupTtl` in the `config-diff.ts` scalar registry so config diffs display it. Without the mapping, any UI config edit would silently wipe `backup_ttl` — the exact failure FR-005 exists to prevent, extended to the UI client.
- New test `frontend/src/__tests__/deployment-detail/BackupExpiry.test.tsx` (no backup-list component test exists today; `DeploymentDetailHeader.test.tsx` provides the mocking pattern for `useListBackupsQuery`).

**Rationale**: FR-008 + SC-005; the PRD's "no new routes, extend the existing list". The `deployment-input.ts`/`config-diff.ts` additions are a small necessary extension beyond the PRD's literal frontend list, forced by FR-005's own logic (flagged for the critique phase).

**Alternatives considered**: a shared date-format helper — rejected for this feature: no canonical helper exists (`relative-time.ts` is coarse); introducing one is a refactor outside scope. A dedicated backup-list component extraction — rejected: unnecessary churn in a 1,100-line page for a one-column change.

## R8. CLI surface

**Decision**: `cli/src/styrminctl/commands/backups.py` — add `"expires_at"` to the row dicts and an `Expires` column to `print_table` in `list_backups` (line 132), rendering `"—"` (em dash) when null for contract parity with the UI; add TTL/Expires lines to `backups get` (the per-field block at lines 81-89). SDK exposes the fields after regeneration; `resources/backups.py` needs no hand-written changes.

**Rationale**: FR-010 mirrors the UI contract ("—" when null). Extending `get` costs two lines and serves the same audit story (user story 4); the CLI test module (`cli/tests/test_backups.py:144,157`) extends with value and null cases.

**Alternatives considered**: new `backups retention` command — rejected: PRD says no new commands.

## R9. Test strategy mapping

**Decision** (full mapping in plan.md Project Structure):
- **Validator** (FR-004): parametrise `backend/tests/unit/context/test_base_config_section.py` — accept `720h`, `2160h`, `1h`, `90m`, `1h30m`, `1.5h`; reject `30d`, `0h`, `-24h`, `720`, `""`, `0h0m` — asserting the field name and hint appear.
- **Resolution** (FR-001/FR-003/FR-006): new `backend/tests/unit/services/test_backup_ttl_resolution.py` — one test per precedence hop, fallback to `720h` + `default` source, source-scope values.
- **Builders** (FR-002/FR-003): update the two suites (`test_velero_resources.py:247`, `test_backup_builders.py:27`) to pass explicit TTL; the pinned-`720h` assertion relocates to the resolver tests (SC-004's "no assertion changes beyond relocating the pinned default").
- **Propagation** (Constitution §V, FR-005/FR-007): `backup_ttl` round-trips in `test_environment_update_propagation.py` (forced by the line-507 schema-walk guard), `test_update_deployment_input_propagation.py`, `test_deploy_input_propagation.py`; `Backup.ttl`/`Backup.expiresAt` projection test seeding `metadata_` and asserting resolver output (including null for missing keys and Failed backups).
- **E2E** (Constitution §V): extend `test_backup_and_restore_lifecycle` (`e2e/test_backup_restore.py:112`, `shard_backup`) — set `backup_ttl` on the scenario environment before the backup step, then assert the Velero Backup CRD's `spec.ttl` alongside the existing `assert_velero_backup_uses_bsl` storage-location assertion (helper at lines 81-108) and assert `Backup.ttl`/`expiresAt` via the SDK after completion. No new node, no marker change — the test already exercises the dual-entrypoint `create_backup` scenario-driver method under both `[api-chromium]` and `[ui-chromium]`.
- **CLI/Frontend**: as R7/R8.

**Rationale**: matches the PRD's Testing Decisions verbatim; asserts external behaviour (rendered Velero spec, GraphQL values, table output), not internals.

## R10. Documentation set

**Decision**: Same-change updates (Constitution §VII):
- `docs/docs/concepts-and-architecture/backups-and-restores.md`: new **Retention** section — the `backup_ttl` knob, three scopes + deepest-wins, `720h` default, applies-to-future-backups-only limitation, expired-backup restore warning (cross-ref #304 behaviour), cluster-scope-is-create-only note.
- `dev/knowledge/backend/backup-restore.md`: metadata keys (`ttl`, `ttl_source`, `expires_at`), the resolution helper, the builder's required-TTL signature, `status.expiration` plumbing.
- `CONTEXT.md`: **Backup retention TTL** glossary entry placed after **Backup storage location** (line 53), three-line house convention, explicitly distinguished from `BackupSchedule.retention_count` (count-based, currently unenforced).

**Rationale**: Constitution §VII is non-negotiable; the docs page currently never mentions retention or the 30-day window, which is part of the problem statement (invisibility).

## R11. Explicitly out of scope (confirmed against codebase)

- No cluster-update mutation exists (`mutation.py` has create/delete only) — cluster scope stays set-at-create; documented.
- `BackupSchedule.retention_count` untouched (semantically distinct count, currently unenforced — no `prefect_deployment_id` is ever assigned).
- No retro-patching of existing Velero backups; no per-backup TTL override on `createBackup`; no per-schedule TTL; no `30d` sugar; no expired-backup drift reconciliation (documented warning instead, adjacent to #304).
