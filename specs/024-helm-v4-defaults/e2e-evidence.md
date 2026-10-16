# E2E Evidence: helm-controller with Helm v4 Defaults

This file records the local E2E runs for spec 024 ([#435](https://github.com/opsmill/styrmin/issues/435)), with the details that Constitution §V asks for: the pytest node IDs, the exact command, the start and end times, the vcluster and its kubeconfig path, and the `PASSED` lines as pytest printed them. Each run has its own section; add later runs at the end of the file.

- Branch: `fac/helm-v4-end3k`
- Commit tested: `f752856a` ("feat(agent): run helm-controller with Helm v4 defaults (#435)"), so the agent chart runs helm-controller v1.6.5 without `--feature-gates=UseHelm3Defaults=true`, and the every-resource label patch is the strategic merge of commit `8a5d3b61`.
- Server image: `STYRMIN_IMAGE_VER=helmv4-f752856a`, built once with `docker compose build server` before run 1 and used by every run below unless its section names another tag.
- The E2E fixture sets `STYRMIN_OPERATOR_HELM_RELEASE_TIMEOUT=240` and `STYRMIN_OPERATOR_DEPLOYMENT_READY_TIMEOUT=210` (`backend/tests/e2e/fixtures/styrmin-values.yaml`), so every HelmRelease in these runs has `spec.timeout: 4m`.
- Every run gives pytest a standard input that stays open, so `--pdb` can stop at a failure, and stops only its own `sleep` afterwards (the pattern below). This replaces the `sleep infinity |` prefix of tasks.md and has the same effect.
- Colour codes are removed from the quoted pytest lines. With `-s`, other output can sit between a node ID and its `PASSED`; where it does, the node ID is given with the line.
- FluxCD state comes from `kubectl` snapshots of the session's vcluster taken every 10 seconds during the run (HelmReleases, their Events, StyrminDeployments, Helm release Secrets, workload `managedFields`), and from the operator and helm-controller logs. The snapshots are not committed.

## Run 1: shard_task_steps, API variant (T011)

- Command, from the repository root:

  ```bash
  export STYRMIN_IMAGE_VER=helmv4-f752856a
  exec 3< <(sleep infinity); spid=$!
  uv run pytest backend/tests/e2e -m "ci and shard_task_steps" -k api-chromium -v -s --pdb <&3 > e2e-task-steps.log 2>&1
  exec 3<&-; kill "$spid"
  ```

- Start: 2026-10-16T08:41:05Z. End: 2026-10-16T08:50:28Z.
- vcluster: `pytest-aebe3cf0-7b84-4fcb-9e12-4383c63b5847` (kubeconfig context `vcluster-docker_pytest-aebe3cf0-7b84-4fcb-9e12-4383c63b5847`).
- Kubeconfig: `/tmp/pytest-of-root/pytest-1718/vcluster0/kubeconfig`.
- Collected: `collected 195 items / 190 deselected / 5 selected`.

Result lines:

```text
backend/tests/e2e/test_task_steps.py::test_hook_action_error_shows_failed_step[api-chromium]   (node ID line; PASSED follows the -s output)
PASSED
backend/tests/e2e/test_task_steps.py::test_command_output_on_failed_step[api-chromium] PASSED
backend/tests/e2e/test_task_steps.py::test_prerequisite_failure_shows_attempts[api-chromium] PASSED
backend/tests/e2e/test_task_steps.py::test_update_recreates_a_missing_namespace[api-chromium] PASSED
backend/tests/e2e/test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason[api-chromium] PASSED
=========== 5 passed, 190 deselected, 1 warning in 560.55s (0:09:20) ===========
```

The warning is a `DeprecationWarning` from `kr8s` (`asyncio.iscoroutinefunction`), not from Styrmin.

`test_helmrelease_failure_shows_fluxcd_reason` asserts that the failed "Install or upgrade the HelmRelease" step has FluxCD's reason as its detail and the pods' `ImagePullBackOff` or `ErrImagePull` in its errors, so its pass covers SC-002.

### FluxCD state during the rollback in test_helmrelease_failure_shows_fluxcd_reason

The test's deployment is `styrmin-9e0ef838-8ce0-4747-bb90-7cceae3a00cf` (HelmRelease and namespace of the same name). `test_update_recreates_a_missing_namespace` deleted its namespace before, so its Helm release history starts again at v1. The image override that cannot be pulled is HelmRelease generation 2.

Timeline, from the snapshots, FluxCD's Events and the conditions' `lastTransitionTime`:

- 08:45:50: helm-controller starts the upgrade to release v2 (v2 `lastDeployed`).
- 08:49:21 (snapshot): the operator's readiness timeout fails the rollout: StyrminDeployment `displayState: Error`, message `Deployment did not reach Ready within 210s (phase: CreatingHelmRelease)`, phase still `CreatingHelmRelease`.
- 08:49:50: the upgrade fails at the 4-minute HelmRelease timeout (`lastAttemptedReleaseActionDuration: 4m0.366317087s`). Event `UpgradeFailed`.
- 08:49:51: FluxCD rolls back to v1, which creates release v3. Event `RollbackSucceeded`.
- 08:50:02: FluxCD reports generation 2 `Ready=True`.

HelmRelease `status` at 08:49:51, after the rollback:

- `Ready`: `False`, reason `RollbackSucceeded`, observedGeneration 2, message `Helm rollback to previous release styrmin-9e0ef838-8ce0-4747-bb90-7cceae3a00cf/styrmin-9e0ef838-8ce0-4747-bb90-7cceae3a00cf.v1 with chart simple-app@0.1.0 succeeded`.
- `Released`: `False`, reason `UpgradeFailed`, observedGeneration 2, message `Helm upgrade failed for release styrmin-9e0ef838-8ce0-4747-bb90-7cceae3a00cf/styrmin-9e0ef838-8ce0-4747-bb90-7cceae3a00cf with chart simple-app@0.1.0: timeout waiting for: [Deployment/styrmin-9e0ef838-8ce0-4747-bb90-7cceae3a00cf/styrmin-simple-app status: 'InProgress']`.
- `Remediated`: `True`, reason `RollbackSucceeded`, same message as `Ready`.
- `Reconciling`: `True`, reason `ProgressingWithRetry`.
- `failures: 1`, `upgradeFailures: 1`, `lastAttemptedGeneration: 2`, `observedGeneration: 1`.

HelmRelease `status` at 08:50:12, after FluxCD reported the rollback as ready:

- `Ready`: `True`, reason `UpgradeSucceeded`, observedGeneration 2, lastTransitionTime 2026-10-16T08:50:02Z, message `Helm upgrade succeeded for release styrmin-9e0ef838-8ce0-4747-bb90-7cceae3a00cf/styrmin-9e0ef838-8ce0-4747-bb90-7cceae3a00cf.v3 with chart simple-app@0.1.0`.
- `Released`: `True`, reason `UpgradeSucceeded`, observedGeneration 2, same message and time as `Ready`.
- `Remediated` and `Reconciling` are gone.
- `failures: 1`, `upgradeFailures: 1`, `lastAttemptedGeneration: 2`, `observedGeneration: 2`. The post-renderers digest (`observedPostRenderersDigest: sha256:1da04457b3527c4c3538c191905657c614092de7b1b25b96d99c2a8c898a954d`) did not change between the two snapshots.

`status.history` at both times, as FluxCD wrote it (all with `chartVersion: 0.1.0` and `configDigest: sha256:e809f44eddadf16bf4a3de6f01ddf5aa98b0868e64b4aca4c8dfbc26598e2862`):

| Version | Status | Action | lastDeployed | Digest |
| --- | --- | --- | --- | --- |
| 3 | `deployed` | `rollback` | 2026-10-16T08:49:51Z | `sha256:697a8d16687b24036157f07f21bae730fb16d32811fb68dd8d23046a0d55b77c` |
| 2 | `failed` | `upgrade` | 2026-10-16T08:45:50Z | `sha256:a46b241db825f51be7ab5c64e8d8c7905b96462921ba51d2e042434fac6a3742` |
| 1 | `superseded` | `rollback` | 2026-10-16T08:45:18Z | `sha256:eae3a79354b3d8f73abc80ab7adb6848ac5e49ac6e219b8348c481d7018a55a2` |

The Helm release record of v1 has the description "Install complete"; why FluxCD's history names its action `rollback` is not known.

StyrminDeployment `status` that the operator wrote:

- 08:49:51: `HelmReleaseReady=False`, reason `UpgradeFailed`, with the `Released` message above; `HelmReleaseRemediated=True`, reason `RollbackSucceeded`.
- 08:50:12: phase `Failed`, `displayState: Error`, message `FluxCD rolled the release back after release v2 failed: Helm upgrade failed for release … timeout waiting for: [Deployment/styrmin-9e0ef838-8ce0-4747-bb90-7cceae3a00cf/styrmin-simple-app status: 'InProgress']`; `Ready=False`, reason `RolledBack`; `HelmReleaseReady` keeps `False`, reason `UpgradeFailed`.

### Answer: helm-controller v1.6.5 with Helm v4 defaults reports the rollback as Ready=True

Yes. 11 seconds after its rollback of a change that only adds a post-render image override, helm-controller v1.6.5 with Helm v4 defaults reported the HelmRelease's current generation `Ready=True` and `Released=True`, both with reason `UpgradeSucceeded` and the message "Helm upgrade succeeded for release ….v3", while `status.failures` and `status.upgradeFailures` stayed at 1 and the newest history entry (v3, `deployed`) directly follows the `failed` v2. It did not try the upgrade again. This is the state that the operator knowledge page describes in "Rollback reported Ready" for v1.1.0 (`dev/knowledge/agent/operator.md`), and the operator's rollback rule answered it with `RolledBack`, as the test asserts.

### The kstatus wait ran to the HelmRelease timeout

With pods in `ImagePullBackOff`, FluxCD's wait ended at the 4-minute HelmRelease timeout (4m0.37s) with `status: 'InProgress'` for the Deployment, about 30 seconds after the operator's 210-second readiness timeout. This matches research R-005: kstatus keeps such a Deployment `InProgress` and does not end the wait early.

### Apply method of the new releases

Every release record in the run's snapshots (the deployment above and the ingress controller `styrmin-bccab2d9-bb75-49c7-b079-e9b77d3b62e9`) has `apply_method: ssa`. Each workload that Helm created (`Deployment/styrmin-simple-app`, `StatefulSet/styrmin-postgresql`, `Deployment/styrmin-traefik`) has a `metadata.managedFields` entry with manager `helm-controller` and operation `Apply`, and none with operation `Update` from `helm-controller`. New installs used server-side apply.

## Run 2: shard_configuration, API variant (T012)

CI does not run this cell, so this local run is its only E2E coverage.

- Command, from the repository root:

  ```bash
  export STYRMIN_IMAGE_VER=helmv4-f752856a
  exec 3< <(sleep infinity); spid=$!
  uv run pytest backend/tests/e2e -m "ci and shard_configuration" -k api-chromium -v -s --pdb <&3 > e2e-configuration.log 2>&1
  exec 3<&-; kill "$spid"
  ```

- Start: 2026-10-16T08:53:03Z. End: 2026-10-16T09:07:28Z.
- vcluster: `pytest-de8167c0-b674-48d0-b691-0ba2facbd5e7` (kubeconfig context `vcluster-docker_pytest-de8167c0-b674-48d0-b691-0ba2facbd5e7`).
- Kubeconfig: `/tmp/pytest-of-root/pytest-1719/vcluster0/kubeconfig`.
- Collected: `collected 195 items / 175 deselected / 20 selected`. The 12 skipped tests are the `ui_only` tests in `backend/tests/e2e/configuration/`.

Result lines:

```text
backend/tests/e2e/test_deployment_container_overrides.py::test_us1_override_args_on_server[api-chromium]   (node ID line; PASSED follows the -s output)
PASSED
backend/tests/e2e/test_deployment_container_overrides.py::test_us2_command_independent_of_args[api-chromium] PASSED
backend/tests/e2e/test_deployment_container_overrides.py::test_us3_set_and_clear_command_and_args[api-chromium] PASSED
backend/tests/e2e/test_deployment_container_overrides.py::test_us4_invalid_overrides_rejected[api-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_override_then_clear[api-chromium]   (node ID line; PASSED follows the -s output)
PASSED
backend/tests/e2e/test_deployment_image_override.py::test_override_with_version_change_reaches_upgrade_job[api-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_token_follows_upgrade_and_action_job[api-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_misnamed_container_never_added[api-chromium] PASSED
===== 8 passed, 12 skipped, 175 deselected, 1 warning in 862.89s (0:14:22) =====
```

The warning is the same `kr8s` `DeprecationWarning` as in run 1.

### The component-container guard in test_misnamed_container_never_added

The test asserts that the deployment fails with `HelmReleaseReady=False`, reason `ComponentContainerNotFound`, and a message that names the component and the container, and that the live workload keeps one container and the chart image. The logs show the same sequence as with the gate (operator knowledge page, "A failed change reported in sync"):

- 09:07:20.524: helm-controller: `error while running post render on files: error in remove for path: '/spec/template/spec/styrmin.io~1component-container~1server~1wrong-name/image': Unable to remove nonexistent key: image…`. No release is stored.
- 09:07:21.296: helm-controller: `release in-sync with desired state`, 0.8 seconds later, without a new attempt.
- 09:07:21.626: operator: `Deployment styrmin-84194a6a-3bf2-4abd-a6f1-86497f4453f7/styrmin-84194a6a-3bf2-4abd-a6f1-86497f4453f7 failed: Component 'server': component container 'wrong-name' was not found in its rendered workload. Styrmin never adds a container; fix components.server.container in the driver specification file.`

### A crashing container waits the full HelmRelease timeout in test_us4_invalid_overrides_rejected

Step (d) of `test_us4_invalid_overrides_rejected` sets the server command to `["sh", "-c", ""]`, so the container exits at once, and then restores the deployment without waiting. The two updates reached the HelmRelease as generations 7 and 8 at 08:57:13 (two "Update instance (CRD)" flow runs in the operator log, 20 ms apart). helm-controller upgraded to generation 7 (release v7), waited the 4-minute timeout with the Deployment `InProgress` (`timeout waiting for: [Deployment/…/styrmin-simple-app status: 'InProgress']`), rolled back to v6 (release v8) at 09:01:14, and applied generation 8 (release v9, `Ready=True`) at 09:01:24. The test waits up to 480 seconds for the deployment to run again, so it passed. As in run 1, kstatus did not end the wait early for a container that does not start.

### Apply method of the new releases

Every release record in the run's snapshots has `apply_method: ssa`, including the failed v7 and the rollback v8 of the container override deployment, and every workload that Helm created has a `managedFields` entry with manager `helm-controller` and operation `Apply`.

## Operator rules under Helm v4 defaults (T013)

No operator change needed. Every FluxCD state that runs 1 and 2 produced got the CR status that the table in "What the timer writes in `CreatingHelmRelease`" (`dev/knowledge/agent/operator.md`) gives for it:

- `Ready=True` for a release that is not a rollback: `HelmReleaseReady=True`, reason `FluxReady`, then phase `Ready` (every install and upgrade that succeeded).
- `Ready=False` after a rollback: `HelmReleaseReady` took the reason and message of `Released=False` (`UpgradeFailed`), and `Remediated=True` was copied into `HelmReleaseRemediated` (run 1).
- `Ready=True` for FluxCD's rollback of a failed release of the current generation: phase `Failed`, `displayState: Error`, message `FluxCD rolled the release back after release v2 failed: …`, `Ready=False` with reason `RolledBack` (run 1).
- `Ready=True` after a failed upgrade that stored no release (the guard): phase `Failed` with the guard message and `HelmReleaseReady` reason `ComponentContainerNotFound` (run 2).
- Readiness timeout: `displayState: Error` and `Deployment did not reach Ready within 210s (phase: CreatingHelmRelease)`, before FluxCD's rollback (run 1).

`Stalled=True` did not occur in these runs; unit tests cover it (spec Clarifications).

One text that users read differs from the unit-test fixtures written for spec 019: FluxCD's upgrade failure message, which the operator copies into `HelmReleaseReady`, the CR message and the HelmRelease step, now ends with kstatus's `timeout waiting for: [Deployment/<namespace>/<name> status: 'InProgress']`. The fixtures in `backend/tests/unit/test_styrmin_deployment_helmrelease_generation.py` use `context deadline exceeded`. Whether that was the exact text of an E2E run with the gate is not known. The operator does not parse this text, so no rule depends on it.

## Run 3: shard_compute, API variant (T021)

- Code tested: the working tree that is committed as `d6193096` ("test(e2e): add a pre-upgrade Helm hook to the scheduling E2E (#435)"): the simple-app chart's `preUpgradeHookJob` value, the `hook-job` test driver, and the hook checks in `test_pod_scheduling.py`. This change has no backend code, so the server image is the same `STYRMIN_IMAGE_VER=helmv4-f752856a`, built again with `docker compose build server` before the run.

### Unit test of the chart's hooks (T016)

- Command, from the repository root: `uv run pytest backend/tests/unit/test_simple_app_hook_job.py -v`
- Run at 2026-10-16T09:33:49Z, with helm v4.1.0 on PATH, so the test was not skipped.

```text
backend/tests/unit/test_simple_app_hook_job.py::test_no_hook_by_default PASSED [ 50%]
backend/tests/unit/test_simple_app_hook_job.py::test_enabled_renders_the_hook_job_and_the_unlabelled_hook_config_map PASSED [100%]
============================== 2 passed in 0.10s ===============================
```

### E2E session

- Command, from the repository root:

  ```bash
  export STYRMIN_IMAGE_VER=helmv4-f752856a
  exec 3< <(sleep infinity); spid=$!
  uv run pytest backend/tests/e2e -m "ci and shard_compute" -k api-chromium -v -s --pdb <&3 > compute-api.log 2>&1
  exec 3<&-; kill "$spid"
  ```

- Start: 2026-10-16T09:22:23Z. End: 2026-10-16T09:32:55Z.
- vcluster: `pytest-5016eb89-01ec-494a-b643-3c50f21712ee` (kubeconfig context `vcluster-docker_pytest-5016eb89-01ec-494a-b643-3c50f21712ee`).
- Kubeconfig: `/tmp/pytest-of-root/pytest-1721/vcluster0/kubeconfig`.
- Collected: `collected 195 items / 187 deselected / 8 selected`.

Result lines:

```text
backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress[api-chromium]   (node ID line; PASSED follows the -s output)
PASSED
backend/tests/e2e/test_cluster_update.py::test_edit_cluster_config_from_detail_page[api-chromium] SKIPPED
backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress[api-chromium] PASSED
backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_loadbalancer_ingress[api-chromium] PASSED
backend/tests/e2e/test_ingress_controller.py::test_ip_whitelist_enforcement_allows_and_rejects[api-chromium] PASSED
backend/tests/e2e/test_ingress_controller.py::test_deleting_last_app_tears_down_dedicated_ingress[api-chromium] PASSED
backend/tests/e2e/test_pod_scheduling.py::test_scheduling_end_to_end[api-chromium] PASSED
backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql[api-chromium] PASSED
====== 7 passed, 1 skipped, 187 deselected, 1 warning in 630.22s (0:10:30) ======
```

`test_edit_cluster_config_from_detail_page` is marked `ui_only`, so its API variant is skipped. The warning is the same `kr8s` `DeprecationWarning` as in run 1.

A first attempt, started at 2026-10-16T09:20:44Z on vcluster `pytest-3148d805-f6aa-429d-88d9-b3d9057f2bca`, stopped in the setup of the `git_server` fixture before any test ran: the push of the `hook-job` driver failed with `dulwich.errors.GitProtocolError: access denied or repository not exported: /hook-job.git`. The git-server image creates one bare repository per driver, and tasks.md did not list that step. `RUN git init --bare /git/hook-job.git` in `backend/tests/e2e/fixtures/git-server/Dockerfile` fixed it. The session was stopped by its own `sleep` PID, and the fixture teardown deleted that vcluster.

### The hook Job and the hook ConfigMap after the scheduling update

From the `kubectl` snapshot of 2026-10-16T09:31:23Z of namespace `styrmin-b7726f34-7170-42cd-b373-482c0db37492` (deployment `scheduling-a`, driver `hook-job`). No hook resource existed before the scheduling update: Helm runs pre-upgrade hooks only on an upgrade, and this update was the deployment's first upgrade.

Job `styrmin-simple-app-pre-upgrade-hook`:

- Created 09:31:15Z, completed 09:31:18Z: `status.succeeded: 1`, conditions `SuccessCriteriaMet` and `Complete`, reason `CompletionsReached`.
- Annotations: `helm.sh/hook: pre-upgrade`, `helm.sh/hook-weight: "0"`, `helm.sh/hook-delete-policy: before-hook-creation`.
- Styrmin's labels in `metadata.labels`: `styrmin/component: server`, `styrmin/deployment_id: b7726f34-7170-42cd-b373-482c0db37492`, `styrmin/environment_id: 30a7cd83-c4a4-4471-bc1a-04efa168f901`. The other labels are the chart's (`app.kubernetes.io/name: simple-app`, `app.kubernetes.io/component: pre-upgrade-hook`, …) and helm-controller's (`helm.toolkit.fluxcd.io/name`, `helm.toolkit.fluxcd.io/namespace`).
- `spec.template.spec`:
  - `tolerations`: `[{key: dedicated, operator: Equal, value: batch, effect: NoSchedule}]`;
  - `affinity.nodeAffinity.preferredDuringSchedulingIgnoredDuringExecution`: weight 1, `node-type In [worker]`;
  - `affinity.podAffinity.preferredDuringSchedulingIgnoredDuringExecution`: weight 50, `matchLabels: {app.kubernetes.io/name: simple-app}`, `topologyKey: kubernetes.io/hostname`;
  - `topologySpreadConstraints`: `[{maxSkew: 1, topologyKey: kubernetes.io/hostname, whenUnsatisfiable: ScheduleAnyway}]`;
  - `runtimeClassName: kata-e2e`;
  - `containers[0].resources`: `{requests: {memory: 192Mi}, limits: {cpu: 500m}}`. The scheduling patch replaces the chart's `requests` of `cpu: 10m`, `memory: 32Mi`.
- Pod template labels: `app.kubernetes.io/component`, `app.kubernetes.io/instance` and the Job controller's labels, without `app.kubernetes.io/name`.
- Pod `styrmin-simple-app-pre-upgrade-hook-6d9bz`: `Completed`, 0 restarts, on node `pytest-5016eb89-01ec-494a-b643-3c50f21712ee`, the vcluster's only node.

ConfigMap `styrmin-simple-app-pre-upgrade-hook`:

- Created 09:31:15Z. Annotations: `helm.sh/hook: pre-upgrade`, `helm.sh/hook-weight: "-1"`, `helm.sh/hook-delete-policy: before-hook-creation`. Data: `hook: pre-upgrade`.
- `metadata.labels`: `styrmin/deployment_id: b7726f34-7170-42cd-b373-482c0db37492`, `styrmin/environment_id: 30a7cd83-c4a4-4471-bc1a-04efa168f901`, `helm.toolkit.fluxcd.io/name`, `helm.toolkit.fluxcd.io/namespace`. It has no `styrmin/component` label, because no component identifier label matches it. The chart renders it without `metadata.labels`, so the upgrade's render succeeded with the strategic-merge label patch and gave it Styrmin's labels (FR-013, SC-006).

At 09:32:26Z, the update of `test_pod_anti_affinity_cross_deployment_via_graphql`, which sets only a pod anti-affinity, replaced the Job (`before-hook-creation`). The new Job has that pod anti-affinity and no toleration or runtime class, and it succeeded. Each upgrade's hook Job gets the scheduling settings of that upgrade.

The vcluster has one node, so SC-004 ("runs on those nodes") is checked by the hook pod's scheduling fields and its completion, not by the node it ran on.

## Run 4: shard_compute, UI variant (T022)

The module's fixtures changed and the shard holds tests with both variants, so the UI variant runs in its own session. Both tests of `test_pod_scheduling.py` are marked `api_only`, so this session does not create the `hook-job` deployment; its `git_server` setup does push the `hook-job` driver repository.

- Code tested: commit `d6193096`. Server image: `STYRMIN_IMAGE_VER=helmv4-f752856a`.
- Command, from the repository root:

  ```bash
  export STYRMIN_IMAGE_VER=helmv4-f752856a
  exec 3< <(sleep infinity); spid=$!
  uv run pytest backend/tests/e2e -m "ci and shard_compute" -k ui-chromium -v -s --pdb <&3 > compute-ui.log 2>&1
  exec 3<&-; kill "$spid"
  ```

- Start: 2026-10-16T09:36:09Z. End: 2026-10-16T09:40:43Z.
- vcluster: `pytest-c86e8031-09f0-4ccd-ad09-2f7c363ed3b0` (kubeconfig context `vcluster-docker_pytest-c86e8031-09f0-4ccd-ad09-2f7c363ed3b0`).
- Kubeconfig: `/tmp/pytest-of-root/pytest-1725/vcluster0/kubeconfig`.
- Collected: `collected 195 items / 187 deselected / 8 selected`.

Result lines:

```text
backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress[ui-chromium] SKIPPED
backend/tests/e2e/test_cluster_update.py::test_edit_cluster_config_from_detail_page[ui-chromium]   (node ID line; PASSED follows the -s output)
PASSED
backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress[ui-chromium]   (node ID line; PASSED follows the -s output)
PASSED
backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_loadbalancer_ingress[ui-chromium] PASSED
backend/tests/e2e/test_ingress_controller.py::test_ip_whitelist_enforcement_allows_and_rejects[ui-chromium] PASSED
backend/tests/e2e/test_ingress_controller.py::test_deleting_last_app_tears_down_dedicated_ingress[ui-chromium] SKIPPED
backend/tests/e2e/test_pod_scheduling.py::test_scheduling_end_to_end[ui-chromium] SKIPPED
backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql[ui-chromium] SKIPPED
===== 4 passed, 4 skipped, 187 deselected, 1 warning in 270.97s (0:04:30) ======
```

The four skipped tests are marked `api_only`. The warning is the same `kr8s` `DeprecationWarning` as in run 1.

This is the second UI session. The first, from 2026-10-16T09:33:40Z to 09:35:44Z on vcluster `pytest-a657945f-1c1a-445b-88d5-37c4745a3d3c` (kubeconfig `/tmp/pytest-of-root/pytest-1724/vcluster0/kubeconfig`), failed `test_edit_cluster_config_from_detail_page[ui-chromium]` at `backend/tests/e2e/test_cluster_update.py:360`: the review dialog listed `Ingress class traefik → traefikedit-680548.styrmin.com`, so the FQDN suffix text had gone into the Ingress class field. This is a known flake of that test on this host, which does not use the `hook-job` driver or any Helm hook, so the session was stopped by its own `sleep` PID and run again once, unchanged.
