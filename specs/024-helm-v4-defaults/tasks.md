---

description: "Tasks for 024: helm-controller runs with Helm v4 defaults"
---

# Tasks: helm-controller Runs with Helm v4 Defaults

**Input**: Design documents from `specs/024-helm-v4-defaults/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/behaviour.md](contracts/behaviour.md), [quickstart.md](quickstart.md)

**Tests**: Required. Every FR in the spec names its verification, and Constitution §V requires E2E coverage with local PASS evidence for each new or modified E2E test.

**Organization**: One phase per user story. All four stories ship in one change (spec Context). Phase 2 holds the gate removal and the label patch fix, which every story depends on.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US4 (spec user stories)
- Paths are relative to the repository root

## E2E run rules (apply to every E2E task)

- Build the server image once before the first session: `docker compose build server`.
- One CI shard per pytest session (`-m "ci and shard_<name>"`), and `api-chromium` and `ui-chromium` in separate sessions.
- Run with `--pdb`. From a non-interactive shell, prefix the command with `sleep infinity |` and stop the run by PID, not with `pkill -f`.
- Record each passing run in `specs/024-helm-v4-defaults/e2e-evidence.md`: pytest node IDs, the exact command, ISO 8601 start and end times, the vcluster name and kubeconfig path, and the verbatim `PASSED` lines (Constitution §V).

---

## Phase 1: Setup

**Purpose**: a green baseline before any change.

- [X] T001 Run `uv sync`, then `uv run pytest backend/tests/unit/test_helm_agent_crd_upgrade.py backend/tests/unit/agent/test_blocks.py backend/tests/unit/agent/test_custom_resources.py -q` and `uv run pytest backend/tests/integration/test_component_container_kustomize.py -q`, and note the results as the baseline (no file change). Check that `helm` and `kubectl` are on PATH (`helm version`, `kubectl version --client`)

---

## Phase 2: Foundational (blocks every story)

**Purpose**: Styrmin's labels reach a resource without labels (research R-008, plan D-006), and helm-controller runs without the gate (plan D-001). The label patch change lands first, because without it a chart Helm hook without labels fails the render as soon as the gate is gone.

- [X] T002 In `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py` add a `Patch` subclass `MetadataLabelsMergePatch` next to `LabelPatch`, with fields `labels: dict[str, str]` and `label_prefix: str = ""`. `render_value()` returns, built with `yaml.dump` only (never string formatting), a strategic-merge document `{"apiVersion": "v1", "kind": "any", "metadata": {"name": "any", "labels": {<key>: <value>}}}` where `<key>` is `f"{label_prefix.strip('/')}/{key}"` when `label_prefix` is set and `key` otherwise. Values are rendered as strings. Add a docstring with a doctest, in the style of `LabelPatch`, that says the patch adds the labels map when a resource has none (plan D-006)
- [X] T003 In `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` change the first entry of `build_target_for_label_patches` (`Target(name=".*")`) from `LabelPatch` to `MetadataLabelsMergePatch` with the same `labels` and `label_prefix`. Keep the `Deployment` and `StatefulSet` `TemplateLabelPatch` entries and `build_target_for_component_labels` unchanged
- [X] T004 [P] In `backend/tests/unit/agent/test_blocks.py` add tests for `MetadataLabelsMergePatch.render_value()`: one unprefixed label, a `styrmin` prefix, a key that already contains `/` (for example `app.kubernetes.io/name`), a value such as `"123"` or `"true"` that stays a string after `yaml.safe_load`, and a value with a newline that stays one value after `yaml.safe_load`
- [X] T005 [P] Run `grep -rn "build_target_for_label_patches\|LabelPatch(" backend/tests` and update any test that pins the JSON-patch form of the every-name label patch to the strategic-merge form. Leave tests of `LabelPatch` and `TemplateLabelPatch` themselves unchanged
- [X] T006 [P] Create `backend/tests/integration/test_label_patch_kustomize.py`, modelled on `backend/tests/integration/test_component_container_kustomize.py` (same `kubectl kustomize` helper and skip rule): build the post-renderer patches with `ApplicationHelmReleaseBuilder.build_target_for_label_patches(labels={"deployment-id": "abc"}, label_prefix="styrmin")` (an instance method that reads only its arguments; build the builder as the existing builder tests in `backend/tests/unit/agent/` do), run them on a stream with a `Deployment` that has its own labels, a `ConfigMap` without `metadata.labels` and a `Job` annotated `helm.sh/hook: pre-upgrade` without `metadata.labels`; assert the render succeeds, all three carry `styrmin/deployment-id: abc`, the `Deployment` keeps its own labels, and the `Job` keeps its `helm.sh/hook` annotation (contract C-004a, FR-013, SC-006)
- [X] T007 Remove `--feature-gates=UseHelm3Defaults=true` and its comment line from the helm-controller container `args` in `helm/agent/templates/helm-controller/deployment.yaml` and in `backend/tests/integration/fixtures/templates/helm-controller/deployment.yaml` (contract C-001)
- [X] T008 In `backend/tests/unit/test_helm_agent_crd_upgrade.py` add `test_helm_controller_runs_with_helm_v4_defaults`: load `helm/agent/templates/helm-controller/deployment.yaml` the way `test_fixture_controllers_run_the_chart_images` does (drop lines containing `{{`, `yaml.safe_load`), take the first container's `args`, and assert that no argument contains `UseHelm3Defaults` and none starts with `--feature-gates`. It must not call `helm`, so it cannot be skipped (plan D-001, critique E3). Extend the module docstring: the chart runs helm-controller with Helm v4 defaults (#435)
- [X] T009 [P] In `backend/tests/unit/agent/test_custom_resources.py` add a test that renders `build_minimal_helm_release("rel", "chart").render()` (from `backend/styrmin_backend/agent/service/kubernetes/resources/builders/base.py`) and asserts `spec["install"] == {"remediation": {"retries": 3}}`, `spec["upgrade"] == {"remediation": {"retries": 3}}`, and that `spec` has no `waitStrategy`, `postRenderStrategy` or `rollback` key (contract C-002, FR-001)
- [X] T010 Run `uv run pytest backend/tests/unit/test_helm_agent_crd_upgrade.py backend/tests/unit/agent/test_blocks.py backend/tests/unit/agent/test_custom_resources.py -q` and `uv run pytest backend/tests/integration/test_label_patch_kustomize.py backend/tests/integration/test_component_container_kustomize.py -q`; fix failures, then `uv run invoke format lint`

**Checkpoint**: the agent chart and the fixture run helm-controller without the gate, and the label patch works on resources without labels.

---

## Phase 3: User Story 1 - Users view the same task results with Helm v4 defaults (Priority: P1) 🎯

**Goal**: the operator reports the same task results and steps as with Helm v3 behaviour (FR-002, SC-001, SC-002, SC-005).

**Independent Test**: the E2E shards that cover a successful install, the rollback with `ImagePullBackOff`, and the component-container guard pass against the agent chart without the gate.

- [X] T011 [US1] Run `shard_task_steps`, API variant: `sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_task_steps" -k "api-chromium" -v -s --pdb 2>&1 | tee /tmp/e2e-task-steps.log`. `test_helmrelease_failure_shows_fluxcd_reason` must pass: the failed "Install or upgrade the HelmRelease" step has FluxCD's reason and the pods' `ImagePullBackOff` or `ErrImagePull` (SC-002). While the session runs or from the log, record FluxCD's state after the rollback of that test (`kubectl get helmrelease -n styrmin-<id> -o yaml`: `status.history`, the `Ready` and `Released` conditions) to answer whether v1.6.5 still reports the rollback of a post-renderers change as `Ready` (operator knowledge page, "Rollback reported Ready"). Record the evidence in `specs/024-helm-v4-defaults/e2e-evidence.md`
- [X] T012 [US1] Run `shard_configuration`, API variant, which CI excludes: `sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_configuration" -k "api-chromium" -v -s --pdb`. `test_deployment_image_override.py::test_misnamed_container_never_added` must pass with `COMPONENT_CONTAINER_NOT_FOUND`, and the image and container override tests must pass. Record the evidence in `specs/024-helm-v4-defaults/e2e-evidence.md`
- [X] T013 [US1] If T011 or T012 shows a result that differs from the Helm v3 behaviour described in `dev/knowledge/agent/operator.md` ("What the timer writes in `CreatingHelmRelease`"), change the operator rule in `backend/styrmin_backend/operator/reconciler.py` or `backend/styrmin_backend/operator/handlers/styrmin_deployment.py`, add a unit test with the recorded FluxCD state to `backend/tests/unit/test_styrmin_deployment_helmrelease_generation.py`, and re-run the failing shard. If no result differs, record "no operator change needed" in `specs/024-helm-v4-defaults/e2e-evidence.md` (FR-002)

**Checkpoint**: SC-001, SC-002 and SC-005 have local PASS evidence; the full suite runs in CI on the pull request.

---

## Phase 4: User Story 2 - Helm hook Jobs run with the deployment's scheduling settings (Priority: P1)

**Goal**: Helm hook Jobs of a deployment's chart receive the deployment's scheduling settings and Styrmin's labels, and an unlabelled hook renders with Styrmin's labels (FR-003, FR-005, FR-013, SC-004, SC-006).

**Independent Test**: `test_scheduling_end_to_end[api-chromium]` passes and checks the pre-upgrade hook Job and the unlabelled hook ConfigMap after the scheduling update.

- [X] T014 [P] [US2] In `driver/examples/simple-app/src/helm/values.yaml` add `preUpgradeHookJob: {enabled: false}` (block style) with a comment: only the `hook-job` E2E test driver turns it on, to check that Helm hooks receive Styrmin's post-render patches (#435)
- [X] T015 [US2] Create `driver/examples/simple-app/src/helm/templates/pre-upgrade-hook-job.yaml`, wrapped in `{{- if .Values.preUpgradeHookJob.enabled }}`, with two documents (plan D-002, contract C-005):
  - a `batch/v1` Job named `{{ include "simple-app.fullname" . }}-pre-upgrade-hook`; annotations `helm.sh/hook: pre-upgrade`, `helm.sh/hook-weight: "0"`, `helm.sh/hook-delete-policy: before-hook-creation`; `metadata.labels` = `simple-app.labels` plus `app.kubernetes.io/component: pre-upgrade-hook`; `spec.backoffLimit: 0`; pod template labels `app.kubernetes.io/component: pre-upgrade-hook` and `app.kubernetes.io/instance: {{ .Release.Name }}` only; `restartPolicy: Never`; one container `hook` with `image: {{ include "simple-app.image" . }}`, `imagePullPolicy: {{ .Values.image.pullPolicy }}`, the chart's `securityContext`, `command: ["python", "-c", "print('pre-upgrade hook')"]` and `resources.requests` `cpu: 10m`, `memory: 32Mi` (no limits); no `ttlSecondsAfterFinished`;
  - a `v1` ConfigMap named `{{ include "simple-app.fullname" . }}-pre-upgrade-hook` with the same three hook annotations except `helm.sh/hook-weight: "-1"`, no `labels` key at all, and `data: {hook: pre-upgrade}`
- [X] T016 [P] [US2] Create `backend/tests/unit/test_simple_app_hook_job.py`: render `driver/examples/simple-app/src/helm` with `helm template` (skip when `helm` is not on PATH, as `_render()` in `backend/tests/unit/test_helm_agent_crd_upgrade.py` does); with default values no document has a `helm.sh/hook` annotation; with `--set preUpgradeHookJob.enabled=true` exactly two do: the Job (annotations, `app.kubernetes.io/name` in `metadata.labels` and not in `spec.template.metadata.labels`, no `resources.limits`) and the ConfigMap (no `metadata.labels`) (contract C-005)
- [X] T017 [P] [US2] Create the test driver `backend/tests/e2e/fixtures/drivers/hook-job/`: `driver.styrmin.yml` copied from `driver/examples/simple-app/driver.styrmin.yml` with `metadata.name: hook-job`, the same `helm.main` block, components (`server` with container `simple-app`, `database` with container `postgresql` and the same backup block), `env_vars` and `services`, no `actions`, `info.description: "Test driver: the simple-app chart with its pre-upgrade Helm hooks turned on (#435)"`, and a header comment in the style of `backend/tests/e2e/fixtures/drivers/late-container/driver.styrmin.yml`; `values.j2.yml` copied from `driver/examples/simple-app/values.j2.yml` with `preUpgradeHookJob: {enabled: true}` added
- [X] T018 [US2] In `backend/tests/e2e/conftest.py` add `"hook-job": {"source": FIXTURES_DIR / "drivers" / "hook-job", "chart_name": "simple-app"}` to the `drivers` map, with a comment naming `test_pod_scheduling.py` and #435, next to the `failing-actions` and `late-container` entries. Also add `RUN git init --bare /git/hook-job.git` to `backend/tests/e2e/fixtures/git-server/Dockerfile`: the git server accepts pushes only to repositories that exist (found by the first T021 run, which stopped in `git_server` setup with "repository not exported: /hook-job.git")
- [X] T019 [US2] In `backend/tests/e2e/test_pod_scheduling.py` change the `scheduling_deployment` fixture: add the `git_server: dict[str, str]` fixture parameter, call `await driver.load_driver_version(git_url=git_server["hook-job"], ref="master")` before `create_deployment` (as `failing_actions_deployment` in `backend/tests/e2e/test_task_steps.py` does), create the deployment with `driver="hook-job"`, and update the docstring (the deployment runs the simple-app chart with its pre-upgrade Helm hooks on). Leave `scheduling_deployment_b` on `simple-app` (plan D-003, critique E2)
- [X] T020 [US2] In `test_scheduling_end_to_end` in `backend/tests/e2e/test_pod_scheduling.py`, after the existing assertions on the server Deployment, add (plan D-003, contract C-004):
  - list Jobs in the deployment's namespace with `kubeclient.BatchV1Api(vcluster["api"]).list_namespaced_job(label_selector="app.kubernetes.io/component=pre-upgrade-hook")`; assert exactly one;
  - assert its `spec.template.spec` has the `dedicated=batch:NoSchedule` toleration, the preferred node affinity, the pod affinity, the `kubernetes.io/hostname` topology spread constraint, `runtime_class_name == "kata-e2e"`, and `containers[0].resources` with `requests.memory == "192Mi"` and `limits.cpu == "500m"`;
  - assert its `metadata.labels` include every `styrmin/`-prefixed label of the server Deployment except pod-template-only ones (compare key sets read from the server Deployment's `metadata.labels`, not hard-coded values) and the component label `styrmin/component: server`;
  - poll until `status.succeeded == 1` (timeout 120 s), which shows the pod was scheduled with those settings and ran;
  - read the ConfigMap `<fullname>-pre-upgrade-hook` (find it by name prefix `styrmin-simple-app-pre-upgrade-hook` or by listing ConfigMaps with the `helm.sh/hook` annotation) and assert its `metadata.labels` include the same `styrmin/` keys (FR-013, SC-006);
  - extend the module and test docstrings: the vcluster has one node, so SC-004 is checked by the hook pod's scheduling fields and completion
- [X] T021 [US2] Run `uv run pytest backend/tests/unit/test_simple_app_hook_job.py -v`, then `shard_compute`, API variant: `sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_compute" -k "api-chromium" -v -s --pdb`. `test_scheduling_end_to_end[api-chromium]` and the other `shard_compute` tests must pass. Record the evidence in `specs/024-helm-v4-defaults/e2e-evidence.md`
- [X] T022 [US2] Run `shard_compute`, UI variant, in its own session (`-k "ui-chromium"`), because the module's fixtures changed and the shard holds dual-variant tests. Record the evidence in `specs/024-helm-v4-defaults/e2e-evidence.md`

**Checkpoint**: FR-003, FR-005, FR-013, SC-004 and SC-006 have local PASS evidence.

---

## Phase 5: User Story 3 - Upgrading the agent chart leaves existing deployments unchanged (Priority: P1)

**Goal**: an agent chart upgrade from a version with the gate creates no new Helm release revision, and existing releases keep client-side apply (FR-004, SC-003).

**Independent Test**: the manual check in [quickstart.md](quickstart.md) §4.

- [X] T023 [US3] Run the manual check of `specs/024-helm-v4-defaults/quickstart.md` §4 on a disposable cluster (for example `vcluster create helm-v4-check --driver docker`): install Styrmin with the agent chart from `develop` (gate on), create a `simple-app` deployment, record the release Secrets and pod start times, upgrade the chart to this branch, force a HelmRelease reconcile, record them again, then change the deployment and check the task result, `Running`, and that the workload's `metadata.managedFields` show client-side apply. Write the commands, outputs and the conclusion to `specs/024-helm-v4-defaults/agent-upgrade-check.md`, for the pull request description. Delete the cluster afterwards. If no cluster can be created, write the steps and "not run" with the reason, and flag it in the pull request (contract C-006)

**Checkpoint**: SC-003 is checked, or its gap is recorded for the reviewer.

---

## Phase 6: User Story 4 - Driver authors and operators read what changed (Priority: P1)

**Goal**: the documentation states the new behaviour in the same change (FR-006 to FR-011, Constitution §VII).

**Independent Test**: each page below states the item listed for it.

- [X] T024 [P] [US4] In `docs/docs/concepts-and-architecture/operator-and-crds.md` replace the paragraph that says helm-controller runs with the `UseHelm3Defaults` feature gate: helm-controller runs with Helm v4 defaults; deployments created after this change are installed with server-side apply, and deployments created before keep client-side apply; installs and upgrades wait with kstatus; Helm hooks of a driver's chart receive Styrmin's post-render patches. Add the rollback note: downgrading the agent chart turns the gate on again, and deployments created while it was off keep server-side apply (FR-006, critique P2)
- [X] T025 [P] [US4] In `docs/docs/drivers/creating-a-driver.md` (FR-007, plan D-005):
  - Step 1 "Analyse the Helm chart": add Helm hooks (`helm.sh/hook`) to what to look for, and list which post-render patches reach them: Styrmin's labels always, also on hooks without labels; scheduling settings on hook `Job`, `CronJob`, `Deployment`, `StatefulSet`, `DaemonSet` and `ReplicaSet` resources that carry a component's identifier label (all such resources when the driver declares no components); env var, image and container overrides and the component-container guard only on a hook `Deployment` or `StatefulSet` that matches a component. Add that a chart `Deployment` with `progressDeadlineSeconds` below 270 seconds makes FluxCD fail a change before Styrmin reads the pods' reason (research R-005);
  - "The component container": change "not chart `Job`s or `CronJob`s" to also name Helm hook Jobs;
  - Step 7 "Lifecycle actions": for a deployment installed with server-side apply, a field of a chart resource that an action changes returns to the chart's value at the next upgrade, because helm-controller forces conflicts (research R-002)
- [X] T026 [P] [US4] In `dev/knowledge/agent/operator.md` (FR-008): replace the "Helm v3 behaviour" bullet under "FluxCD controllers" with the Helm v4 defaults (server-side apply for new installs with forced conflicts and field manager `helm-controller`; `auto` keeps each release's apply method; kstatus wait that ends early on a `Failed` resource; `combined` post-rendering), citing research R-001 to R-005; replace "The readiness and rollback rules below were observed with Helm v3's behaviour" with the runs of T011, T012 and T021; update the last paragraph of "Rollback reported Ready" with the answer recorded in T011
- [X] T027 [P] [US4] In `CONTEXT.md` add a **Helm hook** entry next to **Hook** (definition from the spec's Key Entities: a chart resource annotated `helm.sh/hook` that Helm creates at a set point of an install, upgrade, rollback, uninstall or test; it receives Styrmin's post-render patches; not a Styrmin **hook**), and add "Helm hook" to the **Hook** entry's `_Avoid_` line (FR-009)
- [X] T028 [P] [US4] Create `dev/adr/0072-helm-v4-defaults-releases-keep-apply-method.md` (0071 is taken on the open branch `fac/ingress-class-post-render-tb7qv`) (MADR, in the format of `dev/adr/0069-container-command-args-by-post-render.md`; take the next free number if 0071 is used when the branch merges): context (#435, #434), decisions (drop the gate for all HelmReleases; keep `auto`, no move of existing releases; hooks receive post-render patches; no special handling of server-side apply conflicts because helm-controller forces them; the every-resource label patch becomes a strategic merge), consequences (turning the gate on again leaves releases installed in the meantime on server-side apply; the rollback path; the backup annotation patch limitation), alternatives (per-HelmRelease Helm v3 fields, excluding hooks with `annotationSelector`), and links to research R-001 to R-008 (FR-010)
- [X] T029 [P] [US4] Create the changelog fragment with `uv run towncrier create -c "<text>" 435.changed.md`: helm-controller runs with Helm v4 defaults; deployments created from this version are installed with server-side apply and existing ones keep client-side apply; installs and upgrades wait with kstatus; Helm hooks of a driver's chart receive Styrmin's labels and scheduling settings; a chart resource without labels no longer fails the render. Follow `dev/guidelines/changelog.md` (FR-011)
- [X] T030 [P] [US4] In `dev/knowledge/backend/e2e-testing.md` (the "test drivers" paragraph that describes `failing-actions` and `late-container`) add `hook-job`: the simple-app chart with its pre-upgrade Helm hook Job and unlabelled hook ConfigMap turned on, used by `test_pod_scheduling.py` (#435)

**Checkpoint**: FR-006 to FR-011 are met.

---

## Phase 7: Polish and Verification

- [X] T031 Run `uv run invoke format lint`, `uv run invoke test`, `uv run pytest backend/tests/integration -q` and the docs build (`cd docs && pnpm install && pnpm build`, in a Node 22 container if the host Node is older); fix failures
- [X] T032 Check that no reference to the gate remains outside the specs and the history: `grep -rn "UseHelm3Defaults" --include=*.py --include=*.yaml --include=*.yml --include=*.md . | grep -v "specs/\|CHANGELOG.md\|dev/adr/0072"` (ADR-072, see T028) returns only text that describes the old behaviour on purpose
- [X] T033 Walk through `specs/024-helm-v4-defaults/quickstart.md` §1 to §5 and confirm each expected result; note any that differ in `specs/024-helm-v4-defaults/e2e-evidence.md`
- [X] T034 Prepare the pull request notes: link `e2e-evidence.md` and `agent-upgrade-check.md`; state that the `api` cell of `shard_configuration` was run locally because CI excludes it; ask the maintainer to confirm that `Stalled` and the readiness timeout keep unit-test coverage only (spec Clarifications, critique P3)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: T002 → T003 → T005, T006; T002 → T004; T007 → T008; T009 is independent; T010 after T002 to T009. Blocks every story.
- **US1 (Phase 3)**: after Phase 2. T011 and T012 in either order (separate sessions); T013 after both.
- **US2 (Phase 4)**: after Phase 2. T014 → T015 → T016; T017 → T018 → T019 → T020 → T021 → T022. T021 needs T015 too.
- **US3 (Phase 5)**: after Phase 2 (the branch's chart is what gets installed).
- **US4 (Phase 6)**: T024, T025, T027 to T030 any time after Phase 2; T026 after T011, T012 and T021, because it cites their runs.
- **Polish (Phase 7)**: after all stories.

### User Story Dependencies

- US1, US2 and US3 need only Phase 2.
- US4 needs the E2E results of US1 and US2 for T026.

### Parallel Opportunities

- Phase 2: T004, T005, T006 and T009 in parallel after T002/T003.
- US2: T014 and T017 in parallel; T016 in parallel with T018 to T020.
- E2E sessions (T011, T012, T021, T022) each need a full vcluster; run them in sequence on one host unless it has the memory for two.
- US4: T024, T025 and T027 to T030 in parallel.

## Parallel Example: Phase 2 and User Story 2

```text
T004 unit tests of MetadataLabelsMergePatch
T006 kustomize integration test of the label patch
T009 HelmRelease spec unit test
T014 simple-app chart value
T017 hook-job test driver
```

## Implementation Strategy

1. Phase 1 and Phase 2: label patch fix and gate removal, with unit and integration tests. This is the whole production change.
2. US1: E2E evidence that task results do not change. This is the first state worth reviewing.
3. US2: the hook Job and the unlabelled hook in the scheduling E2E.
4. US3: the manual agent-upgrade check.
5. US4 and Polish: documentation, ADR, changelog, full verification. All four stories ship in one change; do not merge the gate removal without D-006 and the documentation.
