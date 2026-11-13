# Kubernetes Operator

<!-- Extracted from specs/001-k8s-operator and specs/001-deployment-crd on 2026-04-06 -->

## Overview

The operator is a kopf-based Kubernetes controller that runs alongside the Prefect agent in a single container, sharing one async event loop. It manages the full lifecycle of Kubernetes resources for Styrmin deployments through a custom `StyrminDeployment` CRD.

```text
┌──────────────────────────────────────────────────────────┐
│                  Combined Container                       │
│                                                          │
│  ┌─────────────────┐    ┌─────────────────────────────┐  │
│  │  Prefect Agent   │    │     Kopf Operator           │  │
│  │  (worker loop)   │    │  (CRD watcher + reconciler) │  │
│  └────────┬─────────┘    └──────────┬──────────────────┘  │
│           │                         │                     │
│           └────────┬────────────────┘                     │
│                    │                                      │
│           Shared asyncio event loop                       │
└──────────────────────────────────────────────────────────┘
```

The entrypoint uses `asyncio.gather(kopf.operator(...), run_prefect_worker())` to run both components concurrently. See ADR-002 for the rationale.

## StyrminDeployment CRD

The operator watches `StyrminDeployment` custom resources (`styrmin.io/v1alpha1`). These are created by Prefect flows and contain the full deployment specification.

**API Group**: `styrmin.io` | **Version**: `v1alpha1` | **Kind**: `StyrminDeployment` | **Short name**: `sd`

### Spec Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `deploymentId` | string (UUID) | Yes | Links to Styrmin database deployment |
| `releaseReference` | string | Yes | Kubernetes release reference |
| `appName` | string | Yes | Application name from driver |
| `appVersion` | string | Yes | Application version |
| `context` | object | Yes | Serialized GlobalContext (full deployment config) |
| `helm` | object | Yes | Chart and repository specs |
| `labels` | object | No | Custom labels for managed resources |
| `parameters` | object | No | User-provided parameters |
| `deletionRequested` | boolean | No (default `false`) | Set to `true` by the backend's `deleteDeployment` mutation to request operator-driven teardown. Immutable once `true` (CEL transition rule `oldSelf == false \|\| self == true` enforced by the API server). |

The context is embedded directly in the CRD (see ADR-004), making the operator autonomous — no backend API calls needed during reconciliation.

### Namespace co-location (load-bearing constraint)

The CRD is `scope: Namespaced` and lives **inside the deployment's own namespace** (`styrmin-{deployment_id}`). Deleting that namespace deletes the CR with it. Any state transition you want observed must complete BEFORE the namespace is gone, OR you must rely on a separate "DB DELETING + CR absent → infer terminal" path (this is what the agent's status reporter does for the platform-driven delete flow — see [`overview.md`](overview.md) → Status Reporter and `services/deployment_status.py`). New work that needs a phase change to land after namespace deletion will silently fail without this callout — design accordingly.

### Name of the CR and the release reference

<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

`build_styrmin_deployment_body` (`operator/crd/builder.py`) names the CR after its namespace, not after `spec.releaseReference`. There is one StyrminDeployment per deployment namespace, and the status reporter, `delete_deployment` and the janitor all find it by that name.

For an ordinary deployment the two strings are equal: `styrmin-<deployment id>`. They differ only for the counterpart deployment of an environment clone. The counterpart keeps its own namespace and CR name, but its `releaseReference` is the Helm release name of the source deployment. The restored Helm release, its storage record and the `meta.helm.sh/release-*` annotations on the restored chart objects all carry that name. A release named after the counterpart would make FluxCD install over objects that another release owns, and Helm's ownership check would fail. See [ADR-056](../../adr/0056-environment-clone-record-and-cross-target-restore.md) §3.

### Status

| Field | Description |
|-------|-------------|
| `phase` | `Pending` / `CreatingPrerequisites` / `CreatingHelmRelease` / `CreatingServices` / `Ready` / `Failed` / `Deleting` / `Deleted` |
| `displayState` | User-facing state surfaced to the UI: `Deploying` / `Running` / `Restoring` / `Error` / `Deleting` / `Deleted` |
| `message` | The message of the current phase, or the reason of a failure |
| `conditions` | K8s-standard condition array: `NetworkPoliciesReady`, `SecretsReady`, `HelmReleaseReady`, `HelmReleaseRemediated`, `ServicesReady`, `MiddlewaresReady`, `Ready`, `Deleted` |
| `managedResources` | Counts by type (networkPolicies, secrets, helmReleases, services, middlewares) |
| `instanceId` | The `spec.instanceId` that the create, update or resume handler last acted on. Written at the end of the handler, also when the handler raises. The status reporter sends it, so the server can link each report to the task that rolled out that instance. |
| `rolloutStartedAt` | When the current rollout started (ISO 8601). Set by the create and update handlers; the resume handler sets it only when it is missing. The readiness timeout counts from it. |

The CRD's status schema keeps `x-kubernetes-preserve-unknown-fields: true`, so `instanceId`, `rolloutStartedAt` and `HelmReleaseRemediated` need no CRD change on existing installs. `helm/agent/crds/styrmin.io_styrmindeployments.yaml` documents them.

Printer columns for `kubectl get styrmindeployments`: Phase, App, Version, Age.

## Phase-Based Deployment

Resources are deployed in a guaranteed order using kopf sub-handlers (see ADR-005):

```text
StyrminDeployment Created
    │
    ├── Phase 1: NetworkPolicies + Secrets
    │   (HelmRelease is NOT created until all prerequisites are verified)
    │
    ├── Phase 2: HelmRelease
    │   (Wait for FluxCD to report the HelmRelease's current generation Ready)
    │
    └── Phase 3: Services + Middlewares
         │
         └── phase: Ready
```

