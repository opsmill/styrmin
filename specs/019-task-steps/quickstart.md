# Quickstart: Validate Steps and Failure Causes

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

How to prove the feature works, from unit tests to the E2E scenarios that close the definition of done (Constitution §V).

## Prerequisites

```bash
uv sync
cd frontend && pnpm install && cd ..
uv run invoke pre-commit-install
```

E2E tests need `docker` and `vcluster` on `PATH` (see [`dev/knowledge/backend/e2e-testing.md`](../../dev/knowledge/backend/e2e-testing.md)). `uv run invoke generate` and `uv run invoke lint` also need Node 22 first on `PATH`, because they run the frontend code generator.

## 1. Schema, migration and generated code

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
uv run invoke validate-graphql
STYRMIN_DB_TYPE=postgres STYRMIN_DB_NAME=styrmin uv run styrmin db migrate
uv run styrmin db status
uv run styrmin db downgrade -1
uv run styrmin db migrate
```

The `styrmin db` commands use the same `STYRMIN_DB_*` variables in every line. For a PostgreSQL server that is not on `localhost:5432` without a password, also set `STYRMIN_DB_HOST`, `STYRMIN_DB_PORT`, `STYRMIN_DB_USERNAME` and `STYRMIN_DB_PASSWORD`.

Expected:

- `schema.graphql` does not change, and contains `type Step`, `enum TaskResult` and `recordStep(input: RecordStepInput!): Step!`, which only the `styrmin-actions` service account can call.
- `styrmin db status` prints `Rev: e2f3a4b5c6d7 (head)` ("add steps").
- `styrmin db downgrade -1` returns the database to `d1e2f3a4b5c6`: the `step` table and the `task.instance_id` and `task.started_by_step_id` columns are removed.
- The second `styrmin db migrate` applies the revision again on a database at the previous head.
- `backend/tests/unit/db/test_steps_migration.py` runs the same round trip on PostgreSQL and SQLite.

## 2. Unit and propagation tests

```bash
uv run pytest backend/tests/unit -k "step or task_result or operator_report or phase_history or record_step or job_output" -v
uv run pytest backend/tests/unit -k "styrmin_deployment or reporter" -v
uv run invoke test
cd frontend && pnpm test && cd ..
uv run pytest -v python_sdk/tests
uv run pytest -v cli/tests
```

Run the SDK tests and the CLI tests as two commands, as CI does. In one command, pytest stops before it runs a test with `ImportPathMismatchError`, because both folders are named `tests`.

Expected: the tests listed in [contracts/graphql.md](contracts/graphql.md), [contracts/operator-status.md](contracts/operator-status.md), [contracts/flow-step-reporter.md](contracts/flow-step-reporter.md) and [contracts/client-surfaces.md](contracts/client-surfaces.md) pass. `uv run invoke test` also runs `backend/tests/integration`, which creates a vCluster.

Two CLI tests fail when the tests run as `root`, because `root` can write to the read-only folder that they create: `test_unwritable_dir_falls_back_to_ephemeral_id` and `test_commands_succeed_under_unwritable_dir`. They also fail on the commit before this feature (`675e057a`), so this feature does not cause the failure.

## 3. E2E scenarios

Run each changed node with `--pdb`, as AGENTS.md requires. In a non-interactive shell, prefix with `sleep infinity |`.

| Scenario | Command (node id) | Variants | What it proves |
|---|---|---|---|
| A create shows its plan, resource write and operator steps | `backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_has_entries` (extended) | api + ui | US1 |
| An upgrade shows ordered steps, the two tasks its hook started (`stop_components` and `start_components`) and the task results | `backend/tests/e2e/test_deploy_app.py::test_upgrade_simple_app` (extended) | api + ui | US1, US3 AS2, SC-002 |
| A hook action raises | `backend/tests/e2e/test_task_steps.py::test_hook_action_error_shows_failed_step` | api only | SC-001 type 1 |
| A command run by an action fails | `backend/tests/e2e/test_task_steps.py::test_command_output_on_failed_step` | api only | SC-001 type 2, FR-003 |
| The HelmRelease does not become Ready (image cannot be pulled), and FluxCD's rollback leaves the rollout failed | `backend/tests/e2e/test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason` | api + ui | SC-001 type 3, US2 AS1, US5 AS3, FR-004 |
| The operator cannot create a prerequisite | `backend/tests/e2e/test_task_steps.py::test_prerequisite_failure_shows_attempts` | api only | SC-001 type 4, FR-002 attempts |
| A `READ_ONLY` user reads the same steps, errors and command output | part of `test_helmrelease_failure_shows_fluxcd_reason` | SDK client in both variants | SC-004 |
| A backup lists one step per component; a restore lists its three steps in order | `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle` (extended) | api + ui | US6 |
| A Velero restore of a removed Velero backup fails "Run the Velero restore" with Velero's validation error | `backend/tests/e2e/test_backup_restore.py::test_restore_of_removed_velero_backup_fails_velero_step` | api only | US6, SC-005 |

The `[ui-chromium]` variant of an `api only` node is skipped by design. `test_task_steps.py`, `test_deploy_app.py` and `test_deployment_timeline.py` belong to `shard_general`; `test_backup_restore.py::test_backup_and_restore_lifecycle` and `test_restore_of_removed_velero_backup_fails_velero_step` belong to `shard_backup`.

Example:

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason[api-chromium]" -v -s --pdb 2>&1 | tee /tmp/pdb.log
```

