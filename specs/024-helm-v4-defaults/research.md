# Research: helm-controller Runs with Helm v4 Defaults

Sources: helm-controller [v1.6.5](https://github.com/fluxcd/helm-controller/tree/v1.6.5) (commit `37dce43`), which requires `helm.sh/helm/v4` [v4.2.4](https://github.com/helm/helm/tree/v4.2.4) ([go.mod#L44](https://github.com/fluxcd/helm-controller/blob/v1.6.5/go.mod#L44)) and pins kustomize to v5.8.1 (`sigs.k8s.io/kustomize/api v0.21.1`). Styrmin code was read at `develop` commit `fd17ffb7`.

## R-001: What the `UseHelm3Defaults` gate changes

- **Decision**: removing the gate changes exactly three defaults, all on HelmRelease fields the operator does not write: install apply method, wait strategy, and post-render strategy. Nothing else in helm-controller reads the gate.
- **Evidence**:
  - The gate is defined at [features.go#L70](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/features/features.go#L70), default `false`, and copied once into `action.UseHelm3Defaults` ([main.go#L177-L183](https://github.com/fluxcd/helm-controller/blob/v1.6.5/main.go#L177-L183)).
  - Install apply method: `install.ServerSideApply = false` with the gate, `true` without; `spec.install.serverSideApply` overrides it ([install.go#L78-L86](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/install.go#L78-L86)).
  - Wait strategy: `helmkube.LegacyStrategy` with the gate, `StatusWatcherStrategy` (kstatus) without, for install, upgrade, rollback and uninstall ([wait.go#L57-L60](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/wait.go#L57-L60)).
  - Post-render strategy: `PostRenderStrategyNoHooks` with the gate, `Combined` without, for install and upgrade ([post_render.go#L29-L33](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/post_render.go#L29-L33)).
  - Not changed by the gate: upgrade and rollback apply method stay `auto` "regardless of UseHelm3Defaults" ([upgrade.go#L104](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/upgrade.go#L104), [rollback.go#L103](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/rollback.go#L103)); take-ownership and OpenAPI validation come from the spec only.
- **Styrmin side**: `build_minimal_helm_release()` ([builders/base.py](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/base.py)) is the only HelmRelease builder, and its `Install` and `Upgrade` blocks render `remediation` only ([blocks/spec.py](../../backend/styrmin_backend/agent/service/kubernetes/resources/blocks/spec.py)). The operator already writes none of the fields (FR-001).
- **Alternatives considered**: set `install.serverSideApply: false`, `waitStrategy.name: legacy` and `postRenderStrategy: nohooks` on each HelmRelease, then drop the gate. Rejected by the PRD's decision: it keeps Helm v3 behaviour under another name, and the issue asks for Helm v4's behaviour.

## R-002: Server-side apply field ownership conflicts

- **Decision**: no Styrmin handling. helm-controller always forces conflicts under server-side apply, so a field that another manager changed does not fail the upgrade: Helm takes the field back at the next install, upgrade or rollback. The driver documentation states this.
- **Evidence**:
  - Install: `install.ForceConflicts = install.ServerSideApply // We always force conflicts on server-side apply.` ([install.go#L53](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/install.go#L53)).
  - Upgrade and rollback: `ForceConflicts = serverSideApply` and `ForceReplace = Force && !serverSideApply` ([upgrade.go#L77-L78](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/upgrade.go#L77-L78), [rollback.go#L93-L94](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/rollback.go#L93-L94)).
  - The field manager is `helm-controller` ([main.go#L66](https://github.com/fluxcd/helm-controller/blob/v1.6.5/main.go#L66), [main.go#L261](https://github.com/fluxcd/helm-controller/blob/v1.6.5/main.go#L261); Helm uses it at [client.go#L989-L993](https://github.com/helm/helm/blob/v4.2.4/pkg/kube/client.go#L989-L993)).
  - No HelmRelease field turns forcing off; `spec.upgrade.force` "is ignored for server-side apply (which always forces conflicts with other field managers)" ([helmrelease_types.go#L854-L859](https://github.com/fluxcd/helm-controller/blob/v1.6.5/api/v2/helmrelease_types.go#L854-L859)).
- **Consequence for users**: on a deployment installed with server-side apply, a field that the chart sets and that `kubectl`, a driver action or an autoscaler changed returns to the chart's value at the next upgrade. A field the chart does not set stays as the other manager left it. Styrmin changes workloads only through post-render patches (component stop and start set `enabled` on the component, which the next render turns into a `replicas: 0` patch; [`services/primitives.py`](../../backend/styrmin_backend/services/primitives.py)), so Styrmin causes no such change itself.
- **Effect on the spec**: the edge case "can make the next upgrade fail, or Helm can take the field back" resolves to "Helm takes the field back". FR-007's documentation text is adjusted (see the plan).
- **Alternatives considered**: an upstream option to turn forcing off. Rejected: nothing in Styrmin needs it, and forcing avoids a failure mode the PRD worried about.

## R-003: Does removing the gate upgrade an in-sync release?

- **Decision**: no. The new defaults take effect only at the next install, upgrade or rollback that a spec, chart or values change triggers. SC-003 is expected to hold; the manual check in [quickstart.md](quickstart.md) §4 confirms it.
- **Evidence**:
  - A deployed release is out of sync only when the chart name or version or the values digest changed ([verify.go#L174-L179](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/verify.go#L174-L179), [state.go#L138-L145](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/reconcile/state.go#L138-L145)). The post-renderers digest is compared only while `status.observedGeneration` differs from `metadata.generation` ([state.go#L158-L173](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/reconcile/state.go#L158-L173)).
  - The release digest has no apply method, wait strategy or post-render strategy ([observation.go#L63-L88](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/release/observation.go#L63-L88)).
  - The in-sync branch returns no action unless a force annotation is pending ([atomic_release.go#L333-L404](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/reconcile/atomic_release.go#L333-L404)).
  - Not confirmed from source: that the controller's startup list reaches the reconciler as Create events. It does not change the result, because the in-sync branch takes no action either way.

## R-004: How `auto` resolves for releases installed with the gate

- **Decision**: releases installed before the change keep client-side apply on every later upgrade and rollback. No migration step is needed, and none is added (out of scope).
- **Evidence**:
  - The controller resolves `auto` from the newest stored revision: `serverSideApply = lastReleaseTyped.ApplyMethod == "ssa"` ([upgrade.go#L62-L76](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/upgrade.go#L62-L76)). A rollback uses the target revision's method ([rollback.go#L82-L91](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/rollback.go#L82-L91)).
  - Helm v4's release record has `ApplyMethod string \`json:"apply_method,omitempty"\` // "ssa" | "csa"`; empty means client-side apply ([release.go#L51-L53](https://github.com/helm/helm/blob/v4.2.4/pkg/release/v1/release.go#L51-L53)). Revisions written by Helm v3 (helm-controller v1.1.0) have no such field and so resolve to client-side apply; Helm v4 records the next one as `csa` ([action.go#L726-L731](https://github.com/helm/helm/blob/v4.2.4/pkg/action/action.go#L726-L731)).
- **Turning the gate on again**: a release installed while the gate was off has `apply_method: ssa`, so its upgrades keep server-side apply. The ADR records this.

## R-005: Does the kstatus wait end early on a failed resource? (SC-002)

- **Decision**: yes for a resource that kstatus reports `Failed`, but a Deployment whose pods are in `ImagePullBackOff` stays `InProgress`. FluxCD's wait for such a change still ends at the 300-second HelmRelease timeout, after the operator's 270-second readiness check, so the failed step keeps the pods' reason. No operator change; `test_helmrelease_failure_shows_fluxcd_reason` confirms it.
- **Evidence**:
  - For the `poller` strategy helm-controller uses its own waiter, which calls `ssa.WaitForSetWithContext` from fluxcd/pkg/ssa v0.76.2 ([client.go#L68-L77](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/client.go#L68-L77)). Resource waits use `failFast = true`; hook waits use `failFast = false // We never want to fail fast for hooks` ([wait.go#L87](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/wait.go#L87), [#L114](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/action/wait.go#L114)).
  - The wait stops when the aggregate is the desired status, when fail-fast is on and a resource failed, or when only `Failed` and `Current` statuses are left ([manager_wait.go#L137-L152](https://github.com/fluxcd/pkg/blob/ssa/v0.76.2/ssa/manager_wait.go#L137-L152)).
  - kstatus reports a Deployment `Failed` only for the `Progressing` reason `ProgressDeadlineExceeded` ([core.go#L184-L189](https://github.com/fluxcd/cli-utils/blob/v1.2.3/pkg/kstatus/status/core.go#L184-L189)); missing available or ready replicas give `InProgress` ([core.go#L225-L233](https://github.com/fluxcd/cli-utils/blob/v1.2.3/pkg/kstatus/status/core.go#L225-L233)). Kubernetes' default `progressDeadlineSeconds` is 600.
  - The default HelmRelease timeout is 300 seconds ([helmrelease_types.go#L1585-L1588](https://github.com/fluxcd/helm-controller/blob/v1.6.5/api/v2/helmrelease_types.go#L1585-L1588)); Styrmin writes `5m`.
- **Consequences recorded for the documentation**:
  - A chart Deployment with `progressDeadlineSeconds` below 270 seconds now fails FluxCD's wait early. FluxCD rolls back before the readiness timeout, so the failed step shows FluxCD's `ProgressDeadlineExceeded` failure rather than the pods' reason. The example charts do not set it.
  - A template `Job` that fails, or another resource that kstatus reports `Failed`, ends the wait early too. The task shows FluxCD's failure, sooner than before; the operator rules that read FluxCD's conditions do not change.

## R-006: Release Secrets written by Helm v4 (restore and clone)

- **Decision**: no change to `restore_recovery.py`. Helm v4 stores releases in Secrets of the same type, with the same labels and encoding; the one new record field passes through the restore path, which keeps every field.
- **Evidence**:
  - `Type: "helm.sh/release.v1"` with labels `name`, `owner=helm`, `status`, `version` ([secrets.go#L263-L284](https://github.com/helm/helm/blob/v4.2.4/pkg/storage/driver/secrets.go#L263-L284)), the same as Helm v3.22.1; name prefix `sh.helm.release.v1` ([storage.go#L38](https://github.com/helm/helm/blob/v4.2.4/pkg/storage/storage.go#L38)).
  - Encoding: JSON, gzip, base64 ([util.go#L38-L56](https://github.com/helm/helm/blob/v4.2.4/pkg/storage/driver/util.go#L38-L56)), as `_HELM_RELEASE_SECRET_TYPE` and `_GZIP_MAGIC` in [`restore_recovery.py`](../../backend/styrmin_backend/operator/restore_recovery.py) expect.
  - New field `apply_method` ([release.go#L53](https://github.com/helm/helm/blob/v4.2.4/pkg/release/v1/release.go#L53)). Time fields use `omitzero`; `Info.UnmarshalJSON` reads empty strings as zero.
- **Verification**: the backup and clone shards in CI, which restore releases installed with server-side apply after this change.

## R-007: How Helm hooks reach Styrmin's post-render patches under `combined`

- **Decision**: no change to the patch targets. Kustomize receives hooks and templates in one stream and cannot tell them apart, so every patch whose target matches a hook applies to it, as the PRD intends.
- **Evidence**:
  - helm-controller builds one `Combined` post-renderer: one kustomize renderer per `spec.postRenderers` entry, then CommonMetadata, then OriginLabels ([build.go#L30-L52](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/postrender/build.go#L30-L52)).
  - Helm merges all rendered files, runs the post-renderer once, then splits hooks out by the `helm.sh/hook` annotation ([action.go#L431-L464](https://github.com/helm/helm/blob/v4.2.4/pkg/action/action.go#L431-L464)). Hook order is set after post-rendering, by weight and name ([hooks.go#L172-L177](https://github.com/helm/helm/blob/v4.2.4/pkg/action/hooks.go#L172-L177)).
  - Kustomize's target selection matches namespace, name, group-version-kind, labels and annotations only ([reswrangler.go#L632-L677](https://github.com/kubernetes-sigs/kustomize/blob/api/v0.21.1/api/resmap/reswrangler.go#L632-L677)).
  - Styrmin's patches add keys under `metadata.labels`, `spec.template…` and container fields; none replaces `metadata.annotations`, so the `helm.sh/hook` annotation survives.
  - A resource declared both as a hook and as a template once failed with "may not add resource with an already registered id"; the v1.5.4 changelog lists "Fix post-renderer conflict of overlapping hooks and templates" (#1461). Not checked in source.
  - JSON-patch `replace` of a missing `containers/0/resources` key, which `ResourcesPatch` emits, adds the key in kustomize v5.7.1 (checked locally with `kubectl kustomize`), so a hook Job without `resources` still receives the scheduling resources.
- **Alternatives considered**: exclude hooks from Styrmin's patches with `annotationSelector: "!helm.sh/hook"`, which helm-controller passes to kustomize ([kustomize.go#L130](https://github.com/fluxcd/helm-controller/blob/v1.6.5/internal/postrender/kustomize.go#L130)), or set `postRenderStrategy: nohooks` per HelmRelease. Rejected by the PRD's decision that hooks receive the patches.

## R-008: The Styrmin label patch fails on a resource without `metadata.labels`

- **Finding**: the patch that adds Styrmin's labels to every resource (`build_target_for_label_patches`, target `name: ".*"`) is a JSON patch with one `add` per key at `/metadata/labels/<key>`. JSON patch `add` needs the parent to exist, so a resource without `metadata.labels` fails the whole render: `kubectl kustomize` (v5.7.1) reports `add operation does not apply: doc is missing path: "/metadata/labels/styrmin~1deployment-id": missing value`. Today only templates reach the patch, and chart templates carry labels. Under `combined`, Helm hooks reach it too, and a chart hook without labels would fail every install and upgrade of that driver after the agent upgrade.
- **Charts checked** (rendered or read on 2026-10-16):
  - semaphore 16.0.11: its `test-success` Pod has labels;
  - infrahub 4.33.2 and infrahub-enterprise 4.19.2: hook templates exist (the infrahub upgrade Job, prefect-server migrations, infrahub-backup, nats tests, neo4j cleanup), all labelled, and the drivers' values turn none of them on;
  - app-template 5.2.1 (generic-app) and infrahub-mcp 0.1.0: no hook templates.
- **Decision**: render the every-resource label patch as a strategic-merge patch on `metadata.labels` with the same target. Kustomize applies it to every kind, creates the map when it is missing and keeps existing labels (checked locally on a `ConfigMap` and a `Job` without labels and a custom resource with labels). The per-component label patch (`build_target_for_component_labels`) and the pod template label patch keep their JSON form: they select by label or target `Deployment` and `StatefulSet` pod templates, which always have labels.
- **Effect on existing deployments**: the HelmRelease's `spec.postRenderers` changes only when the operator renders it again, which it does for a new rollout and for a resume that is not `Ready` ([`on_styrmin_deployment_resume`](../../backend/styrmin_backend/operator/handlers/styrmin_deployment.py)). An agent upgrade therefore leaves `Ready` deployments' HelmReleases unchanged (SC-003); a later change carries the new patch with the rest of its spec.
- **Alternatives considered**:
  - Leave the patch and document that driver charts must label every Helm hook. Rejected: a third-party driver that works today would fail after the agent upgrade (spec need 7).
  - Exclude unlabelled resources: kustomize cannot select "no labels".
  - Upstream: nothing to change in kustomize or helm-controller; JSON patch semantics are the cause.

## R-009: Node placement in the scheduling E2E test

- **Finding**: Styrmin's scheduling configuration has no node selector field; it pins pods with node affinity and tolerations (`SchedulingConfig` in [`context/models/config.py`](../../backend/styrmin_backend/context/models/config.py)). The E2E vcluster has one node ([`test_pod_scheduling.py`](../../backend/tests/e2e/test_pod_scheduling.py) module comment).
- **Decision**: the hook Job check asserts the Job's tolerations, node affinity and the other scheduling fields of the update, and that the Job completed. It does not assert placement on a second node. The PRD's "node selector" reads as node affinity.

## Not related to the gate

- helm-controller issue [#1562](https://github.com/fluxcd/helm-controller/issues/1562) (a panic on hooks with `helm.sh/hook-output-log-policy`) affects hook execution with or without the gate.
- Issue [#1607](https://github.com/fluxcd/helm-controller/issues/1607) (a failed `postRenderers`-only upgrade reported `Ready`) was reported with the gate on; the operator's "failed change reported in sync" rule handles it.
