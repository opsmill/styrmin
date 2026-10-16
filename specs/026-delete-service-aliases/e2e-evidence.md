# E2E Local-PASS Evidence: Deleting a Deployment Deletes Its Service Aliases (#503)

Constitution §V definition-of-done record for task T015.

The `api-chromium` session of `backend/tests/e2e/test_service_discovery.py` passed locally on 2026-10-16 at the first attempt. The module's three tests ran in one pytest session, the new test last. The module carries the `shard_general` marker, and the new test carries `ci` and `api_only`.

## How the run built the Styrmin image from this branch

The image was built once before the session, with a tag of its own, because the fixture's parallel `docker compose build` races on one tag and other sessions on the host build Styrmin images:

```bash
export STYRMIN_IMAGE_VER=e2e-503-1792193732
docker compose build server
```

The working tree held commit `9c1e5533` plus the uncommitted new test, `tasks.md` and `pr-notes.md`. The image therefore holds the operator teardown step and the alias flow of this branch. The `styrmin_deployment` fixture installs the Helm chart with `image.tag` and `styrmin-agent.image.tag` set to `STYRMIN_IMAGE_VER`.

## api-chromium session

| Item | Value |
|---|---|
| pytest node IDs | `backend/tests/e2e/test_service_discovery.py::test_service_discovery_between_apps[api-chromium]`, `backend/tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service[api-chromium]`, `backend/tests/e2e/test_service_discovery.py::test_deleted_deployment_leaves_no_alias[api-chromium]` |
| Exact command | `export STYRMIN_IMAGE_VER=e2e-503-1792193732 npm_config_ignore_workspace=true; exec 3< <(sleep infinity); spid=$!; uv run pytest backend/tests/e2e/test_service_discovery.py -k api-chromium -v -s --pdb <&3 > e2e-api-1.log 2>&1; exec 3<&-; kill "$spid"` |
| Start (UTC) | `2026-10-16T23:36:09Z` |
| Last `PASSED` line (UTC) | `2026-10-16T23:38:33Z` |
| End, pytest exited (UTC) | `2026-10-16T23:38:38Z` |
| vcluster name | `pytest-31c5f1a9-617d-485d-b6d8-bcbcbdb06939` (deleted by the fixture teardown after the pass) |
| Kubeconfig path during the run | `/tmp/pytest-of-root/pytest-1870/vcluster0/kubeconfig` |
| Summary line | `============ 3 passed, 3 deselected, 1 warning in 147.03s (0:02:27) ============` |

The `sleep infinity` file descriptor keeps the standard input of pytest open, as `sleep infinity |` does in the quickstart command, so pdb would pause on a failure. The command ends when pytest exits after a pass. The 3 deselected items are the `ui-chromium` variants.

Verbatim `PASSED` lines (ANSI color codes removed). With `-s`, the fixture output appears between the first node ID and its `PASSED`, and the vcluster teardown log shares the last line:

```text
backend/tests/e2e/test_service_discovery.py::test_service_discovery_between_apps[api-chromium] 23:36:11 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
...
PASSED
backend/tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service[api-chromium] PASSED
backend/tests/e2e/test_service_discovery.py::test_deleted_deployment_leaves_no_alias[api-chromium] PASSED23:38:33 info Removing vCluster container vcluster.cp.pytest-31c5f1a9-617d-485d-b6d8-bcbcbdb06939...
```

The one warning is the `DeprecationWarning` for `asyncio.iscoroutinefunction` raised in `kr8s/_vendored/asyncache`. It is not related to this change.

## Operator log of the deletion of `intent`

In this session `intent` had the id `3963174c-5fc2-4b1a-84c4-74d21362c390` and `executor` had the id `d1016018-db9a-42df-949e-f6ef0728c12d`. The agent log (`kubectl -n styrmin logs -f <agent pod> --all-containers --timestamps`) shows the new teardown step first, on both deletion paths:

- The `deletionRequested` handler, started by `client.deployments.delete`, deleted the alias `intent` in `executor`'s namespace:

  ```text
  2026-10-16T23:38:23.281394856Z 2026-10-16 23:38:23,281 INFO     kopf.objects: Deletion requested via spec for styrmin-3963174c-5fc2-4b1a-84c4-74d21362c390/styrmin-3963174c-5fc2-4b1a-84c4-74d21362c390 — running teardown
  2026-10-16T23:38:23.281412329Z 2026-10-16 23:38:23,281 INFO     kopf.objects: Teardown step 1: service aliases of 3963174c-5fc2-4b1a-84c4-74d21362c390 in all namespaces
  2026-10-16T23:38:23.354196623Z 2026-10-16 23:38:23,354 INFO     kopf.objects: Deleted 1 service aliases of 3963174c-5fc2-4b1a-84c4-74d21362c390
  2026-10-16T23:38:23.354231658Z 2026-10-16 23:38:23,354 INFO     kopf.objects: Teardown step 2: Services / Middlewares for styrmin-3963174c-5fc2-4b1a-84c4-74d21362c390/styrmin-3963174c-5fc2-4b1a-84c4-74d21362c390
  2026-10-16T23:38:23.357763153Z 2026-10-16 23:38:23,357 INFO     kopf.objects: Teardown step 3: HelmRelease for styrmin-3963174c-5fc2-4b1a-84c4-74d21362c390/styrmin-3963174c-5fc2-4b1a-84c4-74d21362c390
  2026-10-16T23:38:23.363726424Z 2026-10-16 23:38:23,363 INFO     kopf.objects: Teardown step 4: NetworkPolicies / Secrets for styrmin-3963174c-5fc2-4b1a-84c4-74d21362c390/styrmin-3963174c-5fc2-4b1a-84c4-74d21362c390
  ```

- The delete handler, which ran when the StyrminDeployment was deleted with its namespace, found no alias left:

  ```text
  2026-10-16T23:38:28.564818799Z 2026-10-16 23:38:28,564 INFO     kopf.objects: Teardown step 1: service aliases of 3963174c-5fc2-4b1a-84c4-74d21362c390 in all namespaces
  2026-10-16T23:38:28.569651903Z 2026-10-16 23:38:28,569 INFO     kopf.objects: Deleted 0 service aliases of 3963174c-5fc2-4b1a-84c4-74d21362c390
  ```

Three seconds before the deletion, the alias flow of the rename test had written the alias `intent` into `executor`'s namespace again (`Applying service alias: intent in namespace styrmin-d1016018-db9a-42df-949e-f6ef0728c12d` at 23:38:20.729). The test's first assertion found that alias before it deleted `intent`, so the test could not pass without an alias to delete.

## What the new test checks

`test_deleted_deployment_leaves_no_alias` (research R-008):

1. It waits until `executor`'s namespace holds the alias `intent` labelled with `intent`'s id, and asserts it.
2. It deletes `intent` with `client.deployments.delete`.
3. It polls `client.deployments.get` every 5 seconds, up to 300 seconds, until the status is `deleted`.
4. It lists the Services of `executor`'s namespace and asserts that none has the label `styrmin.io/deployment-id=<intent id>` and none has a `spec.externalName` whose second part is `styrmin-<intent id>`.
