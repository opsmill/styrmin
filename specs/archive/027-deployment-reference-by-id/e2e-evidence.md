# E2E Evidence: Deployment References Stored by Id

Local PASS evidence for each new or modified E2E test (Constitution §V, [tasks.md](tasks.md) "E2E run rules").

## T021: rename of the deployment that an affinity term names (US1)

- Test: `test_pod_anti_affinity_cross_deployment_via_graphql`, extended in T020 ([research R-013](research.md)).
- Pytest node id: `backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql[api-chromium]`
- Shard and markers: `shard_compute`, `ci`, `api_only`. The `[ui-chromium]` variant is deselected by `-k api-chromium`.
- Code under test: commit `256bb517` (branch `fac/affinity-by-id-zsdtf`).
- Server image: built once before the session from the same production code, tag `registry.opsmill.io/opsmill/styrmin:e2e-508-1792195869`.
- Command:

  ```bash
  export STYRMIN_IMAGE_VER=e2e-508-1792195869   # set before `docker compose build server`
  exec 3< <(sleep infinity); spid=$!
  uv run pytest "backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql" \
    -m "ci and shard_compute" -k api-chromium -v -s --pdb <&3 > e2e-run1.log 2>&1; rc=$?
  exec 3<&-; kill "$spid"
  ```

