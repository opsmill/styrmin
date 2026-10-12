# E2E Local-Pass Evidence: spec 021 (Cluster Config Update)

Constitution §V definition-of-done record for tasks **T032** and **T033** (User Stories 1 and 2).
T044 appends the User Story 3 evidence.

Both runs used the server image built first with
`export STYRMIN_IMAGE_VER=fac-cu-1791813432 && docker compose build server`, with the same
`STYRMIN_IMAGE_VER` exported for the pytest session. The output was written to a log in the
session scratch directory instead of `/tmp/cluster-update-api.log`; the pytest arguments are
unchanged.

## T032: `test_cluster_update_redeploys_and_moves_dedicated_ingress[api-chromium]`

| Item | Value |
|---|---|
| pytest node ID | `backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress[api-chromium]` |
| Exact command | `sleep infinity \| uv run pytest "backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress" -k api-chromium -v -s --pdb 2>&1 \| tee <scratch>/cluster-update-api.log` |
| ISO 8601 timestamp (UTC) | `2026-10-12T14:14:13+00:00` (run started 14:10:09, PASS observed 14:14:04) |
| vCluster id | `pytest-4d6df62b-0ee9-4237-8892-b150361f4546` (created 14:10:27, deleted by the fixture teardown after the PASS) |
| Kubeconfig path (during run) | `/tmp/pytest-of-root/pytest-1339/vcluster0/kubeconfig` |
| Verbatim `PASSED` line | `PASSED14:14:04 info Removing vCluster container vcluster.cp.pytest-4d6df62b-0ee9-4237-8892-b150361f4546...` (pytest's `PASSED` and the teardown log share the line because of `-s`; ANSI colour codes stripped) |
| Verbatim summary line | `============ 1 passed, 1 deselected, 1 warning in 238.39s (0:03:58) ============` |

### Earlier failed attempt (not caused by this feature)

The first attempt (vCluster `pytest-d4f9bf52-5a99-48c7-a4d8-cd3a85fe7f53`, started 13:57:41) failed
in phase 1. B's dedicated ingress controller stayed `deleting` for 300 s:
`AssertionError: Ingress controller f520abe7-2aa5-4aaf-83e0-2d6d5b9af0fc never reached 'deleted'`.

- Styrmin requested the removal at the right time: after B's application redeploy ended, the
  operator ran the `deletionRequested` teardown and requested the deletion of the namespace.
- The namespace deletion deleted the `StyrminDeployment` CR. The kopf `on.delete` handler ran and
  logged `Deletion is processed: 1 succeeded`, but the `styrmin.io/kopf-finalizer` finalizer was
  never removed, so the namespace stayed `Terminating` and the status reporter kept reporting
  `Deleting`.
- The CR's `kopf_styrmin_deployment_timer` tick ran at the same moment as the delete handler
  (both logged at 14:00:10.44). kopf 1.44.5 keeps the finalizer while a timer is still exiting,
  and then relies on the event of its own patch to process the object again. The delete
  handler's patch sets the `Deleting` phase that the `deletionRequested` handler had already set,
  so the patch can change nothing and produce no event.
- Adding an annotation to the CR by hand made kopf run the handler again and remove the
  finalizer, which supports this cause.

The race is in the operator's deletion path of #252, which this feature does not change. A's
controller in the same run, and both controllers in the passing runs, were removed normally.

## T033: whole `shard_compute`, API variant

| Item | Value |
|---|---|
| Exact command | `uv run pytest -v -m "ci and shard_compute" -k api-chromium backend/tests/e2e` (the CI selector) |
| ISO 8601 timestamp (UTC) | `2026-10-12T14:24:16+00:00` (run started 14:14:22, summary written 14:24:01) |
| vCluster id | `pytest-13608cdc-22e4-491b-96df-497167396551` (deleted by the fixture teardown) |
| Kubeconfig path (during run) | `/tmp/pytest-of-root/pytest-1340/vcluster0/kubeconfig` |
| Verbatim summary line | `=========== 7 passed, 175 deselected, 1 warning in 577.41s (0:09:37) ===========` |

Verbatim `PASSED` lines:

```text
backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress[api-chromium] PASSED [ 14%]
backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress[api-chromium] PASSED [ 28%]
backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_loadbalancer_ingress[api-chromium] PASSED [ 42%]
backend/tests/e2e/test_ingress_controller.py::test_ip_whitelist_enforcement_allows_and_rejects[api-chromium] PASSED [ 57%]
backend/tests/e2e/test_ingress_controller.py::test_deleting_last_app_tears_down_dedicated_ingress[api-chromium] PASSED [ 71%]
backend/tests/e2e/test_pod_scheduling.py::test_scheduling_end_to_end[api-chromium] PASSED [ 85%]
backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql[api-chromium] PASSED [100%]
```

The cluster update test ran first in the shard, and the tests after it passed on the restored
session config. That includes `test_deleting_last_app_tears_down_dedicated_ingress`, which uses
the helpers moved to `backend/tests/e2e/helpers/ingress.py` (T029).

The single warning in both runs is the unrelated `kr8s/_vendored/asyncache` `DeprecationWarning`
for `asyncio.iscoroutinefunction`.
