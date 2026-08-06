# Quickstart Validation: Environment Clone

**Feature**: `specs/002-env-clone` | **Date**: 2026-08-06

Runnable scenarios proving the feature end-to-end. Contracts: [contracts/graphql.md](contracts/graphql.md); entities: [data-model.md](data-model.md); design: [research.md](research.md).

## Prerequisites

- `docker` and `vcluster` on PATH (E2E fixtures are self-bootstrapping — no dev stack needed).
- `uv sync` done; `cd frontend && pnpm install` done (required by `uv run invoke generate`).

## 1. Static gates (fast, run first)

```bash
uv run invoke format lint          # includes validate-graphql + generate-validate (codegen drift)
uv run pytest backend/tests/unit/services/backup/ -k clone -v
uv run pytest backend/tests/functional/graphql/test_environment_clone.py -v
uv run pytest backend/tests/unit/test_e2e_driver_conformance.py -v
cd frontend && pnpm test -- EnvironmentClone
cd cli && uv run pytest tests/test_environment_clones.py -v
```

Expected: all pass; `schema.graphql`, SDK `_generated/`, and `frontend/src/generated/` are drift-free.

## 2. Migration round-trip

```bash
uv run pytest backend/tests/unit/db/ -k migration -v
```

Expected: upgrade head applies `environmentclone` and the nullable `restore.environment_clone_id` FK; downgrade removes them cleanly. `down_revision = "c1d2e3f4a5b6"`.

## 3. E2E — the definition-of-done run (SC-001…SC-005)

```bash
sleep infinity | uv run pytest \
  "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" \
  -v -s --pdb 2>&1 | tee /tmp/env-clone-e2e.log
```

Run for **both** entrypoints (`[api-chromium]` / `[ui-chromium]`). The scenario asserts:

1. Environment with ≥2 data-bearing deployments, data marker written → one `cloneEnvironment` call with a selection excluding one deployment (SC-001).
2. Clone reaches a terminal status; the clone environment exists with exactly the selected counterpart deployments `RUNNING`, and the marker data is present in the counterpart (SC-004).
3. Source config and every source deployment's declared state are unchanged; the only source-side artefact is the environment backup (SC-002).
4. `deploymentResults` accounts for every selected deployment — the excluded one is absent, ineligible ones (if seeded) are `SKIPPED` with a reason (SC-003).
5. Delete the clone environment (ordinary `deleteEnvironment`) → re-clone under the same name succeeds (SC-005).
6. Scratch namespaces (`styrmin-clone-*`) are gone after each constituent restore (teardown always runs).

Constitution §V evidence to record on completion: pytest node ID, exact command, ISO timestamp, vcluster id + kubeconfig path, verbatim `PASSED` line — for each entrypoint.

## 4. CLI smoke (manual, against a dev stack)

```bash
uv run styrminctl env-clones create test-environment --new-name test-environment-copy --wait
uv run styrminctl env-clones list test-environment
uv run styrminctl env-clones get <environment-clone-id>
uv run styrminctl environments delete test-environment-copy
```

Expected: create prints the record with derived status and, on `--wait`, the final per-deployment results table; deleting the clone environment leaves the clone record readable with `createdEnvironment: null`.

## 5. Frontend smoke (manual)

Environments list → "Clone" action (ADMIN-gated) → dialog: new name, deployment multi-select, optional config override → submit. Source environment detail → Clones tab: watch derived status auto-refresh (10 s), expand per-deployment results, follow the link to the created environment.

## 6. Edge-case checks (unit-level, already in gate 1)

- New name taken → `ALREADY_EXISTS` upfront, zero rows created (FR-012).
- Selection containing an ineligible or foreign deployment id → `VALIDATION_ERROR` upfront (D6).
- Backup phase derives `FAILED` → clone `FAILED`, no environment created (FR-002).
- Backup `PARTIAL` → clone proceeds; failed constituents carried into `deploymentResults` as `SKIPPED` with reason (D4).
- Captured driver version unresolvable → that deployment `FAILED` in results, rest proceed (spec edge 2); fingerprint fallback sets `fingerprintFallback: true` (D3).
- `deleteEnvironmentBackup` on a backup with an in-flight clone → `OPERATION_DENIED` (FR-008); after `deleteEnvironmentClone`, the same deletion succeeds (escape hatch).
- Second clone of the same source while one is in flight → `ALREADY_IN_PROGRESS`, zero side effects (D4 amendment).
- Derivation property tests: `finished_at` unset ⇒ never terminal; terminal statuses computed only from `deployment_results` + linked restores; deleted linked rows never flip a `cloned` outcome.
- Scratch isolation prelude: the deny-all NetworkPolicy is created in the scratch namespace **before** the Velero restore is dispatched (critique E1); the namespace carries the `styrmin.io/environment-clone-restore` label.
- Bounded waits: a counterpart that never reaches `RUNNING` within its timeout is attributed `failed` with reason and the saga continues; `finished_at` is stamped on every survivable exit path (critique E2).
- Strategy-less constituent (e.g. `action`-only components) → outcome `cloned` with the "no restorable data strategies" reason note; phases 0–3 skipped (critique Q1).
