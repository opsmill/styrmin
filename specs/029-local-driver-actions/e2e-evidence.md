# E2E Evidence: Run the Actions of Driver Versions Loaded from a Local Directory

**Spec**: [spec.md](spec.md) | **Tasks**: [tasks.md](tasks.md)

Constitution §V requires, for each new or modified E2E test, the pytest node ID, the exact command, the ISO 8601 time of the passing run, the cluster identifier with its kubeconfig path, and the verbatim `PASSED` line. Each run below is one pytest session on its own vCluster, started from a non-interactive shell.

With `-s`, pytest prints the fixture output between the node ID and its result, so the node ID and `PASSED` are on different lines of the log. Both lines are quoted below, with the vCluster's colour codes removed.

## T022: user story 1, the setup and upgrade actions run

- Node ID: `backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade[api-chromium]`. The `[ui-chromium]` variant is skipped by its `api_only` marker.
- Command:

  ```shell
  docker compose build server
  sleep infinity | uv run pytest "backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade" -v -s --pdb 2>&1 | tee /tmp/029-us1.log
  ```

- Start: 2026-10-19T09:29:38Z. End: 2026-10-19T09:32:49Z (189.13 s).
- vCluster: `pytest-d834b579-2ea0-4c71-a522-2155ec2208c2`, kubeconfig `/tmp/pytest-of-ubuntu/pytest-36/vcluster0/kubeconfig`. Torn down at the end of the session.
- Styrmin image: `registry.opsmill.io/opsmill/styrmin:latest`, built from the working tree by the `styrmin_deployment` fixture (image id `sha256:4da3ee4a419d6b07bf0062460561a8de314ea52175c83810aed25f964f9f78bf`). It holds the fixture driver at `/source/backend/tests/e2e/fixtures/drivers/local-actions`.
- Result lines:

  ```text
  backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade[api-chromium]
  PASSED
  backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade[ui-chromium] SKIPPED
  ============= 1 passed, 1 skipped, 5 warnings in 189.13s (0:03:09) =============
  ```

## T021: the module that `_kubectl_cp` moved out of

T021 moved `_kubectl_cp` from `test_driver_reload_identity.py` into `backend/tests/e2e/helpers/drivers.py`. The module was run once to check that it still passes. Its local driver now registers its actions when it is loaded (T015).

- Node ID: `backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change`.
- Command:

  ```shell
  sleep infinity | uv run pytest "backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change" -v -s --pdb 2>&1 | tee /tmp/029-reload-identity.log
  ```

- Start: 2026-10-19T09:33:31Z. End: 2026-10-19T09:34:43Z (70.33 s).
- vCluster: `pytest-1a67f13d-fe75-4e45-97d3-3f97f6f0b7cc`, kubeconfig `/tmp/pytest-of-ubuntu/pytest-37/vcluster0/kubeconfig`. Torn down at the end of the session.
- Styrmin image: `registry.opsmill.io/opsmill/styrmin:latest`, built from the same working tree by the `styrmin_deployment` fixture (image id `sha256:b296355cc891c8735f1828966cfd466f20421324a447351389fd8a778c17b856`).
- Result lines:

  ```text
  backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change
  PASSED
  =================== 1 passed, 2 warnings in 70.33s (0:01:10) ===================
  ```

## T028: user story 2, a changed or missing local driver fails the hook step

- Node IDs:
  - `backend/tests/e2e/test_local_driver_actions.py::test_changed_local_driver_fails_with_the_fingerprint_error[api-chromium]`
  - `backend/tests/e2e/test_local_driver_actions.py::test_driver_missing_from_the_action_image_fails_with_the_missing_files_error[api-chromium]`

  The `[ui-chromium]` variants are skipped by their `api_only` marker.
- Command. Another worktree ran its own E2E session on the same Docker daemon at the same time, and `docker compose build` tags `registry.opsmill.io/opsmill/styrmin:latest` in every worktree. `STYRMIN_IMAGE_VER` gives this session's image its own tag, as CI does:

  ```shell
  export STYRMIN_IMAGE_VER=fac-029-us2
  docker compose build server
  sleep infinity | uv run pytest "backend/tests/e2e/test_local_driver_actions.py" -k "fingerprint_error or missing_files_error" -v -s --pdb 2>&1 | tee /tmp/029-us2.log
  ```

