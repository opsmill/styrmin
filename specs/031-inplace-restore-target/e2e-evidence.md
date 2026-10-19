# E2E Evidence: An In-Place Restore Restores Into the Deployment Its Backup Was Taken Of (#532)

## Overview

This file records the local E2E runs that Constitution §V requires before the change is done. Each section covers one pytest session, run under the E2E run rules of [tasks.md](tasks.md): one CI shard per session, `api-chromium` and `ui-chromium` in separate sessions, `--pdb` with `sleep infinity |`, and a Styrmin image tag that belongs to this worktree only.

## T038: all six `api-chromium` nodes of `shard_backup` passed

The session ran on commit `133ed150` of the branch `fac/remove-targetnamespace-restore-8n884`. It covers the five nodes that this branch modifies and one node of the same shard that the branch does not modify (`test_renamed_bsl_cluster_objects_follow_the_location_id`).

| Item | Value |
|---|---|
| Exact command | `export STYRMIN_IMAGE_VER=inplace-restore-133ed150; sleep infinity \| uv run pytest backend/tests/e2e -m shard_backup -k "api-chromium" -v -s --pdb 2>&1 \| tee <scratchpad>/t038.log` |
| Start (ISO 8601, UTC) | `2026-10-19T17:10:42+00:00` |
| End (ISO 8601, UTC) | `2026-10-19T17:25:35+00:00`, recorded after pytest printed the summary line; pytest reports 882.30 s |
| Image tag | `registry.opsmill.io/opsmill/styrmin:inplace-restore-133ed150` |
| Image digest that the Styrmin pods ran | `sha256:94c05dd0eee7eecce5d004beb2a2ee0c157f87a16776a827927e1ad5ff931606` |
| vcluster name | `pytest-d457e9d3-5939-4b1e-be59-7c0e1843ae66`, deleted by the fixture teardown (`Successfully deleted virtual cluster pytest-d457e9d3-5939-4b1e-be59-7c0e1843ae66`) |
| Kubeconfig path | `/tmp/pytest-of-ubuntu/pytest-127/vcluster0/kubeconfig` |

`<scratchpad>` is the session scratchpad directory of the agent that ran the command. The log file is not committed.

### Which image the session ran

The image was built before the session with `STYRMIN_IMAGE_VER=inplace-restore-133ed150 docker compose build server`. That build gave the tag the digest `sha256:96841e45b5387295c1d9a4760e487d64c7939a5129e11617df63a17ea573db5c`, created at `2026-10-19T17:10:24Z`.

The `styrmin_deployment` fixture then ran `docker compose build`, which builds the `task-worker`, `agent-operator` and `server` services under the same tag. Every build step came from the cache, so the image layers did not change. Docker Compose adds the label `com.docker.compose.service` with each service's name to the image config, and the last of the three builds to write the tag (`agent-operator`) moved it to the digest `sha256:94c05dd0eee7eecce5d004beb2a2ee0c157f87a16776a827927e1ad5ff931606`. The image creation time stayed `2026-10-19T17:10:24Z`.

During the session, `kubectl get pods -n styrmin` reported that image ID for the containers of the `styrmin-server`, `styrmin-styrmin-agent-agent` and `styrmin-task-worker` pods.

### Pytest node IDs and verbatim `PASSED` lines

ANSI color codes are removed. Fixture setup output separates the first node ID from its `PASSED` line, and a log line printed by the test separates the fourth node ID from its `PASSED` line. The last `PASSED` line shares its line with the vcluster teardown output.

