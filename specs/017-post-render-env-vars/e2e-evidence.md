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
