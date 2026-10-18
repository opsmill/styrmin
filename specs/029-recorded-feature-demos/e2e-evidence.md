# E2E Evidence: Recorded Demos of Four Styrmin Features

## Overview

This file records each run of an E2E test that spec 029 changes, as Constitution §V requires. Spec 029 changes one E2E test: the FR-016 alias check in `test_environment_clone_lifecycle` ([`backend/tests/e2e/test_backup_restore.py`](../../backend/tests/e2e/test_backup_restore.py), task T005).

## FR-016 alias check fails on both variants

The check failed in the `api-chromium` run (T006) and in the `ui-chromium` run (T007), as research [R-013](research.md#r-013-a-clones-alias-services-point-to-the-source) expected. In both runs:

- The counterpart deployment's namespace held one `ExternalName` alias Service, so the check did not pass or fail on an empty list.
- That alias has the same name, the same `styrmin.io/deployment-id` label and the same `spec.externalName` as the alias in the source deployment's namespace. This matches research R-013: the cross-target restore copies the source namespace, alias Services included.
- Its `spec.externalName` points to the namespace of the test's second source deployment, the peer `env-clone-<suffix>` that the clone did not select. So the short name `envclone<suffix>`, looked up from the counterpart's namespace, resolves to a deployment of the source environment. The runs did not test this with a DNS lookup.

The created environment held two deployments in each run: the counterpart and the internal ingress-controller deployment, which the agent log names "Internal deployment" with `ingress-controller:1.0.0`. The check counts both as namespaces of the clone.

The `kubectl` output taken while pdb was paused shows the clone namespaces as `Terminating` or already gone. Post-mortem pdb starts after the test's `finally` block, and that block deletes the created environments and the peer deployment. The alias watcher, which listed the alias Services every 20 seconds during each run, shows the state before that cleanup.

### Run 1: `api-chromium` (T006)

- Node ID: `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]`
- Server image built before the session with `export STYRMIN_IMAGE_VER=spec029-alias-check && docker compose build server`.
- Command, from the repository root, with `STYRMIN_IMAGE_VER=spec029-alias-check` exported. The `exec 3<` form keeps pdb's standard input open, as `sleep infinity |` does, and lets the script stop the run by the PID of its own `sleep`:

  ```bash
  exec 3< <(sleep infinity); spid=$!
  uv run pytest backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle \
    -m "ci and shard_env_backup" -k api-chromium -v -s --pdb \
    --basetemp=/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-demo-beta-presentation-bhshh/c3d2eae7-0490-4cdf-a9f4-4b6551ffd707/scratchpad/pt-api-chromium \
    <&3 > /tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-demo-beta-presentation-bhshh/c3d2eae7-0490-4cdf-a9f4-4b6551ffd707/scratchpad/e2e-api-chromium.log 2>&1
  ```

- Start: `2026-10-18T09:48:35Z`. End: `2026-10-18T09:53:46Z` (pytest exit code 2, after the run was stopped in pdb).
- vCluster: `pytest-83fdfc69-7769-494a-b6af-7faf87b978d3`, deleted by the session teardown at 09:53:45.
- Kubeconfig: `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-demo-beta-presentation-bhshh/c3d2eae7-0490-4cdf-a9f4-4b6551ffd707/scratchpad/pt-api-chromium/vcluster0/kubeconfig`
- Deployments:
  - source deployment `cf237321-461d-41e3-b0ca-0b79a45d45ee`;
  - peer that the clone did not select `5691a1af-da00-4f15-8420-396442a20d6d`;
  - counterpart deployment `53b1b2ab-a423-4b03-a571-1896fbd7cb88`;
  - internal deployment of the created environment `133da29c-527f-4d73-aa52-ba96bd1b8491`.
- Result line, verbatim:

  ```text
  FAILED backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]
  ============ 1 failed, 1 deselected, 1 warning in 309.30s (0:05:09) ============
  ```

- Failure output, verbatim:

  ```text
  E           AssertionError: an alias in the clone points outside the clone's namespaces ['styrmin-133da29c-527f-4d73-aa52-ba96bd1b8491', 'styrmin-53b1b2ab-a423-4b03-a571-1896fbd7cb88'] (FR-016): envclone76472b72 -> envclone76472b72.styrmin-5691a1af-da00-4f15-8420-396442a20d6d.svc.cluster.local
  E           assert not {'envclone76472b72': 'envclone76472b72.styrmin-5691a1af-da00-4f15-8420-396442a20d6d.svc.cluster.local'}

  backend/tests/e2e/test_backup_restore.py:2527: AssertionError
  ```

- Alias watcher at `2026-10-18T09:52:17Z`, before the cleanup (columns: namespace, name, `styrmin.io/deployment-id`, `spec.externalName`):

  ```text
  styrmin-53b1b2ab-a423-4b03-a571-1896fbd7cb88   envclone76472b72   5691a1af-da00-4f15-8420-396442a20d6d   envclone76472b72.styrmin-5691a1af-da00-4f15-8420-396442a20d6d.svc.cluster.local
  styrmin-5691a1af-da00-4f15-8420-396442a20d6d   simple-app         cf237321-461d-41e3-b0ca-0b79a45d45ee   simple-app.styrmin-cf237321-461d-41e3-b0ca-0b79a45d45ee.svc.cluster.local
  styrmin-cf237321-461d-41e3-b0ca-0b79a45d45ee   envclone76472b72   5691a1af-da00-4f15-8420-396442a20d6d   envclone76472b72.styrmin-5691a1af-da00-4f15-8420-396442a20d6d.svc.cluster.local
  ```

- `kubectl get svc -A -l styrmin.io/service-alias=true -o wide` while pdb was paused, at `2026-10-18T09:53:03Z` (the counterpart's namespace was `Terminating`, the peer's namespace was gone):

  ```text
  NAMESPACE                                      NAME               TYPE           CLUSTER-IP   EXTERNAL-IP                                                                       PORT(S)   AGE    SELECTOR
  styrmin-53b1b2ab-a423-4b03-a571-1896fbd7cb88   envclone76472b72   ExternalName   <none>       envclone76472b72.styrmin-5691a1af-da00-4f15-8420-396442a20d6d.svc.cluster.local   <none>    48s    <none>
  styrmin-cf237321-461d-41e3-b0ca-0b79a45d45ee   envclone76472b72   ExternalName   <none>       envclone76472b72.styrmin-5691a1af-da00-4f15-8420-396442a20d6d.svc.cluster.local   <none>    113s   <none>
  ```

- Logs: the pytest log above and the alias watcher log `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-demo-beta-presentation-bhshh/c3d2eae7-0490-4cdf-a9f4-4b6551ffd707/scratchpad/aliases-api-chromium.log`.

### Run 2: `ui-chromium` (T007)

- Node ID: `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]`
- Command: the same as run 1, in its own session, with `-k ui-chromium`, `--basetemp=<scratchpad>/pt-ui-chromium` and the log `<scratchpad>/e2e-ui-chromium.log`, where `<scratchpad>` is `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-demo-beta-presentation-bhshh/c3d2eae7-0490-4cdf-a9f4-4b6551ffd707/scratchpad`.
- Start: `2026-10-18T09:53:57Z`. End: `2026-10-18T09:59:22Z` (pytest exit code 2, after the run was stopped in pdb).
- vCluster: `pytest-955a852e-6a0e-4cbf-9431-f0c23fb2fb83`, deleted by the session teardown at 09:59:21.
- Kubeconfig: `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-demo-beta-presentation-bhshh/c3d2eae7-0490-4cdf-a9f4-4b6551ffd707/scratchpad/pt-ui-chromium/vcluster0/kubeconfig`
- Deployments:
  - source deployment `2f4a8bd3-b848-4c55-b2b2-d9043473a5a4`;
  - peer that the clone did not select `c4aad9e8-6e44-4747-8a19-2094005624e5`;
  - counterpart deployment `7839c2d7-99b6-45f8-b6b9-03449596d2bc`;
  - internal deployment of the created environment `3e592126-03cc-4781-b926-3e34efdf11f3`.
- Result line, verbatim:

  ```text
  FAILED backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]
  ============ 1 failed, 1 deselected, 1 warning in 322.98s (0:05:22) ============
  ```

- Failure output, verbatim:

  ```text
  E           AssertionError: an alias in the clone points outside the clone's namespaces ['styrmin-3e592126-03cc-4781-b926-3e34efdf11f3', 'styrmin-7839c2d7-99b6-45f8-b6b9-03449596d2bc'] (FR-016): envclone14c3c868 -> envclone14c3c868.styrmin-c4aad9e8-6e44-4747-8a19-2094005624e5.svc.cluster.local
  E           assert not {'envclone14c3c868': 'envclone14c3c868.styrmin-c4aad9e8-6e44-4747-8a19-2094005624e5.svc.cluster.local'}

  backend/tests/e2e/test_backup_restore.py:2527: AssertionError
  ```

- Alias watcher at `2026-10-18T09:58:19Z`, before the cleanup (same columns as run 1):

  ```text
  styrmin-2f4a8bd3-b848-4c55-b2b2-d9043473a5a4   envclone14c3c868   c4aad9e8-6e44-4747-8a19-2094005624e5   envclone14c3c868.styrmin-c4aad9e8-6e44-4747-8a19-2094005624e5.svc.cluster.local
  styrmin-7839c2d7-99b6-45f8-b6b9-03449596d2bc   envclone14c3c868   c4aad9e8-6e44-4747-8a19-2094005624e5   envclone14c3c868.styrmin-c4aad9e8-6e44-4747-8a19-2094005624e5.svc.cluster.local
  ```

- `kubectl get svc -A -l styrmin.io/service-alias=true -o wide` while pdb was paused, at `2026-10-18T09:59:01Z` (the counterpart's namespace and the peer's namespace were already gone):

  ```text
  NAMESPACE                                      NAME               TYPE           CLUSTER-IP   EXTERNAL-IP                                                                       PORT(S)   AGE     SELECTOR
  styrmin-2f4a8bd3-b848-4c55-b2b2-d9043473a5a4   envclone14c3c868   ExternalName   <none>       envclone14c3c868.styrmin-c4aad9e8-6e44-4747-8a19-2094005624e5.svc.cluster.local   <none>    2m20s   <none>
  ```

- Logs: `<scratchpad>/e2e-ui-chromium.log` and `<scratchpad>/aliases-ui-chromium.log`.

## UI smoke tests pass with Playwright 1.64 (T011)

Spec 029 does not change `test_ui_smoke.py`. This run checks that the upgrade from Playwright 1.58.0 to 1.64.0 (task T002), which changes the Chromium build of the UI variant, does not break the UI E2E suite. The installed version during the run was `playwright` 1.64.0.

All seven tests of the file carry `shard_general` (module-level `pytestmark`), so the filter selected all seven `ui-chromium` variants and left out the seven `api-chromium` variants.

- Node IDs, all in `backend/tests/e2e/test_ui_smoke.py`:
  - `test_deployment_header_shows_driver_name[ui-chromium]`
  - `test_deploy_form_shows_driver_label_after_selection[ui-chromium]`
  - `test_pods_tab_copy_logs_command[ui-chromium]`
  - `test_driver_detail_inspects_versions_via_tabs[ui-chromium]`
  - `test_driver_logo_description_and_links_render[ui-chromium]`
  - `test_browser_tab_title_names_page_and_product[ui-chromium]`
  - `test_cluster_detail_shows_full_configuration[ui-chromium]`
- Server image: `STYRMIN_IMAGE_VER=spec029-alias-check`, the image built for runs 1 and 2 above. The backend has not changed since that build.
- Command, from the repository root, with `STYRMIN_IMAGE_VER=spec029-alias-check` exported, where `<scratchpad>` is `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-demo-beta-presentation-bhshh/c3d2eae7-0490-4cdf-a9f4-4b6551ffd707/scratchpad`:

  ```bash
  exec 3< <(sleep infinity); spid=$!
  uv run pytest backend/tests/e2e/test_ui_smoke.py -m "ci and shard_general" -k ui-chromium \
    -v -s --pdb --basetemp=<scratchpad>/pt-ui-smoke <&3 > <scratchpad>/e2e-ui-smoke.log 2>&1
  rc=$?; exec 3<&-; kill "$spid"
  ```

- Start: `2026-10-18T10:04:45Z`. End: `2026-10-18T10:07:20Z` (pytest exit code 0).
- vCluster: `pytest-da1a29b4-fcc3-40f3-9e7f-6ecec17b56a8`, deleted by the session teardown at 10:07:18.
- Kubeconfig: `<scratchpad>/pt-ui-smoke/vcluster0/kubeconfig`
- Result lines, verbatim. The `PASSED` of the first test is printed on its own line, because the session fixtures write their output between the node ID and the result:

  ```text
  backend/tests/e2e/test_ui_smoke.py::test_deploy_form_shows_driver_label_after_selection[ui-chromium] PASSED
  backend/tests/e2e/test_ui_smoke.py::test_pods_tab_copy_logs_command[ui-chromium] PASSED
  backend/tests/e2e/test_ui_smoke.py::test_driver_detail_inspects_versions_via_tabs[ui-chromium] PASSED
  backend/tests/e2e/test_ui_smoke.py::test_driver_logo_description_and_links_render[ui-chromium] PASSED
  backend/tests/e2e/test_ui_smoke.py::test_browser_tab_title_names_page_and_product[ui-chromium] PASSED
  backend/tests/e2e/test_ui_smoke.py::test_cluster_detail_shows_full_configuration[ui-chromium] PASSED
  ============ 7 passed, 7 deselected, 1 warning in 152.46s (0:02:32) ============
  ```

- The one warning is a `DeprecationWarning` from `kr8s` (`asyncio.iscoroutinefunction`), not from Playwright.
- Log: `<scratchpad>/e2e-ui-smoke.log`.

## Decision on the defect (T008)

The defect is filed as [#530](https://github.com/opsmill/styrmin/issues/530), "a clone keeps the source's service aliases, which point to the source environment's namespaces". The maintainer decided on 2026-10-18:

- The product fix is made in its own issue and pull request, not in spec 029.
- In a clone of some of the deployments, an alias for a peer that was not cloned is removed, not left pointing to the source. So the FR-016 assertion stays as written: no alias in the clone may point outside the clone.
- Phase 6 (demo 4, the environment clone) waits for the fix. Phases 3, 4, 5, 7 (for demos 1 to 3), 8 and 9 go on.

Until the check passes, the T005 commit `472fe403` stays on the branch and is not pushed, and the check is not marked `xfail` (critique X1). Before the branch is pushed, `472fe403` must be moved off it, because later commits sit on top of it.
