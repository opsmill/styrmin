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

## T036: user story 3, a missing registration fails the hook step and loading again repairs it

- Node IDs:
  - `backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade[api-chromium]`
  - `backend/tests/e2e/test_local_driver_actions.py::test_missing_registration_fails_and_loading_again_repairs_it[api-chromium]`

  The user story 3 test reuses the deployment that the user story 1 test upgrades to `0.2.0`, so both run in one session, in this order. The test fails with a message that names the user story 1 test when the deployment is not running at `0.2.0`. The `[ui-chromium]` variants are skipped by their `api_only` marker.
- What the test does:
  - It deletes the three Prefect deployments tagged `directory//source/backend/tests/e2e/fixtures/drivers/local-actions`.
  - The version change to `0.1.0`, pinned to the driver version, returns a `failed` task of type `upgrade_instance`. Its `hook:upgrade:core` step fails with the `ActionNotRegisteredError` text, and the deployment stays running at `0.2.0` with the same driver version.
  - Loading the driver again returns the same driver version and registers the three actions again.
  - The same version change returns a new task that succeeds with a succeeded `hook:upgrade:core` step. The `upgrade` marker is in the logs of the action's flow run, logged after the second request, and the deployment runs `0.1.0`.
  - The test deletes the deployment at its end.
- Command. `STYRMIN_IMAGE_VER` gives this session's image its own tag, because other worktrees build `registry.opsmill.io/opsmill/styrmin:latest` on the same Docker daemon:

  ```shell
  export STYRMIN_IMAGE_VER=fac-029-us3
  docker compose build server
  sleep infinity | uv run pytest "backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade" "backend/tests/e2e/test_local_driver_actions.py::test_missing_registration_fails_and_loading_again_repairs_it" -v -s --pdb 2>&1 | tee /tmp/029-us3.log
  ```

- Start: 2026-10-19T11:42:03Z. End: 2026-10-19T11:45:34Z (209.85 s). The first run passed.
- vCluster: `pytest-533af663-ec83-4989-b8fc-cb01dbd0955b`, kubeconfig `/tmp/pytest-of-ubuntu/pytest-69/vcluster0/kubeconfig`. Torn down at the end of the session.
- Styrmin image: `registry.opsmill.io/opsmill/styrmin:fac-029-us3`, built from the working tree by the `styrmin_deployment` fixture (image id `sha256:23ea8fa8736a33d209c5380387416f6b1e865abea33e3f1a063cfa1ea8afb155`). It holds the backend changes of T029, T031 and T033.
- Result lines:

  ```text
  backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade[api-chromium]
  PASSED
  backend/tests/e2e/test_local_driver_actions.py::test_missing_registration_fails_and_loading_again_repairs_it[api-chromium] PASSED
  backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade[ui-chromium] SKIPPED
  backend/tests/e2e/test_local_driver_actions.py::test_missing_registration_fails_and_loading_again_repairs_it[ui-chromium] SKIPPED
  ============= 2 passed, 2 skipped, 6 warnings in 209.85s (0:03:29) =============
  ```

## T052: deleting the deployment of a create that failed before its `StyrminDeployment`

The two user story 2 tests no longer create their deployments in an environment of their own. Each test creates its deployment in the scenario environment and ends by deleting it with `deleteDeployment` (`client.deployments.delete`). It asserts that the call returns a `delete_deployment` task with the status `success`, that the deployment reaches `deleted` with `deletedAt` set, and that the `resource:delete-request` and `operator:teardown` steps of the delete task succeeded.

### Reproduction before the fix

- Command, with the changed tests and the backend of commit `958d562a`:

  ```shell
  export STYRMIN_IMAGE_VER=fac-029-delete-repro
  sleep infinity | uv run pytest "backend/tests/e2e/test_local_driver_actions.py" -k "fingerprint_error or missing_files_error" -v -s --pdb > /tmp/029-delete-repro.log 2>&1
  ```

- Start: 2026-10-19T11:52:36Z. vCluster `pytest-6ea87d3a-0b6e-4cab-9aa3-3ce1f40849ba`, kubeconfig `/tmp/pytest-of-ubuntu/pytest-70/vcluster0/kubeconfig`. Image `registry.opsmill.io/opsmill/styrmin:fac-029-delete-repro` (`sha256:ef91014460af96372548aee1053e979308ab861af58652b898b336c874e071be`), removed afterwards.
- Every assertion of `test_changed_local_driver_fails_with_the_fingerprint_error` before the deletion passed. `client.deployments.delete` raised `OperationFailedError: An internal error occurred`.
- The deployment's namespace did not exist in the vCluster (`kubectl get ns` listed only the namespace of the environment's ingress controller), so the deployment had no `StyrminDeployment`. The server log held this traceback (shortened):

  ```text
  ERROR | styrmin_backend.api.errors - Unexpected GraphQL error: Custom resource styrmindeployments/styrmin-f8f9cbad-37da-4280-9561-dd6d3c0a9426 not found in namespace styrmin-f8f9cbad-37da-4280-9561-dd6d3c0a9426
  kubernetes_asyncio.client.exceptions.ApiException: (404)
  HTTP response body: {"kind":"Status",...,"message":"styrmindeployments.styrmin.io \"styrmin-f8f9cbad-37da-4280-9561-dd6d3c0a9426\" not found","reason":"NotFound",...,"code":404}
  During handling of the above exception, another exception occurred:
    File "/source/backend/styrmin_backend/api/schema/mutation.py", line 950, in delete_deployment
    File "/source/backend/styrmin_backend/services/deployment.py", line 2061, in delete_deployment
      await _patch_deletion_requested(deployment_id)
    File "/source/backend/styrmin_backend/services/deployment.py", line 2244, in _patch_deletion_requested
    File "/source/backend/styrmin_backend/agent/service/kubernetes/primitives.py", line 304, in patch_custom_resource
  styrmin_backend.agent.service.kubernetes.exceptions.CustomResourceNotFound: Custom resource styrmindeployments/styrmin-f8f9cbad-37da-4280-9561-dd6d3c0a9426 not found in namespace styrmin-f8f9cbad-37da-4280-9561-dd6d3c0a9426
  ```

