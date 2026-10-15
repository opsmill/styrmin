# Local E2E Evidence: Ingress Class Set Only After the Chart Renders

**Feature**: [spec.md](spec.md) | **Tasks**: T014, T015, T027 in [tasks.md](tasks.md) | **Rule**: Constitution §V, local PASS evidence

Both tests are existing `shard_compute` tests. This feature changes the `simple-app` driver they deploy, so both were run locally against a disposable vCluster. Neither test was added or changed for this feature.

## Shared run conditions

- Git HEAD: `8ad5053f5e24e4419a68a7cd2adf4f907450ccac` (branch `fac/ingress-class-post-render-tb7qv`, clean working tree).
- Server image: `registry.opsmill.io/opsmill/styrmin:e2e-471-8ad5053f`, built before the first run:

  ```bash
  export STYRMIN_IMAGE_VER=e2e-471-8ad5053f
  docker compose build server
  ```

- Each test ran in its own pytest session, API variant only (`-k api-chromium`), with `STYRMIN_IMAGE_VER=e2e-471-8ad5053f` exported in the same shell.
- Host clock is UTC. With `-s`, pytest prints the node ID, then the fixture output, then `PASSED` on a later line, directly followed by the vCluster teardown message. The lines below are copied from the logs with ANSI color codes removed.

## T014: `test_cluster_update_redeploys_and_moves_dedicated_ingress`

- Node ID: `backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress[api-chromium]`
- Command:

  ```bash
  export STYRMIN_IMAGE_VER=e2e-471-8ad5053f
  sleep infinity | uv run pytest "backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress" -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-471-cluster-update.log
  ```

- Session started: `2026-10-15T09:24:29Z`. Test reported `PASSED`: `2026-10-15T09:28:02Z`.
- vCluster: `pytest-86b2527d-eba2-4eaa-963a-299a4b774148` (fixture `vcluster0`), kubeconfig `/tmp/pytest-of-root/pytest-1543/vcluster0/kubeconfig`. The fixture deleted the vCluster at the end of the session.
- Attempts: 1.
- Node ID line:

  ```text
  backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress[api-chromium] 09:24:31 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
  ```

- `PASSED` line:

  ```text
  PASSED09:28:02 info Removing vCluster container vcluster.cp.pytest-86b2527d-eba2-4eaa-963a-299a4b774148...
  ```

- Summary line:

  ```text
  ============ 1 passed, 1 deselected, 1 warning in 216.53s (0:03:36) ============
  ```

What the pass shows, with the `simple-app` template that no longer sets a class (FR-001, FR-002, FR-004, SC-002):

- After `dedicated_ingress` was removed from the cluster config, every Ingress of both applications had `spec.ingressClassName` and `kubernetes.io/ingress.class` set to `traefik`.
- After the cluster's `ingress_class` was changed to `nginx`, every Ingress of application A had both set to `nginx`.
- After the original config, with `dedicated_ingress`, was restored, application A answered over HTTP through its new dedicated Traefik controller.

## T015: `test_traffic_routes_through_dedicated_ingress`

- Node ID: `backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress[api-chromium]`
- Command:

  ```bash
  export STYRMIN_IMAGE_VER=e2e-471-8ad5053f
  sleep infinity | uv run pytest "backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress" -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-471-traffic.log
  ```

- Session started: `2026-10-15T09:28:50Z`. Test reported `PASSED`: `2026-10-15T09:31:09Z`.
- vCluster: `pytest-2f89eaa9-c014-4e12-ac9b-58209f7a8a10` (fixture `vcluster0`), kubeconfig `/tmp/pytest-of-root/pytest-1546/vcluster0/kubeconfig`. The fixture deleted the vCluster at the end of the session.
- Attempts: 1.
- Node ID line:

  ```text
  backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress[api-chromium] 09:28:52 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
  ```

- `PASSED` line:

  ```text
  PASSED09:31:09 info Removing vCluster container vcluster.cp.pytest-2f89eaa9-c014-4e12-ac9b-58209f7a8a10...
  ```

- Summary line:

  ```text
  ============ 1 passed, 1 deselected, 1 warning in 142.00s (0:02:22) ============
  ```