```text
backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[api-chromium] 17:10:44 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
[fixture setup output]
PASSED
backend/tests/e2e/test_backup_restore.py::test_restore_lifecycle_transitions[api-chromium] PASSED
backend/tests/e2e/test_backup_restore.py::test_restore_failure_marks_failed_not_indefinite[api-chromium] PASSED
backend/tests/e2e/test_backup_restore.py::test_restore_of_removed_velero_backup_fails_velero_step[api-chromium] failed restore 5a120623-b921-4759-b5df-21b1ccbdfecf: status='failed' error_message='Velero restore failed validation: Error retrieving backup: can\'t find backup styrmin/styrmin-8b7da89b-8928-4dbb-90a1-04d281991eff: Backup.velero.io "styrmin-8b7da89b-8928-4dbb-90a1-04d281991eff" not foun[...]
PASSED
backend/tests/e2e/test_backup_restore.py::test_renamed_bsl_cluster_objects_follow_the_location_id[api-chromium] PASSED
backend/tests/e2e/test_backup_restore_databases.py::test_mariadb_mongodb_backup_and_restore_lifecycle[api-chromium] #0 building with "default" instance using docker driver
[fixture and image build output]
PASSED17:25:21 info Removing vCluster container vcluster.cp.pytest-d457e9d3-5939-4b1e-be59-7c0e1843ae66...
```

The `failed restore ... status='failed'` text in the fourth node is the outcome that the test expects, because that test restores a backup that Velero no longer has.

### Final pytest summary line

```text
========== 6 passed, 199 deselected, 7 warnings in 882.30s (0:14:42) ===========
```

The seven warnings are not caused by this change:

- one `DeprecationWarning` from `kr8s/_vendored/asyncache/__init__.py:81`, because `asyncio.iscoroutinefunction` is deprecated in Python 3.14;
- six `UserWarning` lines from `kr8s/_api.py:91`, because kr8s 0.20.15 supports Kubernetes 1.28 to 1.35 and the vcluster runs v1.36.0.

### What the passing nodes check for #532

Each of the five modified nodes sends only the backup id to `createRestore`, through the API scenario driver or the SDK client:

- `test_backup_and_restore_lifecycle` restores a backup of the 0.1.0 instance after the deployment was upgraded to 0.2.0. It then reads the restore back with `client.backups.get_restore` and checks that `target_namespace` is `styrmin-<deployment id>` and that `target_instance_id` is the deployment's active 0.2.0 instance.
- `test_restore_lifecycle_transitions` checks that the deployment status passes through `restoring` and returns to `running`.
- `test_restore_failure_marks_failed_not_indefinite` checks that `create_restore` with an unknown backup id raises an error and leaves the deployment status unchanged.
- `test_restore_of_removed_velero_backup_fails_velero_step` restores a backup that Velero no longer has, and checks that the step "Run the Velero restore" fails with Velero's validation error.
- `test_mariadb_mongodb_backup_and_restore_lifecycle` writes data to MariaDB and MongoDB, backs it up, changes the data, restores the backup and checks the data.

### Nodes of `shard_backup` that did not run in this session

No node was skipped. Of the 199 deselected nodes, 193 are outside `shard_backup` and were deselected by `-m shard_backup`. The other six are the `ui-chromium` variants of this shard, deselected by `-k "api-chromium"`; pytest gives no other reason for a deselection. Task T039 runs them in a separate session:

- `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[ui-chromium]`
- `backend/tests/e2e/test_backup_restore.py::test_restore_lifecycle_transitions[ui-chromium]`
- `backend/tests/e2e/test_backup_restore.py::test_restore_failure_marks_failed_not_indefinite[ui-chromium]`
- `backend/tests/e2e/test_backup_restore.py::test_restore_of_removed_velero_backup_fails_velero_step[ui-chromium]`
- `backend/tests/e2e/test_backup_restore.py::test_renamed_bsl_cluster_objects_follow_the_location_id[ui-chromium]`
- `backend/tests/e2e/test_backup_restore_databases.py::test_mariadb_mongodb_backup_and_restore_lifecycle[ui-chromium]`

### Cleanup after the session

pytest exited after the summary line. The `sleep infinity` process of this run (PID 2304973) was then stopped by its PID. `vcluster list --driver=docker` listed no vcluster afterwards, and no Docker container with the name `pytest-d457e9d3` remained.

## T039: the three dual-entrypoint nodes of `shard_backup` passed under `ui-chromium`