- Run started: 2026-10-17T00:17:51+00:00. Run passed and ended: 2026-10-17T00:21:55+00:00 (pytest exit code 0).
- vCluster: `pytest-b46f26c7-ae52-4e17-8a8e-15d522f53cf9` (fixture id `vcluster0`), kubeconfig `/tmp/pytest-of-root/pytest-1886/vcluster0/kubeconfig`. The fixture deleted the vCluster at the end of the session.
- Log: `/tmp/e2e-scheduling.log`.
- Verbatim result lines (ANSI colours removed; with `-s`, pytest prints `PASSED` after the test's captured output, here on the same line as the vCluster teardown message):

  ```text
  backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql[api-chromium] 00:17:53 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
  PASSED00:21:50 info Removing vCluster container vcluster.cp.pytest-b46f26c7-ae52-4e17-8a8e-15d522f53cf9...
  ============ 1 passed, 1 deselected, 1 warning in 241.05s (0:04:01) ============
  ```

What the passing run checked:

- A's affinity term written with `DeploymentReferenceInput(deploymentName="scheduling-b")` is stored with B's id.
- Both rendered pod templates select the other deployment's `styrmin/deployment_id`.
- After B is renamed to `scheduling-b-renamed`, B is `running`. A keeps its active instance, its stored config and the uids of its workload pods.
- A's config written back as read returns a null `Task`.
- A updated with a changed env var reaches `running`. Its rendered pod template has the env var and still selects `styrmin/deployment_id=<B's id>`.
- The cleanup renames B back to `scheduling-b` and clears the scheduling of both deployments.

## T031: environment clone whose peer names the primary in an affinity term (US5, US6)

- Test: `test_environment_clone_lifecycle`, extended in T030 ([research R-013](research.md)).
- Shard and markers: `shard_env_backup`, `ci`. The test runs in both variants, one variant per pytest session.
- Code under test: commit `14cbc24c` (branch `fac/affinity-by-id-zsdtf`).
- Server image: built once before both sessions from the same production code, tag `registry.opsmill.io/opsmill/styrmin:e2e-508-1792204778`.
- Scope of the runs: the node only, not the whole shard. The only other test in `shard_env_backup`, `test_environment_backup_and_restore_lifecycle`, comes before it in the module. The test deletes the peer and both environments that the clones created, and it does not change the primary's config, so the shard's session state after the test is the same as before the change.

### `[api-chromium]`

- Pytest node id: `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]`
- Command:

  ```bash
  export STYRMIN_IMAGE_VER=e2e-508-1792204778   # set before `docker compose build server`
  exec 3< <(sleep infinity); spid=$!
  uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" \
    -m "ci and shard_env_backup" -k api-chromium -v -s --pdb <&3 > /tmp/e2e-clone-api.log 2>&1; rc=$?
  exec 3<&-; kill "$spid"
  ```

- Run started: 2026-10-17T02:39:55+00:00. Run passed and ended: 2026-10-17T02:44:57+00:00 (pytest exit code 0).
- vCluster: `pytest-f097d326-bf0b-4381-923f-bfd0d35a72bd` (fixture id `vcluster0`), kubeconfig `/tmp/pytest-of-root/pytest-1896/vcluster0/kubeconfig`. The fixture deleted the vCluster at the end of the session.
- Log: `/tmp/e2e-clone-api.log`.
- Verbatim result lines (ANSI colours removed; with `-s`, pytest prints `PASSED` after the test's captured output, on the same line as the vCluster teardown message):

  ```text
  backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium] 02:39:57 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
  PASSED02:44:52 info Removing vCluster container vcluster.cp.pytest-f097d326-bf0b-4381-923f-bfd0d35a72bd...
  ============ 1 passed, 1 deselected, 1 warning in 299.13s (0:04:59) ============
  ```

### `[ui-chromium]`

- Pytest node id: `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]`
- Command: the same as for `[api-chromium]`, in a new session, with `-k ui-chromium` and the log `/tmp/e2e-clone-ui.log`.
- Run started: 2026-10-17T02:45:14+00:00. Run passed and ended: 2026-10-17T02:50:55+00:00 (pytest exit code 0).
- vCluster: `pytest-7a8ba2a6-5087-4c4e-8cf5-e54219ffb4ee` (fixture id `vcluster0`), kubeconfig `/tmp/pytest-of-root/pytest-1897/vcluster0/kubeconfig`. The fixture deleted the vCluster at the end of the session.
- Log: `/tmp/e2e-clone-ui.log`.
- Verbatim result lines (ANSI colours removed):

  ```text
  backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium] 02:45:16 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
  PASSED02:50:49 info Removing vCluster container vcluster.cp.pytest-7a8ba2a6-5087-4c4e-8cf5-e54219ffb4ee...
  ============ 1 passed, 1 deselected, 1 warning in 338.06s (0:05:38) ============
  ```

What both passing runs checked:

- The peer's preferred pod affinity term, written with the primary's name through the SDK, is stored with the primary's id, and the peer runs again after the update.
- A clone request that selects only the peer is refused through the SDK with `OperationFailedError`, `typename == "VALIDATION_ERROR"` and the message "An affinity term names a deployment that the clone does not copy: <primary's name>". The same request sent as raw GraphQL returns `extensions.deployments` with the primary's id and name and the path `deployment[<peer's name>].config.scheduling.pod_affinity.preferred[0].term`. The list of the source environment's clones is unchanged, and the source gains no environment backup other than the one of the accepted clone.
- The clone that selects both deployments (through the SDK in `[api-chromium]`, through the clone dialog in `[ui-chromium]`) starts both entries `PENDING`, captures both deployments, and ends `COMPLETED` with both entries `CLONED`, each with a counterpart deployment and a restore.
- The peer's counterpart's term gives the primary's counterpart's id. The deployment references in the new environment's config and in both counterparts' configs are exactly the primary's counterpart's id, so none gives a source deployment's id. The peer's counterpart reaches `running`.
- The re-clone with an empty selection attributes both source deployments `SKIPPED` with the reason "not included in the requested deployment selection" and no counterpart.

## T045: walk-through of quickstart sections 1, 2 and 5

Not an E2E run: the local results of [quickstart.md](quickstart.md) §1, §2 and §5, on commit `09accc64`, with `pr-notes.md` and this section the only uncommitted changes.

- §1, generated surface: the expected result holds. After `uv run styrmin export graphql-schema schema.graphql` (exit code 0, 2026-10-17T03:44:29+00:00) and the type generation, `git diff --stat schema.graphql python_sdk/src/styrmin_sdk/graphql/_generated frontend/src/generated` printed nothing. Compared with the base commit `ca9c19f9`, only the descriptions of `DeploymentReferenceInput` and of its `deploymentId` and `deploymentName` fields change.
- §1, difference from the quickstart: `uv run invoke generate` completed its SDK step (`ariadne-codegen`) and failed at its frontend step (exit code 1, 2026-10-17T03:44:33+00:00). The step printed only `ELIFECYCLE Command failed with exit code 1`, so the cause is not known. This host runs Node 18.19.1, and commit 413455d9 records the same failure. `pnpm -C frontend --ignore-workspace codegen`, run directly, completed (exit code 0, 2026-10-17T03:44:40+00:00), and so did the frontend codegen that `uv run invoke lint` runs to check the generated types.
- §2, unit tests: the expected result holds. Exit code 0, 2026-10-17T03:44:51+00:00, `137 passed in 0.49s`.
- §2, functional tests: the expected result holds. Exit code 0, 2026-10-17T03:45:10+00:00, `148 passed in 11.32s`.
- §5, `uv run invoke format lint`: the expected result holds. Exit code 0, 2026-10-17T03:46:21+00:00: ruff, ty and rumdl report no issue, yamllint gives the same two warnings as in T044 in files that this change does not touch, "277/277 .graphql files passed validation.", and the generated types are up to date.

## Whole `shard_env_backup` shard after the environment restore change

- Why: commit `4350614b` changed `restore_environment_backup` after the T031 runs, so that each redeploy of the restore's fan-out runs in its own savepoint. `test_environment_backup_and_restore_lifecycle` restores an environment backup through `scenario_driver.restore_environment_backup`, so the whole shard was run again.
- Tests: the two tests of `shard_env_backup`, `test_environment_backup_and_restore_lifecycle` and `test_environment_clone_lifecycle`, in both variants, one variant per pytest session.
- Shard and markers: `shard_env_backup`, `ci`.
- Code under test: commit `06645477` (branch `fac/affinity-by-id-zsdtf`). The orchestrator ran both sessions.
- Server image: built once before both sessions from the same production code, tag `registry.opsmill.io/opsmill/styrmin:e2e-508-final-1792208899`.
- Command, with `<variant>` set to `api-chromium` and then to `ui-chromium`:

  ```bash
  export STYRMIN_IMAGE_VER=e2e-508-final-1792208899 && docker compose build server
  exec 3< <(sleep infinity); spid=$!
  uv run pytest backend/tests/e2e -m "ci and shard_env_backup" -k <variant> -v -s --pdb <&3 > <log> 2>&1
  exec 3<&-; kill "$spid"
  ```

### `[api-chromium]` of the shard

- Pytest node ids:
  - `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium]`
  - `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]`
- Run started: 2026-10-17T03:48:26+00:00. Run passed and ended: 2026-10-17T03:56:18+00:00 (pytest exit code 0).
- vCluster: `pytest-9a2cbfca-babd-42cb-af33-be2e77f316f5`. The log does not print the kubeconfig path. The fixture deleted the vCluster at the end of the session.
- Log: `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-affinity-by-id-zsdtf/6c6555ca-4cb0-4ef2-9353-5841c914d68b/scratchpad/e2e/shard-env-backup-api-chromium.log`.
- Verbatim result lines (ANSI colours removed; with `-s`, pytest prints the `PASSED` of the first test after its captured output, on its own line):

  ```text
  backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium] 03:48:28 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
  PASSED
  backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium] PASSED03:56:13 info Removing vCluster container vcluster.cp.pytest-9a2cbfca-babd-42cb-af33-be2e77f316f5...
  =========== 2 passed, 199 deselected, 1 warning in 469.80s (0:07:49) ===========
  ```

### `[ui-chromium]` of the shard

- Pytest node ids:
  - `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[ui-chromium]`
  - `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]`
- Run started: 2026-10-17T03:56:18+00:00. Run passed and ended: 2026-10-17T04:04:52+00:00 (pytest exit code 0).
- vCluster: `pytest-fbc6560e-76e9-49d9-8d89-81bcf1cd491c`. The log does not print the kubeconfig path. The fixture deleted the vCluster at the end of the session.
- Log: `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-affinity-by-id-zsdtf/6c6555ca-4cb0-4ef2-9353-5841c914d68b/scratchpad/e2e/shard-env-backup-ui-chromium.log`.
- Verbatim result lines (ANSI colours removed):

  ```text
  backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[ui-chromium] 03:56:19 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
  PASSED
  backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium] PASSED04:04:46 info Removing vCluster container vcluster.cp.pytest-fbc6560e-76e9-49d9-8d89-81bcf1cd491c...
  =========== 2 passed, 199 deselected, 1 warning in 511.15s (0:08:31) ===========
  ```

### Commits after the shard run

These commits came after the run and were verified by the unit and functional suites only, not by an E2E run:

- `ee5d0f99`: the restore log lines give `environment_restore_id`, `error_code` and `path`, and count failed redeploys in `config_redeploy_failed`.
- `64accb4e` and `0f069283`: tests only.
- `6a3d7c33`: the binder checks each deployment reference with `DeploymentReference` before it looks the reference up.
- `b781eace`: the clone flow logs `env_clone_environment_reference_not_cloned`.

## Rebase onto `develop` on 2026-10-17

The branch was rebased onto `origin/develop` at `ce8cb7d8` ("chore(changelog): add the fragment for #509"), which brings in 18 commits, among them #493 ("keep each counterpart deployment by its id, not its name"). The commit ids in this file, in `pr-notes.md` and in `opsmill-implement-report.md` are the ids after the rebase. Every run recorded above was made before the rebase, on the same commits without those 18.

The rebase had four conflicts:

- `backend/styrmin_backend/services/deployment.py`: `deploy_application` keeps the `Task | UUID` return type and the two overloads from #493, and gains `deployment_id` and `upcoming_deployments` in both overloads.
- `backend/styrmin_backend/workflows/templates/clone.py`: `_create_counterpart` returns the id that `deploy_application` returns, as in #493. That id is the one the clone chose in advance.
- `dev/knowledge/backend/services.md` and `dev/README.md`: both sides of each row are kept.

Checks run after the rebase, on `4153fc46` before this section was added:

- `uv run invoke format lint`: exit code 0, finished at 2026-10-17T11:50:55+00:00, "All checks passed!"
- `uv run pytest backend/tests/unit -q`: exit code 0, finished at 2026-10-17T11:52:16+00:00, `4217 passed, 1 skipped, 33 warnings in 73.31s (0:01:13)`.
- `uv run pytest backend/tests/functional -q`: exit code 0, finished at 2026-10-17T11:53:40+00:00, `774 passed, 2 skipped, 2 warnings in 59.27s`.
- `uv run pytest python_sdk/tests -q`: exit code 0, finished at 2026-10-17T11:53:41+00:00, `298 passed in 0.41s`.
- `uv run invoke validate-graphql`: exit code 0, "277/277 .graphql files passed validation."

No E2E test was run after the rebase.

## Runs after the review of PR #519 on 2026-10-17

The runs below were made on the working tree on top of commit `b54d6bd6`, with the review changes uncommitted (`git diff | sha256sum` began with `917902c9172e` when the runs started). After that, only Markdown files changed. The server image was built first with `STYRMIN_IMAGE_VER=review519-1792246976 docker compose build server`. Each variant ran in its own pytest session, with `--pdb` and a stdin held open by `sleep infinity`.

`test_environment_clone_lifecycle` changed in this round: the SDK error message of the refused clone request now gives the reason and the term's path, and `extensions.deployments` gives `reason`.

### `shard_env_backup`, `[api-chromium]`

- Command: `uv run pytest backend/tests/e2e -m "ci and shard_env_backup" -k api-chromium -v -s --pdb`.
- Started 2026-10-17T14:23:08+00:00, ended 2026-10-17T14:30:54+00:00, pytest exit code 0.
- vCluster: `pytest-37963b8d-43ec-4e46-8461-416f5946b693`, deleted by the fixture at the end of the session.

  ```text
  backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium] 14:23:10 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
  PASSED
  backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium] PASSED14:30:48 info Removing vCluster container vcluster.cp.pytest-37963b8d-43ec-4e46-8461-416f5946b693...
  =========== 2 passed, 199 deselected, 1 warning in 463.25s (0:07:43) ===========
  ```

### `shard_env_backup`, `[ui-chromium]`

- Command: `uv run pytest backend/tests/e2e -m "ci and shard_env_backup" -k ui-chromium -v -s --pdb`.
- Started 2026-10-17T14:30:54+00:00, ended 2026-10-17T14:39:52+00:00, pytest exit code 0.
- vCluster: `pytest-f936c9d7-5366-4d04-82a0-1144b0f5c461`, deleted by the fixture at the end of the session.

  ```text
  backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[ui-chromium] 14:30:56 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
  PASSED
  backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium] PASSED14:39:47 info Removing vCluster container vcluster.cp.pytest-f936c9d7-5366-4d04-82a0-1144b0f5c461...
  =========== 2 passed, 199 deselected, 1 warning in 536.15s (0:08:56) ===========
  ```

### `test_pod_anti_affinity_cross_deployment_via_graphql[api-chromium]` (`shard_compute`)

Re-run because `updateDeployment` now resolves the terms of every level before it saves.

- Command: `uv run pytest "backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql" -k api-chromium -v -s --pdb`.
- Started 2026-10-17T14:39:52+00:00, ended 2026-10-17T14:43:52+00:00, pytest exit code 0.
- vCluster: `pytest-a25071ab-9b9b-4193-98ef-4d15c66b1234`, deleted by the fixture at the end of the session.

  ```text
  backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql[api-chromium] 14:39:54 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
  PASSED14:43:46 info Removing vCluster container vcluster.cp.pytest-a25071ab-9b9b-4193-98ef-4d15c66b1234...
  ============ 1 passed, 1 deselected, 1 warning in 237.18s (0:03:57) ============
  ```

### Other checks on the same working tree

- `uv run pytest backend/tests/unit backend/tests/functional -q -p no:randomly`: `5012 passed, 3 skipped, 35 warnings in 129.49s (0:02:09)`, log written at 2026-10-17T14:19:24+00:00. The savepoint tests in `test_unit_of_work_savepoint.py` ran on SQLite and PostgreSQL.
- `uv run pytest python_sdk/tests -q`: `298 passed in 0.40s`.
- `npm_config_ignore_workspace=true uv run invoke format lint`: exit code 0 at 2026-10-17T14:22:24+00:00, "All checks passed!", "277/277 .graphql files passed validation." yamllint gave the two warnings in files that this change does not touch.
- Frontend, in a `node:22-slim` container: `vitest run src/__tests__/environments/EnvironmentCloneDialog.test.tsx` (31 passed), `prettier --check` and `tsc -b` on the changed files passed; `eslint` gave only the `react-refresh/only-export-components` warnings that the file's other exports already give.
