# Quickstart Validation: Configurable Backup Retention TTL

**Feature**: 016-backup-retention-ttl

Runnable scenarios proving the feature end-to-end. Contracts: [contracts/graphql-delta.md](contracts/graphql-delta.md); data shapes: [data-model.md](data-model.md).

## Prerequisites

```bash
uv sync                        # Python workspaces
cd frontend && pnpm install    # frontend deps (needed by `uv run invoke generate`)
```

E2E additionally needs `docker` and `vcluster` on PATH (self-bootstrapping fixtures — no dev stack required).

## 1. Fast feedback — unit + propagation suites

```bash
# Validator accept/reject matrix (FR-004) + precedence/fallback/source-scope (FR-001/003/006)
uv run pytest backend/tests/unit/context/test_base_config_section.py \
              backend/tests/unit/services/test_backup_ttl_resolution.py -v

# Builder pass-through with explicit TTL (FR-002; relocated default assertion)
uv run pytest backend/tests/unit/agent/test_velero_resources.py \
              backend/tests/unit/agent/test_backup_builders.py -v

# GraphQL ↔ DB propagation (FR-005/FR-007 — Constitution §V, blocking)
uv run pytest backend/tests/functional/graphql/test_environment_update_propagation.py \
              backend/tests/functional/graphql/test_update_deployment_input_propagation.py \
              backend/tests/functional/graphql/test_deploy_input_propagation.py \
              backend/tests/functional/graphql/ -k backup -v
```

Expected: all green; the schema-walking guard (`test_update_environment_input_covers_every_environment_config_field`) passes only once `UpdateEnvironmentInput.backup_ttl` exists.

## 2. Regeneration is clean (CI parity)

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
git diff --exit-code schema.graphql python_sdk/src/styrmin_sdk/graphql/_generated frontend/src/generated
```

Expected after committing regenerated artifacts: empty diff. `schema.graphql` shows exactly: `Backup.ttl`, `Backup.expiresAt`, `UpdateEnvironmentInput.backupTtl`, `DeploymentConfigInput.backupTtl`.

## 3. Client surfaces

```bash
cd frontend && pnpm test BackupExpiry        # expiry cell renders date / "—", TTL exposed accessibly (FR-008)
uv run pytest cli/tests/test_backups.py -v   # expiry column, "—" when null (FR-010)
```

Pass the vitest name filter **without** `--` — `pnpm test -- BackupExpiry` drops
the filter and runs the whole suite (58 files) instead of the one file.

## 4. E2E — the definition-of-done gate (Constitution §V)

Extended existing node (no new node, `shard_backup`). Run the two entrypoint
variants as **two separate pytest sessions**, exactly as CI drives them:

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" \
  -k api-chromium -v -s --pdb 2>&1 | tee /tmp/backup-ttl-e2e-api.log

sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" \
  -k ui-chromium -v -s --pdb 2>&1 | tee /tmp/backup-ttl-e2e-ui.log
```

One session cannot run both: `styrmin_resources` depends on the parametrised
`driver_mode` fixture, so it re-runs per mode and calls
`create_cluster(name="test-cluster")` a second time — `[api-chromium]` passes and
`[ui-chromium]` then errors in fixture setup on the duplicate. `-k` splitting is
why `backend/tests/e2e/conftest.py` (`driver_mode`, ~line 669) gives each mode its
own CI job with a fresh vcluster.

The extended test must: set `backup_ttl` (e.g. `"2160h"`) on the scenario environment → create a backup via the dual-entrypoint scenario driver → assert the Velero Backup CRD `spec.ttl == "2160h"` (next to the existing `assert_velero_backup_uses_bsl` storage-location assertion) → after completion, assert `Backup.ttl == "2160h"` and `expiresAt` non-null via the SDK.

Record PASS evidence per Constitution §V: node ID, exact command, ISO timestamp, vcluster id + kubeconfig path, verbatim `PASSED` line.

## 5. Manual smoke (optional, full dev stack)

```bash
uv run invoke dev   # then, against the GraphQL endpoint:
```

```graphql
mutation { updateEnvironment(environmentId: "<id>", input: { backupTtl: "2160h" }) { id } }
mutation { updateEnvironment(environmentId: "<id>", input: { backupTtl: "30d" }) { id } }   # must fail: names backup_ttl, hints "720h"
mutation { createBackup(deploymentId: "<id>") { id } }
query { backups(instanceId: "<instance-id>") { name ttl expiresAt } }
```

Expected: `30d` rejected with the typed hint and nothing persisted (P3 journey); the new backup reports `ttl: "2160h"` and, once Completed, a matching `expiresAt`; UI backup list shows the expiry date, `styrminctl backups list` shows the Expires column, pre-existing backups show "—".

## 6. Regression guard (SC-004)

```bash
uv run pytest backend/tests/unit backend/tests/functional -q   # no assertion changes beyond the relocated 720h default
uv run invoke format lint                                       # §VI gate
```
