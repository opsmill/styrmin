# Quickstart: Validate Per-Component Replica Counts

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Run from the repository root. Contracts: [graphql.md](contracts/graphql.md), [errors.md](contracts/errors.md), [post-render-patch.md](contracts/post-render-patch.md), [driver-format.md](contracts/driver-format.md), [cli-and-ui.md](contracts/cli-and-ui.md).

## Prerequisites

- `uv sync`; frontend dependencies installed (in an emdash worktree: `pnpm install --ignore-workspace` in `frontend/`, inside a Node 22 container when the host Node is older).
- For E2E: `docker` and `vcluster` on `PATH`. Build the server image once before the run: `docker compose build server`.

## 1. Regenerate and lint

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
uv run invoke format lint
```

Expected: `schema.graphql` has `ComponentConfigInput.replicas`, `Deployment.componentReplicas`, `ComponentReplicas`, `ReplicaSource`, `ComponentConfig.replicas` and `ComponentConfig.singleton`; lint passes.

## 2. Unit, integration and functional tests

```bash
uv run pytest backend/tests/unit/services/replicas backend/tests/unit/services/driver/test_component_replicas.py \
  backend/tests/unit/services/parameters/test_retired.py -q
uv run pytest backend/tests/unit/agent -q -k "replica or post_render or ordering"
uv run pytest backend/tests/integration/test_component_container_kustomize.py -q
uv run pytest backend/tests/functional/graphql -q -k "replica or retired or infrahub_replica"
uv run pytest backend/tests/unit/test_e2e_driver_conformance.py -q
```

Expected:

- The resolver follows the order of precedence in [data-model.md](data-model.md); a stopped component patches 0.
- Real `kubectl kustomize` sets `spec.replicas` to the override on a chart that renders 3 and on one that renders none, and to 0 when stopped.
- A driver file with `singleton: true` and `replicas: 3` fails to load.
- `SINGLETON_REPLICA_OVERRIDE` on create, update, `updateDeploymentVersion(input:)` and a version change; no task is created and the row is unchanged.
- The `infrahub` version 4 → 5 change with default parameter values succeeds, and `componentReplicas` reports `server` 1 and `task-worker` 2 (`DRIVER_DEFAULT`); with `replicas_task_worker: 4` it fails with `RETIRED_PARAMETER_VALUE` naming the parameter and `4`.

## 3. SDK, CLI and frontend tests

```bash
# One session each: both packages have a tests/conftest.py, which pytest cannot import twice.
uv run pytest python_sdk/tests/test_deployments.py -q
uv run pytest cli/tests/test_deployments.py -q
cd frontend
pnpm test -- ComponentOverridesSection ComponentOverridesSummary DeployFormPage ComponentsTab deployment-input config-diff
pnpm lint
```

## 4. E2E (both variants, one per session)

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_deployment_image_override.py" -m "ci and shard_configuration" \
  -k api-chromium -v -s --pdb 2>&1 | tee /tmp/replicas-api.log
sleep infinity | uv run pytest "backend/tests/e2e/test_deployment_image_override.py" -m "ci and shard_configuration" \
  -k ui-chromium -v -s --pdb 2>&1 | tee /tmp/replicas-ui.log
```

Expected for `test_scale_server_and_singleton_guard`:

1. After setting `server` to 2 and waiting for the update task, a single read of the `styrmin-simple-app` `Deployment` shows 2 updated, ready and available replicas and `status.replicas` 2; `componentReplicas` reports `server` 2 / `OVERRIDE`.
2. The `database` `StatefulSet` has 1 ready replica; `componentReplicas` reports 1 / `DRIVER_DEFAULT` / `singleton: true`. The UI variant shows `database` fixed at 1 in the edit drawer.
3. Submitting `database` replicas 2 through the SDK fails with `SINGLETON_REPLICA_OVERRIDE`; no new task.
4. After clearing the `server` override and waiting for the update task, a single read shows all counts at 1; the source is `CHART`.

Record for each variant (Constitution §V): the node ID, the command, the ISO 8601 time of the passing run, the vcluster id and kubeconfig path, and the verbatim `PASSED` line. Stop a paused run by PID, not with `pkill -f`.

Also run the rest of `shard_configuration` once in each variant, because the `simple-app` driver version changes (D-013):

```bash
sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_configuration" -k ui-chromium -v -s --pdb
```

## 5. Manual check (optional)

```bash
uv run invoke dev
```

1. Deploy `simple-app` with "Component replicas" `server` = 2 in the create form; the deployment runs 2 `server` pods.
2. Open the configuration view: `server` shows `2 (override)`, `database` shows `1 (driver default, singleton)`.
3. In the edit drawer, the `database` field is fixed at `1 (singleton)`; clear the `server` field and apply: the view shows `set by the chart`.
4. `uv run styrminctl deployments get <name>`: the Components table shows the `Replicas` column.

## Validation record (T066, 2026-10-15, commit `973f9a47`)

Sections 1 to 4, run on the host, with the frontend commands in a `node:22-slim` container.

1. Regenerate and lint
   - [x] `schema.graphql` has `ComponentConfigInput.replicas`, `Deployment.componentReplicas`, `ComponentReplicas`, `ReplicaSource`, `ComponentConfig.replicas` and `ComponentConfig.singleton`. Regenerating the schema, the SDK types and the frontend types changed no file.
   - [x] `uv run invoke format lint` passes.
2. Unit, integration and functional tests
   - [x] Resolver and driver tests: 135 passed. Agent tests: 11 passed. Kustomize integration tests: 21 passed. GraphQL functional tests: 35 passed. Driver conformance tests: 26 passed.
3. SDK, CLI and frontend tests
   - [x] SDK: 72 passed. CLI: 45 passed. Before this record, the section ran both files in one session, which fails at collection.
   - [x] Frontend: the six named test files pass within the full run (93 files, 1019 tests). `pnpm lint` reports 0 errors.
4. E2E
   - [x] Expected results 1 to 4 of `test_scale_server_and_singleton_guard` hold in both variants. The UI variant also checks the replica lines of the configuration view. See [e2e-evidence.md](e2e-evidence.md).
   - [x] The rest of `shard_configuration` passes in both variants: API 9 passed, 12 skipped; UI 13 passed, 8 skipped.