The session ran on commit `3e9e3a31` of the branch `fac/remove-targetnamespace-restore-8n884`. No source file changed after commit `133ed150`, so the session reused the image tag of T038. It covers the three nodes of `shard_backup` that run under both scenario drivers: `test_backup_and_restore_lifecycle`, `test_restore_lifecycle_transitions` and `test_mariadb_mongodb_backup_and_restore_lifecycle`.

| Item | Value |
|---|---|
| Exact command | `export STYRMIN_IMAGE_VER=inplace-restore-133ed150; sleep infinity \| uv run pytest backend/tests/e2e -m shard_backup -k "ui-chromium" -v -s --pdb 2>&1 \| tee <scratchpad>/t039.log` |
| Start (ISO 8601, UTC) | `2026-10-19T17:28:33+00:00` |
| End (ISO 8601, UTC) | `2026-10-19T17:41:27+00:00`, recorded after pytest printed the summary line; pytest reports 766.39 s |
| Image tag | `registry.opsmill.io/opsmill/styrmin:inplace-restore-133ed150` |
| Image digest that the Styrmin pods ran | `sha256:b6c5f8d167e3191bfb98138cc7a9ac3cf3cee181e2bbf8d4063df7d66a1b30d7` |
| vcluster name | `pytest-faaeb3b0-a754-428f-9ef4-3871ba23cdef`, deleted by the fixture teardown (`Successfully deleted virtual cluster pytest-faaeb3b0-a754-428f-9ef4-3871ba23cdef`) |
| Kubeconfig path | `/tmp/pytest-of-ubuntu/pytest-128/vcluster0/kubeconfig` |
| Browser | Chromium 145.0.7632.6, launched by Playwright 1.58.0. pytest does not print the version; it was read afterwards with `browser.version` from the same Playwright installation. |

`<scratchpad>` is the session scratchpad directory of the agent that ran the command. The log file is not committed.

### Which image the session ran

The `styrmin_deployment` fixture ran `docker compose build` for the `task-worker`, `agent-operator` and `server` services under the tag of T038. Every build step of the Styrmin image came from the cache (`CACHED`), so the image layers did not change and the image creation time stayed `2026-10-19T17:10:24Z`. Docker Compose writes the label `com.docker.compose.service` with each service's name into the image config. In this session the `task-worker` build was the last to write the tag, so the tag moved to the digest `sha256:b6c5f8d167e3191bfb98138cc7a9ac3cf3cee181e2bbf8d4063df7d66a1b30d7`, whose label is `task-worker`. In T038 the last build was `agent-operator`, which is why the two sessions record different digests for the same layers.

During the session, `kubectl get pods -n styrmin -o jsonpath='{..imageID}'` reported that image ID for the containers of the `styrmin-server`, `styrmin-styrmin-agent-agent` and `styrmin-task-worker` pods.

### Pytest node IDs and verbatim `PASSED` lines

ANSI color codes are removed. Fixture setup output separates the first node ID from its `PASSED` line, and image build output separates the last node ID from its `PASSED` line. The last `PASSED` line shares its line with the vcluster teardown output.

```text
backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[ui-chromium] 17:28:35 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
[fixture setup output]
PASSED
backend/tests/e2e/test_backup_restore.py::test_restore_lifecycle_transitions[ui-chromium] PASSED
backend/tests/e2e/test_backup_restore_databases.py::test_mariadb_mongodb_backup_and_restore_lifecycle[ui-chromium] #0 building with "default" instance using docker driver
[fixture and image build output]
PASSED17:41:14 info Removing vCluster container vcluster.cp.pytest-faaeb3b0-a754-428f-9ef4-3871ba23cdef...
```

### Final pytest summary line

```text
===== 3 passed, 3 skipped, 199 deselected, 6 warnings in 766.39s (0:12:46) =====
```

The six warnings are not caused by this change:

- one `DeprecationWarning` from `kr8s/_vendored/asyncache/__init__.py:81`, because `asyncio.iscoroutinefunction` is deprecated in Python 3.14;
- five `UserWarning` lines from `kr8s/_api.py:91`, because kr8s 0.20.15 supports Kubernetes 1.28 to 1.35 and the vcluster runs v1.36.0.

