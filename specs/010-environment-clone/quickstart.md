# Quickstart: Environment Clone — validation guide

**Feature**: 010-environment-clone

Runnable scenarios proving the feature works. Contracts: [contracts/graphql.md](contracts/graphql.md);
entities: [data-model.md](data-model.md).

## Prerequisites

- `uv sync` and `cd frontend && pnpm install` done once.
- For E2E: `docker` daemon running and `vcluster` on PATH (the session fixture boots a
  disposable cluster — no dev stack needed).

## 1. Fast checks (no cluster)

```bash
uv run invoke format lint            # §VI gate
uv run invoke validate-graphql       # all new .graphql operations validate
uv run invoke generate               # SDK + frontend types regenerate cleanly (no diff in CI)
uv run pytest backend/tests/unit -k "clone" -v
uv run pytest backend/tests/functional/graphql/test_environment_clone.py -v
cd frontend && pnpm test -- clone    # dialog + clones list component tests
```

Expected: all green; propagation tests assert through the real repository (writes
reach rows, rows project to resolvers).

## 2. Migration check

```bash
STYRMIN_DB_TYPE=postgres STYRMIN_DB_NAME=styrmin uv run styrmin db migrate
```

Expected: applies the `environmentclone` revision on a database at previous head;
`alembic heads` shows a single head.

## 3. E2E — the definitive validation (`shard_backup`)

```bash
sleep infinity | uv run pytest \
  "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]" \
  -v -s --pdb 2>&1 | tee /tmp/clone-e2e.log
```

The scenario (single dual-entrypoint node, reusing the environment-backup stack):

1. Deploy stack via existing session fixtures (`deployed_simple_app`, `velero_ready`).
2. Write a data marker to the source app (`/count` recipe).
3. Invoke clone (new target name) via the scenario driver.
4. After the capture goes terminal, mutate the source data again.
5. Wait for the clone to reach a terminal status.
6. Assert:
   - clone `COMPLETED`; every source deployment attributed (SC-003);
   - counterpart deployment `RUNNING`, data equals the marker, not the post-capture
     mutation (SC-001, SC-004, FR-007);
   - source environment config + declared state unchanged; only source-side artefact
     is the environment backup (SC-002);
   - config override visible on the created environment (FR-006).
7. Delete the cloned environment; re-clone under the same name succeeds (SC-005).

Also run the `[ui-chromium]` variant (clone dialog → clones list → status badge).

**Record local PASS evidence** (Constitution §V): node id, exact command, ISO 8601
timestamp, vcluster id + kubeconfig path, verbatim `PASSED` line.

## 4. Manual smoke (optional, via dev stack)

```bash
uv run invoke dev    # interactive stack
# CLI:
uv run styrminctl env-clones create <source-env> --name rehearsal \
  --config-override '{"env_vars": [{"name": "SMTP_HOST", "value": "sink.local"}]}' --wait
uv run styrminctl env-clones list <source-env>
```

Expected: `create --wait` polls to terminal and exits 0 on `COMPLETED`
(1 on `FAILED`/`PARTIAL`); UI shows the clone with derived status on the source
environment's page.

## 5. Negative paths (unit/propagation-level)

- Clone with a taken name → `ALREADY_EXISTS`, zero side effects (FR-011).
- Clone during another environment-level op on the source → `ALREADY_IN_PROGRESS` (D8).
- Delete the backing environment backup mid-clone → `IN_USE` (FR-008).
- Non-admin clone attempt → `FORBIDDEN` (FR-010).
- Capture forced to fail → no environment created, clone `FAILED` (FR-002).