The operator change of research D5 changes the timing of every rollout, so also run the whole `shard_general` and `shard_backup` shards once per variant, as CI does:

```bash
uv run pytest -v -m "ci and shard_general" -k "api-chromium" backend/tests/e2e
uv run pytest -v -m "ci and shard_general" -k "ui-chromium" backend/tests/e2e
uv run pytest -v -m "ci and shard_backup" -k "api-chromium" backend/tests/e2e
uv run pytest -v -m "ci and shard_backup" -k "ui-chromium" backend/tests/e2e
```

To run several sessions at the same time, give each its own `STYRMIN_IMAGE_VER`, as CI does. Create that image tag before the run, for example with `docker tag registry.opsmill.io/opsmill/styrmin:latest registry.opsmill.io/opsmill/styrmin:$STYRMIN_IMAGE_VER`. Otherwise `docker compose build` can fail with `image "…" already exists`, because three services build the same new tag at the same time.

Record for each new or changed E2E test the node id, the command, the time of the passing run, the vCluster id and kubeconfig path, and the `PASSED` line (Constitution §V), in [e2e-evidence.md](e2e-evidence.md).

## 4. Manual check on the dev stack (optional)

```bash
uv run invoke dev
```

1. Deploy `simple-app` 0.1.0, then upgrade to 0.2.0 from the deployment page.
2. Open the Timeline tab while the upgrade runs. Expected: the entry labelled "Upgrade" is expanded with result `RUNNING`; steps appear within 15 seconds of each change; two started tasks, `stop_components` and `start_components`, appear under "Run the upgrade hook".
3. When the deployment is `RUNNING`, the upgrade and its last started task (`start_components`) show `SUCCEEDED`. The earlier started task (`stop_components`) shows `SUCCEEDED`, or `SUPERSEDED` with a link to `start_components` if `start_components` interrupted its rollout.
4. Set an image override with a tag that does not exist and apply. Expected: within about five minutes (the operator's 300-second readiness timeout) the entry shows `FAILED`, and the step "Install or upgrade the HelmRelease" shows FluxCD's reason and "Pods not ready: … ImagePullBackOff". When FluxCD then rolls the release back, the step and the entry stay `FAILED`, the deployment is `failed`, and the StyrminDeployment's message says that FluxCD rolled the release back.
5. `styrminctl tasks get <task id>` prints the same steps. `styrminctl deployments apply -f <manifest> --wait` prints `failed <name>: step "Install or upgrade the HelmRelease" failed: …`.
6. Log in as a `READ_ONLY` user and open the same deployment. Expected: the same steps, errors and output.
