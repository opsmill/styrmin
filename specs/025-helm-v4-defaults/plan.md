# Implementation Plan: helm-controller Runs with Helm v4 Defaults

**Branch**: `fac/helm-v4-end3k` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/025-helm-v4-defaults/spec.md` (PRD: [#435 comment](https://github.com/opsmill/styrmin/issues/435#issuecomment-6210811102))

## Summary

The agent chart runs FluxCD's helm-controller v1.6.5 with `--feature-gates=UseHelm3Defaults=true`, so every HelmRelease runs with Helm v3 behaviour. This change removes the gate, so new installs use server-side apply, every install and upgrade uses kstatus health checks, and Helm hooks reach Styrmin's post-render patches. The operator's rules do not change; the existing E2E suite checks that users view the same task results.

Technical approach (details in [research.md](research.md)):

- Remove the gate argument from the agent chart's helm-controller Deployment and from the integration fixture copy; add a chart test that fails when the gate is set (R-001).
- Pin with a unit test that the operator writes none of the Helm v4 fields on HelmReleases (R-001).
- Rely on helm-controller's own behaviour for existing releases: `auto` keeps client-side apply, and an in-sync release is not upgraded when only the defaults change (R-003, R-004). Confirm with a manual agent-upgrade check.
- Accept that helm-controller forces server-side apply conflicts, and document it for driver authors (R-002).
- Render the patch that adds Styrmin's labels to every resource as a strategic merge, so a Helm hook without `metadata.labels` no longer fails the render (R-008, D-006).
- Add an off-by-default pre-upgrade Helm hook Job to the `simple-app` test chart, turn it on through a new `hook-job` E2E test driver, and extend `test_pod_scheduling.py` to check the Job's scheduling fields, labels and completion (D-002, D-003).
- Run the full E2E suite in CI and the `api` cell of `shard_configuration` locally (D-004).
- Update the operator and CRDs page, the driver guide, the operator knowledge page, `CONTEXT.md`, add an ADR and a towncrier fragment (D-005).

## Technical Context

**Language/Version**: Python 3.14+ (backend, agent, operator, tests); Helm chart YAML (agent chart, `simple-app` test chart)

**Primary Dependencies**: FluxCD helm-controller v1.6.5 (Helm v4.2.4, kustomize v5.8.1), source-controller v1.9.6; kopf; kubernetes-asyncio. No new dependency, no version change.

**Storage**: N/A. No database, GraphQL, SDK or frontend change (spec FR-012).

**Testing**: pytest unit tests (`helm template` of the agent chart and the `simple-app` chart; HelmRelease spec rendering); E2E on vCluster (`shard_compute` for the scheduling test, `shard_task_steps`, `shard_configuration` api cell run locally, full suite in CI); a manual agent-upgrade check.

**Target Platform**: Styrmin agent on Kubernetes 1.34.1 or later (Flux v2.9 minimum).

**Project Type**: Web service (backend + agent + operator) with a Helm agent chart and example drivers.

**Performance Goals**: No new goal. The scheduling E2E test gains one Job check after an update it already makes; the hook Job runs for a few seconds per upgrade of the scheduling deployment only.

**Constraints**:

- Helm charts ship `resources.requests` only, never `resources.limits` (AGENTS.md; `test_helm_resource_limits.py`). The hook Job in the test chart sets no limits.
- The integration fixture copy of helm-controller must match the chart (`test_fixture_controllers_run_the_chart_images`).
- No CI workflow change: the `api`/`configuration` exclusion in `.github/workflows/ci.yml` stays; that cell is run locally (Governance gate).
- The operator's readiness timeout stays 270 seconds below FluxCD's 300-second HelmRelease timeout.

**Scale/Scope**: 2 chart files (agent chart, fixture), 2 test-chart files, 1 E2E test driver, 1 production Python change (the every-resource label patch, D-006), 3 unit test files, 1 integration test, 1 E2E test file, 5 documentation files, 1 ADR, 1 changelog fragment.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
| --- | --- | --- |
| I. Declarative state reconciliation | Pass | No reconciliation change. An in-sync release is not upgraded by the gate removal (R-003), and the operator does not render a `Ready` deployment's HelmRelease again on resume (R-008), so the agent upgrade is idempotent for existing deployments. The new label patch gives the same labels for the same stored config. |
| II. Driver-based deployment | Pass | Post-render patches now reach Helm hooks of driver charts; the driver guide states which ones (FR-007). The label patch change keeps drivers whose hooks have no labels working (FR-013). The hook Job is added to a test chart behind a value that no example driver turns on. |
| III. Layered architecture | Pass | No API, service or repository change. |
| IV. Type safety and typed errors | Pass | No new error type. The guard keeps `COMPONENT_CONTAINER_NOT_FOUND`. |
| V. Test-first development | Pass, with one flagged decision | `test_pod_scheduling.py` is extended (reuse before boot) for the new user-visible behaviour (FR-003). The existing suite covers FR-002. `Stalled` and the readiness timeout keep unit-test coverage only; the spec flags this for maintainer confirmation as AGENTS.md asks. Local PASS evidence is recorded for every new or modified E2E test. |
| VI. Format and lint | Pass | `uv run invoke format lint` before each commit. |
| VII. Documentation accuracy | Pass | `docs/` (operator and CRDs, creating a driver), `dev/knowledge/agent/operator.md`, `CONTEXT.md`, a new ADR and a towncrier fragment ship in the same change (D-005). |
| Governance gates | Pass | No schema, GraphQL, dependency, CI workflow or auth change. |

Post-design re-check (after Phase 1): unchanged. The `hook-job` test driver lives under `backend/tests/e2e/fixtures/drivers/`, like `failing-actions` and `late-container`, so no example driver gains a test-only parameter.

## Design Decisions

### D-001: Remove the gate in the chart and the fixture, and pin it with tests

- Remove `--feature-gates=UseHelm3Defaults=true` and its comment from `helm/agent/templates/helm-controller/deployment.yaml` and `backend/tests/integration/fixtures/templates/helm-controller/deployment.yaml`.
- Add `test_helm_controller_runs_with_helm_v4_defaults` to `backend/tests/unit/test_helm_agent_crd_upgrade.py`: read `helm/agent/templates/helm-controller/deployment.yaml` the way `test_fixture_controllers_run_the_chart_images` does (drop the template lines, load the YAML) and assert that no container argument contains `UseHelm3Defaults`. It needs no `helm` binary, so it cannot be skipped in CI (critique E3). Update the module docstring to cover the controllers' arguments.
- Add a unit test next to the HelmRelease rendering tests (`backend/tests/unit/agent/test_custom_resources.py`) that renders `build_minimal_helm_release()` and asserts that `install` and `upgrade` are `{"remediation": {"retries": 3}}` and that `spec` has no `waitStrategy`, `postRenderStrategy` or `rollback` key (contract C-002).
- Rationale: FR-001's two halves. The fixture comparison test already fails if only one copy changes.

### D-002: `simple-app` test chart gets an off-by-default pre-upgrade hook Job

- New template `driver/examples/simple-app/src/helm/templates/pre-upgrade-hook-job.yaml`, rendered only when `.Values.preUpgradeHookJob.enabled` is true; new value `preUpgradeHookJob.enabled: false` in the chart's `values.yaml` with a comment saying only the `hook-job` E2E test driver turns it on.
- The Job:
  - annotations `helm.sh/hook: pre-upgrade`, `helm.sh/hook-weight: "0"`, `helm.sh/hook-delete-policy: before-hook-creation`, so the Job stays after the upgrade and the test can read it;
  - `metadata.labels`: the chart's standard labels (`simple-app.labels`, which include `app.kubernetes.io/name: simple-app`, the server component's identifier label), plus `app.kubernetes.io/component: pre-upgrade-hook`;
  - pod template labels: `app.kubernetes.io/component: pre-upgrade-hook` and `app.kubernetes.io/instance` only, without `app.kubernetes.io/name`, so the simple-app Service and the scheduling test's pod affinity rule do not select the hook pod;
  - one container `hook` with the chart's image (`simple-app.image`), the chart's `securityContext`, `command: ["python", "-c", "print('pre-upgrade hook')"]`, `restartPolicy: Never`, `backoffLimit: 0`, and `resources.requests` only (no limits);
  - no `ttlSecondsAfterFinished`, so the completed Job stays until the next upgrade replaces it.
- Behind the same value, a `ConfigMap` annotated `helm.sh/hook: pre-upgrade`, `helm.sh/hook-weight: "-1"` and `helm.sh/hook-delete-policy: before-hook-creation`, with no `metadata.labels` and one data key. It checks FR-013 end to end with helm-controller's own kustomize (critique X1, E5).
- Rationale: per-component scheduling patches are narrowed by the component's identifier label selector, which kustomize matches against the resource's own `metadata.labels` ([`application.py` `build_scheduling_post_rendering_patches`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py)), so the Job must carry `app.kubernetes.io/name: simple-app` on its metadata to receive them. The component-container patches and the guard target `Deployment` and `StatefulSet` only, so they do not reach the Job (data-model.md).
- A unit test `backend/tests/unit/test_simple_app_hook_job.py` renders the chart with `helm template` with the value off (no hook resource) and on (one Job with the annotations and labels of contract C-005). It skips when `helm` is not on PATH, like the agent chart tests. The chart's `charts/` directory already vendors the PostgreSQL subchart.
- Alternative rejected: a boolean parameter on the `simple-app` example driver. It would add a test-only field to the deploy form of a driver users read as a reference.
- Alternative rejected: patching the HelmRelease's `spec.values` from the test, as `test_deployment_env_vars.py` does for `extraEnv`. The next Styrmin update rewrites `spec.values`, and the scheduling test's update is exactly the upgrade that must run the hook.

### D-003: `hook-job` E2E test driver and the extended scheduling test

- New test driver `backend/tests/e2e/fixtures/drivers/hook-job/` (`driver.styrmin.yml`, `values.j2.yml`), registered in the `drivers` map of `backend/tests/e2e/conftest.py` with `chart_name: simple-app`. It is the `simple-app` driver with the same components, container names, services and backup settings, no actions, and `preUpgradeHookJob.enabled: true` in its values template.
- `test_pod_scheduling.py`: the module-scoped `scheduling_deployment` fixture takes the `git_server` fixture, loads the driver with `driver.load_driver_version(git_url=git_server["hook-job"], ref="master")` as `failing_actions_deployment` in `test_task_steps.py` does, and creates its deployment from `hook-job` instead of `simple-app` (critique E2). `scheduling_deployment_b` stays on `simple-app`.
- `test_scheduling_end_to_end` gains, after its existing assertions on the server Deployment:
  - read the Jobs in the deployment's namespace with label selector `app.kubernetes.io/component=pre-upgrade-hook`; exactly one exists;
  - its `spec.template.spec` has the `dedicated=batch:NoSchedule` toleration, the preferred node affinity, the pod affinity, the topology spread constraint, `runtimeClassName: kata-e2e`, and the resources of the update on `containers[0]`;
  - its `metadata.labels` carry Styrmin's labels (the keys of `context.labels` with the `styrmin` prefix, read from the server Deployment's labels to avoid hard-coding them) and the `component` label;
  - its `status.succeeded` is 1, which shows the pod was scheduled with those settings and ran;
  - the unlabelled hook `ConfigMap` exists and its `metadata.labels` carry Styrmin's labels (FR-013, SC-006).
- The vcluster has one node, so SC-004 ("runs on those nodes") is checked by the pod's scheduling fields and completion, not by placement on a second node. The test docstring says so.
- The test stays `api_only` and `shard_compute`. No new test node and no new heavy fixture.
- Rationale: FR-003 and SC-004 with the cheapest reuse; the update in `test_scheduling_end_to_end` is already a Helm upgrade, which runs the pre-upgrade hook with the new post-renderers.

### D-004: E2E runs for FR-002 and SC-001/SC-002

- CI runs the full suite, both variants as marked, on the pull request.
- Run locally, one shard per session, `api-chromium` and `ui-chromium` in separate sessions:
  - `shard_configuration` with `-k api-chromium`, which CI excludes; it holds `test_misnamed_container_never_added` (the guard) and the image and container override tests;
  - `shard_compute` with `-k api-chromium` for the extended scheduling test (local PASS evidence);
  - `shard_task_steps` with `-k api-chromium` for `test_helmrelease_failure_shows_fluxcd_reason` (rollback and `ImagePullBackOff`), to confirm SC-002 before CI.
- If a run shows a different result from Helm v3 behaviour, the operator rule is changed in the same change and the knowledge page records the new FluxCD state (FR-002). The plan expects none (R-005, R-006).

### D-006: Strategic-merge label patch for every resource

- Add a `MetadataLabelsMergePatch` (name to settle in implementation) to [`blocks/patches.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py) that renders a strategic-merge patch:

  ```yaml
  apiVersion: v1
  kind: any
  metadata:
    name: any
    labels:
      styrmin/<key>: <value>
  ```

  with the same `label_prefix` handling as `LabelPatch` (the prefix joined to the key with `/`).
