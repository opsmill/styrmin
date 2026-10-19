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
