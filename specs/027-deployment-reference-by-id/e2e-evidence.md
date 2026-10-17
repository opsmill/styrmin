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