### What the passing nodes check for #532 under `ui-chromium`

Each of the three nodes starts its restore with `scenario_driver.create_restore(backup_id=...)`. Under `ui-chromium`, that call clicks the backup row's Restore button on the deployment detail page and opens the "Restore Backup" dialog. Before it submits the dialog, it reads the read-only "Target Namespace" field and fails the scenario unless the field shows `styrmin-<deployment id>` of the deployment on that page. The web app then sends only the backup id to `createRestore`.

- `test_backup_and_restore_lifecycle` restores a backup of the 0.1.0 instance after the deployment was upgraded to 0.2.0. It then reads the restore back with `client.backups.get_restore` and checks that `target_namespace` is `styrmin-<deployment id>` and that `target_instance_id` is the deployment's active 0.2.0 instance.
- `test_restore_lifecycle_transitions` checks that the deployment status passes through `restoring` and returns to `running`.
- `test_mariadb_mongodb_backup_and_restore_lifecycle` writes data to MariaDB and MongoDB, backs it up, changes the data, restores the backup from the web app and checks the data.

### Nodes of `shard_backup` that did not run in this session

Three `ui-chromium` nodes were skipped. Each test carries the `api_only` marker, and `pytest_collection_modifyitems` in `backend/tests/e2e/conftest.py` adds a skip marker with the marker's reason to its `ui-chromium` variant. The session log shows only `SKIPPED`, because `-v` does not print skip reasons. The reasons below are pytest's verbatim output for the same three node IDs, run again with `-rs` after the session. A skip marker skips a test before any fixture starts, so that second run took 0.01 s and booted no vcluster.

```text
SKIPPED [1] backend/tests/e2e/test_backup_restore.py:1819: api_only: Every action is a raw SDK call — the driver half of ``session_scenario_driver`` is discarded (``_, client = ...``) and no dual-entrypoint driver method is invoked. The flow provokes a rejected restore by passing a non-existent backup id, which the UI cannot express: the restore button is bound to a listed backup row, so there is no Playwright path to submit an unknown id. The [ui-chromium] variant would replay the identical GraphQL calls for ~20 minutes of extra CI time.
SKIPPED [1] backend/tests/e2e/test_backup_restore.py:1882: api_only: Every action is a raw SDK or Kubernetes call and no dual-entrypoint driver method is invoked. Component tests in BackupRestoreSteps.test.tsx cover how a failed restore step and its error appear on the Backups tab, and test_backup_and_restore_lifecycle[ui-chromium] reads restore steps from the page; a [ui-chromium] variant would repeat the same GraphQL calls with one more deployment boot.
SKIPPED [1] backend/tests/e2e/test_backup_restore.py:2162: api_only: Every action is an SDK or Kubernetes call and no dual-entrypoint driver method is invoked; the assertions read cluster objects that the UI does not show.
```

The three skipped nodes are, in the same order:

- `backend/tests/e2e/test_backup_restore.py::test_restore_failure_marks_failed_not_indefinite[ui-chromium]`
- `backend/tests/e2e/test_backup_restore.py::test_restore_of_removed_velero_backup_fails_velero_step[ui-chromium]`
- `backend/tests/e2e/test_backup_restore.py::test_renamed_bsl_cluster_objects_follow_the_location_id[ui-chromium]`

Their `api-chromium` variants passed in T038.

Of the 199 deselected nodes, 193 are outside `shard_backup` and were deselected by `-m shard_backup`. The other six are the `api-chromium` variants of this shard, deselected by `-k "ui-chromium"`; pytest gives no other reason for a deselection. T038 ran them.

### Cleanup after the session

pytest exited after the summary line. The `sleep infinity` process of this run (PID 2416149) was then stopped by its PID. `vcluster list --driver=docker` listed no vcluster afterwards, and no Docker container with the name `faaeb3b0` remained.

## T040: the enterprise Infrahub node of `shard_infrahub` passed under `api-chromium`

The session ran on commit `463fa1a6` of the branch `fac/remove-targetnamespace-restore-8n884`. No source file changed after commit `133ed150`, so the session reused the image tag of T038. It covers `test_infrahub_enterprise_backup_and_restore_lifecycle`, which this branch modifies and which carries the `api_only` marker.

