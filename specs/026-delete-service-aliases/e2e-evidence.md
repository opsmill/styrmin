# E2E Local-PASS Evidence: Deleting a Deployment Deletes Its Service Aliases (#503)

Constitution §V definition-of-done record for tasks T015, T035 and T036. Three sessions of `backend/tests/e2e/test_service_discovery.py` ran on 2026-10-16, one after the other, each at the first attempt:

| Session | Task | Image tag | Result |
|---|---|---|---|
| `api-chromium` | T015 | `e2e-503-1792193732` | `3 passed, 3 deselected` |
| `ui-chromium` | T035 | `e2e-503-1792194439` | `1 passed, 2 skipped, 3 deselected` |
| `api-chromium`, paused after the deletion for the `kubectl` checks | T036 | `e2e-503-1792194439` | `3 passed, 3 deselected` |
| `api-chromium`, after the review fixes (2026-10-17) | review | `e2e-503-1792203741` | `3 passed, 3 deselected` |

The `api-chromium` session of `backend/tests/e2e/test_service_discovery.py` passed locally on 2026-10-16 at the first attempt. The module's three tests ran in one pytest session, the new test last. The module carries the `shard_general` marker, and the new test carries `ci` and `api_only`.

## How the session of task T015 built the Styrmin image from this branch

The image was built once before the session, with a tag of its own, because the fixture's parallel `docker compose build` races on one tag and other sessions on the host build Styrmin images:

```bash
export STYRMIN_IMAGE_VER=e2e-503-1792193732
docker compose build server
```

The working tree held commit `9c1e5533` plus the uncommitted new test, `tasks.md` and `pr-notes.md`. The image therefore holds the operator teardown step and the alias flow of this branch. The `styrmin_deployment` fixture installs the Helm chart with `image.tag` and `styrmin-agent.image.tag` set to `STYRMIN_IMAGE_VER`.

## api-chromium session (task T015)

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

## ui-chromium session (task T035)

The `ui-chromium` session of the module passed on 2026-10-16 at the first attempt. It started after `uv run invoke test` had finished, when `vcluster list --driver=docker` listed no vcluster on the host.

