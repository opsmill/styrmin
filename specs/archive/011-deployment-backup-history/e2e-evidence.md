# E2E Local-PASS Evidence: Deployment Backup History (#304)

Constitution §V definition-of-done record for task T029.

Both variants of `test_backup_and_restore_lifecycle` passed locally on 2026-10-08, each in its own pytest session.

The test is in `backend/tests/e2e/test_backup_restore.py` and carries the `ci` and `shard_backup` markers. It reuses the session-shared `deployed_simple_app` deployment (simple-app 0.1.0), as research R9 decided.

## How the runs built the Styrmin image from this branch

The `styrmin_deployment` fixture runs `docker compose build` from the repository root. `docker/Dockerfile` copies `backend/`, `python_sdk/`, `cli/` and `frontend/` from the working tree and builds the frontend with `pnpm build`, so the image holds this branch's backend and frontend code. The fixture installs the Helm chart with `image.tag` and `styrmin-agent.image.tag` set to `STYRMIN_IMAGE_VER`.

Each run set `STYRMIN_IMAGE_VER=local-f8kjf-backup-history`, because other sessions on the same host were building Styrmin images at the same time. With the default `latest` tag, another session's build could replace the image this test runs against.

## Evidence for the api-chromium variant

| Item | Value |
|---|---|
| pytest node ID | `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[api-chromium]` |
| Exact command | `PATH=<scratchpad>/node22/bin:$PATH npm_config_ignore_workspace=true STYRMIN_IMAGE_VER=local-f8kjf-backup-history uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" -k "api-chromium" -v -s --pdb < <(exec sleep 987654) > e2e-api-2.log 2>&1` |
| ISO 8601 timestamp (UTC) | `2026-10-08T23:27:46Z` (`PASSED` line; run started 23:23:33Z, pytest exited 23:27:52Z) |
| vcluster id | `pytest-0546f061-48ab-4fad-98f3-938cee81978c` (deleted by the fixture teardown after the pass) |
| Kubeconfig path during the run | `/tmp/pytest-of-root/pytest-1037/vcluster0/kubeconfig` |
| Verbatim `PASSED` line | `PASSED23:27:46 info Removing vCluster container vcluster.cp.pytest-0546f061-48ab-4fad-98f3-938cee81978c...` (pytest's `PASSED` and the teardown log share the line; ANSI color codes removed) |
| Verbatim summary line | `============ 1 passed, 1 deselected, 1 warning in 256.28s (0:04:16) ============` |

## Evidence for the ui-chromium variant

| Item | Value |
|---|---|
| pytest node ID | `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[ui-chromium]` |
| Exact command | `PATH=<scratchpad>/node22/bin:$PATH npm_config_ignore_workspace=true STYRMIN_IMAGE_VER=local-f8kjf-backup-history uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" -k "ui-chromium" -v -s --pdb < <(exec sleep 987654) > e2e-ui-1.log 2>&1` |
| ISO 8601 timestamp (UTC) | `2026-10-08T23:33:46Z` (`PASSED` line; run started 23:28:34Z, pytest exited 23:33:51Z) |
| vcluster id | `pytest-249aa49a-e677-4b16-b7e5-d928d753bbc5` (deleted by the fixture teardown after the pass) |
| Kubeconfig path during the run | `/tmp/pytest-of-root/pytest-1038/vcluster0/kubeconfig` |
| Verbatim `PASSED` line | `PASSED23:33:46 info Removing vCluster container vcluster.cp.pytest-249aa49a-e677-4b16-b7e5-d928d753bbc5...` (ANSI color codes removed) |
| Verbatim summary line | `============ 1 passed, 1 deselected, 1 warning in 314.70s (0:05:14) ============` |

The one warning in both runs is the `DeprecationWarning` for `asyncio.iscoroutinefunction` raised in `kr8s/_vendored/asyncache`. It is not related to this change.

`< <(exec sleep 987654)` keeps the standard input of pytest open, as `sleep infinity |` does in the quickstart command, so pdb would pause on a failure. It also lets the command end when pytest exits after a pass.

## Earlier run that did not reach the test

The first api-chromium session (vcluster `pytest-5b4504ea-a166-4e1e-90de-72117aef5c98`, started 2026-10-08T23:21:06Z) failed in fixture setup, before the test body ran. `docker compose build` builds the `task-worker`, `agent-operator` and `server` services in parallel under one image tag. The first time that tag was created, one of the three builds failed with `image "registry.opsmill.io/opsmill/styrmin:local-f8kjf-backup-history": already exists`. A second `docker compose build` with the tag already present succeeded, and the passing runs above reused it.

## What the passing runs check

Each variant checks the following through its own entrypoint, the SDK for api-chromium and the deployment page for ui-chromium:

- After the `backup_ttl` fanout gives the deployment a new instance, the test backs up the active instance it reads with `client.deployments.get`.
- Setting `STYRMIN_E2E_BACKUP_HISTORY=1` on the `server` component with `set_component_env_vars` gives the deployment a new active instance. The test asserts the instance id changed.
- `scenario_driver.list_backups(deployment_id=...)` still lists the backup, with application version `0.1.0`. The API driver reads `client.backups.list_backups(deployment_id=...)`. The UI driver reads each `backup-row` on the Backups tab, including `data-backup-application-version`.
- Restoring that backup of an earlier instance, checking the restored counter in Postgres, and deleting the backup all succeed. These are the existing steps 3 to 6, unchanged.

The restore was stable after the config edit in both variants, so the fallback in research R9 (moving the edit and the history check after step 5) was not needed.

## Review round: the test with an upgrade, 2026-10-09

After the review of #417, `test_backup_and_restore_lifecycle` also upgrades the deployment from 0.1.0 to 0.2.0 after the config edit, which reproduces #304 with the simple app. Both variants passed locally, each in its own pytest session, on the branch rebased onto `develop` at `2d738114`.

Both runs used an image built before the runs with `STYRMIN_IMAGE_VER=local-f8kjf-review docker compose build`, for the same reason as above.

| Item | api-chromium | ui-chromium |
|---|---|---|
| Exact command | `npm_config_ignore_workspace=true PYTHONUNBUFFERED=1 STYRMIN_IMAGE_VER=local-f8kjf-review uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" -k "api-chromium" -v -s --pdb < <(exec sleep 987654)` | The same command with `-k "ui-chromium"` |
| Run started (UTC) | `2026-10-09T18:33:27Z` | `2026-10-09T18:39:07Z` |
| `PASSED` line (UTC) | `18:39:01` | `18:45:26` |
| vcluster id | `pytest-b48d790f-2f45-4f0b-9abe-f8b76f70819e` (deleted by the fixture teardown) | `pytest-7186b07b-49c9-47c8-bdb1-7aa72dcbfe0f` (deleted by the fixture teardown) |
| Verbatim summary line | `============ 1 passed, 1 deselected, 1 warning in 337.56s (0:05:37) ============` | `============ 1 passed, 1 deselected, 1 warning in 381.97s (0:06:21) ============` |

The added steps check, through each variant's entrypoint:

- After the upgrade, the deployment has a new active instance at version 0.2.0, and `scenario_driver.list_backups(deployment_id=...)` still lists the backup with application version `0.1.0`.
- After the restore of that backup, the application's `/version` endpoint answers `0.1.0`, and the deployment keeps version 0.2.0 and the same active instance.

### Earlier runs in the review round

- The first api-chromium run, with the default image tag, failed in the new upgrade step: `TimeoutError: Pods in styrmin-<deployment-id> did not become ready within 180.0s`. The upgrade runs the driver's action Job, and `wait_for_pods_ready` waited for its completed pod, which never becomes ready. The helper now skips pods in phase `Succeeded`. The `finally` block of that run also failed to downgrade the deployment to 0.1.0 with `Job styrmin-<deployment-id>-job already exists`, which is #374, so the test no longer downgrades.
- A second api-chromium run with the default image tag passed (`1 passed, 1 deselected, 1 warning in 374.61s`). It is not counted, because other sessions on the host can replace the `latest` image during a run.
