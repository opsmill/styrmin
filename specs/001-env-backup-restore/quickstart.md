# Quickstart Validation: Environment-Level Backup and Restore

**Feature**: `specs/001-env-backup-restore` | **Date**: 2026-08-06

Runnable scenarios proving the feature end-to-end. Contracts: [contracts/graphql.md](contracts/graphql.md); entities: [data-model.md](data-model.md).

## Prerequisites

- `docker` and `vcluster` on PATH (E2E fixtures are self-bootstrapping — no dev stack needed).
- `uv sync` done; `cd frontend && pnpm install` done (required by `uv run invoke generate`).

## 1. Static gates (fast, run first)

```bash
uv run invoke format lint          # includes validate-graphql + generate-validate (codegen drift)
uv run pytest backend/tests/unit/services/backup/ -k environment -v
uv run pytest backend/tests/functional/graphql/test_environment_backup.py -v
cd frontend && pnpm test -- EnvironmentBackups
cd cli && uv run pytest tests/test_environment_backups.py -v
```

Expected: all pass; `schema.graphql`, SDK `_generated/`, and `frontend/src/generated/` are drift-free.

## 2. Migration round-trip

```bash
uv run pytest backend/tests/unit/db/ -k migration -v   # or the repo's migration smoke test location
```

Expected: upgrade head applies `environmentbackup` + `environmentrestore` tables and the two nullable FK columns; downgrade removes them cleanly.

## 3. E2E — the definition-of-done run (SC-001…SC-005)

```bash
sleep infinity | uv run pytest \
  "backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle" \
  -v -s --pdb 2>&1 | tee /tmp/env-backup-e2e.log
```

Run for **both** entrypoints (the node is parametrized `[api-chromium]` / `[ui-chromium]`). The scenario asserts:

1. Environment with ≥2 deployments → one `createEnvironmentBackup` call creates one constituent per eligible deployment (SC-001), each landing `COMPLETED` in Velero.
2. Derived parent status transitions `IN_PROGRESS → COMPLETED` and always matches the constituent derivation rule (SC-003).
3. Mutate environment config + application data → `restoreEnvironmentBackup` → env config equals the captured config (SC-005), application data is back (SC-002), and any non-restored constituent appears in `skippedConstituents` with deployment name + reason (SC-004).
4. `deleteEnvironmentBackup` removes constituents and their restores.

Constitution §V evidence to record on completion: pytest node ID, exact command, ISO timestamp, vcluster id + kubeconfig path, verbatim `PASSED` line — for each entrypoint.

## 4. CLI smoke (manual, against a dev stack)

```bash
uv run styrminctl env-backups create test-environment --wait
uv run styrminctl env-backups list test-environment
uv run styrminctl env-backups restore <environment-backup-id> --wait
```

Expected: create prints the new snapshot with derived status; restore prints skipped constituents (if any) with reasons.

## 5. Frontend smoke (manual)

Environment detail page → Backups tab (the `SOON` badge is gone): trigger backup, watch status auto-refresh (10s), expand per-constituent outcomes, trigger restore, confirm skipped-constituent reporting, delete a snapshot.

## 6. Edge-case checks (unit-level, already in gate 1)

- Empty environment → config-only backup, immediately `COMPLETED` (FR-011).
- Constituent conflict (seeded in-progress backup) → recorded error, `PARTIAL`, mutation succeeds (FR-005).
- Second env-level operation while one is in flight → `ALREADY_IN_PROGRESS` typed error (FR-009).
- Restore with deleted/expired/tombstoned constituents → uniform skip-and-report (FR-007).
- Restore never creates or deletes deployments (FR-008): deployment count unchanged across restore.