Sub-handlers provide automatic idempotency — completed phases are never re-executed on retry. If the operator restarts mid-deployment, it resumes from the last completed phase.

### Deletion

Two paths exist:

**Platform-driven (preferred)**: the backend's `deleteDeployment` mutation patches `spec.deletionRequested = true`. A `@kopf.on.update(field="spec.deletionRequested", new=True)` handler observes the flip and runs `_teardown_owned_resources` in reverse order (service aliases in all namespaces → Ingresses, then Services → HelmRelease → NetworkPolicies/Secrets), then issues a namespace delete. The periodic timer advances `phase` to `Deleted` once the namespace returns 404. Because the StyrminDeployment CR lives inside the deployment's own namespace, the CR is garbage-collected with the namespace; the agent's status reporter detects "DB DELETING + CR absent" and synthesises a final `displayState: Deleted` report so the DB is tombstoned race-free. Kubernetes deletes the CR with the rest of the namespace's contents, before it removes the namespace itself, so the reporter sends no synthetic report while the namespace has a deletion timestamp, or while it cannot read the namespace.

The first step, `_delete_service_aliases`, deletes the deployment's service aliases in the namespaces of the other deployments ([#503](https://github.com/opsmill/styrmin/issues/503)). It lists the aliases in all namespaces with two label selectors that the API server applies: `styrmin.io/service-alias=true,styrmin.io/deployment-id=<spec.deploymentId>`, and `styrmin.io/service-alias=true,!styrmin.io/deployment-id` for the aliases written before the label existed. It deletes those that `is_alias_of_deployment` (`agent/service/kubernetes/service_alias_rules.py`) assigns to the deployment: an alias whose `styrmin.io/deployment-id` label holds `spec.deploymentId`, or, for an alias without that label, an alias whose `spec.externalName` points into the deployment's namespace. It deletes each alias with the `resourceVersion` of the listing, so it does not delete a Service that replaced the alias since, such as another deployment's `ClusterIP` Service with the same name. The step acts only when the CR's namespace is `styrmin-<spec.deploymentId>`; otherwise it logs a warning and deletes no alias, so a CR copied into another deployment's namespace cannot delete the aliases of the deployment it was copied from. The step is best-effort, like the rest of the teardown: a 404, or a 409 from the precondition, is logged and is no error, a failure of either listing or of a delete is logged, and the teardown continues to its next step. Both deletion paths run it, except for a CR annotated `styrmin.io/skip-teardown: "true"`, for which the delete handler skips the whole teardown and deletes no alias. On the `kubectl delete` path, when `spec.deletionRequested` is not set, it runs only while the namespace exists and is not `Terminating` (`teardown_deletes_aliases`, the rule that the alias flow's second read also uses), so a restore's namespace deletion, which deletes the StyrminDeployment with the namespace, deletes no alias of the restored deployment. When it cannot read the namespace on that path, it logs the error and deletes no alias.

