# E2E Evidence: Deployment References Stored by Id

Local PASS evidence for each new or modified E2E test (Constitution §V, [tasks.md](tasks.md) "E2E run rules").

## T021: rename of the deployment that an affinity term names (US1)

- Test: `test_pod_anti_affinity_cross_deployment_via_graphql`, extended in T020 ([research R-013](research.md)).
- Pytest node id: `backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql[api-chromium]`
- Shard and markers: `shard_compute`, `ci`, `api_only`. The `[ui-chromium]` variant is deselected by `-k api-chromium`.
- Code under test: commit `ae8dff34` (branch `fac/affinity-by-id-zsdtf`).
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
- Code under test: commit `17ca4840` (branch `fac/affinity-by-id-zsdtf`).
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

Not an E2E run: the local results of [quickstart.md](quickstart.md) §1, §2 and §5, on commit `065eaec2`, with `pr-notes.md` and this section the only uncommitted changes.

- §1, generated surface: the expected result holds. After `uv run styrmin export graphql-schema schema.graphql` (exit code 0, 2026-10-17T03:44:29+00:00) and the type generation, `git diff --stat schema.graphql python_sdk/src/styrmin_sdk/graphql/_generated frontend/src/generated` printed nothing. Compared with the base commit `73859192`, only the descriptions of `DeploymentReferenceInput` and of its `deploymentId` and `deploymentName` fields change.
- §1, difference from the quickstart: `uv run invoke generate` completed its SDK step (`ariadne-codegen`) and failed at its frontend step (exit code 1, 2026-10-17T03:44:33+00:00). The step printed only `ELIFECYCLE Command failed with exit code 1`, so the cause is not known. This host runs Node 18.19.1, and commit fc04c22a records the same failure. `pnpm -C frontend --ignore-workspace codegen`, run directly, completed (exit code 0, 2026-10-17T03:44:40+00:00), and so did the frontend codegen that `uv run invoke lint` runs to check the generated types.
- §2, unit tests: the expected result holds. Exit code 0, 2026-10-17T03:44:51+00:00, `137 passed in 0.49s`.
- §2, functional tests: the expected result holds. Exit code 0, 2026-10-17T03:45:10+00:00, `148 passed in 11.32s`.
- §5, `uv run invoke format lint`: the expected result holds. Exit code 0, 2026-10-17T03:46:21+00:00: ruff, ty and rumdl report no issue, yamllint gives the same two warnings as in T044 in files that this change does not touch, "277/277 .graphql files passed validation.", and the generated types are up to date.