- `build_target_for_label_patches` uses it for the `Target(name=".*")` entry. The `Deployment` and `StatefulSet` `TemplateLabelPatch` entries, and `build_target_for_component_labels`, keep `LabelPatch` and `TemplateLabelPatch`: they match resources by label or pod templates that always have labels.
- Tests:
  - unit: the rendered patch YAML for a prefixed and an unprefixed label set (next to the existing `LabelPatch` doctests and `test_blocks.py`);
  - integration: `backend/tests/integration/test_label_patch_kustomize.py`, modelled on `test_component_container_kustomize.py`, runs `kubectl kustomize` with the patch on a labelled `Deployment`, an unlabelled `ConfigMap` and an unlabelled hook `Job`; all three get the labels, and the `Deployment` keeps its own (FR-013, SC-006).
- Existing deployments: the HelmRelease's `spec.postRenderers` changes the next time the operator renders it (a rollout, or a resume that is not `Ready`). `Ready` deployments are not rendered again at agent upgrade, so SC-003 holds (R-008).
- Rationale: R-008. Without it, a driver whose chart has a Helm hook without labels fails every install and upgrade after the gate removal.

### D-005: Documentation

- `docs/docs/concepts-and-architecture/operator-and-crds.md`: replace "helm-controller runs with the `UseHelm3Defaults` feature gate…" with: helm-controller runs with Helm v4 defaults; new deployments are installed with server-side apply, deployments installed before keep client-side apply; installs and upgrades wait with kstatus; Helm hooks receive Styrmin's post-render patches.
- `docs/docs/drivers/creating-a-driver.md`:
  - Step 1 ("Analyse the Helm chart"): list Helm hooks (`helm.sh/hook`) among what to look for, and state which post-render patches reach them (Styrmin's labels always; scheduling settings for hook `Job`, `CronJob`, `Deployment`, `StatefulSet`, `DaemonSet` and `ReplicaSet` resources that carry a component's identifier label; overrides and the guard only for a hook `Deployment` or `StatefulSet` that matches a component). State that a chart `Deployment` with `progressDeadlineSeconds` below 270 seconds makes FluxCD fail the change before Styrmin reads the pods' reason (R-005).
  - "The component container": keep "not chart `Job`s or `CronJob`s" and add "including Helm hook Jobs".
  - Step 7 ("Lifecycle actions"): for deployments installed with server-side apply, a field of a chart resource that an action changes returns to the chart's value at the next upgrade, because helm-controller forces conflicts (R-002). This replaces the PRD's "can make the next upgrade fail", which research showed does not happen.
