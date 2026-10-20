# Quickstart: Validate the Actions of Driver Versions Loaded from a Local Directory

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

This guide lists the commands that prove the feature works. It does not describe the implementation; see the [contracts](contracts/) for that.

## Prerequisites

- `uv sync` at the repository root.
- For the E2E test: `docker` and `vcluster` on `PATH` (AGENTS.md, "Debugging E2E Tests"). No running dev stack is needed; the session fixtures create their own vCluster.
- For the manual scenarios: the dev stack (`uv run invoke dev`, or the `dev-validate` skill), and `styrminctl` signed in.

## 1. Unit and functional tests

```shell
uv run pytest backend/tests/unit/services/driver backend/tests/unit/workflows \
  backend/tests/unit/services/reconciliation backend/tests/unit/agent -q
uv run pytest backend/tests/functional/test_user_action_registration.py -q
```

Expected:

- The fingerprint at a path equals the loader's `content_hash` ([local-driver-check.md](contracts/local-driver-check.md#fingerprint-at-a-path)).
- The check step returns the directory, or raises the errors of [errors.md](contracts/errors.md) with the required parts.
- Hook resolution follows the truth table of [hook-resolution.md](contracts/hook-resolution.md#functions).
- With a real Prefect server, the five bundled drivers loaded from `driver/examples/<name>` register three actions each, and a repeated load registers only what is missing ([action-registration.md](contracts/action-registration.md#observable-results-tests)).

## 2. E2E test

Interactive shell:

```shell
uv run pytest backend/tests/e2e/test_local_driver_actions.py -v -s --pdb
```

Non-interactive shell (agent tool, background job):

```shell
sleep infinity | uv run pytest backend/tests/e2e/test_local_driver_actions.py -v -s --pdb 2>&1 | tee /tmp/local-driver-actions.log
```

Expected: every test `PASSED`.

- User story 1:
  - the setup actions run as the `hook:setup:pre` and `hook:setup:post` steps of the create task;
  - the upgrade action runs as the `hook:upgrade:core` step;
  - each marker is in its action's flow run logs.
- User story 2:
  - an edited copy of the driver at the same path in the agent pod makes `hook:setup:pre` fail with the fingerprint error;
  - a driver copied only into the server pod fails with the missing-files error;
  - both failed deployments are then deleted (FR-011).
- User story 3:
  - after the version's Prefect deployments are deleted, the upgrade request returns a failed task with a failed `hook:upgrade:core` step, and the deployment keeps its version;
  - after the driver is loaded again, the same request runs the upgrade action.

Record the evidence that Constitution §V requires: the node ID, the command, the ISO 8601 time of the passing run, the vCluster id and kubeconfig path, and the verbatim `PASSED` line.

While pytest is paused on a failure, inspect from a second shell:

```shell
export KUBECONFIG=$(ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1)
kubectl get pods -A | grep -i agent
kubectl logs -n <namespace> <agent pod> --all-containers
kubectl get jobs -A   # Jobs that execute_commands creates, named <release reference>-job
```

## 3. Manual scenarios on the dev stack

These reproduce the steps of [#372](https://github.com/opsmill/styrmin/issues/372) and the journeys of the spec.

### Registration of a bundled driver (FR-001)

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/semaphore
```

In the Prefect UI, filter deployments by the tag `directory//styrmin/drivers/semaphore`. Expected: three deployments named `User Action: pre_setup (semaphore@…)`, `User Action: post_setup (semaphore@…)` and `User Action: upgrade (semaphore@…)`.

### Setup and upgrade actions of a local driver (user story 1)

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/simple-app
uv run styrminctl deployments create simple-app 0.1.0 <environment>
uv run styrminctl tasks get <task id>
uv run styrminctl deployments update-version <deployment id> 0.2.0
uv run styrminctl tasks get <task id>
```

Expected: the create task lists "Run the setup pre-hook" and "Run the setup post-hook" as succeeded, and the upgrade task lists "Run the upgrade hook" as succeeded.

### Setup and upgrade actions of the bundled Infrahub driver (SC-001, SC-004)

This is the driver that the INFP-726 sandbox rebuild uses. It needs a cluster that can run Infrahub.

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
uv run styrminctl deployments create infrahub <application version> <environment>
uv run styrminctl tasks get <task id>
uv run styrminctl deployments update-version <deployment id> <newer application version>
uv run styrminctl tasks get <task id>
```

Pick two application versions that the driver's `supported_versions` accepts. Expected: the create task lists "Run the setup pre-hook" and "Run the setup post-hook" as succeeded. The upgrade task lists "Run the upgrade hook" as succeeded, and that hook's started tasks stop and start the Infrahub components. Repeat for `infrahub-enterprise`, `semaphore` and `slurpit` when their stacks are available.

### An edited action without an image rebuild (user story 2)

1. Edit `driver/examples/simple-app/actions.py` (for example, change a log line).
2. Load it again without rebuilding: `uv run styrminctl drivers load-local-version /styrmin/drivers/simple-app`. The dev stack bind-mounts `driver/examples` into the server and into the agent, so both read the edit.
3. Create a deployment pinned to the new driver version (`--driver-version-id`).

Expected: the task succeeds, and the edited action runs. No image rebuild is needed on the dev stack. The fingerprint error of user story 2 appears only when the agent pod holds other files than the server at the path; the E2E test of section 2 covers it.

### A version without registrations (user story 3)

1. In the Prefect UI, delete the three deployments of the loaded `simple-app` local version.
2. `uv run styrminctl deployments update-version <deployment id> 0.1.0`. Expected: the command prints `Error: task <id> failed: <message>` and exits with status 1. The message names the driver version, the hook, the mode and the action, the task's "Run the upgrade hook" step holds the same error, and `styrminctl deployments get <deployment id>` still shows `0.2.0`.
3. `uv run styrminctl drivers load-local-version /styrmin/drivers/simple-app`, then the same `update-version` command. Expected: the task succeeds and the upgrade hook step succeeded.

## 4. Checks before committing

```shell
uv run invoke format lint
```