What the pass shows: the `simple-app` application answered `200` through the environment's dedicated Traefik controller (FR-002, FR-004, SC-002).

Observed in the same vCluster while the test ran (read with `kubectl` using the kubeconfig above):

- The `simple-app` Ingress `styrmin-simple-app` in namespace `styrmin-11c84ef7-5eb7-43b7-89a2-57acfd2e38c2` had no `spec.ingressClassName` and had the annotation `kubernetes.io/ingress.class: traefik`.
- The first `postRenderers` patch of its HelmRelease targets `kind: Ingress` and sets `spec.ingressClassName: null`. A later patch adds the `kubernetes.io/ingress.class: traefik` annotation.

## T027: Re-runs after the review fixes (final runs)

The first check of T027, on `2026-10-15T09:48:18Z` at HEAD `9a607117`, found no change under `backend/styrmin_backend/` or `driver/examples/` after `8ad5053f`. The review fixes in commit `1e6efea3` then changed a comment in `utilities/ingress.py` and the `render_value_template` docstring in `builders/application.py`; `git diff --stat 8ad5053f..HEAD -- backend/styrmin_backend driver/examples` lists only these two files. No code changed, but T027 requires a re-run after any change under `backend/styrmin_backend/`, so both tests ran again. These runs supersede the T014 and T015 runs above as the final runs.

Shared run conditions:

- Git HEAD: `5ebee84639dd8192367e74b8270c29ed95b34d46` (branch `fac/ingress-class-post-render-tb7qv`, clean working tree).
- Server image: `registry.opsmill.io/opsmill/styrmin:e2e-471-5ebee846`, built before the first run with `export STYRMIN_IMAGE_VER=e2e-471-5ebee846 && docker compose build server`.
- Each test ran in its own pytest session, API variant only, with `STYRMIN_IMAGE_VER=e2e-471-5ebee846` exported in the same command line. Lines are copied from the logs with ANSI color codes removed.

### `test_cluster_update_redeploys_and_moves_dedicated_ingress` (re-run)

- Node ID: `backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress[api-chromium]`
- Command:

  ```bash
  export STYRMIN_IMAGE_VER=e2e-471-5ebee846 && sleep infinity | uv run pytest "backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress" -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-471-cluster-update-rerun.log
  ```

- Session started: `2026-10-15T10:18:25Z`. Test reported `PASSED`: `2026-10-15T10:22:14Z`.
- vCluster: `pytest-8a6d40e0-e21f-40f8-820c-fba965fd1338` (fixture `vcluster0`), kubeconfig `/tmp/pytest-of-root/pytest-1596/vcluster0/kubeconfig`. The fixture deleted the vCluster at the end of the session.
- Attempts: 1.
- Node ID line:

  ```text
  backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress[api-chromium] 10:18:27 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
  ```

- `PASSED` line:

  ```text
  PASSED10:22:14 info Removing vCluster container vcluster.cp.pytest-8a6d40e0-e21f-40f8-820c-fba965fd1338...
  ```

- Summary line:

  ```text
  ============ 1 passed, 1 deselected, 1 warning in 231.94s (0:03:51) ============
  ```

### `test_traffic_routes_through_dedicated_ingress` (re-run)

- Node ID: `backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress[api-chromium]`
- Command:

  ```bash
  export STYRMIN_IMAGE_VER=e2e-471-5ebee846 && sleep infinity | uv run pytest "backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress" -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-471-traffic-rerun.log
  ```

- Session started: `2026-10-15T10:22:38Z`. Test reported `PASSED`: `2026-10-15T10:24:52Z`.
- vCluster: `pytest-fce84793-3f02-4064-bb34-eac6bb537481` (fixture `vcluster0`), kubeconfig `/tmp/pytest-of-root/pytest-1597/vcluster0/kubeconfig`. The fixture deleted the vCluster at the end of the session.
- Attempts: 1.
- Node ID line:

  ```text
  backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress[api-chromium] 10:22:40 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
  ```

- `PASSED` line:

  ```text
  PASSED10:24:52 info Removing vCluster container vcluster.cp.pytest-fce84793-3f02-4064-bb34-eac6bb537481...
  ```

- Summary line:

  ```text
  ============ 1 passed, 1 deselected, 1 warning in 137.56s (0:02:17) ============
  ```
