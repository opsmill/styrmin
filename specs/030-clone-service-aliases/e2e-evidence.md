# E2E Local-PASS Evidence: A Clone Writes Its Own Service Aliases (#530)

Constitution §V definition-of-done record for the E2E tasks of spec 030. Each section records one pytest session of the two `shard_env_backup` nodes of `backend/tests/e2e/test_backup_restore.py`.

| Session | Task | Image tag | Result |
|---|---|---|---|
| `api-chromium`, first attempt | T035 | `e2e-530-1792325479` | `1 failed, 1 passed, 2 deselected` (test defect, fixed in `73d9d4bf`) |
| `api-chromium`, second attempt | T035 | `e2e-530-1792325479` | `2 passed, 2 deselected` |
| `ui-chromium` | T036 | `e2e-530-1792325479` | `2 passed, 2 deselected` |
| `api-chromium`, at the final head `ffbcf1b1` | re-run after the review | `e2e-530-r2-1792394706` | `2 passed, 2 deselected` |
| `ui-chromium`, at the final head `ffbcf1b1` | re-run after the review | `e2e-530-r2-1792394706` | `2 passed, 2 deselected` |
| `api-chromium`, after the review of #531 | re-run at `b21ab009` | `e2e-530-r3-1792403506` | `2 passed, 2 deselected` |
| `ui-chromium`, after the review of #531 | re-run at `b21ab009` | `e2e-530-r3-1792403506` | `2 passed, 2 deselected` |