- The session was stopped at the `(Pdb)` prompt by ending its `sleep infinity`; pytest tore the vCluster down.

### Passing run with the fix

- Node IDs:
  - `backend/tests/e2e/test_local_driver_actions.py::test_changed_local_driver_fails_with_the_fingerprint_error[api-chromium]`
  - `backend/tests/e2e/test_local_driver_actions.py::test_driver_missing_from_the_action_image_fails_with_the_missing_files_error[api-chromium]`

  The `[ui-chromium]` variants are skipped by their `api_only` marker.
- Command:

  ```shell
  export STYRMIN_IMAGE_VER=fac-029-delete
  docker compose build server
  sleep infinity | uv run pytest "backend/tests/e2e/test_local_driver_actions.py" -k "fingerprint_error or missing_files_error" -v -s --pdb 2>&1 | tee /tmp/029-delete.log
  ```

- Start: 2026-10-19T11:57:35Z. End: 2026-10-19T12:00:45Z (187.39 s). The first run passed.
- The first test's deployment was the last application of the scenario environment, so its deletion started the removal of the environment's ingress controller (#252). The second test's create was rejected once with "The dedicated ingress controller is being removed" and `_create_pinned_deployment` retried it.
- vCluster: `pytest-f517511d-c385-492c-91ea-0a1391948996`, kubeconfig `vcluster0/kubeconfig` under the session's base directory in `/tmp/pytest-of-ubuntu/`. The log does not print the directory, and pytest removed it once later sessions on the machine created newer ones; its number is not known. Torn down at the end of the session ("Successfully deleted virtual cluster pytest-f517511d-c385-492c-91ea-0a1391948996").
- Styrmin image: `registry.opsmill.io/opsmill/styrmin:fac-029-delete`, built from the working tree with the fix (image id `sha256:4515a4839b55971fb8b10b162004c795b30e7bd06277d8581c592efbe4b26442`).
- Result lines:

  ```text
  backend/tests/e2e/test_local_driver_actions.py::test_changed_local_driver_fails_with_the_fingerprint_error[api-chromium]
  PASSED
  backend/tests/e2e/test_local_driver_actions.py::test_driver_missing_from_the_action_image_fails_with_the_missing_files_error[api-chromium]
  PASSED
  backend/tests/e2e/test_local_driver_actions.py::test_changed_local_driver_fails_with_the_fingerprint_error[ui-chromium] SKIPPED
  backend/tests/e2e/test_local_driver_actions.py::test_driver_missing_from_the_action_image_fails_with_the_missing_files_error[ui-chromium] SKIPPED
  ====== 2 passed, 2 skipped, 4 deselected, 6 warnings in 187.39s (0:03:07) ======
  ```

## The image of the final runs, T048 and T049

Both sessions ran against commit `03c8e6a0`, the final code of the branch, with no change between them.

- Tag: `registry.opsmill.io/opsmill/styrmin:fac-029-final`. `STYRMIN_IMAGE_VER` gives the image its own tag, because other worktrees build `registry.opsmill.io/opsmill/styrmin:latest` on the same Docker daemon.
- Built once before T048 with `docker compose build server` (image id `sha256:7cd3f50672b9bdf43da60cd8f616d173003f6856a3315d5ec6b1cc20ea006005`, created 2026-10-19T12:34:22Z). The image holds the fixture driver at `/source/backend/tests/e2e/fixtures/drivers/local-actions` (`actions.py`, `driver.styrmin.yml`, `values.j2.yml`).
- The `styrmin_deployment` fixture runs `docker compose build` again at the start of each session. It builds the three services `server`, `agent-operator` and `task-worker` from `docker/Dockerfile` into the same tag, from the build cache: the image keeps its creation time, 2026-10-19T12:34:22Z, and the id of the tag changes with each build. After T048 the tag's id was `sha256:a5d2827e9e65d39787cc22d48adf6500612493cd87b360a4769a23f37c0d6f6e`; after T049 it was `sha256:d78ac3d2c72082b578dc3fb84c9c1268fcec1227dd6b9d98c98c43453cc6dadd`.

## T048: the whole module in one session

- Node IDs:
  - `backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade[api-chromium]`
  - `backend/tests/e2e/test_local_driver_actions.py::test_changed_local_driver_fails_with_the_fingerprint_error[api-chromium]`
  - `backend/tests/e2e/test_local_driver_actions.py::test_driver_missing_from_the_action_image_fails_with_the_missing_files_error[api-chromium]`
  - `backend/tests/e2e/test_local_driver_actions.py::test_missing_registration_fails_and_loading_again_repairs_it[api-chromium]`

  The `[ui-chromium]` variants are skipped by their `api_only` marker.
- Command:

  ```shell
  export STYRMIN_IMAGE_VER=fac-029-final
  docker compose build server
  sleep infinity | uv run pytest backend/tests/e2e/test_local_driver_actions.py -v -s --pdb 2>&1 | tee /tmp/029-e2e.log
  ```

- Start: 2026-10-19T12:34:33Z. End: 2026-10-19T12:38:51Z (255.77 s). The first run passed, with no retry.
- vCluster: `pytest-0107b83d-5044-48a4-b574-12344a53a33a`, kubeconfig `/tmp/pytest-of-ubuntu/pytest-81/vcluster0/kubeconfig`. Torn down at the end of the session ("Successfully deleted virtual cluster pytest-0107b83d-5044-48a4-b574-12344a53a33a").
- Styrmin image: `registry.opsmill.io/opsmill/styrmin:fac-029-final` (see the image section above).
- Result lines:

  ```text
  backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade[api-chromium]
  PASSED
  backend/tests/e2e/test_local_driver_actions.py::test_changed_local_driver_fails_with_the_fingerprint_error[api-chromium] PASSED
  backend/tests/e2e/test_local_driver_actions.py::test_driver_missing_from_the_action_image_fails_with_the_missing_files_error[api-chromium] PASSED
  backend/tests/e2e/test_local_driver_actions.py::test_missing_registration_fails_and_loading_again_repairs_it[api-chromium] PASSED
  backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade[ui-chromium] SKIPPED
  backend/tests/e2e/test_local_driver_actions.py::test_changed_local_driver_fails_with_the_fingerprint_error[ui-chromium] SKIPPED
  backend/tests/e2e/test_local_driver_actions.py::test_driver_missing_from_the_action_image_fails_with_the_missing_files_error[ui-chromium] SKIPPED
  backend/tests/e2e/test_local_driver_actions.py::test_missing_registration_fails_and_loading_again_repairs_it[ui-chromium] SKIPPED
  ============= 4 passed, 4 skipped, 8 warnings in 255.77s (0:04:15) =============
  ```

## T049: the E2E tests whose path changed, in one session

These tests run hooks, load drivers or read task steps, so the change from a skipped hook to a failed hook step could break them (SC-002). Every selected test passed, so none of them relied on a skipped hook. No code was changed.

- Node IDs:
  - `backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change`
  - `backend/tests/e2e/test_driver_version_reselection.py::test_driver_version_reselection[api-chromium]`
  - `backend/tests/e2e/test_driver_version_reselection.py::test_drivers_of_one_repository_keep_their_own_actions[api-chromium]`
  - `backend/tests/e2e/test_driver_version_reselection.py::test_drivers_list_caps_long_histories[api-chromium]`, skipped by its `ui_only` marker
  - `backend/tests/e2e/test_task_steps.py::test_hook_action_error_shows_failed_step[api-chromium]`
  - `backend/tests/e2e/test_task_steps.py::test_command_output_on_failed_step[api-chromium]`
  - `backend/tests/e2e/test_task_steps.py::test_prerequisite_failure_shows_attempts[api-chromium]`
  - `backend/tests/e2e/test_task_steps.py::test_update_recreates_a_missing_namespace[api-chromium]`
  - `backend/tests/e2e/test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason[api-chromium]`
  - `backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[api-chromium]`
  - `backend/tests/e2e/test_deploy_app.py::test_upgrade_simple_app[api-chromium]`
  - `backend/tests/e2e/test_deploy_app.py::test_deployment_records_created_by[api-chromium]`
  - `backend/tests/e2e/test_deploy_app.py::test_deployed_service_external_url_includes_port[api-chromium]`
  - `backend/tests/e2e/test_deploy_app.py::test_environment_views_hide_ingress_controller[api-chromium]`, skipped by its `ui_only` marker

  `-k "not ui-chromium"` deselected the 13 `[ui-chromium]` variants: pytest collected 27 items and selected 14.
- Command:

  ```shell
  export STYRMIN_IMAGE_VER=fac-029-final
  sleep infinity | uv run pytest backend/tests/e2e/test_driver_reload_identity.py backend/tests/e2e/test_driver_version_reselection.py backend/tests/e2e/test_task_steps.py backend/tests/e2e/test_deploy_app.py -k "not ui-chromium" -v -s --pdb 2>&1 | tee /tmp/029-regression.log
  ```

- Start: 2026-10-19T12:39:23Z. End: 2026-10-19T12:52:51Z (805.63 s). The first run passed, with no retry.
- vCluster: `pytest-f6232844-6e71-483f-8f12-8dcd7e6d0670`, kubeconfig `/tmp/pytest-of-ubuntu/pytest-82/vcluster0/kubeconfig`. Torn down at the end of the session ("Successfully deleted virtual cluster pytest-f6232844-6e71-483f-8f12-8dcd7e6d0670").
- Styrmin image: `registry.opsmill.io/opsmill/styrmin:fac-029-final` (see the image section above).
- Result lines:

  ```text
  backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change
  PASSED
  backend/tests/e2e/test_driver_version_reselection.py::test_driver_version_reselection[api-chromium]
  PASSED
  backend/tests/e2e/test_driver_version_reselection.py::test_drivers_of_one_repository_keep_their_own_actions[api-chromium] PASSED
  backend/tests/e2e/test_driver_version_reselection.py::test_drivers_list_caps_long_histories[api-chromium] SKIPPED
  backend/tests/e2e/test_task_steps.py::test_hook_action_error_shows_failed_step[api-chromium] PASSED
  backend/tests/e2e/test_task_steps.py::test_command_output_on_failed_step[api-chromium] PASSED
  backend/tests/e2e/test_task_steps.py::test_prerequisite_failure_shows_attempts[api-chromium] PASSED
  backend/tests/e2e/test_task_steps.py::test_update_recreates_a_missing_namespace[api-chromium] PASSED
  backend/tests/e2e/test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason[api-chromium] PASSED
  backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[api-chromium] PASSED
  backend/tests/e2e/test_deploy_app.py::test_upgrade_simple_app[api-chromium]
  PASSED
  backend/tests/e2e/test_deploy_app.py::test_deployment_records_created_by[api-chromium] PASSED
  backend/tests/e2e/test_deploy_app.py::test_deployed_service_external_url_includes_port[api-chromium] PASSED
  backend/tests/e2e/test_deploy_app.py::test_environment_views_hide_ingress_controller[api-chromium] SKIPPED
  ===== 12 passed, 2 skipped, 13 deselected, 8 warnings in 805.63s (0:13:25) =====
  ```

## T050: the quickstart sections

T050 ran the sections of [quickstart.md](quickstart.md) on 2026-10-19, at commit `db886826`. The code is that of commit `03c8e6a0`: the two later commits change only `e2e-evidence.md` and `tasks.md` (`git diff --stat 03c8e6a0..HEAD`). T050 added and modified no test, and changed no code.

### Which sections and scenarios ran

- Section 1, the unit and functional tests: ran. Both commands passed.
- Section 2, the E2E module: not run again, because no code changed since T048 ran the whole module at commit `03c8e6a0` (2026-10-19T12:34:33Z to 12:38:51Z, `4 passed, 4 skipped`; see [T048](#t048-the-whole-module-in-one-session)).
- Section 3, the manual scenarios on the dev stack:
  - "Registration of a bundled driver": ran with `semaphore`, and matched. The registration of `infrahub` was checked too.
  - "Setup and upgrade actions of a local driver": ran. As written, with `/styrmin/drivers/simple-app`, the create cannot install the chart on the dev stack. With a copy of the driver whose chart location points to a chart server in the dev cluster, the create and the upgrade matched.
  - "Setup and upgrade actions of the bundled Infrahub driver": the `infrahub` registration ran; its create and upgrade did not run (reason below). Of the drivers that the scenario says to repeat it with, `semaphore` ran and matched; `infrahub-enterprise` and `slurpit` did not run.
  - "An edited action without an image rebuild": ran, with the driver copy. The task succeeded instead of failing, because of the bind mount (below). The second half of the scenario (rebuild, restart, load, create) did not run, because nothing had failed.
  - "A version without registrations": ran. Steps 1 and 2 matched. In step 3 the upgrade action ran but failed on a Job left by the earlier upgrade; after that Job was deleted, a request for `0.2.0` ran the upgrade action to success.
- Section 4, `uv run invoke format lint`: ran (result below).

### Section 1: the unit and functional tests

- `uv run pytest backend/tests/unit/services/driver backend/tests/unit/workflows backend/tests/unit/services/reconciliation backend/tests/unit/agent -q`
  - First run, 2026-10-19T12:55:49Z to 12:56:07Z, exit status 0. Its output was cut with `tail`, and the output written at process exit (dulwich progress lines and a Prefect logging message) pushed the summary line out, so the command was run again.
  - Second run, 2026-10-19T12:56:41Z to 12:56:59Z, exit status 0:

    ```text
    1123 passed, 33 warnings in 13.23s
    ```

- `uv run pytest backend/tests/functional/test_user_action_registration.py -q`, 2026-10-19T12:56:07Z to 12:56:20Z:

  ```text
  11 passed in 9.67s
  ```

### Section 3: how the dev stack was brought up

The stack followed phases 0 and 2 to 5 of the `dev-validate` skill. Its phase 1 (the whole test suites) is covered by T047 and section 1, and its phases 6 to 8 (Semaphore at `2.16.47`, the Kubernetes resources, the frontend) were replaced by the quickstart scenarios.

- At 2026-10-19T12:55:54Z, before the start: no container ran on the Docker daemon, ports 8000 and 4200 were free (`ss -ltnp`), and `vcluster list --driver docker` listed no vCluster.
- Differences from the skill, so that no state of another worktree changes:
  - The vCluster is named `fac-029-dev` instead of `styrmin`: `vcluster create fac-029-dev --upgrade --driver=docker --connect=false` (12:59:11Z to 12:59:31Z, "Successfully created virtual cluster fac-029-dev"), then `vcluster connect fac-029-dev --driver=docker`.
  - `KUBECONFIG` points to a file in the session's scratchpad directory instead of `~/.kube/config`. The agent container mounts `${KUBECONFIG}`; the API server is at `https://localhost:10635`.
  - `STYRMIN_IMAGE_VER=fac-029-dev`, so that `docker compose build` tags `registry.opsmill.io/opsmill/styrmin:fac-029-dev` and not `latest`. The build (12:59:40Z to 12:59:41Z) came from the build cache of the T048 image: id `sha256:a145f9cced7dc72e2c4c0f8275d90b5da69fee8c2a68352f1f4f8e628df85460`, created 2026-10-19T12:34:22Z. The server, the task worker and the agent bind-mount `./backend` and `./driver/examples`, so they ran the working tree.
  - `styrminctl` used `STYRMIN_TOKEN`, an admin token from the `login` mutation, instead of `styrminctl login`, which writes a token file in the home directory.
- `helm upgrade --install agent helm/agent -n styrmin --create-namespace --set agent.enabled=false --dependency-update` (the `cluster.init` task), 12:59:43Z to 13:00:01Z: `STATUS: deployed`.
- `docker compose up -d`, 13:00:06Z to 13:00:39Z. At 13:00:44Z, `curl -sf http://localhost:8000/health` returned `{"status":"healthy"}` and `http://localhost:4200/api/health` returned 200. The agent logged `Prefect worker 'ProcessWorker 2191a024-6543-452b-8beb-660ef2b4aa61' started for pool 'user-work-pool'` at 13:00:28Z.
- `uv run invoke dev.bootstrap`, 13:01:29Z: created the cluster `local` and the environment `local`, and loaded `infrahub` (`Driver version loaded: 5 (id: 5ef2b894-0e27-4548-927c-c875b285cffa)`) and `semaphore`.

Three changes to the environment were needed to run the scenarios. Each is a problem of the dev stack, not of this feature; this branch changes neither `docker-compose.yml` nor the `dev` and `cluster` tasks.

1. The flow runs of the agent could not reach the Styrmin API. The work pool `user-work-pool` sets `STYRMIN_URL_API=http://host.docker.internal:8000` for each flow run (from `STYRMIN_URL_API_K8S` in `docker-compose.yml`). The agent container uses the host network, and on this Linux host `host.docker.internal` does not resolve. The agent logged `Could not record STARTED for step hook:setup:pre: [Errno -2] Name or service not known` for each step. At 13:03:48Z the line `127.0.0.1 host.docker.internal` was added to `/etc/hosts` in the agent container only; `curl http://host.docker.internal:8000/health` then returned 200 there.
2. The services phase failed with `Failed to apply Middleware/auth: (404)`: the dev bootstrap creates the cluster without `dedicated_ingress` and installs no Traefik, so the Traefik CRDs are missing. The E2E session creates its cluster with `dedicated_ingress`, and only the demo flow runs `cluster.traefik`. From 13:10:33Z to 13:10:49Z, Traefik was installed with the values of `cluster.traefik`, with `--repo` instead of `helm repo add` so that the Helm repository list in the home directory stays unchanged: `helm upgrade --install traefik traefik --repo https://helm.traefik.io/traefik -n styrmin --create-namespace -f dev/local/traefik-values.yaml --set service.type=ClusterIP --take-ownership --wait --timeout 5m`. 25 `traefik.io` CRDs were then present.
3. `deleteDeployment` fails on the dev stack. At 13:04:00Z it returned `{"data": null, "errors": [{"message": "An internal error occurred", "path": ["deleteDeployment"], "extensions": {"code": "INTERNAL_ERROR"}}]}`, and the server logged `Failed to load in-cluster Kubernetes config. Are you running inside a Kubernetes pod? Error: Service host/port is not set.` from `_patch_deletion_requested`: the server container has no Kubernetes configuration. A failed deployment keeps its service name, so the later creates used new environments on the same cluster: `quickstart`, `quickstart-2` and `quickstart-3`.

### Scenario: registration of a bundled driver (FR-001)

- 13:01:15Z, before the bootstrap loaded any driver: `uv run styrminctl drivers load-local-version /styrmin/drivers/semaphore`. Exit status 0. Driver version `2` (`90d261f0-ae14-4732-8fc9-cc3f1b248f57`), fingerprint `0565277`, actions `upgrade`, `pre_setup` and `post_setup`.
- The deployments were read from the Prefect API (`POST /api/deployments/filter`, tag `directory//styrmin/drivers/semaphore`) instead of the Prefect UI filter:

  ```text
  3 deployments with tag directory//styrmin/drivers/semaphore
  User Action: post_setup (semaphore@0565277 7d8720f07207) | actions.py:post_setup | user-work-pool
  User Action: pre_setup (semaphore@0565277 7d8720f07207) | actions.py:pre_setup | user-work-pool
  User Action: upgrade (semaphore@0565277 7d8720f07207) | actions.py:upgrade | user-work-pool
  ```

  Each has one pull step, `styrmin_backend.workflows.local_driver.check_local_driver`, with `directory: /styrmin/drivers/semaphore`, the 64-character `content_hash` and the three file names. This matches the quickstart.
- The bootstrap loaded `semaphore` again at 13:01:29Z. The load returned the same driver version, and the three deployments kept their `updated` times of 13:01:15Z, so the repeated load wrote nothing to Prefect.
- `infrahub`, loaded by the bootstrap: three deployments with the tag `directory//styrmin/drivers/infrahub`, such as `User Action: pre_setup (infrahub@751f957 a93c0a65fecd)`.

### Scenario: setup and upgrade actions of a local driver (user story 1)

As written, with the bundled driver:

- 13:01:56Z: `uv run styrminctl drivers load-local-version /styrmin/drivers/simple-app` loaded `4@ec23d5c` (`6f38937c-a724-4d54-a392-d65d888331e7`) and registered three deployments. `uv run styrminctl deployments create simple-app 0.1.0 local --cluster local` returned deployment `fd2b219a-8a80-4ded-b9af-5659c77ba7d8` and task `ca713579-369a-4c6d-ae69-1a1c27ceb415`.
- The agent log shows that the check passed and both setup actions ran: `The driver files at /styrmin/drivers/simple-app have the provenance fingerprint ec23d5c of the driver version. The action runs from /styrmin/drivers/simple-app.`, `Executing simple-app pre-setup...`, `Executing simple-app post-setup...`. The steps were not recorded (change 1 above was not made yet), so at 13:02:27Z the task read `create_instance success SUCCEEDED` with only "Plan the changes".
- The create cannot complete on the dev stack: the driver's chart location is `simple-app`, with no repository, so the operator creates a HelmRepository with an empty URL and fails with `HelmRepository.source.toolkit.fluxcd.io "styrmin-d20cfde1-f458-4bff-9261-7d534b881663" is invalid: spec.url: Required value`. The deployment ended `failed`. The E2E session rewrites this location to its chart server (`backend/tests/e2e/conftest.py`).

With a driver whose chart the dev cluster can fetch:

- Setup, 13:04:24Z to 13:04:35Z:
  - A chart server built from `backend/tests/e2e/fixtures/chart-server/Dockerfile` as `chart-server:fac-029-dev` and deployed in the dev cluster from that fixture's `deployment.yaml`.
  - A copy of `actions.py`, `driver.styrmin.yml` and `values.j2.yml` of `driver/examples/simple-app` at `driver/examples/simple-app-dev/`, with the chart location `http://chart-server.default.svc.cluster.local:8080/simple-app`. The copy was untracked and was deleted at the end. Like the bundled driver, it reaches the server and the agent through the `./driver/examples` bind mount, at `/styrmin/drivers/simple-app-dev`.
  - Two `simple-app` driver versions were loaded, so each create and version change pinned `--driver-version-id` instead of relying on latest-wins.
- 13:04:35Z: `uv run styrminctl drivers load-local-version /styrmin/drivers/simple-app-dev` loaded `4@839887d` (`4e28f237-60b8-4c5d-856c-e69c9169bfc5`) and registered three deployments.
- 13:04:41Z: the create in the environment `local` returned `Error: Service name 'simple-app' already exists in environment` (the failed deployment above holds the name; change 3 above).
- 13:04:49Z, environment `quickstart`, before Traefik was installed: the create of task `8bb254a5-13b4-4144-9698-053be8781428` ran "Run the setup pre-hook" and "Run the setup post-hook" to success, then failed at 13:09:33Z on "Create services and middlewares" with `Deployment did not reach Ready within 270s (phase: CreatingServices)` (change 2 above).
- 13:11:10Z, environment `quickstart-2`: `uv run styrminctl deployments create simple-app 0.1.0 quickstart-2 --cluster local --driver-version-id 4e28f237-60b8-4c5d-856c-e69c9169bfc5` returned deployment `5aed98ba-fb67-4e69-8933-74d4bc3a839b` and task `4140ded0-0b41-4846-b94d-92ff2454ceaa`. `uv run styrminctl tasks get 4140ded0-0b41-4846-b94d-92ff2454ceaa` at 13:12:26Z:

  ```text
  │ 4140ded0-0b41-4846-b94d-92ff2454ceaa │ create_instance │ success │ SUCCEEDED │ All states completed. │ 5aed98ba-fb67-4e69-8933-74d4bc3a839b │
  │ Plan the changes                     │ SUCCEEDED │ <1s      │ 1        │
  │ Run the setup pre-hook               │ SUCCEEDED │ 4s       │ 1        │
  │ Write the StyrminDeployment resource │ SUCCEEDED │ <1s      │ 1        │
  │ Create network policies and secrets  │ SUCCEEDED │ <1s      │ 1        │
  │ Run the setup post-hook              │ SUCCEEDED │ 4s       │ 1        │
  │ Install or upgrade the HelmRelease   │ SUCCEEDED │ 59s      │ 1        │
  │ Create services and middlewares      │ SUCCEEDED │ <1s      │ 1        │
  │ Wait for the deployment to be ready  │ SUCCEEDED │ <1s      │ 1        │
  ```

  `uv run styrminctl deployments get 5aed98ba-…`: `Status: running`, `Application version: 0.1.0@839887d`.
- 13:12:34Z: `uv run styrminctl deployments update-version 5aed98ba-fb67-4e69-8933-74d4bc3a839b 0.2.0 --driver-version-id 4e28f237-60b8-4c5d-856c-e69c9169bfc5` returned task `66d6d11a-7d6f-4014-bf8e-a2775d115a15`. At 13:13:25Z the task read `upgrade_instance │ success │ SUCCEEDED`, with "Run the upgrade hook" `SUCCEEDED` (29 s) and the started tasks `stop_components` (`SUPERSEDED`) and `start_components` (`SUCCEEDED`). The deployment: `Status: running`, `Application version: 0.2.0@839887d`.
- The agent log holds the lines of the three actions: `Executing simple-app pre-setup...` (13:11:21Z), `Executing simple-app post-setup...` (13:11:25Z), `Starting simple-app upgrade...` (13:12:45Z) and `Simple-app upgrade to 0.2.0 complete.` (13:13:11Z).
- Result: with the driver copy, the create task lists "Run the setup pre-hook" and "Run the setup post-hook" as succeeded and the upgrade task lists "Run the upgrade hook" as succeeded, as the quickstart expects.

### Scenario: setup and upgrade actions of the bundled Infrahub driver and the other bundled drivers

- `infrahub`: the registration ran (above). The create and the upgrade did not run. The driver declares a server that requests 4 CPUs, two task workers, Neo4j and Redis, and its chart (`oci://registry.opsmill.io/opsmill/chart/infrahub` 4.33.2) adds its own services. The machine has 8 CPUs and 30 GB of memory, and the E2E sessions of other worktrees use the same Docker daemon; such a stack would slow them down.
- `infrahub-enterprise` and `slurpit`: did not run, for the same reason; they were not loaded.
- `semaphore`, in the environment `local`:
  - 13:19:07Z: `uv run styrminctl deployments create semaphore 2.16.47 local --cluster local` returned deployment `4a41839e-9315-4ff4-8c2e-403e707a6e44` and task `5d560d27-a4b6-4b56-a664-678f40f9892b`. At 13:20:22Z: `create_instance success SUCCEEDED`, with "Run the setup pre-hook" and "Run the setup post-hook" `SUCCEEDED`. The deployment: `Status: running`, `Application version: 2.16.47@0565277`.
  - 13:20:29Z: `uv run styrminctl deployments update-version 4a41839e-9315-4ff4-8c2e-403e707a6e44 2.16.48` returned task `f3129247-f7c5-4775-bd75-85202dad2655`. At 13:21:25Z: `upgrade_instance success SUCCEEDED`, with "Run the upgrade hook" `SUCCEEDED`. The deployment: `Status: running`, `Application version: 2.16.48@0565277`. The agent log holds `Starting Semaphore upgrade...` and `Semaphore upgrade to 2.16.48 complete.`

### Scenario: an edited action without an image rebuild (user story 2)

- 13:16:51Z: `driver/examples/simple-app-dev/actions.py` was changed so that `pre_setup` logs `Executing simple-app pre-setup (edited for T050)`. The server and the agent containers both showed the edited line at `/styrmin/drivers/simple-app-dev/actions.py` at once. `uv run styrminctl drivers load-local-version /styrmin/drivers/simple-app-dev` loaded a new driver version, `4@0e6066d` (`2eaa9f12-116e-481f-ba66-c77a27d12861`).
- 13:16:56Z, environment `quickstart-3`: `uv run styrminctl deployments create simple-app 0.1.0 quickstart-3 --cluster local --driver-version-id 2eaa9f12-116e-481f-ba66-c77a27d12861` returned deployment `e0755ce6-0e19-42fd-ba0d-f0ca15ea2737` and task `86b3da38-e74f-4b62-97a8-d5ff184af1fa`.
- Observed at 13:18:16Z: `create_instance success SUCCEEDED`, with "Run the setup pre-hook" `SUCCEEDED`. The agent log: `The driver files at /styrmin/drivers/simple-app-dev have the provenance fingerprint 0e6066d of the driver version.` and `Executing simple-app pre-setup (edited for T050)`.
- Why the task did not fail: the actions run as processes in the agent container, not in a Job in an image, and the dev stack bind-mounts `./driver/examples` into the agent container as it does into the server container. The agent reads the same edited files that the server loaded, so their provenance fingerprint is the one of the new driver version. The quickstart's expected failure on "Run the setup pre-hook" happens only when the files at the path in the agent differ from the files the server loaded, as in the T028 E2E test, which copies a changed `actions.py` into the agent pod.
- The second half of the scenario (`docker compose build`, restart, load again, create again) did not run, because the first create already succeeded.

### Scenario: a version without registrations (user story 3)

On deployment `5aed98ba-fb67-4e69-8933-74d4bc3a839b`, at `0.2.0` after the user story 1 scenario:

1. 13:13:45Z: the three Prefect deployments of `4@839887d` were deleted through the Prefect API (`DELETE /api/deployments/<id>`, status 204 each) instead of the Prefect UI. No deployment was left with the tag `directory//styrmin/drivers/simple-app-dev`.
2. 13:13:45Z: `uv run styrminctl deployments update-version 5aed98ba-fb67-4e69-8933-74d4bc3a839b 0.1.0 --driver-version-id 4e28f237-60b8-4c5d-856c-e69c9169bfc5` returned `Status: failed` and task `79230ae3-6d71-4858-aa6f-e8034d5ebfe2`. The task has one step, "Run the upgrade hook", `FAILED`:

   ```text
   ActionNotRegisteredError: Driver version simple-app 4@839887d declares the action upgrade for the upgrade hook, mode core, but no flow is registered for it, so the hook cannot run. Load the driver again to register its actions: styrminctl drivers load-local-version /styrmin/drivers/simple-app-dev. Then request the change again; a deployment whose creation failed must be deleted and created again. If the driver's files or commit changed since it was loaded, the load creates a new driver version; use that version instead.
   ```

   `uv run styrminctl deployments get 5aed98ba-fb67-4e69-8933-74d4bc3a839b` at 13:13:51Z: `Status: running`, `Application version: 0.2.0@839887d`, the same driver version. This matches the quickstart.
3. 13:14:02Z: `uv run styrminctl drivers load-local-version /styrmin/drivers/simple-app-dev` returned the same driver version (`4e28f237-…`) and registered three new deployments. 13:14:03Z: the same `update-version` command returned task `7f442c5d-cbca-4133-9adf-152ac18bc635`. The upgrade action ran (`Starting simple-app upgrade...` at 13:14:13Z), but at 13:14:29Z the task read `upgrade_instance failed FAILED`, and "Run the upgrade hook" failed with:

   ```text
   RuntimeError: Deployment flow run e8ad4cf9-554c-4632-9b1f-66de978f39c7 failed: Flow run encountered an exception: CustomResourceNotFound: Job styrmin-5aed98ba-fb67-4e69-8933-74d4bc3a839b-job already exists in namespace styrmin-5aed98ba-fb67-4e69-8933-74d4bc3a839b
   ```

   The upgrade action calls `execute_commands`, which names its Job `<release reference>-job`, sets no TTL and does not delete it (`backend/styrmin_backend/actions/primitives.py`; this branch does not change it). The Job of the upgrade at 13:12:56Z (completed at 13:12:59Z) still existed. The action had already stopped the `server` component and changed the version, so the deployment showed `Status: running` at `0.1.0@839887d` with no `simple-app` pod.
4. Not in the quickstart: at 13:15:16Z, `kubectl delete job -n styrmin-5aed98ba-fb67-4e69-8933-74d4bc3a839b styrmin-5aed98ba-fb67-4e69-8933-74d4bc3a839b-job`, then `uv run styrminctl deployments update-version 5aed98ba-fb67-4e69-8933-74d4bc3a839b 0.2.0 --driver-version-id 4e28f237-60b8-4c5d-856c-e69c9169bfc5`, task `0bdd17cc-3741-40c9-b1a8-ae3ed5b0b5bf`. A request for `0.1.0` would have been a no-op, because the failed instance at `0.1.0` was the active instance (research R-009). At 13:16:29Z: `upgrade_instance success SUCCEEDED`, "Run the upgrade hook" `SUCCEEDED`; the deployment `Status: running` at `0.2.0@839887d`, with its `simple-app` pod running.

Result: the missing registration fails the request and keeps the version, as the quickstart says, and loading the driver again makes the same request run the upgrade action. The last expectation of the quickstart (the task succeeds) was not met on the first try, for a reason outside this feature: the Job that the earlier upgrade left behind.

### Section 4: the checks before committing

`export npm_config_ignore_workspace=true && uv run invoke format lint`, 2026-10-19T13:29:53Z to 13:29:59Z, exit status 0, with T050's evidence and T051's `follow-ups.md` written (only files under `specs/` changed, which the Markdown linter excludes). Formatting changed no file. The result line of each check:

```text
988 files left unchanged
All checks passed!
Success: No issues found in 77 files (6ms)
 - Check code with ruff
All checks passed!
 - Check code with ty
All checks passed!
 - Check markdown files with rumdl
Success: No issues found in 77 files (5ms)
 - Check YAML files with yamllint
282/282 .graphql files passed validation.
```

yamllint printed two warnings, on files that this branch does not change: `driver/examples/infrahub-mcp/driver.styrmin.yml` line 57 (`comments-indentation`) and `.specify/workflows/speckit/workflow.yml` line 1 (`document-start`). The last check, "Validating generated types are up to date", printed nothing and passed.

### Differences between the quickstart or the spec and the observed behaviour

T050 does not change quickstart.md, spec.md, plan.md, research.md or the contracts. These differences are for the reconciliation:

1. Quickstart, "An edited action without an image rebuild", and spec user story 2, scenario 1: on the dev stack the task succeeds instead of failing, because the agent container bind-mounts `./driver/examples` as the server container does, and the actions run in the agent container. The quickstart says "The dev stack bind-mounts `driver/examples` into the server, so the server reads the edit"; the agent reads it too. The second half of the scenario has nothing to repair.
2. Quickstart, "Setup and upgrade actions of a local driver": `/styrmin/drivers/simple-app` cannot be deployed on the dev stack, because its chart location `simple-app` has no repository; only the E2E session rewrites it. The scenario needs a chart that the dev cluster can fetch.
3. Quickstart, prerequisites of section 3: on a Linux host, the dev stack also needs `host.docker.internal` to resolve in the agent container, and the Traefik CRDs in the dev cluster. Neither `uv run invoke dev` nor the `dev-validate` skill provides them. Without the first, no step is recorded and each task shows only "Plan the changes".
4. Quickstart, "A version without registrations", step 3: with `simple-app`, the second upgrade of the same deployment fails in the upgrade action, because `execute_commands` leaves its Job behind.
5. Quickstart, section 3: the commands without `--driver-version-id` depend on latest-wins. With two `simple-app` driver versions loaded, as in this run, they can bind another version; the run pinned the driver version.
6. Quickstart, section 2: the inspection commands `kubectl get jobs -A | grep -i action` and `kubectl logs -n <namespace> job/<action job> --all-containers` find no action, because the actions run as processes in the agent pod; their output is in the agent container's log and in the logs of their Prefect flow runs. The expected result "the derived image makes `hook:setup:pre` fail with the fingerprint error" no longer describes the test: since T028, it copies a changed driver into the agent pod and builds no image (see [What the earlier runs of T028 found](#what-the-earlier-runs-of-t028-found)).
7. Spec FR-002, FR-003 and FR-004, user story 1 scenario 4, assumptions A-1 and A-2, research R-001, R-004, R-006, R-011 and R-013, and the contracts `local-driver-check.md` and `errors.md` describe an action as a Job that runs in the action's `image:`. Observed: the action runs as a process in the agent container, and `image:` has no effect. [follow-ups.md](follow-ups.md) lists the texts to reconcile.

One observation outside this feature, not investigated: on the dev stack, `styrminctl deployments get` showed the active instance of each running deployment (`semaphore-1` and both `simple-app-1`) with `status: pending`.

### Teardown of the dev stack

From 13:21:55Z to 13:22:13Z:

- `docker compose down -v` removed the five containers, the two volumes and the network of this worktree's compose project, none of which existed before T050.
- `vcluster delete fac-029-dev --driver=docker`: "Successfully deleted virtual cluster fac-029-dev".
- `driver/examples/simple-app-dev/` was deleted, and the tags `registry.opsmill.io/opsmill/styrmin:fac-029-dev` and `chart-server:fac-029-dev` were removed.

Afterwards `git status --short` printed nothing, ports 8000 and 4200 were free, and no container of this worktree was running. No container, volume or vCluster of another worktree was stopped or deleted.
