# E2E Evidence: Platform-Owned Env Var Injection via Post-Render

**Feature**: 017-post-render-env-vars

Each session builds its own vCluster, so the `[api-chromium]` and `[ui-chromium]` variants ran as
separate pytest sessions (the platform allows one cluster per Styrmin install, so one session
cannot set up both variants). Images were built from the working tree with
`STYRMIN_IMAGE_VER=local-fac017-us1`. The fixture finalizer deleted each vCluster after the run.

## US1 (T021)

The first attempt failed step 3 on both variants: the cleared env vars stayed in the
StyrminDeployment CR `spec.context`, because the agent merge-patched the CR. The agent now replaces
each CR spec key it writes (see research.md D-003 addendum). The passing runs below include that
fix.

### `test_component_env_var_merges_into_chart_env[api-chromium]`

- **Node ID**:
  `backend/tests/e2e/test_deployment_env_vars.py::test_component_env_var_merges_into_chart_env[api-chromium]`
- **Command**:

  ```bash
  sleep infinity | uv run pytest "backend/tests/e2e/test_deployment_env_vars.py" \
    -k "(component_env_var_merges_into_chart_env or test_us1) and api-chromium" \
    -v -s --pdb 2>&1 | tee us1-api.log
  ```

- **Timestamp**: 2026-10-02T17:54:27Z (session end)
- **vCluster**: `pytest-f7f1e964-4b9e-4599-9999-28c98bc5c4ce`, kubeconfig
  `/tmp/pytest-of-root/pytest-299/vcluster0/kubeconfig`
- **Result** (`-s` output separates the node ID from its outcome):

  ```text
  backend/tests/e2e/test_deployment_env_vars.py::test_component_env_var_merges_into_chart_env[api-chromium]
  PASSED
  =========== 2 passed, 10 deselected, 1 warning in 175.28s (0:02:55) ============
  ```

### `test_us1_deployment_level_env_var[api-chromium]`

- **Node ID**:
  `backend/tests/e2e/test_deployment_env_vars.py::test_us1_deployment_level_env_var[api-chromium]`
- **Command**: same session as above.
- **Timestamp**: 2026-10-02T17:54:27Z (session end)
- **vCluster**: `pytest-f7f1e964-4b9e-4599-9999-28c98bc5c4ce`, kubeconfig
  `/tmp/pytest-of-root/pytest-299/vcluster0/kubeconfig`
- **Result**:

  ```text
  backend/tests/e2e/test_deployment_env_vars.py::test_us1_deployment_level_env_var[api-chromium] PASSED
  ```

### `test_component_env_var_merges_into_chart_env[ui-chromium]`

- **Node ID**:
  `backend/tests/e2e/test_deployment_env_vars.py::test_component_env_var_merges_into_chart_env[ui-chromium]`
- **Command**:

  ```bash
  sleep infinity | uv run pytest "backend/tests/e2e/test_deployment_env_vars.py" \
    -k "(component_env_var_merges_into_chart_env or test_us1) and ui-chromium" \
    -v -s --pdb 2>&1 | tee us1-ui.log
  ```

- **Timestamp**: 2026-10-02T17:55:31Z (session end)
- **vCluster**: `pytest-ca4ac041-9578-461e-bae1-b4e8ee0846a0`, kubeconfig
  `/tmp/pytest-of-root/pytest-300/vcluster0/kubeconfig`
- **Result**:

  ```text
  backend/tests/e2e/test_deployment_env_vars.py::test_component_env_var_merges_into_chart_env[ui-chromium]
  PASSED
  ====== 1 passed, 1 skipped, 10 deselected, 1 warning in 187.27s (0:03:07) ======
  ```

