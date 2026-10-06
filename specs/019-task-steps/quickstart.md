# Quickstart: Validate Steps and Failure Causes

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

How to prove the feature works, from unit tests to the E2E scenarios that close the definition of done (Constitution §V).

## Prerequisites

```bash
uv sync
cd frontend && pnpm install && cd ..
uv run invoke pre-commit-install
```

E2E tests need `docker` and `vcluster` on `PATH` (see [`dev/knowledge/backend/e2e-testing.md`](../../dev/knowledge/backend/e2e-testing.md)).

## 1. Schema, migration and generated code

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
uv run invoke validate-graphql
STYRMIN_DB_TYPE=postgres STYRMIN_DB_NAME=styrmin uv run styrmin db migrate
```

Expected: `schema.graphql` contains `type Step`, `enum TaskResult`, `recordStep(input: RecordStepInput!)`; the migration applies on a database at the previous head and `styrmin db downgrade -1` reverses it.

## 2. Unit and propagation tests

```bash
uv run pytest backend/tests/unit -k "step or task_result or operator_report or phase_history or record_step or job_output" -v
uv run pytest backend/tests/unit -k "styrmin_deployment or reporter" -v
uv run invoke test
cd frontend && pnpm test && cd ..
uv run pytest python_sdk/tests cli/tests -v
```

Expected: the tests listed in [contracts/graphql.md](contracts/graphql.md), [contracts/operator-status.md](contracts/operator-status.md), [contracts/flow-step-reporter.md](contracts/flow-step-reporter.md) and [contracts/client-surfaces.md](contracts/client-surfaces.md) pass.

## 3. E2E scenarios

Run each with `--pdb`, as AGENTS.md requires. In a non-interactive shell, prefix with `sleep infinity |`.

| Scenario | Command (node id) | Variants | What it proves |
|---|---|---|---|
| Upgrade shows ordered steps, started tasks and result | `backend/tests/e2e/test_deploy_app.py::test_upgrade_simple_app` (extended) | api + ui | US1, US3 AS2, SC-002 |
| A hook action raises | `backend/tests/e2e/test_task_steps.py::test_hook_action_error_shows_failed_step` | api only | SC-001 type 1 |
| A command run by an action fails | `backend/tests/e2e/test_task_steps.py::test_command_output_on_failed_step` | api only | SC-001 type 2, FR-003 |
| The HelmRelease does not become Ready (image cannot be pulled) | `backend/tests/e2e/test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason` | api + ui | SC-001 type 3, US2 AS1, FR-004 |
| The operator cannot create a prerequisite | `backend/tests/e2e/test_task_steps.py::test_prerequisite_failure_shows_attempts` | api only | SC-001 type 4, FR-002 attempts |
| A `READ_ONLY` user reads the same steps | part of `test_helmrelease_failure_shows_fluxcd_reason` | api | SC-004 |
| A restore shows its steps; a failed Velero restore | `backend/tests/e2e/test_backup_restore.py` (extended) | api + ui for the step list | US6, SC-005 |

Example:

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason" -v -s --pdb 2>&1 | tee /tmp/pdb.log
```

Record for each new or changed E2E test the node id, the command, the time of the passing run, the vCluster id and kubeconfig path, and the `PASSED` line (Constitution §V).

## 4. Manual check on the dev stack (optional)

```bash
uv run invoke dev
```

1. Deploy `simple-app` 0.1.0, then upgrade to 0.2.0 from the deployment page.
2. Open the Timeline tab while the upgrade runs. Expected: the entry labelled "Upgrade" is expanded with result `RUNNING`; steps appear within 15 seconds of each change; three started tasks appear under "Run the upgrade hook".
3. When the deployment is `RUNNING`, the upgrade and its last started task (`start_components`) show `SUCCEEDED`. The earlier started tasks show `SUCCEEDED`, or `SUPERSEDED` with a link to the sibling that interrupted them.
4. Set an image override with a tag that does not exist and apply. Expected: within about five minutes the entry shows `FAILED`, the step "Install or upgrade the HelmRelease" shows FluxCD's reason and "Pods not ready: … ImagePullBackOff".
5. `styrminctl tasks get <task id>` prints the same steps. `styrminctl deployments apply -f <manifest> --wait` prints `failed <name>: step "Install or upgrade the HelmRelease" failed: …`.
6. Log in as a `READ_ONLY` user and open the same deployment. Expected: the same steps, errors and output.