- Start: 2026-10-19T10:08:36Z. End: 2026-10-19T10:11:01Z (144.04 s).
- vCluster: `pytest-c29f4705-ae6a-468f-997d-b48a5203b94d`, kubeconfig `/tmp/pytest-of-ubuntu/pytest-58/vcluster0/kubeconfig`. Torn down at the end of the session.
- Styrmin image: `registry.opsmill.io/opsmill/styrmin:fac-029-us2`, built from the working tree by the `styrmin_deployment` fixture (image id `sha256:86f64ec589cd6c09516178acf2b8dcfc18ce8ec2600b1df79d96b8e25c05f2f7`). The server, the agent and the default image of the work pool `user-work-pool` all use it.
- Result lines:

  ```text
  backend/tests/e2e/test_local_driver_actions.py::test_changed_local_driver_fails_with_the_fingerprint_error[api-chromium]
  PASSED
  backend/tests/e2e/test_local_driver_actions.py::test_driver_missing_from_the_action_image_fails_with_the_missing_files_error[api-chromium] PASSED
  backend/tests/e2e/test_local_driver_actions.py::test_changed_local_driver_fails_with_the_fingerprint_error[ui-chromium] SKIPPED
  backend/tests/e2e/test_local_driver_actions.py::test_driver_missing_from_the_action_image_fails_with_the_missing_files_error[ui-chromium] SKIPPED
  ====== 2 passed, 2 skipped, 2 deselected, 6 warnings in 144.04s (0:02:24) ======
  ```

### What the earlier runs of T028 found

- The first run (2026-10-19T09:52Z, vCluster `pytest-b7e7278c-06cb-4654-867d-9783219bafa6`) followed T026 and T027 as written: the actions of `local-actions-check` named the image `local-actions-check:<session hex>`, which held an edited copy of the driver at the path. The `hook:setup:pre` step failed, but the agent log showed that the agent's Prefect `ProcessWorker` (`entrypoint/combined.py`) ran the action in the agent pod and not in that image. The check raised `DriverFilesNotFoundError` "The driver files are not at /tmp/local-actions-check-9f03826a in the image local-actions-check:9f03826a", although that image held the files. An action's `image:` has no effect while the agent's process worker runs the actions. The test now copies the edited driver into the agent pod at the path instead, and no image is built.
- The same run showed that the step error held only `Process exited with status code: 1. Process exited with a general error.`: the agent logged "Crashed flow run … has no ERROR log". Prefect 3.8.6 runs pull steps in a workspace supervisor that prints the traceback of a failed step and logs nothing in the flow run. `check_local_driver` now logs its error at `ERROR` in the flow run before it raises (unit test `test_check_logs_its_error_in_the_flow_run_before_it_raises`).
- The second run (2026-10-19T10:01Z, vCluster `pytest-e173abdf-4542-45df-8fac-75b0915c9121`) passed both tests, but `deleteDeployment` returned "An internal error occurred" for both deployments. Their create failed at the `hook:setup:pre` step, which runs before the `StyrminDeployment` is written, so `delete_deployment` patches a custom resource that does not exist and raises `CustomResourceNotFound`. The tests now create their deployments in an environment of their own, `check_environment_id`, whose deletion deletes them.
- The third run (2026-10-19T10:06Z, vCluster `pytest-39d24c66-7f95-4347-a9ff-1bee13a90328`) stopped in the `chart_server` fixture: the vCluster node could not create the network of the chart server pod (`FailedCreatePodSandBox`). The next run, above, passed.

## T028: the module whose helper moved

T028 moved `_styrmin_pod_name` from `test_driver_reload_identity.py` into `backend/tests/e2e/helpers/drivers.py`, next to the new `_agent_pod_name`, and gave `_kubectl_cp` a `container` argument. The module was run once to check that it still passes.

- Node ID: `backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change`.
- Command:

  ```shell
  export STYRMIN_IMAGE_VER=fac-029-us2
  sleep infinity | uv run pytest "backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change" -v -s --pdb 2>&1 | tee /tmp/029-reload-identity.log
  ```

- Start: 2026-10-19T10:11:21Z. End: 2026-10-19T10:12:39Z (76.58 s).
- vCluster: `pytest-80890510-0ade-47f0-85fa-d40a0f057303`, kubeconfig `/tmp/pytest-of-ubuntu/pytest-59/vcluster0/kubeconfig`. Torn down at the end of the session.
- Styrmin image: `registry.opsmill.io/opsmill/styrmin:fac-029-us2`, built from the working tree by the `styrmin_deployment` fixture (image id `sha256:e5fa0bf6223f429400e111cdbd519504a9a868a1bbcc97d4a914f4f62c41c829`).
- Result lines:

  ```text
  backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change
  PASSED
  =================== 1 passed, 2 warnings in 76.58s (0:01:16) ===================
  ```