`test_us1_deployment_level_env_var[ui-chromium]` is skipped by its `api_only` marker (the UI
driver's `update_deployment` accepts only the `scheduling` sub-tree).

## US2 (T025)

Both scenarios carry `api_only` (the UI driver's `update_deployment` accepts only the `scheduling`
sub-tree), so only `[api-chromium]` applies. Images were built from the working tree with
`STYRMIN_IMAGE_VER=local-fac017-us2`. The fixture finalizer deleted the vCluster after the run.

### `test_us2_environment_level_env_var_propagates_to_all_deployments[api-chromium]`

- **Node ID**:
  `backend/tests/e2e/test_deployment_env_vars.py::test_us2_environment_level_env_var_propagates_to_all_deployments[api-chromium]`
- **Command**:

  ```bash
  sleep infinity | STYRMIN_IMAGE_VER=local-fac017-us2 uv run pytest \
    backend/tests/e2e/test_deployment_env_vars.py \
    -k "(us2 or us3) and api-chromium" -v -s --pdb 2>&1 | tee us2-api.log
  ```

- **Timestamp**: 2026-10-02T18:04:38Z (session end)
- **vCluster**: `pytest-00174285-1643-4ec4-893a-b1ad5e3c0475`, kubeconfig
  `/tmp/pytest-of-root/pytest-301/vcluster0/kubeconfig`
- **Result** (`-s` output separates the node ID from its outcome):

  ```text
  backend/tests/e2e/test_deployment_env_vars.py::test_us2_environment_level_env_var_propagates_to_all_deployments[api-chromium]
  PASSED
  =========== 2 passed, 10 deselected, 1 warning in 204.95s (0:03:24) ============
  ```

### `test_us3_per_component_env_var_overrides_deployment_level[api-chromium]`

- **Node ID**:
  `backend/tests/e2e/test_deployment_env_vars.py::test_us3_per_component_env_var_overrides_deployment_level[api-chromium]`
- **Command**: same session as above.
- **Timestamp**: 2026-10-02T18:04:38Z (session end)
- **vCluster**: `pytest-00174285-1643-4ec4-893a-b1ad5e3c0475`, kubeconfig
  `/tmp/pytest-of-root/pytest-301/vcluster0/kubeconfig`
- **Result**:

  ```text
  backend/tests/e2e/test_deployment_env_vars.py::test_us3_per_component_env_var_overrides_deployment_level[api-chromium] PASSED
  ```

## SC-003 (T043)

The scenario carries `api_only` (it asserts through kr8s and the Prefect HTTP endpoints), so only
`[api-chromium]` applies; it is the module's only node. It reads the `styrmin-task-manager`
Deployment's Ready pods and asserts their `prefect-server` container keeps the chart default
`PREFECT_UI_SERVE_BASE=/` and carries `PREFECT_SERVER_ANALYTICS_ENABLED=True` (the driver's
`enable_analytics` default). Images were built from the working tree with
`STYRMIN_IMAGE_VER=local-fac017-sc003`. The fixture finalizer deleted the vCluster after the run.

### `test_infrahub_task_manager_service_exposes_prefect_ui[api-chromium]`

- **Node ID**:
  `backend/tests/e2e/test_infrahub_services.py::test_infrahub_task_manager_service_exposes_prefect_ui[api-chromium]`
- **Command**:

  ```bash
  sleep infinity | STYRMIN_IMAGE_VER=local-fac017-sc003 uv run pytest \
    backend/tests/e2e/test_infrahub_services.py -k api-chromium -v -s --pdb 2>&1 \
    | tee sc003-api.log
  ```

- **Timestamp**: 2026-10-02T18:37:59Z (session end)
- **vCluster**: `pytest-8fa6471b-06dc-45d5-9e67-4cf799778fb9`, kubeconfig
  `/tmp/pytest-of-root/pytest-314/vcluster0/kubeconfig`
- **Result** (`-s` output separates the node ID from its outcome):

  ```text
  backend/tests/e2e/test_infrahub_services.py::test_infrahub_task_manager_service_exposes_prefect_ui[api-chromium]
  PASSED
  ============ 1 passed, 1 deselected, 1 warning in 174.30s (0:02:54) ============
  ```

## Final module run (T064)

The full `test_deployment_env_vars.py` module ran on the final change set, one pytest session per
entrypoint. Images were built from the working tree with `STYRMIN_IMAGE_VER=local-fac017-final`.
The fixture finalizer deleted each vCluster after the run. Timestamps are session end.

`test_us5_orphan_visible_across_driver_upgrade` is skipped on both entrypoints by its own
`@pytest.mark.skip` (it needs a driver version that renames a component; unchanged by this
feature). On `[ui-chromium]`, every scenario except the US1 merge test is skipped by its
`api_only` marker.

### `[api-chromium]` session

- **Command**:

  ```bash
  sleep infinity | STYRMIN_IMAGE_VER=local-fac017-final uv run pytest \
    backend/tests/e2e/test_deployment_env_vars.py -k "api-chromium" -v -s --pdb 2>&1 \
    | tee env-vars-api.log
  ```

- **Timestamp**: 2026-10-02T19:27:57Z
- **vCluster**: `pytest-057dbcc2-d07f-4c10-9320-137206420609`, kubeconfig
  `/tmp/pytest-of-root/pytest-324/vcluster0/kubeconfig`
- **Results** (`-s` output separates the first node ID from its outcome):

  ```text
  backend/tests/e2e/test_deployment_env_vars.py::test_component_env_var_merges_into_chart_env[api-chromium]
  PASSED
  backend/tests/e2e/test_deployment_env_vars.py::test_us1_deployment_level_env_var[api-chromium] PASSED
  backend/tests/e2e/test_deployment_env_vars.py::test_us2_environment_level_env_var_propagates_to_all_deployments[api-chromium] PASSED
  backend/tests/e2e/test_deployment_env_vars.py::test_us3_per_component_env_var_overrides_deployment_level[api-chromium] PASSED
  backend/tests/e2e/test_deployment_env_vars.py::test_us4_driver_env_var_docs_surfaced_via_graphql[api-chromium] PASSED
  backend/tests/e2e/test_deployment_env_vars.py::test_us5_orphan_visible_across_driver_upgrade[api-chromium] SKIPPED
  ====== 5 passed, 1 skipped, 6 deselected, 1 warning in 266.65s (0:04:26) =======
  ```

### `[ui-chromium]` session

- **Command**:

  ```bash
  sleep infinity | STYRMIN_IMAGE_VER=local-fac017-final uv run pytest \
    backend/tests/e2e/test_deployment_env_vars.py -k "ui-chromium" -v -s --pdb 2>&1 \
    | tee env-vars-ui.log
  ```

- **Timestamp**: 2026-10-02T19:31:07Z
- **vCluster**: `pytest-f54a3ede-aef0-44e2-a1ad-e827534fe481`, kubeconfig
  `/tmp/pytest-of-root/pytest-328/vcluster0/kubeconfig`
- **Results**:

  ```text
  backend/tests/e2e/test_deployment_env_vars.py::test_component_env_var_merges_into_chart_env[ui-chromium]
  PASSED
  backend/tests/e2e/test_deployment_env_vars.py::test_us1_deployment_level_env_var[ui-chromium] SKIPPED
  backend/tests/e2e/test_deployment_env_vars.py::test_us2_environment_level_env_var_propagates_to_all_deployments[ui-chromium] SKIPPED
  backend/tests/e2e/test_deployment_env_vars.py::test_us3_per_component_env_var_overrides_deployment_level[ui-chromium] SKIPPED
  backend/tests/e2e/test_deployment_env_vars.py::test_us4_driver_env_var_docs_surfaced_via_graphql[ui-chromium] SKIPPED
  backend/tests/e2e/test_deployment_env_vars.py::test_us5_orphan_visible_across_driver_upgrade[ui-chromium] SKIPPED
  ====== 1 passed, 5 skipped, 6 deselected, 1 warning in 202.18s (0:03:22) =======
  ```

### SC-003 re-run on the final change set

- **Node ID**:
  `backend/tests/e2e/test_infrahub_services.py::test_infrahub_task_manager_service_exposes_prefect_ui[api-chromium]`
- **Command**:

  ```bash
  sleep infinity | STYRMIN_IMAGE_VER=local-fac017-final uv run pytest \
    backend/tests/e2e/test_infrahub_services.py -k "api-chromium" -v -s --pdb 2>&1 \
    | tee infrahub-services-api.log
  ```

- **Timestamp**: 2026-10-02T19:34:24Z
- **vCluster**: `pytest-d7711c10-4c5b-4fc5-a7b2-be2476c54389`, kubeconfig
  `/tmp/pytest-of-root/pytest-330/vcluster0/kubeconfig`
- **Result**:

  ```text
  backend/tests/e2e/test_infrahub_services.py::test_infrahub_task_manager_service_exposes_prefect_ui[api-chromium]
  PASSED
  ============ 1 passed, 1 deselected, 1 warning in 178.63s (0:02:58) ============
  ```

### Container overrides regression (simple-app chart and HelmRelease replace)

`test_deployment_container_overrides.py` is not touched by this feature, but it deploys simple-app,
whose chart and values changed, and its clear step relies on the HelmRelease spec replace. Every
scenario is `api_only`, so one `[api-chromium]` session covers it.

The first session (vCluster `pytest-e13fa617-cc32-44a0-921c-cd7b2f2c5b4f`) failed
`test_us4_invalid_overrides_rejected` with `ScenarioTimeout` (status `pending` after 480s). That
step sends two `updateDeployment` calls back to back (`command: ["sh", "-c", ""]`, then the restore).
The deployment row stored the restore, but the two apply-state flows ran concurrently and wrote
the StyrminDeployment CR 24 ms apart (19:32:14.734 and 19:32:14.758); the stale write landed last,
so the CR and HelmRelease kept the crash-looping command. Last-writer-wins between concurrent
flows does not depend on this feature (merge-patch or replace both apply whichever write lands
last), and the test is unchanged. The re-run below passed every scenario.

- **Command**:

  ```bash
  sleep infinity | STYRMIN_IMAGE_VER=local-fac017-final uv run pytest \
    backend/tests/e2e/test_deployment_container_overrides.py -k "api-chromium" -v -s --pdb 2>&1 \
    | tee container-overrides-api-run2.log
  ```

- **Timestamp**: 2026-10-02T19:45:52Z
- **vCluster**: `pytest-08e2c2ba-f0ff-4014-b733-abded28275cf`, kubeconfig
  `/tmp/pytest-of-root/pytest-331/vcluster0/kubeconfig`
- **Results**:

  ```text
  backend/tests/e2e/test_deployment_container_overrides.py::test_us1_override_args_on_server[api-chromium]
  PASSED
  backend/tests/e2e/test_deployment_container_overrides.py::test_us2_command_independent_of_args[api-chromium] PASSED
  backend/tests/e2e/test_deployment_container_overrides.py::test_us3_clear_override_falls_back_to_chart_default[api-chromium] PASSED
  backend/tests/e2e/test_deployment_container_overrides.py::test_us4_invalid_overrides_rejected[api-chromium] PASSED
  backend/tests/e2e/test_deployment_container_overrides.py::test_us6_driver_declares_overridable_component[api-chromium] PASSED
  ============ 5 passed, 5 deselected, 1 warning in 192.62s (0:03:12) ============
  ```

### E2E modules deploying drivers whose values changed, not run

`test_deploy_semaphore.py` (semaphore), `test_backup_restore_databases.py` (db-test),
`test_infrahub_backup_restore.py` (infrahub), and the other simple-app modules are untouched by
this feature and were not run here; CI's shards cover them. No E2E module deploys slurpit or
infrahub-mcp.

## Per-key HelmRelease apply (post-review change)

The HelmRelease apply moved from a whole-`spec` replace to per-key replace (ADR-057 §6). Images
were built from the working tree with `STYRMIN_IMAGE_VER=local-fac017-perkey`. Each session was
launched as `sleep infinity | uv run pytest <module> -k "<selector>" -v -s --pdb` from a runner
script, and the runner killed the process group after the summary line.

| Test id | Passed at (session end) | vCluster | Kubeconfig | Pass line |
|---|---|---|---|---|
| `backend/tests/e2e/test_deployment_env_vars.py::test_component_env_var_merges_into_chart_env[api-chromium]` | 2026-10-02T23:23:30Z | `pytest-5d90518f-dea6-4faa-811c-6ce354860503` | `/tmp/pytest-of-root/pytest-333/vcluster0/kubeconfig` | `PASSED` |
| `...test_deployment_env_vars.py::test_us1_deployment_level_env_var[api-chromium]` | same | same | same | `PASSED` |
| `...test_deployment_env_vars.py::test_us2_environment_level_env_var_propagates_to_all_deployments[api-chromium]` | same | same | same | `PASSED` |
| `...test_deployment_env_vars.py::test_us3_per_component_env_var_overrides_deployment_level[api-chromium]` | same | same | same | `PASSED` |
| `...test_deployment_env_vars.py::test_us4_driver_env_var_docs_surfaced_via_graphql[api-chromium]` | same | same | same | `PASSED` |
| `backend/tests/e2e/test_deployment_env_vars.py::test_component_env_var_merges_into_chart_env[ui-chromium]` | 2026-10-02T23:26:45Z | `pytest-e1ddb8b8-3b5c-4a59-a751-191f767615e4` | `/tmp/pytest-of-root/pytest-334/vcluster0/kubeconfig` | `PASSED` |
| `backend/tests/e2e/test_deployment_container_overrides.py::test_us1_*`, `test_us2_command_independent_of_args`, `test_us3_clear_override_falls_back_to_chart_default`, `test_us6_driver_declares_overridable_component` `[api-chromium]` | 2026-10-02T23:42:39Z | `pytest-19deba43-349b-4fc2-9b4e-388fa2040c59` | `/tmp/pytest-of-root/pytest-336/vcluster0/kubeconfig` | `PASSED` each |

Session summaries:

- env-vars api: `====== 5 passed, 1 skipped, 6 deselected, 1 warning in 254.16s (0:04:14) =======`
  (us5 is skipped by its own marker).
- env-vars ui: `====== 1 passed, 5 skipped, 6 deselected, 1 warning in 185.93s (0:03:05) =======`
  (the others are `api_only`).
- container-overrides api, us4 excluded:
  `============ 4 passed, 6 deselected, 1 warning in 169.39s (0:02:49) ============`

`test_deployment_container_overrides.py::test_us4_invalid_overrides_rejected[api-chromium]`
failed in a first container-overrides session (`pytest-f8553fa8-c26e-4e69-8407-9f77644c62e7`,
`pytest-335`). It is the same race seen in the final-gates run, now confirmed on the live
cluster while pdb was paused:

- The test sends `command: ["sh","-c",""]` and then immediately clears the override. Two
  `apply_state` flows were scheduled 67 ms apart (23:29:16.855Z and 23:29:16.922Z) and both
  started at 23:29:21.36Z.
- The final StyrminDeployment CR carried `spec.instanceId: 444d6e14-…`, the instance of the
  flow with the broken command, so the earlier mutation's write landed last.
- The deployment never reached `running` (the pod crash-loops on `sh -c ""`).

Flows for one deployment are not serialized, and the last CR write wins under merge-patch and
under per-key replace alike. The HelmRelease only mirrors the CR, so the apply-mode change
cannot cause or fix this failure. This is a pre-existing race and should get its own issue.