The field handler runs only after the create cause has succeeded. While the create handler keeps raising `kopf.TemporaryError`, for example because the HelmRelease cannot be created, kopf retries the create cause and stores no last-handled state. A `deletionRequested` flip in that time belongs to the pending create cause: kopf does not compute an update cause for it, so the field handler never fires ([#371](https://github.com/opsmill/styrmin/issues/371)). The create handler therefore checks `spec.deletionRequested` first. When it is `true`, the handler runs the same teardown as the field handler, through `_run_requested_teardown`, instead of the deploy pipeline: it sets `phase: Deleting`, deletes the owned resources and requests the namespace deletion. The create cause then succeeds, and the timer and the status reporter finish the deletion as for any other deployment. A CR that was already stuck this way is torn down by its next create retry, so an operator upgrade is enough to recover it.

The resume handler returns without acting when `spec.deletionRequested` is `true`. kopf runs the resume handlers together with the update handlers when the operator starts with a spec change pending, and never together with a create cause. Resuming the deploy pipeline beside the teardown would recreate the HelmRelease of an internal deployment, or set `phase` back to `CreatingHelmRelease`, while the namespace is being deleted. The create handler or the field handler owns the teardown, so the resume handler does not run it a second time.

A race used to leave the namespace in `Terminating` when the namespace deletion deleted the CR during a run of the CR's timer ([#446](https://github.com/opsmill/styrmin/issues/446), [#461](https://github.com/opsmill/styrmin/issues/461)). It affects agents of Styrmin v0.1.48 and earlier. In kopf 1.44.5 (`kopf/_core/engines/daemons.py`, `kopf/_core/actions/application.py`):

- kopf keeps the `styrmin.io/kopf-finalizer` finalizer while a timer run has not ended, and plans another check after `settings.background.cancellation_polling` seconds (60 by default);
- kopf runs the `@kopf.on.delete` handler again in each check;
- when the patch of a check is empty, kopf sleeps that delay and then writes a `touch-dummy` annotation, whose event starts the next check. When the patch is not empty, kopf skips the sleep and waits for the event of that patch;
- the delete handler's patch set `phase: Deleting`, which the earlier run had already set. From the second check on, the patch was not empty but changed nothing, so no event came and kopf never checked again.

The finalizer stayed, the namespace stayed `Terminating`, and the status reporter kept reporting `Deleting`. The same race stopped restores: `execute_velero_restore` deletes the target namespace and waits up to 600 seconds for it before it creates the Velero `Restore`.

Two changes prevent it:

- The delete handler writes `phase` and `message` only when they differ from the CR's status, so a later run leaves the patch empty and kopf keeps checking.
- `on_startup` in `entrypoint/combined.py` sets `settings.background.cancellation_polling` to `TIMER_EXIT_POLLING_SECONDS` (5 seconds), so kopf removes the finalizer at most about 5 seconds after the timer run ends. kopf also uses this delay when it stops a timer because its resource no longer matches the timer's filters (the HelmRelease timer filters on labels) or because the operator is pausing for peering. It does not use it on operator exit. The agent has no `@kopf.daemon`.

While the finalizer stays, the delete handler and its teardown run again every 5 seconds. On its second completed run for a CR, the handler logs `StyrminDeployment <namespace>/<name> keeps its finalizer until its timer run ends` once. The count lives in kopf's per-CR `memo`, so it restarts with the agent.

A restarted agent removes a finalizer that an earlier agent kept: the new process has no timer run for the CR, so its first check removes the finalizer. `backend/tests/unit/agent/test_kopf_deletion_cycle.py` runs kopf's own event processing to check both behaviours, so a kopf upgrade that changes them fails there. kopf 1.45.1 has the same logic in these files.

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

**Manual safety-net**: `kubectl delete styrmindeployment ...` triggers the existing `@kopf.on.delete` handler, which runs the same `_teardown_owned_resources` helper. This path does **not** produce a DB tombstone — it's a recovery mechanism for when the platform-driven path is unavailable.

The handler skips the teardown for a CR annotated `styrmin.io/skip-teardown: "true"` (`ANNOTATION_SKIP_TEARDOWN` in `operator/config.py`). A cross-target restore sets this annotation on its restored copy of the source's CR before it deletes that copy, because the counterpart CR now owns the resources the copy names. See [ADR-056](../../adr/0056-environment-clone-record-and-cross-target-restore.md) §3.

<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

After the platform-driven path completes, the StyrminDeployment CR remains in `phase: Deleted` for `DELETED_CR_TTL_HOURS` (default 6h, env-configurable) so operators can inspect cluster-side state. A `@kopf.timer` janitor in `operator/janitor.py` reaps CRs whose `Deleted` condition's `lastTransitionTime` is past the TTL. CRs stuck in `Deleting` are NEVER auto-reaped.

## Drift Detection and Reconciliation

A timer handler fires every 60s to compare desired vs actual state for all managed resource types. Drift on any resource is automatically corrected.

### Reconciliation States

| State | Condition |
|-------|-----------|
| `Ready` | All resources match desired state |
| `CreatingPrerequisites` / `CreatingHelmRelease` / `CreatingServices` | Deployment or update in progress |
| `Failed` | Reconciliation failed (API error, permission denied) |

In `CreatingHelmRelease` and, for non-internal deployments, `Ready`, the timer also reads the HelmRelease once per tick. When its current generation failed on the component-container guard (the guard key `styrmin.io~1component-container~1…` in a condition message, Ready not `True`), the CR goes to `Failed` / `Error` at once with `HelmReleaseReady=False` and `Ready=False`, reason `ComponentContainerNotFound`, and the typed `COMPONENT_CONTAINER_NOT_FOUND` message naming the component and container (spec 018, FR-007). During a rollout, the timer also follows FluxCD's state of the current generation, as described in the next section. Once the CR is `Ready`, the timer checks only the guard: a later HelmRelease failure without a spec change is not reflected in the CR status.

### Ingresses that Styrmin builds

<!-- Extracted from specs/033-service-ingress-override on 2026-11-10 -->

For each service that the driver declares `scope: external` (kind `http` or `https`), `IngressUtility.build_resources` returns one Ingress, so the operator treats it as it treats the Services, Secrets and NetworkPolicies of the same builder ([ADR-090](../../adr/0090-styrmin-builds-the-ingress-of-an-external-service.md)).

- `list_managed_resources` and `delete_kubernetes_resource` (`operator/reconciler.py`) handle `Ingress`, and `apply_kubernetes_resource` (`agent/service/kubernetes/primitives.py`) creates it with the networking API and replaces it on a 409.
- The periodic loop of the HelmRelease timer (`kopf_helmrelease_timer`) and the one of the StyrminDeployment timer (`kopf_styrmin_deployment_timer`) reconcile `Ingress` next to `Service` and `Secret`. An Ingress that is no longer in the desired set is deleted, for example when a driver version makes its service internal or removes the service.
- `kopf_on_ingress_update` and `kopf_on_ingress_delete` (`operator/handlers/utility_resources.py`) are filtered on the label `app.kubernetes.io/managed-by=styrmin`. `list_managed_resources` selects on the same label and on the release reference. A chart Ingress carries neither, so the operator never lists, restores or deletes it.
- The teardown deletes the Ingresses before the Services (`_teardown_owned_resources`, step 2).
- The services phase (`execute_phase_services`, `_is_service_or_middleware` in `operator/pipeline.py`) does not include `Ingress`. The Ingress is created by the first run of the HelmRelease timer, which in the end-to-end test happened about one second after the deployment was created, with an interval of 5 seconds. The default interval is 60 seconds (`SETTINGS.operator.reconcile_interval`), so on a default install the first creation can take up to that long after the HelmRelease exists. That delay was not measured. This is the current behavior and it is an open point of [ADR-090](../../adr/0090-styrmin-builds-the-ingress-of-an-external-service.md#open-points): the reason for leaving it, recorded in [e2e-evidence.md](../../../specs/033-service-ingress-override/e2e-evidence.md), was written before the two timers got one release reference and has not been checked again.

### Release reference of the periodic reconciliation

<!-- Extracted from specs/033-service-ingress-override on 2026-11-10 (commit a0885121) -->

Every utility resource carries the label `styrmin.io/release-reference`, which `UtilityResourceBuilder.build` writes from the release reference that its caller passes, and `list_managed_resources` selects on the same label. The two timers, the Prefect flows and the pipeline phases must pass one value for the same objects. Otherwise each one lists none of the objects that the other wrote, creates them again, gets a 409, and replaces the object with a body that carries its own label (reproduced on the end-to-end stack: the label of the Ingress, Services, Secret and NetworkPolicy changed between the real reference and an empty value every 2 to 25 seconds).

| Caller | Release reference it passes |
|--------|-----------------------------|
| Prefect flows `install_utility` and `update_utility` | `context.instance.release_reference` |
| Pipeline phases 1 and 3 (`build_desired_resources_from_crd`) | `spec.releaseReference` of the StyrminDeployment |
| StyrminDeployment timer | `spec.releaseReference` of the StyrminDeployment |
| HelmRelease timer | The `styrmin.io/release-reference` label of the HelmRelease, and when that is empty, `context.instance.release_reference` |

The HelmRelease that the StyrminDeployment pipeline creates has no `styrmin.io/release-reference` label: `ApplicationHelmReleaseBuilder.build` sets `app.kubernetes.io/managed-by` and `styrmin.io/operator-managed` only. The label read by the HelmRelease timer is therefore empty for every deployment that the pipeline manages, and the fallback to the instance's release reference is what makes the timers agree. `UtilityResourceBuilder.build` applies the same fallback, so no caller writes an empty label. For an ordinary deployment the reference is `styrmin-<deployment id>`. See [Name of the CR and the release reference](#name-of-the-cr-and-the-release-reference) for the counterpart of an environment clone.

Known consequences, not changed (sources: the section "Release-reference label" of [e2e-evidence.md](../../../specs/033-service-ingress-override/e2e-evidence.md)):

- The kopf drift handlers for Ingress, Service, Secret and NetworkPolicy read the label of the changed object and then select a HelmRelease by it. A HelmRelease has no such label, so the handlers find none, log "No HelmRelease found ... skipping reconciliation" and do nothing. The timers do the correction. The number of such log lines was not counted.
- `on_helmrelease_delete` passes the empty label of the HelmRelease to `cleanup_operator_resources`, so it selects none of the operator-managed NetworkPolicies that carry the real reference. `_teardown_owned_resources` deletes them by the real reference. A HelmRelease deleted alone was not tested.
- In the end-to-end runs after the fix, Services were still written about every 5 seconds with an unchanged label. The Ingress was not. The cause is not investigated.

## FluxCD controllers

The agent chart installs FluxCD's helm-controller v1.7.1 and source-controller v1.10.1 (Flux v2.10.0) in its namespace: `helm/agent/templates/helm-controller/` and `helm/agent/templates/source-controller/`, with the CRDs in `helm/agent/crds/`. The integration fixtures in `backend/tests/integration/fixtures/` hold copies of the CRDs and the two Deployments; `backend/tests/unit/test_helm_agent_crd_upgrade.py` fails when they differ from the chart. The FluxCD project supports Flux v2.10 on Kubernetes 1.35.2 and later ([Flux v2.10.0 release notes](https://github.com/fluxcd/flux2/releases/tag/v2.10.0)).

- **Helm v4 defaults.** From v1.5.0, helm-controller uses Helm v4. The agent chart runs it without `--feature-gates=UseHelm3Defaults=true` ([#435](https://github.com/opsmill/styrmin/issues/435), [ADR-072](../../adr/0072-helm-v4-defaults-releases-keep-apply-method.md)), and the operator writes none of the HelmRelease fields that set these behaviours (`install.serverSideApply`, `upgrade.serverSideApply`, `rollback.serverSideApply`, `waitStrategy`, `postRenderStrategy`), so FluxCD's defaults apply. The gate changes three defaults: the install apply method, the wait strategy and the post-render strategy (R-001 in [research.md of spec 025](../../../specs/archive/025-helm-v4-defaults/research.md), which holds R-001 to R-008). Without it:
  - New installs use server-side apply, with field manager `helm-controller`. helm-controller always forces field ownership conflicts under server-side apply, and no HelmRelease field turns this off, so at the next install, upgrade or rollback a field that the chart sets returns to the chart's value whatever changed it, and the upgrade does not fail (R-002). In the E2E runs, every new release record has `apply_method: ssa`, and the workloads' `metadata.managedFields` have manager `helm-controller` with operation `Apply` (runs 1 and 2 of [e2e-evidence.md](../../../specs/archive/025-helm-v4-defaults/e2e-evidence.md)).
  - Upgrades and rollbacks keep `auto`, with or without the gate: an upgrade uses the apply method of the newest stored revision, a rollback that of its target revision (R-004). A release installed with the gate (`apply_method: csa`, or no field in a revision that Helm v3 wrote) keeps client-side apply; a release installed without it keeps server-side apply, also if the gate is turned on again. Removing the gate does not upgrade a release that is in sync, because the release digest has no apply method, wait strategy or post-render strategy (R-003). The agent chart upgrade check ([agent-upgrade-check.md](../../../specs/archive/025-helm-v4-defaults/agent-upgrade-check.md)) found no new release revision after the upgrade, and the next change created a revision with `apply_method: csa`. That check kept the same agent image. An upgrade from an earlier release also changes the label patch in each HelmRelease's `spec.postRenderers`, so helm-controller upgrades the release, with client-side apply, the next time the operator writes that HelmRelease; whether that happens right after an agent upgrade was not checked.
  - Installs and upgrades wait with kstatus (`waitStrategy` `poller`), through `ssa.WaitForSetWithContext` of fluxcd/pkg. The wait for the release's resources ends early when one of them is `Failed`. Hook waits run without fail-fast, but Helm waits for each hook by itself and the wait also stops when only `Failed` and `Current` statuses are left, so a failed hook `Job` ends its wait too; a hook that stays `InProgress` waits the full timeout. kstatus reports a `Deployment` `Failed` only for the `Progressing` reason `ProgressDeadlineExceeded`, so a `Deployment` whose pods are in `ImagePullBackOff` stays `InProgress` and FluxCD waits the full HelmRelease timeout (R-005).
  - `postRenderStrategy: combined`: Helm runs the post-renderers once on the hooks and the templates together, then splits the hooks out by their `helm.sh/hook` annotation, so every patch in `spec.postRenderers` whose target matches a Helm hook applies to it (R-007). The patch that adds Styrmin's labels to every resource (`Target(name=".*")`) is a strategic merge, `MetadataLabelsMergePatch`, because the JSON patch `add` it replaced failed the whole render on a resource without `metadata.labels` (R-008).

  The readiness and rollback rules below were checked with these defaults in local E2E runs on 2026-10-16 ([e2e-evidence.md](../../../specs/archive/025-helm-v4-defaults/e2e-evidence.md)): the API variant of `shard_task_steps` (run 1, the rollback of an image override that cannot be pulled), of `shard_configuration` (run 2, the component-container guard and the image and container overrides) and of `shard_compute` (run 3, the pre-upgrade Helm hook Job of `test_pod_scheduling.py`). Every FluxCD state these runs produced got the CR status of the table in [What the timer writes in `CreatingHelmRelease`](#what-the-timer-writes-in-creatinghelmrelease), and no operator rule changed. `Stalled=True` did not occur in these runs; unit tests with recorded FluxCD states cover it and the readiness timeout.
- **Post-renderers digest.** helm-controller upgrades a release whose chart, values or post-renderers changed. v1.7.1 compares the post-renderers digest with `status.observedPostRenderersDigest` on every reconcile, and records the digest only when the release is in sync with the HelmRelease ([fluxcd/helm-controller#1609](https://github.com/fluxcd/helm-controller/pull/1609), released in [v1.7.1](https://github.com/fluxcd/helm-controller/blob/v1.7.1/CHANGELOG.md); [state.go at v1.7.1](https://github.com/fluxcd/helm-controller/blob/v1.7.1/internal/reconcile/state.go)). Earlier versions could report a change of `spec.postRenderers` alone (env vars, image overrides) in sync without applying it:
  - v1.1.0 compared the digest only for a generation that its `Ready` condition had not observed, and advanced that condition's `observedGeneration` before it applied the generation. When an upgrade to another driver version switched `chartRef` to a HelmChart that was not ready yet, `SourceNotReady` set it ([#432](https://github.com/opsmill/styrmin/issues/432)). When a change arrived while helm-controller was still upgrading the previous one, a status patch during the upgrade set it ([#433](https://github.com/opsmill/styrmin/issues/433), fixed upstream by [fluxcd/helm-controller#1412](https://github.com/fluxcd/helm-controller/pull/1412) in v1.5.0).
  - v1.5.0 to v1.7.0 compared the digest only while `status.observedGeneration` differed from `metadata.generation`, and also recorded it after a failed install or upgrade. When the attempt stored no release, for example after a post-render error such as the component-container guard, the next reconcile reported the previous release `Ready=True` and did not try again ([fluxcd/helm-controller#1607](https://github.com/fluxcd/helm-controller/issues/1607)). From v0.1.48, the operator detected this state from FluxCD's `InstallFailed` and `UpgradeFailed` Events ([#434](https://github.com/opsmill/styrmin/pull/434)). v1.7.1 keeps `Ready=False` and `Released=False` with the failure message and tries again, so the operator no longer reads Events and the agent's ClusterRole no longer allows `list` on `events`. A HelmRelease that v1.6.5 already reported in sync after such a failure keeps its recorded digest, so v1.7.1 does not try it again until the next change: in a kind check on Kubernetes 1.35.8 (2026-10-26), such a HelmRelease stayed `Ready=True` with its previous release 90 seconds after the controllers were replaced, while an in-sync HelmRelease got no new revision and its next post-renderers change was applied.
- **CRD upgrades.** Helm installs `crds/` only when a CRD is missing and never updates it. The chart's pre-install and pre-upgrade hook (`templates/crd-upgrade.yaml`, `crdUpgrade.enabled`, `true` by default) runs `styrmin agent apply-crds /crds` with the agent image, its own ServiceAccount and ClusterRole, and the chart's CRD files in a ConfigMap. `operator/crd/install.py` server-side applies each CRD (field manager `styrmin-agent`). A CRD that would drop a version listed in its `status.storedVersions` is deleted and created again when it has no objects, and fails the hook otherwise: the API server rejects such an update, and helm-controller v1.6.5 and later do not start without the `v1` `OCIRepository` CRD, which source-controller v1.4.0's CRD (`storedVersions: [v1beta2]`) does not serve.

## HelmRelease readiness during a rollout

<!-- Extracted from specs/019-task-steps on 2026-10-06 -->

The operator judges the HelmRelease only on its current generation, so an update or an upgrade reaches `Ready` only after FluxCD has applied the new release ([ADR-060](../../adr/0060-steps-and-derived-task-result.md)). Before this rule, the update handler kept `HelmReleaseReady=True` from the previous rollout, and the timer moved the CR to `Ready` on its next tick.

### Start of a rollout

The create and update handlers:

- set `HelmReleaseReady` to `Unknown` with reason `Progressing` ("Waiting for FluxCD to apply the HelmRelease");
- remove `HelmReleaseRemediated`, which belonged to the previous rollout;
- set `status.rolloutStartedAt` to the current time.

A kopf retry of these handlers (for example after `kopf.TemporaryError`, which every handler raises with a delay of `STYRMIN_OPERATOR_RETRY_DELAY` seconds, default 30) runs them again, so it resets `rolloutStartedAt` too. The resume handler continues the rollout: it does not reset `HelmReleaseReady`, and it sets `rolloutStartedAt` only when it is missing, so an operator restart does not extend the readiness timeout.

### Current-generation rule

A FluxCD condition of the HelmRelease counts only when its `observedGeneration` equals the HelmRelease's `metadata.generation`. A condition without `observedGeneration` is compared through `status.lastAttemptedGeneration`. This is the same rule as the component-container guard. `operator/reconciler.py::observe_helmrelease` reads the HelmRelease once per tick and returns FluxCD's `Ready` and `Released` conditions, `Remediated` and `Stalled` when they are `True`, and the guard failure, all for the current generation.

### What the timer writes in `CreatingHelmRelease`

| FluxCD state of the current generation | CR status |
|---|---|
| No condition yet | Nothing changes |
| `Ready=True` | `HelmReleaseReady=True`, reason `FluxReady`; in the same tick the timer creates the services and middlewares and, when that succeeds, moves the CR to `Ready` |
| `Ready` not `True` | `HelmReleaseReady` gets FluxCD's `Ready` status and transition time. When `Ready=False`, the reason and message come from `Released=False` when FluxCD has it (after a rollback, `Ready` describes the rollback), else from `Ready` |
| `Remediated=True` | Copied into `HelmReleaseRemediated` (status, reason such as `RollbackSucceeded` or `UninstallSucceeded`, message, transition time). The phase does not change, because FluxCD tries again after each rollback (`remediation.retries: 3` for install and upgrade) |
| `Stalled=True` | Phase `Failed`, `displayState: Error`, message `"<Stalled message>: <failure message>"`, and `Ready=False` with the `Stalled` reason, for example `RetriesExceeded`. FluxCD has used all its retries |

The timer writes a condition only when its status, reason, message or transition time changes (`operator/crd/status.py::replace_condition`), so a slow rollout does not write the status on every tick.

An internal deployment, such as the ingress controller, also counts as ready when one of its pods is ready, because its HelmRelease can stay `Progressing` while a LoadBalancer gets no external IP. A ready pod wins over `Stalled`.

### Readiness timeout

While the phase is not `Ready`, `Failed` or `Deleting`, the timer compares the time since `status.rolloutStartedAt` with `STYRMIN_OPERATOR_DEPLOYMENT_READY_TIMEOUT` (default 270 seconds). The default is below the HelmRelease timeout, `STYRMIN_OPERATOR_HELM_RELEASE_TIMEOUT` (default 300 seconds, written to every HelmRelease's `spec.timeout` as `5m`; a value that is not whole minutes is written in seconds): at that timeout FluxCD rolls the release back and the failing pods are removed, so a later readiness timeout would fail the HelmRelease step without the pods' reasons, such as `ImagePullBackOff`. With Helm v4 defaults, FluxCD's wait ends before its timeout when a resource is `Failed` for kstatus (see [FluxCD controllers](#fluxcd-controllers)), for example a chart `Deployment` past its `progressDeadlineSeconds`; with a deadline below the readiness timeout, FluxCD rolls the release back before the timer reads the pods' reasons (research R-005). It did not end early for pods in `ImagePullBackOff` or for a container that exits at once (runs 1 and 2 of [e2e-evidence.md](../../../specs/archive/025-helm-v4-defaults/e2e-evidence.md)). A CR written by an older operator, without `rolloutStartedAt`, counts from `metadata.creationTimestamp`. When the timeout comes before the timer's next run (it is less than `STYRMIN_OPERATOR_RECONCILE_INTERVAL` minus one second away), the timer waits until one second after the timeout and then runs the tick. Without the wait, the default 60-second interval could run the check up to 60 seconds late, after FluxCD's rollback. During the wait, kopf keeps updating the timer's view of the CR, so a CR that reached `Ready` or started a new rollout in the meantime is not failed. The wait ends early when kopf stops the timer, for example when the CR is deleted. After the timeout, the timer sets `displayState: Error` and the message `Deployment did not reach Ready within <timeout>s (phase: <phase>)`. The phase does not change, so a later FluxCD attempt that succeeds still moves the CR to `Ready` and `displayState: Running`. The timeout is the safety net when FluxCD never reports `Stalled`.

### FluxCD's retries after a rollback

helm-controller v1.7.1 rolls back each failed install or upgrade and then tries again until it has used its retries (`remediation.retries: 3`). It then reports `Stalled=True`, and the timer fails the CR (see the table above). Because v1.7.1 compares the post-renderers digest on every reconcile (see [FluxCD controllers](#fluxcd-controllers)), this includes a change that only adds or changes post-render overrides (image or environment variable overrides, [ADR-057](../../adr/0057-post-render-component-overrides.md) and [ADR-058](../../adr/0058-image-overrides-and-component-container-guard.md)).

In a local run of `test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason` (API variant, 2026-10-26, HelmRelease timeout `4m`), the upgrade to release v2 (an image override that cannot be pulled) failed at the timeout, and FluxCD rolled back to v1, which created release v3. 11 seconds later FluxCD started the next upgrade attempt (`Ready=Unknown`, reason `Progressing`). Each of the three retries failed at the timeout and was rolled back (releases v5, v7 and v9), and each started 11 to 15 seconds after the previous rollback. After the third, about 17 minutes after the change, FluxCD set `Stalled=True` with reason `RetriesExceeded`. 3 seconds later the operator set the phase `Failed` with the message "Failed to upgrade after 4 attempt(s): <failure message>" and `Ready=False`, reason `RetriesExceeded`. From the readiness timeout on, `displayState` was `Error` and the HelmRelease step and the task result stayed `FAILED`. The CR's `Ready` condition kept `True` from the previous rollout, because the readiness timeout does not change it. The test checks the state until FluxCD starts the next attempt.

Earlier versions reported the rollback of such a change `Ready`. After an attempt at a generation, helm-controller v1.1.0 and v1.6.5 compared only the chart and the values, so 11 to 38 seconds after the rollback they set `Ready=True` and `Released=True` with reason `UpgradeSucceeded` for the rolled-back release and did not try again (run 1 of [e2e-evidence.md of spec 025](../../../specs/archive/025-helm-v4-defaults/e2e-evidence.md)). From spec 019 until the upgrade to v1.7.1, the operator detected this state from FluxCD's release history and failed the CR with the message "FluxCD rolled the release back after release v<N> failed: …" and `Ready=False`, reason `RolledBack` (decision 13 of [ADR-060](../../adr/0060-steps-and-derived-task-result.md)). The state was: failures counted for the current generation, and the newest `deployed` release right after a `failed` one. The rule was removed with the upgrade, because v1.7.1 does not report this state.

## Steps of a rollout

The operator does not write steps. The server builds the operator-phase steps of a task ("Create network policies and secrets", "Install or upgrade the HelmRelease", "Create services and middlewares", "Wait for the deployment to be ready") from the status reports, using `status.instanceId`, the phase, `displayState`, `message` and the conditions above. FluxCD's reasons, rollbacks (`HelmReleaseRemediated`) and retries (`HelmReleaseReady` back to `Progressing`) become the HelmRelease step's detail, rollback and attempts. See [Status Reporter](overview.md#status-reporter) and [ADR-060](../../adr/0060-steps-and-derived-task-result.md).

With Helm v4 defaults, FluxCD's message for an upgrade that reached the HelmRelease timeout ends with the text of the kstatus wait, for example `timeout waiting for: [Deployment/<namespace>/<name> status: 'InProgress']`. The operator copies it into `HelmReleaseReady`, the CR's message and so the HelmRelease step's detail (runs 1 and 2 of [e2e-evidence.md](../../../specs/archive/025-helm-v4-defaults/e2e-evidence.md)). The unit-test fixtures written for spec 019 (`backend/tests/unit/test_styrmin_deployment_helmrelease_generation.py`) use `context deadline exceeded`; whether that was the exact text with the gate is not known. The operator does not parse this text, so no rule depends on it.

## Managed Resources

The operator is the sole owner of all utility resources for CRD-managed deployments:

| Resource | API Version | Created By |
|----------|------------|------------|
| NetworkPolicy | `networking.k8s.io/v1` | Operator |
| Secret | `v1` | Operator |
| HelmRelease | `helm.toolkit.fluxcd.io/v2` | Operator (reconciled by FluxCD) |
| Service | `v1` | Operator |
| Ingress | `networking.k8s.io/v1` | Operator, only for a service that the driver declares `scope: external` (see [Ingresses that Styrmin builds](#ingresses-that-styrmin-builds)); an Ingress that a chart renders belongs to Helm |
| Middleware | `traefik.io/v1alpha1` | Operator |

### Labels

All resources created from a StyrminDeployment carry:

| Label | Value | Purpose |
|-------|-------|---------|
| `app.kubernetes.io/managed-by` | `styrmin` | Identifies Styrmin-managed resources |
| `styrmin.io/deployment-crd` | `<crd-name>` | Links to parent StyrminDeployment |
| `styrmin.io/release-reference` | `<release-ref>` | Links to deployment's release reference |
| `styrmin.io/resource-phase` | `prerequisites` / `helm` / `services` | Deployment phase that created this resource |

### Resource Naming

- NetworkPolicies: the bare policy name (e.g., `default-deny-egress`); each deployment has its own namespace, so names cannot collide
- NetworkPolicies per deployment, from the ingress utility: default-deny-egress, default-deny-ingress, allow-traefik-ingress, allow-egress-to-environment (when the context has an environment id), traefik-netpolicy-egress, prefect-netpolicy-egress, infrahub-netpolicy-egress
- NetworkPolicies per deployment, from the service-discovery utility: `allow-environment-to-<component>`, one for each component that serves a declared service; it admits the namespaces of the environment on the services' ports (#557)
- Plus the policies that the application's chart creates
- Ingresses that Styrmin builds: `styrmin-svc-<driver service name>`, labeled `styrmin.io/service-name=<driver service name>`, `styrmin/environment_id` and `styrmin/deployment_id` (the dedicated controller selects Ingresses by `styrmin/environment_id`: see [ADR-090](../../adr/0090-styrmin-builds-the-ingress-of-an-external-service.md#2-the-ingress-is-named-and-labeled-by-the-driver-service-name)). The name does not use a record id: see [ADR-090](../../adr/0090-styrmin-builds-the-ingress-of-an-external-service.md#relation-to-adr-073)

### Apply semantics

<!-- Extracted from specs/017-post-render-env-vars on 2026-10-03 -->

Custom resources go through `upsert_custom_resource`
(`agent/service/kubernetes/primitives.py`): a create, then a patch on `409 Conflict`. The
operator's HelmRelease apply (`operator/pipeline.py`) opts into
`replace_spec_keys_on_update=True`. The agent's StyrminDeployment writes
(`agent/tasks/orchestration.py::_apply_styrmin_deployment_crd`, used on create, update, and
upgrade) send the same JSON Patch, built by `replace_spec_keys_json_patch`, as a conditional
write: see [Write order of the StyrminDeployment](#write-order-of-the-styrmindeployment).
Every other custom resource keeps JSON merge-patch.

| Path | Behaviour |
|------|-----------|
| Create | Body as rendered; the HelmRelease apply also sets `prune_none_on_create`, so a `null` marker is dropped rather than stored. |
| Update, `spec` (opted in) | One JSON Patch (`application/json-patch+json`): an `add` per top-level spec key the body sets, nested `None` pruned. A top-level key set to `None` becomes `add {}` then `remove`. |
| Update, `metadata.labels` / `metadata.annotations` (opted in) | An `add` per key the body sets (RFC 6901 escaping), so merge semantics hold and Flux's finalizer and kopf's annotations are untouched. |
| Update (not opted in) | `application/merge-patch+json` (RFC 7386): maps merge, keys the body omits survive. |

The rule is: **Styrmin owns each top-level spec key it writes; everything else merges.**
`spec.values` on the HelmRelease and `spec.context` on the CR are replaced, so nested keys a
new render no longer writes disappear (a cleared env var, a values-template key a migrated
driver dropped). Spec keys Styrmin never writes survive: `spec.suspend` set by
`flux suspend hr`, and the server-owned `spec.deletionRequested` on the CR, which the CRD's
CEL rule forbids resetting after a delete request. See
[ADR-057](../../adr/0057-post-render-component-overrides.md) §6.

### Write order of the StyrminDeployment

Each accepted change of a deployment schedules its own `apply_state` flow, and the
remediation flows of two changes made in quick succession can write the StyrminDeployment
in either order ([#386](https://github.com/opsmill/styrmin/issues/386)). Before this, the
last write won, so the StyrminDeployment could keep the older configuration. The decision is
recorded in [ADR-064](../../adr/0064-styrmindeployment-write-order-by-instance-sequence.md).

Each instance therefore carries a `sequence`: 1 for the deployment's first instance, then
one more for each new instance. `SQLModelDeploymentRepository.save` assigns it when it saves
a new active instance, with
`UPDATE deployment SET last_instance_sequence = last_instance_sequence + 1 ... RETURNING`.
The UPDATE keeps the deployment row locked until the transaction commits, so a second
transaction that saves an instance of the same deployment waits, and its instance gets the
next number. The instance committed last therefore holds the highest sequence and is the
active instance. A new deployment's first instance gets 1. The unique constraint
`uq_applicationinstance_deployment_sequence` rejects a duplicate.

The flows pass `Instance.sequence` to `build_styrmin_deployment_body`, which writes it in the
`styrmin.io/instance-sequence` annotation. `_apply_styrmin_deployment_crd` then, up to five
attempts:

1. Reads the StyrminDeployment. When there is none, it creates it. A `409 Conflict` means
   another flow created it after the read, and it reads again.
2. Leaves the StyrminDeployment unchanged when its annotation holds a higher sequence than
   the flow's instance, and returns that instance as a `KeptInstance`. An equal sequence is
   written again. A missing or non-numeric annotation does not stop the write.
3. Otherwise patches the StyrminDeployment with a JSON Patch whose first operation is a
   `test` of `/metadata/resourceVersion`, so the patch applies only to the version it read.
   The patch removes the annotation when the flow's instance has no sequence, because the
   annotation would then describe the previous spec. On `409`, or on `422` after which a
   second read returns a different `resourceVersion` (the write of another flow, a status
   write, a kopf annotation), it reads again. Any other `422`, such as a schema or CEL
   validation error, is raised at once.

After five attempts it raises `CustomResourceWriteConflictError`, which fails the
`resource:styrmindeployment` step with a message that names the StyrminDeployment.

A flow whose write returned a `KeptInstance`:

- logs the reason with the Prefect run logger, stores it as the output of the
  `resource:styrmindeployment` step, and records a `NewerInstanceKept` Kubernetes Event on
  the StyrminDeployment (a failed Event write logs a warning and does not fail the step);
- ends the step as succeeded. The task's operator-phase steps end `superseded` when the
  newer task's write step succeeds
  ([ADR-060](../../adr/0060-steps-and-derived-task-result.md) §20), so the task result is
  `superseded`;
- skips its service aliases, because the flow of the later change writes its own;
- in `upgrade_instance_crd`, skips the status reset;
- still runs its driver hooks. A create, an update and an upgrade still create the namespace
  when it is missing.

The annotation is the only input of the comparison. When it holds a sequence higher than any
instance of the deployment, for example after an edit with `kubectl`, every later flow
leaves the StyrminDeployment unchanged, the newest task keeps running and the deployment
stays `pending`. Removing the annotation and making a change to the deployment writes the
StyrminDeployment again.

A StyrminDeployment without the annotation, written before this change or by the
cross-target restore, is written as before.

The order of the StyrminDeployment writes does not cover FluxCD. helm-controller v1.1.0,
which the agent chart installed before, recorded a HelmRelease generation that arrived during
an upgrade as observed, with its post-renderers digest, so a change to `spec.postRenderers`
alone (env vars, image overrides) could be dropped
([#433](https://github.com/opsmill/styrmin/issues/433)). helm-controller v1.5.0 and later apply it
after the running upgrade (see [FluxCD controllers](#fluxcd-controllers)).

## Kubernetes Events

The operator emits events on the StyrminDeployment resource for observability:

| Event | Type | When |
|-------|------|------|
| `ReconcileSucceeded` | Normal | All resources match desired state |
| `DriftDetected` | Normal | Resource modified or deleted unexpectedly |
| `ReconcileFailed` | Warning | Failed to reconcile a resource |

Events are visible via `kubectl describe styrmindeployment <name>`.

## Leader Election

Uses kopf's built-in peering with `ClusterKopfPeering` CRD (see ADR-003). Priority-based: the highest-priority operator instance runs while others pause. Peer records expire after a configurable lifetime (default 60s).

## Relationship to Prefect Flows

Prefect flows create/update/delete StyrminDeployment CRDs as a declaration of intent (see ADR-006). The operator then manages all Kubernetes resources. Driver pre/post hooks still execute via Prefect.

```text
Prefect Flow                          Operator
    │                                     │
    ├── Compute GlobalContext              │
    ├── Serialize into CRD spec            │
    ├── Create StyrminDeployment ─────────►├── Phase 1: Prerequisites
    │                                     ├── Phase 2: HelmRelease
    ├── Run driver hooks                  ├── Phase 3: Services
    ├── Update task status                └── Continuous drift detection
    │
```

Pre-existing deployments without a StyrminDeployment CRD continue to work unchanged (forward-only).