The enterprise fixtures `load_infrahub_enterprise` and `deployed_infrahub_enterprise_app` in `backend/tests/e2e/conftest.py` read no license key, registry login or environment variable. The driver `driver/examples/infrahub-enterprise` pulls the chart `oci://registry.opsmill.io/opsmill/chart/infrahub-enterprise` version 4.19.2, which `helm show chart` pulled from this host without a login before the session.

| Item | Value |
|---|---|
| Exact command | `export STYRMIN_IMAGE_VER=inplace-restore-133ed150; sleep infinity \| uv run pytest "backend/tests/e2e/test_infrahub_backup_restore.py::test_infrahub_enterprise_backup_and_restore_lifecycle" -k "api-chromium" -v -s --pdb 2>&1 \| tee <scratchpad>/t040.log` |
| Start (ISO 8601, UTC) | `2026-10-19T17:45:31+00:00` |
| End (ISO 8601, UTC) | `2026-10-19T17:52:13+00:00`, recorded after pytest printed the summary line; pytest reports 398.58 s |
| Image tag | `registry.opsmill.io/opsmill/styrmin:inplace-restore-133ed150` |
| Image digest that the Styrmin pods ran | `sha256:ddf7bb946143d0226c69746a58054f1156d5e316ff08ac28ea7f382aa980a5e9` |
| vcluster name | `pytest-1324c775-ee94-4e7a-b521-6970bd942777`, deleted by the fixture teardown (`Successfully deleted virtual cluster pytest-1324c775-ee94-4e7a-b521-6970bd942777`) |
| Kubeconfig path | `/tmp/pytest-of-ubuntu/pytest-129/vcluster0/kubeconfig` |

`<scratchpad>` is the session scratchpad directory of the agent that ran the command. The log file is not committed.

### Which image the session ran

The `styrmin_deployment` fixture ran `docker compose build` for the `task-worker`, `agent-operator` and `server` services under the tag of T038. Every `RUN` and `COPY` step of the Styrmin image came from the cache (`CACHED`), and the image creation time stayed `2026-10-19T17:10:24Z`. The last of the three builds to write the tag moved it to the digest `sha256:ddf7bb946143d0226c69746a58054f1156d5e316ff08ac28ea7f382aa980a5e9`, whose `com.docker.compose.service` label is `agent-operator`. T038 records another digest for the same label; this session did not check which part of the image index differs.

During the session, `kubectl get pods -n styrmin -o jsonpath='{..imageID}'` reported that image ID for the containers of the `styrmin-server`, `styrmin-styrmin-agent-agent` and `styrmin-task-worker` pods.

### Pytest node ID and verbatim `PASSED` line

ANSI color codes are removed. Fixture setup output separates the node ID from its `PASSED` line, which shares its line with the vcluster teardown output.

```text
backend/tests/e2e/test_infrahub_backup_restore.py::test_infrahub_enterprise_backup_and_restore_lifecycle[api-chromium] 17:45:32 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
[fixture setup output]
PASSED17:52:06 info Removing vCluster container vcluster.cp.pytest-1324c775-ee94-4e7a-b521-6970bd942777...
```

### Final pytest summary line

```text
=========== 1 passed, 1 deselected, 4 warnings in 398.58s (0:06:38) ============
```

The four warnings are not caused by this change:

- one `DeprecationWarning` from `kr8s/_vendored/asyncache/__init__.py:81`, because `asyncio.iscoroutinefunction` is deprecated in Python 3.14;
- three `UserWarning` lines from `kr8s/_api.py:91`, because kr8s 0.20.15 supports Kubernetes 1.28 to 1.35 and the vcluster runs v1.36.0.

### What the passing node checks for #532

The test deploys the `infrahub-enterprise` driver at version 1.6.0, writes a `BuiltinTag` node to Neo4j and a file to the Infrahub object store on the server's volume, and takes a backup. It deletes the tag, then restores the backup with `client.backups.create_restore(backup_id=backup.id)`, which sends only the backup id; before this branch, the call also passed `target_namespace=namespace`. It checks that the restore completes, that the pods of `styrmin-<deployment id>` become ready, and that the tag and the file are back in that namespace.

