# E2E Local-PASS Evidence: A Clone Writes Its Own Service Aliases (#530)

Constitution §V definition-of-done record for the E2E tasks of spec 030. Each section records one pytest session of the two `shard_env_backup` nodes of `backend/tests/e2e/test_backup_restore.py`.

| Session | Task | Image tag | Result |
|---|---|---|---|
| `api-chromium`, first attempt | T035 | `e2e-530-1792325479` | `1 failed, 1 passed, 2 deselected` (test defect, fixed in `73d9d4bf`) |
| `api-chromium`, second attempt | T035 | `e2e-530-1792325479` | `2 passed, 2 deselected` |

## Styrmin image under test

The image was built once before the sessions, with a tag of its own, because the fixture's parallel `docker compose build` races on one tag:

```bash
export STYRMIN_IMAGE_VER=e2e-530-1792325479
docker compose build server
```

The build finished at `2026-10-18T12:11:31Z`, after commit `93f757b2`. The commits after `28b1bfc8` (`93f757b2`, `1d9f7ce3`, `73d9d4bf`) change only `docs/`, `dev/`, `specs/` and the E2E test, which runs on the host, so the image holds all the backend code of the tested commit. The `styrmin_deployment` fixture installs the Helm chart with `image.tag` and `styrmin-agent.image.tag` set to `STYRMIN_IMAGE_VER`.

## api-chromium (T035)

The passing session ran at commit `73d9d4bf`.

| Item | Value |
|---|---|
| pytest node IDs | `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium]`, `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]` |
| Exact command | see below |
| Start (UTC) | `2026-10-18T12:25:20+00:00` |
| End, pytest exited (UTC) | `2026-10-18T12:34:02+00:00` (exit code 0) |
| vcluster name | `pytest-17181d4c-5275-4329-9a90-cf4fbb4fd38f` (deleted by the fixture teardown after the pass) |
| Kubeconfig path during the run | `/tmp/pytest-of-root/pytest-2021/vcluster0/kubeconfig` |
| Image tag | `e2e-530-1792325479` |
| HEAD commit tested | `73d9d4bffcfb6010fcf34b1cecddea2a9dd09f22` |
| Summary line | `============ 2 passed, 2 deselected, 1 warning in 519.50s (0:08:39) ============` |

Exact command:

```bash
export STYRMIN_IMAGE_VER=e2e-530-1792325479
exec 3< <(sleep infinity); spid=$!
uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle" "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" -k api-chromium -v -s --pdb <&3 > chunk10-e2e-api.log 2>&1
exec 3<&-; kill "$spid"
```

The `sleep infinity` file descriptor keeps the standard input of pytest open, so pdb would pause on a failure. pytest ran the nodes in file order: the environment backup and restore first, then the clone. The 2 deselected items are the `ui-chromium` variants.

Verbatim `PASSED` lines (ANSI color codes removed). With `-s`, the fixture output appears between the first node ID and its `PASSED`, and the vcluster teardown log shares the last line:

```text
backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium] 12:25:21 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
...
PASSED
backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium] PASSED12:33:56 info Removing vCluster container vcluster.cp.pytest-17181d4c-5275-4329-9a90-cf4fbb4fd38f...
```

The one warning is the `DeprecationWarning` for `asyncio.iscoroutinefunction` raised in `kr8s/_vendored/asyncache`. It is not related to this change.

### First attempt: the SC-001 check could not read an internal deployment

The first session (`2026-10-18T12:13:49+00:00` to `2026-10-18T12:24:49+00:00`, vcluster `pytest-4b7a8e11-a0f9-4afb-b808-2255c97f1c41`, kubeconfig `/tmp/pytest-of-root/pytest-2017/vcluster0/kubeconfig`, commit `1d9f7ce3`) passed `test_environment_backup_and_restore_lifecycle` and failed `test_environment_clone_lifecycle`:

```text
backend/tests/e2e/test_backup_restore.py:2727:
E           TypeError: Expected 'GetDeploymentDeployment' for 'deployment' in GetDeployment, got NoneType
```

- The SC-001 check listed the new environment's deployments with `include_internal=True` and called `client.deployments.get()` for each one.
- The new environment holds an internal deployment, `styrmin-ingress-controller` (driver `traefik`), which the clone creates with the environment. The `deployment` query returns null for an internal deployment, so the check failed before it compared any alias.
- The product behaved as specified. The worker log shows that each restore ran "Apply service aliases" after its recovery: restore `3a4c456c` wrote `envcloneb32e1c05` into the namespace of the primary's counterpart and `simple-app` into the namespace of the peer's counterpart at `12:20:35`, and restore `27d360c6` wrote the same two aliases again at `12:20:42`.