In this variant pytest runs only the discovery test. The rename test and the new test both carry `api_only`, so pytest skips them. The rename test carried `api_only` before this change (commit `545738fe`, #237). The discovery test creates `intent` and `executor` through the deploy form, waits until both are running, and requests `http://intent:8000/health` from `executor`'s pod. The short name `intent` resolves in `executor`'s namespace only through the alias `intent` that the alias flow writes there. The pass therefore shows that the changed alias flow still writes the aliases of running deployments (FR-009). This session did not read the agent log.

The image was built once before this session and served the sessions of tasks T035 and T036. The build reused cached layers:

```bash
export STYRMIN_IMAGE_VER=e2e-503-1792194439
docker compose build server   # 2026-10-16T23:47:19Z to 23:47:26Z, at commit af69546c
```

| Item | Value |
|---|---|
| pytest node IDs | `backend/tests/e2e/test_service_discovery.py::test_service_discovery_between_apps[ui-chromium]` (ran), `backend/tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service[ui-chromium]` (skipped, `api_only`), `backend/tests/e2e/test_service_discovery.py::test_deleted_deployment_leaves_no_alias[ui-chromium]` (skipped, `api_only`) |
| Code under test | commit `af69546c`, working tree unchanged except the tick of T034 in `tasks.md` |
| Exact command | `export STYRMIN_IMAGE_VER=e2e-503-1792194439 npm_config_ignore_workspace=true; exec 3< <(sleep infinity); spid=$!; uv run pytest backend/tests/e2e/test_service_discovery.py -k ui-chromium -v -s --pdb <&3 > e2e-ui-1.log 2>&1 & ppid=$!; wait "$ppid"; exec 3<&-; kill "$spid"` (a `tail -F` loop next to it wrote each result line with the time it appeared) |
| Start (UTC) | `2026-10-16T23:50:54Z` |
| `PASSED` line appeared (UTC) | `2026-10-16T23:53:07Z` |
| End, pytest exited (UTC) | `2026-10-16T23:53:13Z` |
| vcluster name | `pytest-7b9d70a7-17e5-422b-befa-a22d68c0bd16` (deleted by the fixture teardown after the pass) |
| Kubeconfig path during the run | `/tmp/pytest-of-root/pytest-1874/vcluster0/kubeconfig` |
| Summary line | `====== 1 passed, 2 skipped, 3 deselected, 1 warning in 136.63s (0:02:16) =======` |

Verbatim result lines (ANSI color codes removed). The fixture output appears between the first node ID and its `PASSED`, and the vcluster teardown log shares the last line:

```text
backend/tests/e2e/test_service_discovery.py::test_service_discovery_between_apps[ui-chromium] 23:50:56 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
...
PASSED
backend/tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service[ui-chromium] SKIPPED
backend/tests/e2e/test_service_discovery.py::test_deleted_deployment_leaves_no_alias[ui-chromium] SKIPPED23:53:07 info Removing vCluster container vcluster.cp.pytest-7b9d70a7-17e5-422b-befa-a22d68c0bd16...
```

The 3 deselected items are the `api-chromium` variants. The one warning is the same `DeprecationWarning` from `kr8s/_vendored/asyncache` as in the `api-chromium` session.

## Walk-through of quickstart.md (task T036)

The session of task T015 had ended, so the two `kubectl` checks ran on a new `api-chromium` session of the module, on 2026-10-16, with the same image as the `ui-chromium` session (`e2e-503-1792194439`, commit `af69546c`).

### Unit tests

```bash
uv run pytest backend/tests/unit/agent/test_service_aliases.py \
  backend/tests/unit/agent/test_apply_service.py \
  backend/tests/unit/agent/test_namespace_primitives.py \
  backend/tests/unit/test_deployment_deletion_operator.py \
  backend/tests/unit/services/test_context_deleting_peer_services.py -v
```

Run from `2026-10-16T23:57:55Z` to `23:57:57Z`. Summary line: `============================== 85 passed in 0.30s ==============================`. The 85 tests are 33 in `test_service_aliases.py`, 4 in `test_apply_service.py`, 11 in `test_namespace_primitives.py`, 36 in `test_deployment_deletion_operator.py` and 1 in `test_context_deleting_peer_services.py`. This matches the expected result.

### E2E session with a pause after the deletion

For this session only, a temporary `breakpoint()` was added as the last line of `test_deleted_deployment_leaves_no_alias`, after its last assertion, so pytest paused once `intent`'s status was `deleted` and no alias of `intent` was left in `executor`'s namespace. The line was removed after the session, and `git diff -- backend/` was empty afterwards.

Standard input of pytest was a named pipe that a `sleep infinity` process held open, instead of the `sleep infinity |` of quickstart.md, so that pdb could receive `c` after the checks and the test could finish:

| Item | Value |
|---|---|
| pytest node IDs | `backend/tests/e2e/test_service_discovery.py::test_service_discovery_between_apps[api-chromium]`, `backend/tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service[api-chromium]`, `backend/tests/e2e/test_service_discovery.py::test_deleted_deployment_leaves_no_alias[api-chromium]` |
| Exact command | `export STYRMIN_IMAGE_VER=e2e-503-1792194439 npm_config_ignore_workspace=true; mkfifo pdb-in-api-qs; sleep infinity > pdb-in-api-qs & spid=$!; exec 3< pdb-in-api-qs; uv run pytest backend/tests/e2e/test_service_discovery.py -k api-chromium -v -s --pdb <&3 > e2e-api-qs.log 2>&1 & ppid=$!; wait "$ppid"; exec 3<&-; kill "$spid"`, and after the checks `printf 'c\n' > pdb-in-api-qs` |
| Start (UTC) | `2026-10-16T23:54:23Z` |
| Paused at the `breakpoint()` (UTC) | `2026-10-16T23:56:55Z` |
| `kubectl` checks (UTC) | `2026-10-16T23:57:24Z` |
| `c` sent, last `PASSED` line (UTC) | `2026-10-16T23:57:37Z` |
| End, pytest exited (UTC) | `2026-10-16T23:57:42Z` |
| vcluster name | `pytest-3804abbd-c870-4df7-9241-b327e13e4118` (deleted by the fixture teardown after the pass) |
| Kubeconfig path during the run | `/tmp/pytest-of-root/pytest-1877/vcluster0/kubeconfig` |
| Summary line | `============ 3 passed, 3 deselected, 1 warning in 196.42s (0:03:16) ============` |

Verbatim result lines with the time each appeared in the log (ANSI color codes removed; the first `PASSED` is the discovery test's, after its fixture output):

```text
2026-10-16T23:56:25Z PASSED
2026-10-16T23:56:45Z backend/tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service[api-chromium] PASSED
2026-10-16T23:56:55Z >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> PDB set_trace >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
2026-10-16T23:57:37Z >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> PDB continue >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
2026-10-16T23:57:37Z PASSED23:57:37 info Removing vCluster container vcluster.cp.pytest-3804abbd-c870-4df7-9241-b327e13e4118...
2026-10-16T23:57:41Z ============ 3 passed, 3 deselected, 1 warning in 196.42s (0:03:16) ============
```

The last `PASSED` belongs to `test_deleted_deployment_leaves_no_alias[api-chromium]`. The log printed its node ID right after the rename test's `PASSED`, followed by the output of a git push from a fixture and then the pause:

```text
backend/tests/e2e/test_service_discovery.py::test_deleted_deployment_leaves_no_alias[api-chromium] counting objects: 30, done.
```

In this session `intent` had the id `c90a04f1-17d3-4565-a8ff-7a8e38565a54` and `executor` had the id `dc7f7c3e-75d8-4724-b077-c52377174fb1`. The environment also held the ingress controller deployment in `styrmin-56ae4f46-958e-4e88-8f33-3bc5ac6621a6`.

### The two kubectl checks, in all namespaces

`ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1` returned `/tmp/pytest-of-root/pytest-1877/vcluster0/kubeconfig`, the only kubeconfig of that form on the host at that time. Its context, `vcluster-docker_pytest-3804abbd-c870-4df7-9241-b327e13e4118`, names this session's vcluster.

```text
$ kubectl get svc -A -l styrmin.io/service-alias=true,styrmin.io/deployment-id=c90a04f1-17d3-4565-a8ff-7a8e38565a54
No resources found          # on standard error; standard output empty; exit 0

$ kubectl get svc -A -l styrmin.io/service-alias=true \
    -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name} {.spec.externalName}{"\n"}{end}' \
    | grep "styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54"
                            # no output; grep exit 1 (no line matched)
```

For context, at the same time:

- `kubectl get svc -A -l styrmin.io/service-alias=true` listed no Service at all. `executor`'s aliases had been in `intent`'s namespace, which was gone (`kubectl get ns styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54` returned `NotFound`), and the alias `intent` in `executor`'s namespace had been deleted by the teardown.
- `kubectl get styrmindeployments -A` listed only `executor` and the ingress controller deployment, both `Ready` and `Running`.

### Agent log of the deletion of `intent`

The alias flow of the rename test wrote the alias `intent` into `executor`'s namespace 8 seconds before the deletion:

```text
2026-10-16T23:56:37.777956959Z 23:56:37.777 | INFO    | Flow run 'Apply service aliases' - Applying service alias: intent in namespace styrmin-dc7f7c3e-75d8-4724-b077-c52377174fb1
```

The `deletionRequested` handler deleted it in the new first teardown step:

```text
2026-10-16T23:56:45.576359393Z 2026-10-16 23:56:45,576 INFO     kopf.objects: Deletion requested via spec for styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54/styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54 — running teardown
2026-10-16T23:56:45.576375944Z 2026-10-16 23:56:45,576 INFO     kopf.objects: Teardown step 1: service aliases of c90a04f1-17d3-4565-a8ff-7a8e38565a54 in all namespaces
2026-10-16T23:56:45.641640601Z 2026-10-16 23:56:45,641 INFO     kopf.objects: Deleted 1 service aliases of c90a04f1-17d3-4565-a8ff-7a8e38565a54
2026-10-16T23:56:45.641666279Z 2026-10-16 23:56:45,641 INFO     kopf.objects: Teardown step 2: Services / Middlewares for styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54/styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54
2026-10-16T23:56:45.645397981Z 2026-10-16 23:56:45,645 INFO     kopf.objects: Teardown step 3: HelmRelease for styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54/styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54
2026-10-16T23:56:45.656737979Z 2026-10-16 23:56:45,656 INFO     kopf.objects: Teardown step 4: NetworkPolicies / Secrets for styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54/styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54
2026-10-16T23:56:45.670445262Z 2026-10-16 23:56:45,670 INFO     kopf.objects: Namespace styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54 delete requested
```

The delete handler ran when the StyrminDeployment was deleted with its namespace, and found no alias left:

```text
2026-10-16T23:56:51.081542611Z 2026-10-16 23:56:51,081 INFO     kopf.objects: Deleting StyrminDeployment styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54/styrmin-c90a04f1-17d3-4565-a8ff-7a8e38565a54 (safety-net path), cleaning up resources
2026-10-16T23:56:51.081552039Z 2026-10-16 23:56:51,081 INFO     kopf.objects: Teardown step 1: service aliases of c90a04f1-17d3-4565-a8ff-7a8e38565a54 in all namespaces
2026-10-16T23:56:51.085211415Z 2026-10-16 23:56:51,085 INFO     kopf.objects: Deleted 0 service aliases of c90a04f1-17d3-4565-a8ff-7a8e38565a54
```

### Results that differ from quickstart.md

- The first `kubectl` command does not print nothing: it prints `No resources found` on standard error, with empty standard output and exit code 0. The second command prints nothing, as expected.
- At the time of the checks the cluster held no alias of any deployment, so the second check could not have found an alias of `intent` even without the fix. The positive evidence is the first check, the E2E test's own check before the deletion (the alias `intent` was in `executor`'s namespace), and the agent log line `Deleted 1 service aliases of c90a04f1-17d3-4565-a8ff-7a8e38565a54`.
- `ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1` sorts by name, not by time. On this host it found one kubeconfig, which was this session's. When other sessions leave kubeconfigs, it can return another session's file (for example `pytest-999` sorts after `pytest-1877`); `ls -t ... | head -1`, and a check of the context name, find the right one.
- All other results matched: the unit tests passed, the three E2E tests passed with the new one last, and the agent log showed `Teardown step 1: service aliases of <A id> in all namespaces` and `Deleted <n> service aliases of <A id>` on both deletion paths.

## api-chromium session after the review fixes (2026-10-17)

The session ran after the review fixes: the second read follows the operator teardown's rule (rule A), the flow deletes a written alias whatever namespace holds it (rule B), and `test_deleted_deployment_leaves_no_alias` waits with `wait_for_deployment_status` from `backend/tests/e2e/helpers/ingress.py` (timeout 300 seconds). It passed at the first attempt.

The image was built before the session with its own tag. A check in the image found `find_deleted_deployment_namespaces` in `styrmin_backend/agent/tasks/service_aliases.py` and the canonical-id line in `styrmin_backend/operator/handlers/styrmin_deployment.py`. The working tree held commit `d3703200` plus the uncommitted review fixes, which are now commits `32d0fd2f` (code and unit tests) and `88a66613` (documentation).

```bash
export STYRMIN_IMAGE_VER=e2e-503-1792203741
docker compose build server
```

| Item | Value |
|---|---|
| pytest node IDs | `backend/tests/e2e/test_service_discovery.py::test_service_discovery_between_apps[api-chromium]`, `backend/tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service[api-chromium]`, `backend/tests/e2e/test_service_discovery.py::test_deleted_deployment_leaves_no_alias[api-chromium]` |
| Exact command | `export STYRMIN_IMAGE_VER=e2e-503-1792203741 npm_config_ignore_workspace=true; exec 3< <(sleep infinity); spid=$!; uv run pytest backend/tests/e2e/test_service_discovery.py -k api-chromium -v -s --pdb <&3 > e2e-api-1.log 2>&1; rc=$?; exec 3<&-; kill "$spid"` |
| Start (UTC) | `2026-10-17T02:25:24Z` |
| Last `PASSED` line (UTC) | `2026-10-17T02:27:54Z` |
| End, pytest exited (UTC) | `2026-10-17T02:27:59Z`, exit code 0 |
| vcluster name | `pytest-fc2c9cbe-76c5-4d80-ac02-1b81903a4703` (deleted by the fixture teardown after the pass) |
| Kubeconfig path during the run | `/tmp/pytest-of-root/pytest-1892/vcluster0/kubeconfig`, context `vcluster-docker_pytest-fc2c9cbe-76c5-4d80-ac02-1b81903a4703` |
| Summary line | `============ 3 passed, 3 deselected, 1 warning in 152.85s (0:02:32) ============` |

Verbatim `PASSED` lines (ANSI color codes removed):

```text
backend/tests/e2e/test_service_discovery.py::test_service_discovery_between_apps[api-chromium] 02:25:26 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
...
PASSED
backend/tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service[api-chromium] PASSED
backend/tests/e2e/test_service_discovery.py::test_deleted_deployment_leaves_no_alias[api-chromium] PASSED02:27:54 info Removing vCluster container vcluster.cp.pytest-fc2c9cbe-76c5-4d80-ac02-1b81903a4703...
```

In this session `intent` had the id `9f24bf1a-dfc5-4333-952d-632a2fdbb8e6` and `executor` had the id `09712a80-459a-4e73-9eee-8f287bbecdf0`. Agent log, from `kubectl -n styrmin logs -f styrmin-styrmin-agent-agent-7b84dc5dff-fj47c --all-containers --timestamps`:

- The alias flow of the rename test wrote the alias `intent` into `executor`'s namespace 7 seconds before the deletion. It logged no skipped alias and no deleted write:

  ```text
  2026-10-17T02:27:37.353866727Z 02:27:37.353 | INFO    | Flow run 'Apply service aliases' - Applying service alias: intent in namespace styrmin-09712a80-459a-4e73-9eee-8f287bbecdf0
  ```

- The `deletionRequested` handler deleted it in the first teardown step:

  ```text
  2026-10-17T02:27:44.227171057Z 2026-10-17 02:27:44,227 INFO     kopf.objects: Deletion requested via spec for styrmin-9f24bf1a-dfc5-4333-952d-632a2fdbb8e6/styrmin-9f24bf1a-dfc5-4333-952d-632a2fdbb8e6 — running teardown
  2026-10-17T02:27:44.227192457Z 2026-10-17 02:27:44,227 INFO     kopf.objects: Teardown step 1: service aliases of 9f24bf1a-dfc5-4333-952d-632a2fdbb8e6 in all namespaces
  2026-10-17T02:27:44.303871935Z 2026-10-17 02:27:44,303 INFO     kopf.objects: Deleted 1 service aliases of 9f24bf1a-dfc5-4333-952d-632a2fdbb8e6
  ```

- The delete handler ran when the namespace deletion deleted the StyrminDeployment, and found no alias left:

  ```text
  2026-10-17T02:27:49.343486133Z 2026-10-17 02:27:49,343 INFO     kopf.objects: Deleting StyrminDeployment styrmin-9f24bf1a-dfc5-4333-952d-632a2fdbb8e6/styrmin-9f24bf1a-dfc5-4333-952d-632a2fdbb8e6 (safety-net path), cleaning up resources
  2026-10-17T02:27:49.343511060Z 2026-10-17 02:27:49,343 INFO     kopf.objects: Teardown step 1: service aliases of 9f24bf1a-dfc5-4333-952d-632a2fdbb8e6 in all namespaces
  2026-10-17T02:27:49.348019643Z 2026-10-17 02:27:49,347 INFO     kopf.objects: Deleted 0 service aliases of 9f24bf1a-dfc5-4333-952d-632a2fdbb8e6
  ```

The lines at 02:27:54 for `executor` and the ingress controller deployment come from the fixture teardown at the end of the session.

## api-chromium session after the PR #516 review fixes (2026-10-17, task T046)

Run at commit `5e817b92`, which reads the environment's current services in the alias step (FR-018) and replaces the 60-second wait of `c4fd1534`.

| | |
|---|---|
| pytest node IDs | `backend/tests/e2e/test_service_discovery.py::test_service_discovery_between_apps[api-chromium]`, `backend/tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service[api-chromium]`, `backend/tests/e2e/test_service_discovery.py::test_deleted_deployment_leaves_no_alias[api-chromium]` |
| Exact command | `export STYRMIN_IMAGE_VER=e2e-503-review-1792246824 npm_config_ignore_workspace=true; docker compose build server; exec 3< <(sleep infinity); spid=$!; uv run pytest backend/tests/e2e/test_service_discovery.py -k api-chromium -v -s --pdb <&3 > e2e-api.log 2>&1; rc=$?; exec 3<&-; kill "$spid"` |
| Start, vcluster creation (UTC) | `2026-10-17T14:20:34Z` |
| Last `PASSED` line (UTC) | `2026-10-17T14:22:53Z` |
| End | pytest exit code 0 |
| vcluster name | `pytest-2d5b7dd5-5f05-456d-bb57-ee0036f014c1` (deleted by the fixture teardown after the pass) |
| Kubeconfig path during the run | `/tmp/pytest-of-root/pytest-1922/vcluster0/kubeconfig` |
| Summary line | `============ 3 passed, 3 deselected, 1 warning in 144.51s (0:02:24) ============` |

Verbatim `PASSED` lines (ANSI color codes removed):

```text
PASSED
backend/tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service[api-chromium] PASSED
backend/tests/e2e/test_service_discovery.py::test_deleted_deployment_leaves_no_alias[api-chromium] PASSED14:22:53 info Removing vCluster container vcluster.cp.pytest-2d5b7dd5-5f05-456d-bb57-ee0036f014c1...
```

### A paused session to read the alias step's log

The pytest log does not show the flows' logs, so a pass does not show whether the alias step read the server's list or fell back to the context. A second session ran `test_deleted_deployment_leaves_no_alias[api-chromium]` alone, with a temporary `breakpoint()` before the deletion (not committed), at image tag `e2e-503-review-1792247020`. vcluster `pytest-3c88fcd7-34ed-4d07-9e3e-0d0e17cf1fdd`, kubeconfig `/tmp/pytest-of-root/pytest-1924/vcluster0/kubeconfig`. Closing the session's stdin ended it at the breakpoint (pytest exit code 2), and the fixture teardown deleted the vcluster.

In this session `intent` had the id `9b839b61-161a-45d5-a8df-dbbdd98d49a7`, `executor` had the id `9f899b92-6a71-4d9f-85cd-85ae8f8cc3f7`, and the environment's ingress controller deployment had the id `e7e183ca-a512-4a34-962c-ec67be0bdf52`. Alias lines of `kubectl -n styrmin logs styrmin-styrmin-agent-agent-69bfd9847b-m9r8p --all-containers`:

```text
14:25:31.250 | INFO    | Flow run 'Create instance (CRD)' - The server lists services of deployments that the context does not list: 9b839b61-161a-45d5-a8df-dbbdd98d49a7, 9f899b92-6a71-4d9f-85cd-85ae8f8cc3f7
14:25:31.424 | INFO    | Flow run 'Apply service aliases' - Skipping service alias intent in namespace styrmin-e7e183ca-a512-4a34-962c-ec67be0bdf52: namespace styrmin-9b839b61-161a-45d5-a8df-dbbdd98d49a7 does not exist or is terminating, or the deletion of its deployment was requested
14:25:31.425 | INFO    | Flow run 'Apply service aliases' - Skipping service alias executor in namespace styrmin-e7e183ca-a512-4a34-962c-ec67be0bdf52: namespace styrmin-9f899b92-6a71-4d9f-85cd-85ae8f8cc3f7 does not exist or is terminating, or the deletion of its deployment was requested
14:25:36.476 | INFO    | Flow run 'Create instance (CRD)' - The server lists services of deployments that the context does not list: 9f899b92-6a71-4d9f-85cd-85ae8f8cc3f7
14:25:36.588 | INFO    | Flow run 'Apply service aliases' - Applying service alias: executor in namespace styrmin-9b839b61-161a-45d5-a8df-dbbdd98d49a7
14:25:36.611 | INFO    | Flow run 'Apply service aliases' - Applying service alias: intent in namespace styrmin-9f899b92-6a71-4d9f-85cd-85ae8f8cc3f7
14:25:36.702 | INFO    | Flow run 'Apply service aliases' - Applying service alias: intent in namespace styrmin-9f899b92-6a71-4d9f-85cd-85ae8f8cc3f7
14:25:36.726 | INFO    | Flow run 'Apply service aliases' - Applying service alias: executor in namespace styrmin-9b839b61-161a-45d5-a8df-dbbdd98d49a7
```

- At 14:25:36.476, the create flow of `intent`, whose context was built before `executor` was requested, read `executor`'s services from the server and wrote both aliases. This is the case of CI run 39030125607, in which neither alias was written.
- The ingress controller deployment's flow read both deployments from the server at 14:25:31 and skipped them, because their namespaces did not exist yet.
- No line says that the server could not be read.