### Nodes of `shard_infrahub` that did not run in this session

- `backend/tests/e2e/test_infrahub_backup_restore.py::test_infrahub_enterprise_backup_and_restore_lifecycle[ui-chromium]` was deselected by `-k "api-chromium"`. The test carries the `api_only` marker, and CI does not run the `ui` cell of `shard_infrahub`.
- `backend/tests/e2e/test_infrahub_backup_restore.py::test_infrahub_backup_and_restore_lifecycle` was not selected, because the command names only the enterprise test. This branch changes its restore call in the same way, but the test carries `@pytest.mark.skip(reason="backup/restore not supported with community")`, so it runs in no session. pytest's verbatim output for its `api-chromium` variant, run with `-rs` after the session, took 0.01 s and booted no vcluster:

  ```text
  SKIPPED [1] backend/tests/e2e/test_infrahub_backup_restore.py:100: backup/restore not supported with community
  ```

- `backend/tests/e2e/test_infrahub_services.py` also belongs to `shard_infrahub`. This branch does not modify it, and task T040 does not ask for it.

### Cleanup after the session

pytest and `tee` exited after the summary line. The `sleep infinity` process of this run (PID 2513524) was then stopped by its PID. `vcluster list --driver=docker` listed no vcluster afterwards, and no Docker container or network with the name `1324c775` remained.

## Review follow-up: the two `api-chromium` nodes of `shard_env_backup` passed

A review found that this branch changes two callers of `create_restore` that no local session had run: `restore_environment_backup` in [`backend/styrmin_backend/services/backup/environment.py`](../../backend/styrmin_backend/services/backup/environment.py) and `_dispatch_cross_target_restore` in [`backend/styrmin_backend/workflows/templates/clone.py`](../../backend/styrmin_backend/workflows/templates/clone.py). Both now call `create_restore` without a namespace and dispatch the namespace that the server recorded on the restore row, `styrmin-<deployment id>`. This session runs the two E2E nodes that exercise these callers. This branch does not modify either test.

The session ran on commit `fc4532f3` of the branch `fac/remove-targetnamespace-restore-8n884`. The `ui-chromium` variants of the two nodes were not run locally: the web app's environment restore and environment clone pages did not change on this branch, and CI runs those variants.

| Item | Value |
|---|---|
| Exact command | `export STYRMIN_IMAGE_VER=inplace-restore-fc4532f3; date -Iseconds > <scratchpad>/review-env-backup.log.start; sleep infinity \| uv run pytest backend/tests/e2e -m shard_env_backup -k "api-chromium" -v -s --pdb 2>&1 \| tee <scratchpad>/review-env-backup.log` |
| Start (ISO 8601, UTC) | `2026-10-19T18:16:46+00:00` |
| End (ISO 8601, UTC) | `2026-10-19T18:28:19+00:00`, recorded after pytest printed the summary line; pytest reports 678.02 s |
| Image tag | `registry.opsmill.io/opsmill/styrmin:inplace-restore-fc4532f3` |
| Image digest that the Styrmin pods ran | `sha256:2b6d11f1e9aa5797639f9499c119420ea4442e40a75b4477edc33940701ef87c` |
| vcluster name | `pytest-744262fa-0ad2-4547-b83b-e1cc3bdff5d8`, deleted by the fixture teardown (`Successfully deleted virtual cluster pytest-744262fa-0ad2-4547-b83b-e1cc3bdff5d8`) |
| Kubeconfig path | `/tmp/pytest-of-ubuntu/pytest-138/vcluster0/kubeconfig` |

`<scratchpad>` is the session scratchpad directory of the agent that ran the command. The log file is not committed.

### Which image the session ran