Commit `73d9d4bf` reads the recorded services of the new environment with the `environmentServices` query, which lists the services of internal deployments too. That is the set that SC-001 names.

## Observer data for T037

During both sessions a loop read, every 15 seconds, `kubectl get restores.velero.io -A` (name, `spec.namespaceMapping`, `spec.labelSelector`) and `kubectl get svc -A -l styrmin.io/service-alias=true` (namespace, name, owner deployment id, `spec.externalName`), without pausing the test.

- Second attempt (passing session): `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-alias-clone-fix-l1vzt/0f67dc9b-63dd-4768-b324-c77b8a758d6f/scratchpad/chunk10-observer.log`
- First attempt: `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-alias-clone-fix-l1vzt/0f67dc9b-63dd-4768-b324-c77b8a758d6f/scratchpad/chunk10-observer-run1.log`

### Label selector of each Velero Restore

Every cross-target Restore had the selector `{"matchExpressions":[{"key":"styrmin.io/service-alias","operator":"NotIn","values":["true"]}]}`, and the in-place Restore had no selector. In the second attempt:

| Restore | Kind | Namespace mapping | Selector |
|---|---|---|---|
| `styrmin-2bd41112-3d1b-412a-9acf-0a1762a2d7c1` | in place (environment restore) | none | none |
| `styrmin-c4a87552-89e1-4d65-a6d8-e826f9a6443c` | cross-target (first clone, primary) | `styrmin-dd06de03-…` to `styrmin-4df2ee8a-…` | `NotIn` |
| `styrmin-e43819f6-74c4-4b8f-b28e-49525983edba` | cross-target (first clone, peer) | `styrmin-ad3f446f-…` to `styrmin-7a0896f1-…` | `NotIn` |
| `styrmin-7d3c08c0-f210-4210-b59c-edc8f033d612` | cross-target (re-clone, primary) | `styrmin-dd06de03-…` to `styrmin-d2339d2e-…` | `NotIn` |

The first attempt showed the same: `styrmin-a6cb55e2-…` in place with no selector, and `styrmin-3a4c456c-…` and `styrmin-27d360c6-…` cross-target with the `NotIn` selector.

### Alias targets in the clones' namespaces

In the second attempt, the source environment's deployments were the primary `dd06de03`, the second deployment of the backup test `f2d50526` and the peer `ad3f446f`. No alias in a namespace of either clone pointed to one of these namespaces.

- First clone, primary's counterpart `styrmin-4df2ee8a-…`: `envclone5d1b7442`, owner `7a0896f1`, target `styrmin-7a0896f1-…`, the peer's counterpart.
- First clone, peer's counterpart `styrmin-7a0896f1-…`: `simple-app`, owner `4df2ee8a`, target `styrmin-4df2ee8a-…`, the primary's counterpart.
- Re-clone, primary's counterpart `styrmin-d2339d2e-…`: no alias in the reads at `12:33:29` and `12:33:44`. The peer was not cloned, so the namespace has no alias for the peer's service `envclone5d1b7442` (SC-002).

The source environment's own aliases, `simple-app` in the peer's namespace and `envclone5d1b7442` in the primary's namespace, stayed in place in every read up to `12:33:44`.

The 15-second loop saw the first clone's counterpart aliases in one read only (`12:32:44`), because the test deletes that environment soon after it checks it.

Each clone's environment also held a third namespace with an alias: `styrmin-01ee308d-…` (`envclone5d1b7442` to `styrmin-7a0896f1-…`) and `styrmin-3e83a69e-…` (`simple-app` to `styrmin-d2339d2e-…`). Both targets are inside the same clone. In the first attempt, the worker log showed that this namespace belongs to the clone's internal `styrmin-ingress-controller`. Its deployment records no service, so it receives aliases only from its own create flow. That flow skipped the alias of a counterpart whose namespace did not exist yet ("Skipping service alias envcloneb32e1c05 … namespace styrmin-0bf35a41-… does not exist"). SC-001 covers only the counterparts' namespaces, so this namespace is outside its scope. For run 2, the deployment that owns this namespace is not confirmed, because the cluster was deleted after the pass.
