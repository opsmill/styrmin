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