No image had the tag `inplace-restore-fc4532f3` before the session. The `styrmin_deployment` fixture ran `docker compose build` for the `task-worker`, `agent-operator` and `server` services under that tag, from a clean working tree at commit `fc4532f3`. The steps `COPY backend ./backend`, `COPY python_sdk ./python_sdk` and `COPY cli ./cli` and the steps after them ran again instead of coming from the cache, because those directories changed after commit `133ed150`. The image creation time is `2026-10-19T18:17:34Z`. The `task-worker` build was the last of the three to write the tag, so the tag points to the digest `sha256:2b6d11f1e9aa5797639f9499c119420ea4442e40a75b4477edc33940701ef87c`, whose `com.docker.compose.service` label is `task-worker`.

During the session, `kubectl get pods -n styrmin -o jsonpath='{..imageID}'` reported that image ID for the containers of the `styrmin-server`, `styrmin-styrmin-agent-agent` and `styrmin-task-worker` pods.

### Pytest node IDs and verbatim `PASSED` lines

ANSI color codes are removed. Fixture setup and image build output separate the first node ID from its `PASSED` line. The second `PASSED` line shares its line with the vcluster teardown output.

```text
backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium] 18:16:48 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
[fixture setup and image build output]
PASSED
backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium] PASSED18:28:01 info Removing vCluster container vcluster.cp.pytest-744262fa-0ad2-4547-b83b-e1cc3bdff5d8...
```

### Final pytest summary line

```text
========== 2 passed, 203 deselected, 6 warnings in 678.02s (0:11:18) ===========
```

The six warnings are not caused by this change:

- one `DeprecationWarning` from `kr8s/_vendored/asyncache/__init__.py:81`, because `asyncio.iscoroutinefunction` is deprecated in Python 3.14;
- five `UserWarning` lines from `kr8s/_api.py:91`, because kr8s 0.20.15 supports Kubernetes 1.28 to 1.35 and the vcluster runs v1.36.0.

### What the passing nodes check for #532

- `test_environment_backup_and_restore_lifecycle` takes an environment backup of two deployments, deletes the backup of the second deployment, and restores the environment backup with `scenario_driver.restore_environment_backup`. On the server, `restore_environment_backup` creates one restore for the usable constituent with `create_restore` and dispatches the namespace recorded on that restore. The test checks that the environment restore skips the second deployment with the reason `backup deleted` and ends as `PARTIAL`, that the environment config equals the config captured at backup time, and that the primary deployment's counter in `styrmin-<primary deployment id>` is back at its backup-time value. It also checks that the restore created or deleted no deployment, and that the primary's namespace still holds the service alias that points to `styrmin-<second deployment id>`.
- `test_environment_clone_lifecycle` clones the environment that holds the primary deployment and a peer deployment, with `scenario_driver.clone_environment`. On the server, `_dispatch_cross_target_restore` creates one cross-target restore per counterpart deployment with `create_restore` and dispatches the namespace recorded on that restore. The test checks that the clone ends as `COMPLETED`, that both deployments are `CLONED` with a counterpart deployment and a restore id, and that each counterpart's namespace `styrmin-<counterpart deployment id>` holds the service aliases of its peers. It checks that the source environment's config is unchanged and that the clone deleted no object from the primary's namespace. It checks that an authenticated write to the primary's counterpart in `styrmin-<counterpart deployment id>` succeeds and returns the counter that the source held when the clone captured it, not the value that the test wrote to the source after the capture. It then discards the clone, clones the environment's configuration again with no deployment selected, and runs a clone that selects only the primary deployment, which restores one deployment.

### Nodes of `shard_env_backup` that did not run in this session

No node was skipped. Of the 203 deselected nodes, 201 are outside `shard_env_backup` and were deselected by `-m shard_env_backup`. The other two are the `ui-chromium` variants of the two nodes, deselected by `-k "api-chromium"`; pytest gives no other reason for a deselection:

- `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[ui-chromium]`
- `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]`

### Cleanup after the session

pytest and `tee` exited after the summary line. The `sleep infinity` process of this run (PID 2609648) was then stopped by its PID. `vcluster list --driver=docker` listed no vcluster afterwards, and no Docker container or network with the name `744262fa` remained.