- `dev/knowledge/agent/operator.md`: replace the "Helm v3 behaviour" bullet with the Helm v4 defaults, how existing releases keep their apply method, the forced conflicts (R-002) and the early end of FluxCD's wait on a `Failed` resource (R-005); replace "The readiness and rollback rules below were observed with Helm v3's behaviour" with the runs that checked them with Helm v4 defaults; update line 194 ("Whether v1.6.5 still reports the rollback of a post-renderers change as `Ready` was not checked") if the `shard_task_steps` run answers it.
- `CONTEXT.md`: new **Helm hook** entry (definition from the spec's Key Entities); add "Helm hook" to the **Hook** entry's `_Avoid_` list ("a chart resource annotated `helm.sh/hook` is a **Helm hook**, not a **hook**").
- New ADR `dev/adr/0071-helm-v4-defaults-releases-keep-apply-method.md` (number 0070 is used on three open branches; take the next free number at merge): decisions from the spec's Clarifications, R-002 (forced conflicts), R-004 (`auto` and turning the gate on again), and D-006.
- Rollback for administrators, in the operator and CRDs page and the ADR: downgrading the agent chart turns the gate on again; deployments created while it was off keep server-side apply on later upgrades (critique P2, E4).
- `changelog/435.changed.md`: new installs use server-side apply and kstatus health checks, and Helm hooks of a driver's chart receive Styrmin's labels and scheduling settings. A chart resource without labels no longer fails the render.
- No page under `dev/` or `docs/` names the label patch's JSON form (`grep -rn "metadata/labels" dev docs` on 2026-10-16), so none needs that update.

## Risks

| Risk | Effect | Mitigation |
| --- | --- | --- |
| kstatus ends the wait early on a failed resource, so FluxCD rolls back before the 270-second readiness timeout and the pods' reason is lost (SC-002) | The failed step no longer names `ImagePullBackOff` | R-005 shows an `ImagePullBackOff` Deployment stays `InProgress`; `test_helmrelease_failure_shows_fluxcd_reason` asserts the reason, run locally before CI |
| A chart hook without labels fails the render | That driver's installs and upgrades fail after the agent upgrade | D-006 (FR-013) |
| The strategic-merge label patch behaves differently from the JSON form on some kind | Labels missing or a render error | Integration test on a `Deployment`, a `ConfigMap` and a `Job`; the unlabelled hook `ConfigMap` in the scheduling E2E test; the full E2E suite renders every example driver |
| The backup `TemplateAnnotationPatch` (JSON `add` under `/spec/template/metadata/annotations/`) fails on a hook `Deployment` or `StatefulSet` that matches a backup component and has no pod annotations | That driver's render fails | Known limitation, the same as for templates today; recorded in R-008, not changed here (critique E1) |
| A third-party chart's Helm hook fails with Styrmin's patches (for example a hook `Deployment` that matches a component but lacks its container, which the guard fails) | That driver's install or upgrade fails after the agent upgrade | Documented in the driver guide; the example drivers have no such hook (spec Edge Cases) |
| Helm v4 changes the release Secret format | Restore and clone break | R-007; the backup and clone shards run in CI |
| The hook Job adds time to every upgrade of the scheduling deployment | Slower `shard_compute` | The Job runs one `python -c` command; only `scheduling-a` has it |

## Project Structure

### Documentation (this feature)

```text
specs/025-helm-v4-defaults/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── behaviour.md     # Phase 1 output
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
helm/agent/templates/helm-controller/deployment.yaml               # remove the gate
backend/tests/integration/fixtures/templates/helm-controller/deployment.yaml  # remove the gate
backend/tests/unit/test_helm_agent_crd_upgrade.py                  # gate test
backend/tests/unit/agent/test_custom_resources.py                  # HelmRelease spec test
backend/tests/unit/test_simple_app_hook_job.py                     # new: chart render test
backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py      # new label merge patch
backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py  # use it for name ".*"
backend/tests/unit/agent/test_blocks.py                            # patch rendering test
backend/tests/integration/test_label_patch_kustomize.py            # new: kustomize test, modelled on test_component_container_kustomize.py
driver/examples/simple-app/src/helm/values.yaml                    # preUpgradeHookJob.enabled
driver/examples/simple-app/src/helm/templates/pre-upgrade-hook-job.yaml  # new
backend/tests/e2e/fixtures/drivers/hook-job/driver.styrmin.yml     # new test driver
backend/tests/e2e/fixtures/drivers/hook-job/values.j2.yml          # new test driver
backend/tests/e2e/conftest.py                                      # register hook-job
backend/tests/e2e/test_pod_scheduling.py                           # hook Job assertions
docs/docs/concepts-and-architecture/operator-and-crds.md
docs/docs/drivers/creating-a-driver.md
dev/knowledge/agent/operator.md
CONTEXT.md
dev/adr/0071-helm-v4-defaults-releases-keep-apply-method.md        # new
changelog/435.changed.md                                           # new
```

**Structure Decision**: no new module. Production change is the agent chart and one post-render patch; the rest is tests, the test chart and documentation.

## Complexity Tracking

No constitution violation to justify.
