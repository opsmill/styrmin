# Quickstart: Validate helm-controller with Helm v4 Defaults

How to check, after implementation, that the agent runs helm-controller without `UseHelm3Defaults` and that users view the same task results. The contracts are in [contracts/behaviour.md](contracts/behaviour.md); the object changes are in [data-model.md](data-model.md).

## Prerequisites

- `uv sync`, `helm` and `kubectl` on PATH, Docker running, `vcluster` on PATH (see `backend/tests/e2e/conftest.py`).
- Build the server image once before E2E sessions: `docker compose build server`.
- Run each E2E shard in its own pytest session, and `api-chromium` and `ui-chromium` in separate sessions. When the command runs from a non-interactive shell, prefix it with `sleep infinity |` so `--pdb` keeps the cluster alive on failure.

## 1. Unit and chart tests

```bash
uv run pytest backend/tests/unit/test_helm_agent_crd_upgrade.py \
  backend/tests/unit/test_simple_app_hook_job.py \
  backend/tests/unit/agent/test_custom_resources.py \
  backend/tests/unit/agent/test_blocks.py -v
uv run pytest backend/tests/integration/test_label_patch_kustomize.py -v
```

Expected:

- `test_helm_controller_runs_with_helm_v4_defaults` passes: no helm-controller argument names `UseHelm3Defaults`.
- `test_fixture_controllers_run_the_chart_images[helm-controller]` passes: the fixture copy drops the gate too.
- The HelmRelease spec test passes: no `serverSideApply`, `waitStrategy` or `postRenderStrategy` key.
- The simple-app chart test passes: the hook Job renders only with `preUpgradeHookJob.enabled=true`.
- The label patch tests pass: `kubectl kustomize` adds Styrmin's labels to a `ConfigMap` and a hook `Job` that have no labels, and keeps a `Deployment`'s own labels (contract C-004a).

## 2. Helm hook Job receives the scheduling settings (FR-003, SC-004)

```bash
uv run pytest backend/tests/e2e/test_pod_scheduling.py -m "ci and shard_compute" \
  -k "api-chromium and test_scheduling_end_to_end" -v -s --pdb
```

Expected: the test passes. After the scheduling update, the pre-upgrade hook Job in the deployment's namespace has the `dedicated=batch:NoSchedule` toleration and the preferred node affinity, carries Styrmin's labels, and has completed (its pod was scheduled and ran). The vcluster has one node, so the test checks the pod's scheduling fields and completion, not placement on a second node.

## 3. Same task results for failures (FR-002, SC-001, SC-002)

```bash
# Rollback and the pods' reason (ImagePullBackOff)
uv run pytest backend/tests/e2e -m "ci and shard_task_steps" -k "api-chromium" -v -s --pdb

# Component-container guard (CI excludes this cell)
uv run pytest backend/tests/e2e -m "ci and shard_configuration" -k "api-chromium" -v -s --pdb
```

Expected:

- `test_helmrelease_failure_shows_fluxcd_reason` passes: the failed "Install or upgrade the HelmRelease" step has FluxCD's reason and the pods' `ImagePullBackOff` or `ErrImagePull`.
- `test_misnamed_container_never_added` passes: the task fails with `COMPONENT_CONTAINER_NOT_FOUND`.

The full suite runs in CI on the pull request, both variants as marked. The backup and clone shards (`shard_backup`, `shard_env_backup`) answer whether restored Helm v4 release Secrets still work.

## 4. Agent upgrade leaves existing deployments unchanged (FR-004, SC-003)

Manual check, recorded in the pull request description:

1. Install the agent chart from `develop` (gate on) on a test cluster and create a `simple-app` deployment. Wait for `Running`.
2. Record the release revision and pod start times:

   ```bash
   kubectl -n styrmin-<deployment-id> get secret -l owner=helm \
     -o custom-columns=NAME:.metadata.name,STATUS:.metadata.labels.status
   kubectl -n styrmin-<deployment-id> get pods \
     -o custom-columns=NAME:.metadata.name,START:.status.startTime
   ```

3. Upgrade the agent chart to this branch. Wait until helm-controller is ready, then for two HelmRelease intervals of the controller's own reconcile (or force one with `kubectl annotate helmrelease -n styrmin-<id> <name> reconcile.fluxcd.io/requestedAt="$(date +%s)" --overwrite`).
4. Repeat step 2. Expected: the same newest release Secret (`sh.helm.release.v1.<name>.v1`), status `deployed`, and the same pod start times.
5. Change the deployment (for example an env var) and check that the new release revision kept client-side apply: the workload's `metadata.managedFields` shows the `helm` manager (or `helm-controller`) with `operation: Update`, not `Apply`.

## 5. Documentation

Check that each page listed in spec FR-006 to FR-011 states the new behaviour, and that `uv run invoke format lint` and the docs build pass.
