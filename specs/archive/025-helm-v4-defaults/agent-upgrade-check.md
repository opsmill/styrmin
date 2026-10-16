# Agent Chart Upgrade Check: Removing the UseHelm3Defaults Gate

This file records the manual check of [quickstart.md](quickstart.md) §4 for spec 025 ([#435](https://github.com/opsmill/styrmin/issues/435)), for the pull request description. It checks contract C-006 ([contracts/behaviour.md](contracts/behaviour.md)), requirement FR-004 and success criterion SC-003 ([spec.md](spec.md)).

## Result

All expected results were met:

- After an upgrade from the agent chart with `--feature-gates=UseHelm3Defaults=true` to this branch's chart, helm-controller found both existing releases in sync, at its start and at a forced reconcile. It created no new release revision, and no pod in the deployment namespaces restarted.
- The next change to the deployment, made after the upgrade, succeeded. Its new release revision (v2) kept client-side apply: the release record has `apply_method: csa`, and the workloads' `metadata.managedFields` have manager `helm-controller` with operation `Update` and no `Apply` entry.

One limit: the server and agent image was the same before and after the upgrade, so this check covers the chart change only. See [What this check does not cover](#what-this-check-does-not-cover).

## Expected and observed results

| Expected result (quickstart §4) | Observed | Result |
| --- | --- | --- |
| Before the upgrade, helm-controller runs with the gate | Args end with `--feature-gates=UseHelm3Defaults=true`; log line `"loading feature gate","UseHelm3Defaults":true` | Met |
| After the upgrade, helm-controller runs without the gate | Deployment generation 2, args without `--feature-gates`; new pod started 11:10:02Z | Met |
| Same newest release Secret per deployment after the upgrade | `sh.helm.release.v1.<name>.v1` in both namespaces, before and after; no `.v2` | Met |
| Newest release status `deployed` after the upgrade | `deployed` for both | Met |
| Same pod start times after the upgrade | All three pods unchanged, restart count 0 | Met |
| helm-controller takes no action on the existing releases | Log `release in-sync with desired state` for both at its start (11:10:08Z) and after the forced reconcile (11:10:28Z); HelmRelease generation stays 1 | Met |
| The change after the upgrade succeeds | Task `update_instance` result `SUCCEEDED`, all six steps `SUCCEEDED` | Met |
| The deployment reaches `Running` | Deployment status `running` at 11:12:42Z | Met |
| The new release revision keeps client-side apply | Release v2 `apply_method: csa`; `Deployment/styrmin-simple-app` and `StatefulSet/styrmin-postgresql` have `helm-controller` `Update` at 11:12:28Z, no `Apply` | Met |

## Environment

- Branch `fac/helm-v4-end3k` at commit `edea76e4`.
- Server and agent image: `STYRMIN_IMAGE_VER=helmv4-f752856a`, the same image before and after the upgrade.
- helm-controller `fluxcd/helm-controller:v1.6.5`. Helm CLI on the host: v4.1.0 (used for the `helm upgrade` of the `styrmin` release).
- vcluster: `pytest-de7d989e-5ab1-45bc-bdf1-d9faa14877ac`, created by the E2E fixture at 11:07:18Z and deleted by it at 11:13:06Z.
- Kubeconfig: `/tmp/pytest-of-root/pytest-1726/vcluster0/kubeconfig`.
- Time window: 2026-10-16T11:07:00Z to 2026-10-16T11:13:08Z (all times below are UTC on 2026-10-16).
- Deployment under test: `29116ad4-5f57-47ea-a7a4-ff86ded2cb0a` (driver `simple-app` 0.1.0), namespace and HelmRelease `styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a`. The environment's ingress controller, namespace and HelmRelease `styrmin-ee432fda-160f-4029-a83c-8d692b7e384e`, is recorded too, because it is also an existing release.

## Method

### Why this branch's chart with the gate lines put back is the chart from develop

The local `develop` ref is out of date, so the comparison uses `origin/develop` (`cd79af5c`). This branch's only change under `helm/` since its merge base with `origin/develop` is the removal of the gate:

```console
$ git merge-base HEAD origin/develop
fd17ffb7bac2ae3c206c7d0fa0fbc911ad930022
$ git diff fd17ffb7 HEAD --stat -- helm/
 helm/agent/templates/helm-controller/deployment.yaml | 2 --
 1 file changed, 2 deletions(-)
```

The two removed lines are:

```yaml
          # Keep Helm v3's client-side apply and health checks after the move to Helm v4.
          - --feature-gates=UseHelm3Defaults=true
```

With these two lines put back in the working tree (not committed), `git diff fd17ffb7 -- helm/` was empty, so the installed chart was the chart from develop.

### How the cluster and the deployment were created

The check used the E2E fixtures in [`backend/tests/e2e/conftest.py`](../../backend/tests/e2e/conftest.py). They create a disposable vcluster on Docker and install Styrmin with `helm upgrade --install styrmin helm/styrmin`. The agent chart is the `styrmin-agent` subchart of `helm/styrmin`, which the fixture packages from the local `helm/agent` with `helm dependency update helm/styrmin` before the install. The `deployed_simple_app` fixture creates a `simple-app` deployment through the SDK and waits for `Running`.

A temporary test file, `backend/tests/e2e/test_tmp_agent_upgrade_check.py` (deleted after the check, not committed), held the deployment. It used marker files in a scratch directory to wait between the steps:

1. Write the deployment ID, namespace and kubeconfig path, then wait for the `go-change` marker.
2. Update the deployment through the SDK with one deployment-level environment variable, `AGENT_UPGRADE_CHECK=after-upgrade` (`client.deployments.update(deployment_id, input=UpdateDeploymentInput(envVars=[...]))`).
3. Read the deployment timeline until the update's task result is no longer `RUNNING`, wait for `Running`, write the result, and assert `SUCCEEDED`.
4. Wait for the `done` marker, then end, so the fixtures delete the vcluster.

The test kept the server port-forward of the fixture alive, so the update in step 2 used the same SDK client and token as the other E2E tests.

```bash
export UPGRADE_CHECK_DIR=<scratch directory> STYRMIN_IMAGE_VER=helmv4-f752856a
exec 3< <(sleep infinity); spid=$!
uv run pytest "backend/tests/e2e/test_tmp_agent_upgrade_check.py::test_tmp_agent_upgrade_check[api-chromium]" \
  -v -s --pdb <&3 > pytest.log 2>&1
exec 3<&-; kill "$spid"
```

Result line: `=================== 1 passed, 1 warning in 366.07s (0:06:06) ===================`. The warning is the `kr8s` `DeprecationWarning` of every E2E run.

### How the state was recorded

A shell script took the same snapshot at each step, with `KUBECONFIG` set to the path above. The commands, with the namespaces of the deployments:

```bash
# helm-controller arguments and pod
kubectl -n styrmin get deploy -l control-plane=controller \
  -o jsonpath='{range .items[*]}{.metadata.name} generation={.metadata.generation} args={.spec.template.spec.containers[0].args}{"\n"}{end}'
kubectl -n styrmin get pods -l app=helm-controller -o custom-columns=NAME:.metadata.name,START:.status.startTime,READY:.status.containerStatuses[0].ready
# release Secrets (quickstart §4 step 2, all deployment namespaces)
kubectl get secret -A -l owner=helm \
  -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,STATUS:.metadata.labels.status,CREATED:.metadata.creationTimestamp
# pod start times (quickstart §4 step 2)
kubectl get pods -A -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,START:.status.startTime,RESTARTS:.status.containerStatuses[0].restartCount
# HelmReleases
kubectl get helmrelease -A -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,GENERATION:.metadata.generation,OBSERVED:.status.observedGeneration,READY:...,REASON:...,LASTHANDLED:.status.lastHandledReconcileAt,HISTORY:.status.history[*].version
# each release record, decoded (Secret data is base64, Helm's record is base64 + gzip + JSON)
kubectl -n "$ns" get secret "$name" -o jsonpath='{.data.release}' | base64 -d | base64 -d | gunzip \
  | jq -c '{version, status: .info.status, description: .info.description, last_deployed: .info.last_deployed, apply_method: (.apply_method // "<unset>")}'
# workload managedFields
kubectl -n "$ns" get deploy,statefulset,daemonset -o json --show-managed-fields \
  | jq -c '.items[] | {kind, name: .metadata.name, managedFields: [.metadata.managedFields[] | {manager, operation, time, subresource}]}'
```

Rows for the `styrmin` namespace are left out of the release Secrets: the `styrmin` release there is the Styrmin install itself, which the chart upgrade changes on purpose.

## Step 1: install with the gate and create a simple-app deployment

- 11:07:55Z: Styrmin installed, release `styrmin` revision 1.
- 11:08:06Z: helm-controller pod `helm-controller-b7c7ffffb-lsszz` started. At 11:08:13Z it logged:

  ```json
  {"level":"info","ts":"2026-10-16T11:08:13.322Z","logger":"setup","msg":"loading feature gate","UseHelm3Defaults":true}
  ```

- 11:08:51Z: the environment's ingress controller installed (release v1).
- 11:08:56Z: the simple-app deployment installed (release v1).
- 11:09:15Z: the deployment reached `Running`.

## Step 2: state before the upgrade (snapshot at 11:09:28Z)

```text
helm-controller generation=1 args=["--watch-all-namespaces","--log-level=info","--log-encoding=json","--enable-leader-election","--feature-gates=UseHelm3Defaults=true"]
NAME                              START                  READY
helm-controller-b7c7ffffb-lsszz   2026-10-16T11:08:06Z   true

NAMESPACE                                      NAME                                                                 STATUS     CREATED
styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   sh.helm.release.v1.styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a.v1   deployed   2026-10-16T11:08:56Z
styrmin-ee432fda-160f-4029-a83c-8d692b7e384e   sh.helm.release.v1.styrmin-ee432fda-160f-4029-a83c-8d692b7e384e.v1   deployed   2026-10-16T11:08:51Z

NAMESPACE                                      NAME                                           START                  RESTARTS
styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   styrmin-postgresql-0                           2026-10-16T11:09:00Z   0
styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   styrmin-simple-app-794b448467-7gjbg            2026-10-16T11:08:56Z   0
styrmin-ee432fda-160f-4029-a83c-8d692b7e384e   styrmin-traefik-794b8499dd-mhp2x               2026-10-16T11:08:51Z   0

NAMESPACE                                      NAME                                           GENERATION   OBSERVED   READY   REASON             LASTHANDLED   HISTORY
styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   1            1          True    InstallSucceeded   <none>        1
styrmin-ee432fda-160f-4029-a83c-8d692b7e384e   styrmin-ee432fda-160f-4029-a83c-8d692b7e384e   1            1          True    InstallSucceeded   <none>        1
```

Release records:

```json
{"secret":"sh.helm.release.v1.styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a.v1","version":1,"status":"deployed","description":"Install complete","last_deployed":"2026-10-16T11:08:56.433270328Z","apply_method":"csa"}
{"secret":"sh.helm.release.v1.styrmin-ee432fda-160f-4029-a83c-8d692b7e384e.v1","version":1,"status":"deployed","description":"Install complete","last_deployed":"2026-10-16T11:08:51.532472553Z","apply_method":"csa"}
```

Workload `managedFields`:

```json
{"kind":"Deployment","name":"styrmin-simple-app","managedFields":[{"manager":"helm-controller","operation":"Update","time":"2026-10-16T11:08:56Z","subresource":null},{"manager":"kube-controller-manager","operation":"Update","time":"2026-10-16T11:09:06Z","subresource":"status"}]}
{"kind":"StatefulSet","name":"styrmin-postgresql","managedFields":[{"manager":"helm-controller","operation":"Update","time":"2026-10-16T11:08:56Z","subresource":null},{"manager":"kube-controller-manager","operation":"Update","time":"2026-10-16T11:09:01Z","subresource":"status"}]}
{"kind":"Deployment","name":"styrmin-traefik","managedFields":[{"manager":"helm-controller","operation":"Update","time":"2026-10-16T11:08:51Z","subresource":null},{"manager":"kube-controller-manager","operation":"Update","time":"2026-10-16T11:08:54Z","subresource":"status"}]}
```

With the gate, helm-controller v1.6.5 installs with client-side apply and records it as `apply_method: csa`, as [research.md](research.md) R-004 describes for Helm v4.

The HelmReleases have `spec.interval: 1h`, so waiting for two of the controller's own intervals was not practical. The check relies on the reconcile at the controller's start and on a forced reconcile instead, as quickstart §4 step 3 allows.

## Step 3: upgrade the agent chart to this branch

The gate lines were removed again with `git checkout -- helm/agent/templates/helm-controller/deployment.yaml`, the subchart was packaged again, and the `styrmin` release was upgraded with the fixture's own command and values:

```bash
helm dependency update helm/agent
helm dependency update helm/styrmin
helm upgrade --install styrmin --dependency-update --create-namespace -n styrmin helm/styrmin \
  -f backend/tests/e2e/fixtures/styrmin-values.yaml \
  --set styrmin.driver.token=default --set styrmin.agentSource.token=default \
  --set image.tag=helmv4-f752856a --set styrmin-agent.image.tag=helmv4-f752856a \
  --kubeconfig /tmp/pytest-of-root/pytest-1726/vcluster0/kubeconfig --wait --timeout 5m
```

The packaged subchart had no `--feature-gates` argument (`tar -xzOf helm/styrmin/charts/styrmin-agent-0.1.48.tgz styrmin-agent/templates/helm-controller/deployment.yaml | grep -c feature-gates` printed `0`). The upgrade ran from 11:09:56Z to 11:10:04Z:

```text
REVISION  UPDATED                   STATUS      CHART           APP VERSION  DESCRIPTION
1         Fri Oct 16 11:07:55 2026  superseded  styrmin-0.1.48  0.1.48       Install complete
2         Fri Oct 16 11:09:56 2026  deployed    styrmin-0.1.48  0.1.48       Upgrade complete
```

`helm get values` of revisions 1 and 2 were identical. Only the helm-controller pod was replaced (`helm-controller-694dbcdbc-x724g`, started 11:10:02Z); every other pod in the `styrmin` namespace kept its start time, including the agent pod (`styrmin-styrmin-agent-agent-86dff584fd-d2ls6`, 11:08:06Z).

`kubectl -n styrmin rollout status deploy/helm-controller` reported `successfully rolled out`, and the new arguments are:

```text
2 ["--watch-all-namespaces","--log-level=info","--log-encoding=json","--enable-leader-election"]
```

At its start, the new helm-controller reconciled both HelmReleases and took no action (log, trimmed to the time, message and HelmRelease):

```text
2026-10-16T11:10:08.827Z  release in-sync with desired state  styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a
2026-10-16T11:10:08.841Z  release in-sync with desired state  styrmin-ee432fda-160f-4029-a83c-8d692b7e384e
```

Then a reconcile of both HelmReleases was forced, and the controller handled it:

```console
$ kubectl annotate helmrelease -n "$ns" "$ns" reconcile.fluxcd.io/requestedAt="1792149028" --overwrite   # 11:10:28Z, for each namespace
helmrelease.helm.toolkit.fluxcd.io/styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a annotated
helmrelease.helm.toolkit.fluxcd.io/styrmin-ee432fda-160f-4029-a83c-8d692b7e384e annotated
```

```text
2026-10-16T11:10:28.891Z  release in-sync with desired state  styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a
2026-10-16T11:10:29.005Z  release in-sync with desired state  styrmin-ee432fda-160f-4029-a83c-8d692b7e384e
```

Both HelmReleases then had `status.lastHandledReconcileAt: 1792149028`.

## Step 4: state after the upgrade (snapshot at 11:12:06Z, 90 seconds after the forced reconcile)

Compared with the snapshot of step 2, only the helm-controller lines and the `LASTHANDLED` column changed:

```text
helm-controller generation=2 args=["--watch-all-namespaces","--log-level=info","--log-encoding=json","--enable-leader-election"]
NAME                              START                  READY
helm-controller-694dbcdbc-x724g   2026-10-16T11:10:02Z   true

NAMESPACE                                      NAME                                                                 STATUS     CREATED
styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   sh.helm.release.v1.styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a.v1   deployed   2026-10-16T11:08:56Z
styrmin-ee432fda-160f-4029-a83c-8d692b7e384e   sh.helm.release.v1.styrmin-ee432fda-160f-4029-a83c-8d692b7e384e.v1   deployed   2026-10-16T11:08:51Z

NAMESPACE                                      NAME                                           START                  RESTARTS
styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   styrmin-postgresql-0                           2026-10-16T11:09:00Z   0
styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   styrmin-simple-app-794b448467-7gjbg            2026-10-16T11:08:56Z   0
styrmin-ee432fda-160f-4029-a83c-8d692b7e384e   styrmin-traefik-794b8499dd-mhp2x               2026-10-16T11:08:51Z   0

NAMESPACE                                      NAME                                           GENERATION   OBSERVED   READY   REASON             LASTHANDLED   HISTORY
styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   1            1          True    InstallSucceeded   1792149028    1
styrmin-ee432fda-160f-4029-a83c-8d692b7e384e   styrmin-ee432fda-160f-4029-a83c-8d692b7e384e   1            1          True    InstallSucceeded   1792149028    1
```

The decoded release records and the workload `managedFields` were the same as in step 2: version 1, `deployed`, `apply_method: csa`, and `helm-controller` `Update` entries from 11:08:51Z and 11:08:56Z.

## Step 5: change the deployment after the upgrade

At 11:12:13Z the temporary test updated the deployment with the environment variable `AGENT_UPGRADE_CHECK=after-upgrade`. helm-controller, now without the gate, upgraded the release because the post-renderers changed:

```text
2026-10-16T11:12:27.823Z  release out-of-sync with desired state: postrenderers digest has changed  styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a
2026-10-16T11:12:27.840Z  running 'upgrade' action with timeout of 4m0s                            styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a
2026-10-16T11:12:38.266Z  release in-sync with desired state                                       styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a
```

HelmRelease Events:

```text
TIME                   REASON             MSG
2026-10-16T11:09:08Z   InstallSucceeded   Helm install succeeded for release styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a/styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a.v1 with chart simple-app@0.1.0
2026-10-16T11:12:38Z   UpgradeSucceeded   Helm upgrade succeeded for release styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a/styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a.v2 with chart simple-app@0.1.0
```

The task and the deployment, as the test read them through the SDK at 11:12:42Z:

```json
{
  "task_id": "4a9648c8-b3d3-4b11-b73f-5c3a03136d22",
  "task_type": "update_instance",
  "result": "SUCCEEDED",
  "steps": [
    "plan=SUCCEEDED",
    "resource:styrmindeployment=SUCCEEDED",
    "operator:prerequisites=SUCCEEDED",
    "operator:helmrelease=SUCCEEDED",
    "operator:services=SUCCEEDED",
    "operator:ready=SUCCEEDED"
  ],
  "deployment_status": "running"
}
```

The rendered `simple-app` container has `{"name":"AGENT_UPGRADE_CHECK","value":"after-upgrade"}`.

### State after the change (snapshot at 11:12:49Z)

```text
NAMESPACE                                      NAME                                                                 STATUS       CREATED
styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   sh.helm.release.v1.styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a.v1   superseded   2026-10-16T11:08:56Z
styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   sh.helm.release.v1.styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a.v2   deployed     2026-10-16T11:12:28Z
styrmin-ee432fda-160f-4029-a83c-8d692b7e384e   sh.helm.release.v1.styrmin-ee432fda-160f-4029-a83c-8d692b7e384e.v1   deployed     2026-10-16T11:08:51Z

NAMESPACE                                      NAME                                           GENERATION   OBSERVED   READY   REASON             LASTHANDLED   HISTORY
styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a   2            2          True    UpgradeSucceeded   1792149028    2,1
styrmin-ee432fda-160f-4029-a83c-8d692b7e384e   styrmin-ee432fda-160f-4029-a83c-8d692b7e384e   1            1          True    InstallSucceeded   1792149028    1
```

Release records:

```json
{"secret":"sh.helm.release.v1.styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a.v1","version":1,"status":"superseded","description":"Install complete","last_deployed":"2026-10-16T11:08:56.433270328Z","apply_method":"csa"}
{"secret":"sh.helm.release.v1.styrmin-29116ad4-5f57-47ea-a7a4-ff86ded2cb0a.v2","version":2,"status":"deployed","description":"Upgrade complete","last_deployed":"2026-10-16T11:12:28.005786469Z","apply_method":"csa"}
{"secret":"sh.helm.release.v1.styrmin-ee432fda-160f-4029-a83c-8d692b7e384e.v1","version":1,"status":"deployed","description":"Install complete","last_deployed":"2026-10-16T11:08:51.532472553Z","apply_method":"csa"}
```

Workload `managedFields`:

```json
{"kind":"Deployment","name":"styrmin-simple-app","managedFields":[{"manager":"helm-controller","operation":"Update","time":"2026-10-16T11:12:28Z","subresource":null},{"manager":"kube-controller-manager","operation":"Update","time":"2026-10-16T11:12:34Z","subresource":"status"}]}
{"kind":"StatefulSet","name":"styrmin-postgresql","managedFields":[{"manager":"helm-controller","operation":"Update","time":"2026-10-16T11:12:28Z","subresource":null},{"manager":"kube-controller-manager","operation":"Update","time":"2026-10-16T11:12:30Z","subresource":"status"}]}
{"kind":"Deployment","name":"styrmin-traefik","managedFields":[{"manager":"helm-controller","operation":"Update","time":"2026-10-16T11:08:51Z","subresource":null},{"manager":"kube-controller-manager","operation":"Update","time":"2026-10-16T11:08:54Z","subresource":"status"}]}
```

The upgrade to v2 kept client-side apply. This matches research R-004: helm-controller resolves the apply method from the newest stored revision (`csa`), so a release installed with the gate keeps client-side apply. Without the gate, helm-controller uses Helm v4's health checks and post-render strategy for this upgrade, so it is the combination that critique P1 asked to check ([quickstart.md](quickstart.md) §4 step 5). The check observed the apply method; it did not observe the health check or the post-render strategy directly.

The change replaced the simple-app deployment's pods (started 11:12:28Z and 11:12:29Z), as expected for a new environment variable. The ingress controller's release and pod did not change.

## Cleanup

- 11:13:02Z to 11:13:06Z: the test ended (`PASSED`) and the fixture deleted the vcluster: `Successfully deleted virtual cluster pytest-de7d989e-5ab1-45bc-bdf1-d9faa14877ac`. `vcluster list --driver docker` then listed no vcluster.
- The temporary test file was deleted, and the gate lines were not committed: `git status --short` was empty and `git diff fd17ffb7 HEAD --stat -- helm/` still shows only the two removed lines.

## What this check does not cover

- The server and agent image was this branch's image (`helmv4-f752856a`) before and after the upgrade, and the agent pod did not restart. A real upgrade from a develop release also replaces the agent image. That image includes commit `8a5d3b61`, which changes the label patch that Styrmin writes into every HelmRelease's `spec.postRenderers`. A post-renderers change makes helm-controller upgrade a release, as step 5 shows. The commit message states that the operator writes a HelmRelease of an existing deployment again only for a new rollout, or when it resumes a deployment that is not `Ready`. This check did not test that claim. Whether an agent restart on the new image leaves the HelmReleases of `Ready` deployments unchanged is not known from this check.
- The check waited 90 seconds after the forced reconcile, not two of the HelmReleases' own 1-hour intervals. The controller's reconcile at its start and the forced reconcile both found the releases in sync, and research R-003 shows that an in-sync release has no action, so a later scheduled reconcile is expected to behave the same way.