The first three sessions ran on another host, before the review fix `f7bb114f`. The fourth and fifth are described in [Re-run at the final head](#re-run-at-the-final-head-ffbcf1b1), and the last two in [Re-run after the review of #531](#re-run-after-the-review-of-531-b21ab009).

The branch was rebased onto `develop` at `a5ec9446` on 2026-10-19, before the last two sessions. The commit SHAs in the sections before that one name the commits before the rebase. [pr-notes.md](pr-notes.md), "Commits", maps them to the rebased commits.

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

## ui-chromium (T036)

The session ran at commit `b364b819`. After `73d9d4bf`, that commit changes only `specs/030-clone-service-aliases/`, so the E2E test and the backend code are the same as in the passing `api-chromium` session.

| Item | Value |
|---|---|
| pytest node IDs | `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[ui-chromium]`, `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]` |
| Exact command | see below |
| Start (UTC) | `2026-10-18T12:37:33+00:00` |
| End, pytest exited (UTC) | `2026-10-18T12:46:44+00:00` (exit code 0) |
| vcluster name | `pytest-cd1a98bd-0f3d-44ec-abac-44aec202970b` (deleted by the fixture teardown after the pass) |
| Kubeconfig path during the run | `/tmp/pytest-of-root/pytest-2022/vcluster0/kubeconfig` |
| Image tag | `e2e-530-1792325479` |
| HEAD commit tested | `b364b819c5120260e169eaca1d40b0172682a1aa` |
| Summary line | `============ 2 passed, 2 deselected, 1 warning in 547.90s (0:09:07) ============` |

Exact command:

```bash
export STYRMIN_IMAGE_VER=e2e-530-1792325479
exec 3< <(sleep infinity); spid=$!
uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle" "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" -k ui-chromium -v -s --pdb <&3 > chunk11-e2e-ui.log 2>&1
exec 3<&-; kill "$spid"
```

The full pytest log is `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-alias-clone-fix-l1vzt/0f67dc9b-63dd-4768-b324-c77b8a758d6f/scratchpad/chunk11-e2e-ui.log`. The 2 deselected items are the `api-chromium` variants.

In this variant the scenario driver runs its steps through the web UI with Playwright. The environment backup and the environment restore run from the Backups tab of the environment, and the clone and the re-clone run from the Clones tab of the source environment.

Verbatim `PASSED` lines (ANSI color codes removed). With `-s`, the fixture output appears between the first node ID and its `PASSED`, and the vcluster teardown log shares the last line:

```text
backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[ui-chromium] 12:37:35 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
...
PASSED
backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium] PASSED12:46:38 info Removing vCluster container vcluster.cp.pytest-cd1a98bd-0f3d-44ec-abac-44aec202970b...
```

The one warning is the same `DeprecationWarning` for `asyncio.iscoroutinefunction` raised in `kr8s/_vendored/asyncache`. It is not related to this change.

### Observer data of the ui-chromium session

The same 15-second loop as in the `api-chromium` sessions read the Velero Restores and the alias services 35 times, from `12:37:57` to `12:46:44`. Its log is `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-alias-clone-fix-l1vzt/0f67dc9b-63dd-4768-b324-c77b8a758d6f/scratchpad/chunk11-observer.log`. The first two reads ran before Velero was installed and returned `the server doesn't have a resource type "restores"`.

In this session, the primary deployment was `f4b68bb0` (service `simple-app`), the second deployment of the backup test was `320ff969` (service `envsnap360d73bb`), and the peer of the clone test was `c295c515` (service `envclone9bbc2c97`).

| Restore | Kind | Namespace mapping | Selector |
|---|---|---|---|
| `styrmin-8531f746-6ef4-4242-a646-bdacfd1b58b0` | in place (environment restore) | none | none |
| `styrmin-3f90f94f-32de-40b0-887d-89a05cc195f3` | cross-target (first clone, primary) | `styrmin-f4b68bb0-…` to `styrmin-c2653e30-…` | `NotIn` |
| `styrmin-6990087f-a88f-4f20-af97-a783465a823f` | cross-target (first clone, peer) | `styrmin-c295c515-…` to `styrmin-86a4174e-…` | `NotIn` |
| `styrmin-66c45d76-9a30-41bd-a14b-96facf65214e` | cross-target (re-clone, primary) | `styrmin-f4b68bb0-…` to `styrmin-2470d23f-…` | `NotIn` |

`NotIn` stands for `{"matchExpressions":[{"key":"styrmin.io/service-alias","operator":"NotIn","values":["true"]}]}`.

Aliases that the observer read:

- Environment restore: the aliases `simple-app` in `styrmin-320ff969-…` (target `styrmin-f4b68bb0-…`) and `envsnap360d73bb` in `styrmin-f4b68bb0-…` (target `styrmin-320ff969-…`) were present in every read from `12:40:13` to `12:42:44`, including the reads at `12:42:28` and `12:42:44`, after the in-place Restore appeared at `12:42:13`. The next read, at `12:42:59`, held no alias.
- First clone, primary's counterpart `styrmin-c2653e30-…`: `envclone9bbc2c97`, owner `86a4174e`, target `styrmin-86a4174e-…`, the peer's counterpart. Seen in one read (`12:45:14`).
- First clone, peer's counterpart `styrmin-86a4174e-…`: `simple-app`, owner `c2653e30`, target `styrmin-c2653e30-…`, the primary's counterpart. Seen in one read (`12:45:14`).
- Re-clone, primary's counterpart `styrmin-2470d23f-…`: no alias in the reads at `12:45:59`, `12:46:14` and `12:46:29`. The peer was not cloned, so the namespace has no alias for the peer's service `envclone9bbc2c97` (SC-002).
- No alias in a namespace of either clone pointed to `styrmin-f4b68bb0-…`, `styrmin-c295c515-…` or `styrmin-320ff969-…`, the namespaces of the source environment.
- The source environment's own aliases, `simple-app` in `styrmin-c295c515-…` and `envclone9bbc2c97` in `styrmin-f4b68bb0-…`, stayed in place in every read from `12:43:14` to `12:46:29`.

Each clone's environment also held a third namespace with an alias, as in the `api-chromium` session: `styrmin-a7c51807-…` (`simple-app` to `styrmin-c2653e30-…`, reads at `12:44:59` and `12:45:14`) and `styrmin-fa9e3b81-…` (`simple-app` to `styrmin-2470d23f-…`, reads at `12:45:59` and `12:46:14`). Both targets are inside the same clone. The deployment that owns these namespaces is not confirmed for this session, because the cluster was deleted after the pass and the pytest log does not name them.

## Quickstart walk-through (T037)

Each part of [quickstart.md](quickstart.md) was checked at commit `405813a7`. The unit and functional tests ran again. The E2E tests did not run again. The manual check used the observer logs of the E2E sessions instead of a paused session.

### Unit and functional tests: every expectation is met

The quickstart's command ran as written, with its output saved to a log:

```bash
uv run pytest backend/tests/unit/agent/test_backup_builders.py \
  backend/tests/unit/agent/test_service_aliases.py \
  backend/tests/unit/workflows/test_restore_steps.py \
  backend/tests/unit/services/backup/test_environment_clone_status.py \
  backend/tests/functional/graphql/test_environment_clone.py -v 2>&1 | tee chunk12-quickstart-tests.log
```

| Item | Value |
|---|---|
| Start (UTC) | `2026-10-18T12:49:45+00:00` |
| End (UTC) | `2026-10-18T12:49:56+00:00` (exit code 0) |
| Summary line | `============================= 268 passed in 5.63s ==============================` |
| Log | `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-alias-clone-fix-l1vzt/0f67dc9b-63dd-4768-b324-c77b8a758d6f/scratchpad/chunk12-quickstart-tests.log` |

The tests that check each expectation of the quickstart:

- A cross-target restore renders the label selector and an in-place restore does not: `test_cross_target_restore_leaves_out_the_service_aliases`, `test_in_place_restore_has_no_label_selector` and `test_restores_do_not_share_the_label_selector` in `test_backup_builders.py`.
- The restore steps include "Create and delete service aliases" for a cross-target restore only. The quickstart uses the same title as `SERVICE_ALIASES` in `backend/styrmin_backend/domain/steps.py` (key `resource:service-aliases`).
  - `test_a_cross_target_restore_writes_the_aliases_after_the_recovery` and `test_an_in_place_restore_writes_no_aliases` in `test_restore_steps.py` check when the step runs. They replace the step with a mock.
  - `test_a_cross_target_restore_that_fails_before_its_end_writes_no_aliases` (cases `recovery-failed` and `velero-failed`) checks that a restore that fails before its recovery succeeds does not run the step.
  - `test_a_refused_alias_write_fails_the_alias_step_and_the_recovery` runs the real step and checks that its record is named "Create and delete service aliases".
- A refused alias write fails the restore: `test_a_refused_alias_write_fails_the_alias_step_and_the_recovery` (the step fails with the error, and the stored result reads `recovered: False` with the alias error) and `test_a_refused_alias_write_fails_the_restore_and_the_counterpart` (the restore and the counterpart are set to `FAILED` with the alias error).
  - Note (2026-10-19): `323b20bf`, after the review of #531, changed this behaviour and renamed both tests. `test_a_refused_alias_write_fails_the_alias_step_but_not_the_recovery` checks that the stored result reads `recovered: True` with the error under `aliases_error`. `test_a_refused_alias_write_fails_the_restore_and_keeps_the_counterpart_running` checks that the restore is `FAILED` with the error and the counterpart is set to `RUNNING`.
- An entry whose restore failed reads `FAILED` with the restore's error: `test_a_cloned_entry_whose_restore_failed_reads_failed_with_the_error`, `test_a_failed_restore_without_an_error_gives_the_reason_alone`, `test_every_other_entry_is_read_as_stored` and `test_the_entries_read_agree_with_the_derived_status` in `test_environment_clone_status.py`, and, through the GraphQL resolver, `test_a_cloned_entry_whose_restore_failed_reads_failed_on_every_read` in `backend/tests/functional/graphql/test_environment_clone.py`.

### E2E tests: both variants passed in T035 and T036

The E2E tests did not run again; see the sessions above. Two details of those sessions differ from the quickstart's command. Neither changes what the tests check:

- The sessions set `STYRMIN_IMAGE_VER` to a tag built before the first session.
- The sessions kept the standard input of pytest open with a private `sleep infinity` file descriptor instead of `sleep infinity |`, and wrote their logs to the scratchpad instead of `/tmp/e2e-030-api.log`.

### Manual check: the observer logs match the expected aliases and selectors

No session paused after the first clone. `--pdb` pauses only on a failure, and the two passing sessions had none. The first attempt paused after its failure, but the test's cleanup had already deleted the clone's environment by then. The check used instead the observer loop described in "Observer data for T037" above. That loop ran the quickstart's two reads every 15 seconds during each session, with `-A` instead of `-n`, and also printed the namespace mapping of each Restore.

The results compared with the quickstart's "Expected" paragraph:

- Label selector: as expected in all three sessions. Every cross-target Restore had a namespace mapping and the `NotIn` selector, and every in-place Restore had neither (tables above).
- `TARGET` and `OWNER` in the counterparts' namespaces: as expected in both passing sessions. Each alias pointed to the namespace of the other counterpart, and its owner was that counterpart's id.
  - `api-chromium`, read at `12:32:44`: `envclone5d1b7442` in `styrmin-4df2ee8a-…`, owner and target `7a0896f1`; `simple-app` in `styrmin-7a0896f1-…`, owner and target `4df2ee8a`.
  - `ui-chromium`, read at `12:45:14`: `envclone9bbc2c97` in `styrmin-c2653e30-…`, owner and target `86a4174e`; `simple-app` in `styrmin-86a4174e-…`, owner and target `c2653e30`.
  - The re-clone's counterpart held no alias in either session (SC-002).
- First attempt: the observer read no alias in the counterparts' namespaces. Its read at `12:20:31` came before the alias writes, which the agent log records at `12:20:35` and `12:20:42`. Its read at `12:20:46` came after the test's cleanup, which the agent log records at `12:20:43` ("Deleted 2 service aliases of 97eb25a5-…" and "Deleted 1 service aliases of 0bf35a41-…"). For that session, the alias writes are known from the agent log only: `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-alias-clone-fix-l1vzt/0f67dc9b-63dd-4768-b324-c77b8a758d6f/scratchpad/chunk10-diag-styrmin-styrmin-agent-agent-66749f8f4d-q4wzs.log`.

Observer logs:

- `api-chromium`, second attempt: `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-alias-clone-fix-l1vzt/0f67dc9b-63dd-4768-b324-c77b8a758d6f/scratchpad/chunk10-observer.log`
- `api-chromium`, first attempt: `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-alias-clone-fix-l1vzt/0f67dc9b-63dd-4768-b324-c77b8a758d6f/scratchpad/chunk10-observer-run1.log`
- `ui-chromium`: `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-alias-clone-fix-l1vzt/0f67dc9b-63dd-4768-b324-c77b8a758d6f/scratchpad/chunk11-observer.log`

### Differences from the quickstart, and the two fixes to it

- The manual check used observer logs taken during the runs, not a paused session.
- The quickstart did not say how to pause a passing run. In each passing session, the observer read the first clone's counterpart aliases in one read only, so they existed for less than 30 seconds. Fixed in `quickstart.md`: a paragraph says that `--pdb` pauses only on a failure, and that a temporary `breakpoint()` after the SC-001 check pauses a passing run.
- The quickstart's Restore read printed only the name and the selector, so it could not show which Restore is cross-target. Fixed in `quickstart.md`: the read also prints `spec.namespaceMapping`, as the observer did, and the "Expected" paragraph says that the cross-target Restores are the ones with a namespace mapping.
- The Velero namespace `-n styrmin` is correct. Every Restore that the observer read with `-A` was in the namespace `styrmin`, and `execute_restore_workflow` sets `velero_namespace = "styrmin"` in `backend/styrmin_backend/workflows/templates/backup.py`. Not changed.
- The kubeconfig glob matched the sessions' files, for example `/tmp/pytest-of-root/pytest-2021/vcluster0/kubeconfig`. `ls … | tail -1` returns the last path in alphabetical order. That path is the current session's only when no other pytest session runs on the host and the `pytest-<N>` numbers have the same number of digits. The observer instead picked the kubeconfig that names the session's vcluster. Not changed, because `AGENTS.md` gives the same command.

## Re-run at the final head (`ffbcf1b1`)

Both variants ran again on 2026-10-19 at commit `ffbcf1b1a55e23603691ff234cfe3b03abefd645`, so that the E2E evidence includes the review fix `f7bb114f`, which changed the shared alias step. The sessions ran on a different host from the sessions above, as the user `ubuntu`.

### Styrmin image under test

```bash
export STYRMIN_IMAGE_VER=e2e-530-r2-1792394706
docker compose build server
```

- The image was built at `2026-10-19T07:37:01Z`, at `ffbcf1b1`.
- A check in the image found the comment that `f7bb114f` adds to `apply_service_aliases_step`.
- The fixture's own `docker compose build` writes the same tag again at the start of each session, from the same commit.

### api-chromium

| Item | Value |
|---|---|
| pytest node IDs | `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium]`, `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]` |
| Start (UTC) | `2026-10-19T07:37:17+00:00` |
| End, pytest exited (UTC) | `2026-10-19T07:49:06+00:00` (exit code 0) |
| vcluster name | `pytest-0076cc5b-4796-45a6-bae4-61fec86223d8` (deleted by the fixture teardown after the pass) |
| Kubeconfig path during the run | `/tmp/pytest-of-ubuntu/pytest-3/vcluster0/kubeconfig` |
| Summary line | `=========== 2 passed, 2 deselected, 6 warnings in 706.45s (0:11:46) ============` |

### ui-chromium

| Item | Value |
|---|---|
| pytest node IDs | `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[ui-chromium]`, `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]` |
| Start (UTC) | `2026-10-19T07:53:52+00:00` |
| End, pytest exited (UTC) | `2026-10-19T08:05:45+00:00` (exit code 0) |
| vcluster name | `pytest-b34cb423-019c-4f0b-a54e-b67c454af511` (deleted by the fixture teardown after the pass) |
| Kubeconfig path during the run | `/tmp/pytest-of-ubuntu/pytest-6/vcluster0/kubeconfig` |
| Browser | Chrome Headless Shell 145.0.7632.6 (Playwright 1.58.0, `chromium-headless-shell` build 1208) |
| Summary line | `=========== 2 passed, 2 deselected, 6 warnings in 710.30s (0:11:50) ============` |

### Exact command

The command is the same for both variants, with `<variant>` set to `api-chromium` or `ui-chromium`, one pytest session per variant:

```bash
export STYRMIN_IMAGE_VER=e2e-530-r2-1792394706
exec 3< <(sleep infinity); spid=$!
uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle" "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" -k <variant> -v -s --pdb <&3 > e2e-<variant>.log 2>&1
exec 3<&-; kill "$spid"
```

### Verbatim pass lines

ANSI color codes are removed. With `-s`, the fixture output appears between the first node ID and its `PASSED`, and the vcluster teardown log shares the last line.

```text
backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium] 07:37:19 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
...
PASSED
backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium] PASSED07:49:00 info Removing vCluster container vcluster.cp.pytest-0076cc5b-4796-45a6-bae4-61fec86223d8...
```

```text
backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[ui-chromium] 07:53:54 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
...
PASSED
backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium] PASSED08:05:40 info Removing vCluster container vcluster.cp.pytest-b34cb423-019c-4f0b-a54e-b67c454af511...
```

The six warnings of each session are not related to this change:

- one `DeprecationWarning` for `asyncio.iscoroutinefunction`, raised in `kr8s/_vendored/asyncache`, as in the earlier sessions;
- five copies of the `UserWarning` "Kubernetes version v1.36.0 is not supported. Supported versions for kr8s 0.20.15 are 1.28 to 1.35", because the vcluster on this host runs Kubernetes v1.36.0.

### Observer data of the re-run

A loop read every 15 seconds, without pausing the test:

- `kubectl get restores.velero.io -A`, with the name, `spec.namespaceMapping` and `spec.labelSelector` of each Restore;
- `kubectl get svc -A -l styrmin.io/service-alias=true`, with the namespace, name, owner deployment id and `spec.externalName` of each alias.

The `api-chromium` session had 45 reads and the `ui-chromium` session 44. In the tables, `NotIn` stands for `{"matchExpressions":[{"key":"styrmin.io/service-alias","operator":"NotIn","values":["true"]}]}`.

In the `api-chromium` session:

- The source environment's deployments were the primary `0142a2de` (service `simple-app`), the second deployment of the backup test `77f3c7aa` (service `envsnap00df9cf8`) and the peer of the clone test `8edd2b80` (service `envcloneaa8a5c30`).
- The environment restore's aliases were present in every read from `07:41:07` to `07:43:58`:
  - `envsnap00df9cf8` in `styrmin-0142a2de-…`, with the target `styrmin-77f3c7aa-…`;
  - `simple-app` in `styrmin-77f3c7aa-…`, with the target `styrmin-0142a2de-…`.
- First clone, primary's counterpart `styrmin-f6a8f368-…`: it held `envcloneaa8a5c30`, with the owner `5f5eab9e` and the target `styrmin-5f5eab9e-…`, which is the peer's counterpart.
- First clone, peer's counterpart `styrmin-5f5eab9e-…`: it held `simple-app`, with the owner `f6a8f368` and the target `styrmin-f6a8f368-…`, which is the primary's counterpart.
- Re-clone, primary's counterpart `styrmin-6aa3e58c-…`: it held no alias. The peer was not cloned, so the namespace has no alias for the peer's service (SC-002).
- No alias in a namespace of either clone pointed to the source environment's namespaces.
  - The first clone's third namespace, `styrmin-6904e430-…`, held `simple-app`, with the target `styrmin-f6a8f368-…`.
  - This target is inside the same clone, as in the earlier sessions.
- The source environment's own aliases stayed in place in every read from `07:44:29` to `07:48:51`:
  - `envcloneaa8a5c30` in `styrmin-0142a2de-…`;
  - `simple-app` in `styrmin-8edd2b80-…`.

| Restore | Kind | Namespace mapping | Selector |
|---|---|---|---|
| `styrmin-2da13a01-1c9c-4cb8-baa6-00249262b81c` | in place (environment restore) | none | none |
| `styrmin-95aec874-42d1-4a2d-beb8-26ea984e2a4c` | cross-target (first clone, primary) | `styrmin-0142a2de-…` to `styrmin-f6a8f368-…` | `NotIn` |
| `styrmin-14104c7c-7d5a-4d20-887f-5c9209e70ec3` | cross-target (first clone, peer) | `styrmin-8edd2b80-…` to `styrmin-5f5eab9e-…` | `NotIn` |
| `styrmin-adeba698-397f-4944-b09c-3dacecfa5008` | cross-target (re-clone, primary) | `styrmin-0142a2de-…` to `styrmin-6aa3e58c-…` | `NotIn` |

In the `ui-chromium` session:

- The source environment's deployments were the primary `e498740d` (service `simple-app`), the second deployment `42edc1e2` (service `envsnapf61c7693`) and the peer `d64d88d9` (service `envclone96e5d404`).
- The environment restore's aliases were present from `07:56:58` to `08:00:19`:
  - `envsnapf61c7693` in `styrmin-e498740d-…`, with the target `styrmin-42edc1e2-…`;
  - `simple-app` in `styrmin-42edc1e2-…`, with the target `styrmin-e498740d-…`.
- First clone, primary's counterpart `styrmin-64a86ca8-…`: it held `envclone96e5d404`, with the owner `87e7c41d` and the target `styrmin-87e7c41d-…`, which is the peer's counterpart.
- First clone, peer's counterpart `styrmin-87e7c41d-…`: it held `simple-app`, with the owner `64a86ca8` and the target `styrmin-64a86ca8-…`, which is the primary's counterpart.
- Re-clone, primary's counterpart `styrmin-8777ce96-…`: it held no alias (SC-002).
- No alias in a namespace of either clone pointed to the source environment's namespaces.
  - The clones' third namespaces held `simple-app` with a target inside the same clone:
    - `styrmin-a453eeb9-…`, with the target `styrmin-64a86ca8-…`;
    - `styrmin-ac44abb3-…`, with the target `styrmin-8777ce96-…`.
- The source environment's own aliases stayed in place from `08:00:50` to `08:05:31`:
  - `envclone96e5d404` in `styrmin-e498740d-…`;
  - `simple-app` in `styrmin-d64d88d9-…`.

| Restore | Kind | Namespace mapping | Selector |
|---|---|---|---|
| `styrmin-e01cc036-acde-4ddb-9387-061ef6111451` | in place (environment restore) | none | none |
| `styrmin-c0a065d5-ae85-477c-a254-9f5753a6813d` | cross-target (first clone, primary) | `styrmin-e498740d-…` to `styrmin-64a86ca8-…` | `NotIn` |
| `styrmin-e08ca624-8116-4b9a-93ee-ed21572f3781` | cross-target (first clone, peer) | `styrmin-d64d88d9-…` to `styrmin-87e7c41d-…` | `NotIn` |
| `styrmin-2a8bbacc-7492-4c1b-bccc-eb40a15d89bb` | cross-target (re-clone, primary) | `styrmin-e498740d-…` to `styrmin-8777ce96-…` | `NotIn` |

### Failed attempts caused by the host

Three earlier attempts failed in fixture setup, before any test ran. None was caused by the code under test.

1. **`api-chromium`, `2026-10-19T07:26Z`** (vcluster `pytest-604cbe19-d006-46fd-b489-065b696ac605`, kubeconfig `/tmp/pytest-of-ubuntu/pytest-2/vcluster0/kubeconfig`).
   - The host's root file system was 82% full, so the vcluster's node reported `DiskPressure`.
   - The node evicted the `helm-controller` pods, and `helm upgrade --install` timed out.
   - The Docker build cache and unused images were then pruned, which freed 41 GB.
2. **`ui-chromium`, `2026-10-19T07:49Z`** (vcluster `pytest-d0195b17-e9c2-4c43-b5bb-eccc063863d1`, kubeconfig `/tmp/pytest-of-ubuntu/pytest-4/vcluster0/kubeconfig`).
   - The fixture's `docker compose build` builds three services from one image at the same time.
   - During that build, the Docker daemon stopped with `fatal error: concurrent map iteration and map write` in BuildKit (`solver/jobs.go`), and systemd restarted it.
3. **`ui-chromium`, `2026-10-19T07:51Z`** (vcluster `pytest-ace546d8-97b8-46a0-9bc7-2ccab99bbad4`, kubeconfig `/tmp/pytest-of-ubuntu/pytest-5/vcluster0/kubeconfig`).
   - The host had no Chromium for Playwright 1.58.0 (build 1208), and Playwright 1.58.0 does not support downloading it on Ubuntu 26.04.
   - The build was then installed with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 uv run playwright install chromium`.

## Re-run after the review of #531 (`b21ab009`)

Both variants ran again on 2026-10-19 at commit `b21ab00969744d19f684b0066f6453d864cb6b6c`, on the same host as the re-run at `ffbcf1b1`. This commit holds:

- the rebase onto `develop` at `a5ec9446`, which includes #467;
- `dcf60ed0`: the restore flow reads the counterpart's context from its StyrminDeployment body;
- `b7901107` and `323b20bf`: the new error of a failed alias step, and the counterpart set to `RUNNING` when only that step failed;
- `b21ab009`: step 11 of `test_environment_clone_lifecycle` is again the configuration-only re-clone, and the partial clone is step 12.

No observer loop ran in these sessions, so this section has no record of the Velero Restores or the alias Services read during them. The alias checks of the tests themselves passed.

### Styrmin image under test

```bash
export STYRMIN_IMAGE_VER=e2e-530-r3-1792403506
docker compose build server
```

- The image was built at `2026-10-19T09:51:59Z`, at `b21ab009`.
- A check in the image found `_service_aliases_error` and `aliases_error` in `styrmin_backend/workflows/templates/backup.py`, and `describe_api_answer` in `styrmin_backend/agent/service/kubernetes/utils.py`.

### api-chromium

| Item | Value |
|---|---|
| pytest node IDs | `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium]`, `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]` |
| Start (UTC) | `2026-10-19T09:52:26+00:00` |
| End, pytest exited (UTC) | `2026-10-19T10:03:48+00:00` (exit code 0) |
| vcluster name | `pytest-a15d285c-a2d9-4721-98f5-f16c4af1bdb8` (deleted by the fixture teardown after the pass) |
| Summary line | `=========== 2 passed, 2 deselected, 6 warnings in 678.83s (0:11:18) ============` |

### ui-chromium

| Item | Value |
|---|---|
| pytest node IDs | `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[ui-chromium]`, `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]` |
| Start (UTC) | `2026-10-19T10:03:48+00:00` |
| End, pytest exited (UTC) | `2026-10-19T10:16:23+00:00` (exit code 0) |
| vcluster name | `pytest-ce9cbb1b-3744-4400-aad8-569bd8fb6756` (deleted by the fixture teardown after the pass) |
| Summary line | `=========== 2 passed, 2 deselected, 6 warnings in 752.53s (0:12:32) ============` |

### Exact command

The two sessions ran one after the other, from one script, with `<variant>` set to `api-chromium` and then `ui-chromium`:

```bash
export STYRMIN_IMAGE_VER=e2e-530-r3-1792403506
exec 3< <(sleep infinity); spid=$!
uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle" "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" -k <variant> -v -s --pdb <&3 >> e2e-<variant>.log 2>&1
exec 3<&-; kill "$spid"
```

### Verbatim pass lines

ANSI color codes are removed.

```text
backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium] 09:52:28 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
...
PASSED
backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium] PASSED10:03:42 info Removing vCluster container vcluster.cp.pytest-a15d285c-a2d9-4721-98f5-f16c4af1bdb8...
```

```text
backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[ui-chromium] 10:03:50 warn There is a newer version of vcluster: v0.37.3. Run `vcluster upgrade` to upgrade to the newest version.
...
PASSED
backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium] PASSED10:16:17 info Removing vCluster container vcluster.cp.pytest-ce9cbb1b-3744-4400-aad8-569bd8fb6756...
```

The six warnings of each session are of the same two kinds as in the re-run at `ffbcf1b1`: the `DeprecationWarning` for `asyncio.iscoroutinefunction` in `kr8s/_vendored/asyncache`, and the `UserWarning` that kr8s 0.20.15 does not support Kubernetes v1.36.0.
