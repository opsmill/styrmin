---

description: "Tasks for 023: Ingress class set only after the chart renders"
---

# Tasks: Ingress Class Set Only After the Chart Renders

**Input**: Design documents from `specs/023-ingress-class-post-render/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required. The spec's Testing Approach names unit tests, one new integration test and local runs of two existing E2E tests; Constitution §V requires local PASS evidence for the E2E tests. Skipping a new E2E test was approved in the idea review of #471 (spec Testing Approach, plan Constitution Check).

**Organization**: The production code change is small and shared by all three stories, so it is in Phase 2. Each story phase then adds the driver, documentation and integration test work that proves that story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1, US2 or US3 (spec user stories)
- Paths are relative to the repository root

---

## Phase 1: Setup

**Purpose**: Record a green baseline before any change.

- [X] T001 Run `uv sync`, then `uv run pytest backend/tests/unit/agent/test_utility_resources.py backend/tests/unit/agent/test_render_value_template_env_vars.py backend/tests/integration/test_container_override_migration_parity.py -q` and note the result as the baseline (no file change). Confirm `helm` and `kubectl` are on `PATH` (`helm version`, `kubectl version --client`); without them the integration tests are skipped, and a skip does not count as a pass

---

## Phase 2: Foundational (blocks every story)

**Purpose**: Styrmin removes `spec.ingressClassName` after the chart renders in dedicated mode, and the template data keeps `ingress_class` in both modes (research D-001 to D-004, [contracts/post-render-patch.md](contracts/post-render-patch.md), [contracts/template-data.md](contracts/template-data.md)).

- [ ] T002 Add the dataclass `IngressClassNameRemovalPatch(Patch)` to `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py`, after `RuntimeClassPatch`. Fields: `api_version: str = "networking.k8s.io/v1"`, `kind: str = "Ingress"`, `name: str = "any"`, `_path: str = field(init=False, default="/spec/ingressClassName")`, `_operation: str = field(init=False, default="remove")`. `render_value()` builds `{"apiVersion": ..., "kind": ..., "metadata": {"name": ...}, "spec": {"ingressClassName": None}}` and returns `yaml.dump(doc, default_flow_style=False, sort_keys=False)`, so the field renders as `ingressClassName: null`. Docstring: one or two lines saying it is a strategic merge patch that deletes the field when present and does nothing when absent, because a JSON6902 `remove` fails on an absent field (research D-001), plus an `Example:` block with the rendered YAML like `RuntimeClassPatch`
- [ ] T003 [P] Add `TestIngressClassNameRemovalPatch` to `backend/tests/unit/agent/test_utility_resources.py`: `yaml.safe_load(IngressClassNameRemovalPatch().render_value())` equals `{"apiVersion": "networking.k8s.io/v1", "kind": "Ingress", "metadata": {"name": "any"}, "spec": {"ingressClassName": None}}`, and the raw string contains `ingressClassName: null`. Depends on T002
- [ ] T004 In `IngressUtility.build_app_post_rendering_patches` in `backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py`, in the `dedicated_ingress is not None` branch, append `TargetPatch(target=Target(kind="Ingress"), patch=IngressClassNameRemovalPatch())` to `patches` and keep setting the `kubernetes.io/ingress.class` annotation to `dedicated_ingress.implementation`. Leave the `elif context.instance.config.ingress_class` branch (the `SpecPatch` and the annotation) and the no-class case unchanged, so the shared-mode HelmRelease stays byte-identical (research D-002, D-003). Replace the comment "Derive ingress class name from the dedicated ingress implementation" with one line saying the dedicated controller matches on the annotation, so the class that the chart rendered is removed. Depends on T002
- [ ] T005 Update `TestDedicatedIngressPatching` in `backend/tests/unit/agent/test_utility_resources.py` (after T003, same file): replace `test_dedicated_ingress_does_not_set_ingress_class_name` with `test_dedicated_ingress_removes_ingress_class_name`, which asserts exactly one patch whose `patch` is an `IngressClassNameRemovalPatch` and whose `target.render_value()` is `{"kind": "Ingress"}`, and no patch with a `specs` attribute; extend `test_fallback_to_cluster_ingress_class` to assert no `IngressClassNameRemovalPatch` and the annotation `kubernetes.io/ingress.class: cluster-traefik`; extend `test_no_ingress_class_patch_when_neither_set` to assert no `IngressClassNameRemovalPatch` and no `kubernetes.io/ingress.class` key in the annotation patch (FR-006). Update the class docstring. Depends on T004
- [ ] T006 In `ApplicationHelmReleaseBuilder.render_value_template` in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py`, delete the block that pops `ingress_class` from the `instance`, `cluster`, `environment` and `deployment` config sections when `dedicated_ingress` is set, with its comment (research D-004). In the docstring's "Rendering contract surfaced to driver templates", add a short paragraph: `ingress_class` is template data in both modes; driver templates do not set the Ingress class, because Styrmin sets it, or removes it with a dedicated ingress controller, after the chart renders (see `IngressUtility.build_app_post_rendering_patches`)
- [ ] T007 [P] Create `backend/tests/unit/agent/test_render_value_template_ingress_class.py`, modelled on `backend/tests/unit/agent/test_render_value_template_env_vars.py` (call `ApplicationHelmReleaseBuilder.render_value_template.fn(values_template=..., context=...)`). Cases: with `dedicated_ingress=DedicatedIngressConfig()`, a template that renders `instance.config.ingress_class`, `cluster.config.ingress_class`, `environment.config.ingress_class` and `deployment.config.ingress_class` into four keys gets the four configured values (use four different values so a swapped section fails); the same template without `dedicated_ingress` gets the same values; with `ingress_class=None` at every level the keys render empty (FR-003). Depends on T006

**Checkpoint**: `uv run pytest backend/tests/unit/agent/test_utility_resources.py backend/tests/unit/agent/test_render_value_template_ingress_class.py -q` passes.

---

## Phase 3: User Story 1 - A driver author removes the class line from the values template (Priority: P1) 🎯 MVP

**Goal**: The example drivers and the driver documentation set no Ingress class, and the application's Ingress gets the same class as today in both modes.

**Independent Test**: The integration test renders the migrated `simple-app` template in both modes and checks the Ingress after `kubectl kustomize`; the two existing E2E tests deploy `simple-app` without its class line.

- [ ] T008 [P] [US1] Remove the line `className: "{{ instance.config.ingress_class }}"` under `ingress:` in `driver/examples/simple-app/values.j2.yml`. Do not change `spec.version` in `driver/examples/simple-app/driver.styrmin.yml` (research D-005)
- [ ] T009 [P] [US1] Remove the same line under `ingress:` in `driver/examples/semaphore/values.j2.yml`. Do not change `spec.version` in `driver/examples/semaphore/driver.styrmin.yml`
- [ ] T010 [P] [US1] Remove the same line under `ingress:` in `driver/examples/slurpit/values.j2.yml` (keep the `storage_class` `className` lines). Do not change `spec.version` in `driver/examples/slurpit/driver.styrmin.yml`
- [ ] T011 [US1] Create `backend/tests/integration/test_ingress_class_post_render.py`, with helpers adapted from `backend/tests/integration/test_container_override_migration_parity.py` (`_helm_template` on `driver/examples/simple-app/src/helm`, `_kustomize` with the patches rendered as Flux passes them, a `skipif` when `helm` or `kubectl` is missing). Add a context builder that takes `dedicated: bool` and `ingress_class: str | None` and sets them on the cluster config and on `ResolvedConfig` (with `fqdn_suffix`, which the ingress utility requires), and a helper that returns every `kind: Ingress` document. Patches come from `IngressUtility().build_app_post_rendering_patches(context, release_reference)`. Module docstring: two or three lines naming spec 023, FR-001 to FR-006 and SC-003. First test, `test_migrated_simple_app_template_gets_the_class_of_its_mode`, parametrized over dedicated and shared (`ingress_class: nginx`): render `driver/examples/simple-app/values.j2.yml` through `ApplicationHelmReleaseBuilder.render_value_template.fn`, run `helm template` and `kubectl kustomize`, and assert every Ingress has no `spec.ingressClassName` and `kubernetes.io/ingress.class: traefik` (dedicated), or `spec.ingressClassName: nginx` and `kubernetes.io/ingress.class: nginx` (shared) (FR-004, SC-002). Depends on T004, T006, T008
- [ ] T012 [P] [US1] In `docs/docs/drivers/creating-a-driver.md` (Step 5 example), remove `className: "{{ instance.config.ingress_class }}"` from the `values.j2.yml` example and add a "Patterns to know" bullet: **No Ingress class.** Styrmin sets the class of every Ingress after the chart renders, or removes it when the environment has a dedicated ingress controller, so the template sets no class; link to `../concepts-and-architecture/ingress-and-networking.md#dedicated-ingress-controller-or-shared-ingress-class` (FR-008, SC-001)
- [ ] T013 [P] [US1] In `docs/docs/drivers/context.md`, remove `className: "{{ instance.config.ingress_class }}"` from the minimal `values.j2.yml` example and add a bullet after "No `command` or `args` wiring": **No Ingress class.**, with the same text and link as T012. Keep the action example that reads `context.instance.config.ingress_class` (FR-008, SC-001)
- [ ] T014 [US1] Run the existing E2E `test_cluster_update_redeploys_and_moves_dedicated_ingress` locally (it is `api_only`, `shard_compute`): `export STYRMIN_IMAGE_VER=e2e-471-<suffix>`, `docker compose build server`, then `sleep infinity | uv run pytest "backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress" -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-471-cluster-update.log`, until it passes. Stop the paused session by PID, not with `pkill -f`. Record the evidence (pytest node ID, exact command, ISO 8601 time of the passing run, vcluster fixture ID and kubeconfig path, verbatim `PASSED` line) in `specs/023-ingress-class-post-render/e2e-evidence.md` (Constitution §V). Depends on T004, T006, T008
- [ ] T015 [US1] Run the existing E2E `test_traffic_routes_through_dedicated_ingress` locally, in its own pytest session after T014: `sleep infinity | uv run pytest "backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress" -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-471-traffic.log`, until it passes, with the same image and stop procedure. Add its evidence to `specs/023-ingress-class-post-render/e2e-evidence.md`. Depends on T004, T006, T008

**Checkpoint**: The migrated `simple-app` gets the same Ingress class in both modes, on `kubectl kustomize` and on a real cluster.

---

## Phase 4: User Story 2 - A chart that sets its own class works with a dedicated ingress controller (Priority: P2)

**Goal**: Whatever class the chart renders, the Ingress has no `spec.ingressClassName` and the annotation `traefik` in dedicated mode, and the resolved class in shared mode.

**Independent Test**: The integration test renders the `simple-app` chart with `ingress.className` set to `traefik`, then `nginx`, applies the patches of each mode, and checks every Ingress.

- [ ] T016 [US2] In `backend/tests/integration/test_ingress_class_post_render.py`, add `test_chart_class_is_replaced_or_removed`, parametrized over chart `ingress.className` in `""`, `traefik`, `nginx` and over two modes: dedicated, and shared with `ingress_class: traefik`. Build the chart values by rendering the migrated `simple-app` template and setting `values["ingress"]["className"]`. Before `kubectl kustomize`, append to the `helm template` output a second Ingress document, as a subchart would render it, named `subchart-ui`, with `spec.ingressClassName: nginx` and no `metadata.annotations`. Assert for every Ingress, both included: dedicated → no `spec.ingressClassName` and `kubernetes.io/ingress.class: traefik`; shared → `spec.ingressClassName: traefik` and `kubernetes.io/ingress.class: traefik` (FR-001, FR-002, SC-003, spec assumption A-002). The `""` dedicated case proves the render does not fail when the field is absent (spec edge case). Depends on T011
- [ ] T017 [US2] In the same file, add `test_no_class_resolved_keeps_the_chart_class`: shared mode with `ingress_class=None`, chart `ingress.className: nginx`; assert `spec.ingressClassName: nginx` and no `kubernetes.io/ingress.class` annotation on the Ingress (FR-006). Depends on T016

**Checkpoint**: A chart class of `nginx` or `traefik` gives the Ingress shape that the dedicated ingress controller serves.

---

## Phase 5: User Story 3 - A released driver version that still sets the class keeps deploying (Priority: P3)

**Goal**: A template that still sets `className: "{{ instance.config.ingress_class }}"` gets the same Ingress as a template without the line, in both modes.

**Independent Test**: The integration test renders an old-style template through the production renderer in both modes and compares its Ingress with the one from the migrated template.

- [ ] T018 [US3] In `backend/tests/integration/test_ingress_class_post_render.py`, add `test_template_that_still_sets_the_class_gives_the_same_ingress`, parametrized over dedicated and shared (`ingress_class: nginx`). Build the old-style template as the migrated `driver/examples/simple-app/values.j2.yml` text with the line `  className: "{{ instance.config.ingress_class }}"` inserted after `  enabled: true` under `ingress:` (assert the insertion point exists). Render both templates through `ApplicationHelmReleaseBuilder.render_value_template.fn`; assert the old-style values have `ingress.className` equal to the resolved class in both modes, which shows that dedicated mode no longer hides it (FR-003). Run both through `helm template` and `kubectl kustomize` with the mode's patches and assert the Ingress documents are equal (FR-005, SC-004). Depends on T011
- [ ] T019 [US3] Leave `className: "{{ instance.config.ingress_class }}"` in `backend/tests/e2e/fixtures/drivers/late-container/values.j2.yml` and `backend/tests/e2e/fixtures/drivers/failing-actions/values.j2.yml` unchanged: the main E2E cluster has a dedicated ingress controller, so the CI tests that deploy them (`shard_apply`, `shard_task_steps`) render an old-style template in dedicated mode (spec Testing Approach, research D-006). Check with `git diff --stat backend/tests/e2e/fixtures/drivers/` that neither file changed (no file change)

**Checkpoint**: Old-style and migrated templates give equal Ingresses in both modes. Turning dedicated ingress on and off (User Story 3, scenario 3) is covered by T014.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, decision record, changelog and final verification (Constitution §VII, research D-007).

- [ ] T020 [P] In `docs/docs/concepts-and-architecture/ingress-and-networking.md`, section "Dedicated ingress controller or shared ingress class", state the class each mode gives an application's Ingress: with a dedicated ingress controller, Styrmin removes `spec.ingressClassName` from every Ingress of the application after the chart renders and sets the `kubernetes.io/ingress.class` annotation to `traefik`; without one, Styrmin sets both to the resolved `ingress_class`, whatever class the chart sets; with no `ingress_class` resolved (only when the cluster config sets `ingress_class: null`), the chart's class stays (FR-008)
- [ ] T021 [P] In `CONTEXT.md`, entry **Dedicated ingress controller**, add: "While it is on, Styrmin removes `spec.ingressClassName` from every Ingress of the environment's applications after the chart renders and sets the `kubernetes.io/ingress.class` annotation to the controller implementation; while it is off, Styrmin sets both to the resolved `ingress_class`. Driver templates do not set the class."
- [ ] T022 [P] In `dev/knowledge/backend/data-models.md`, section `DedicatedIngressConfig`, replace "removes `ingress_class` from the values-template context" with: the agent removes `spec.ingressClassName` from every application Ingress after the chart renders with a strategic merge patch (`IngressClassNameRemovalPatch`); `ingress_class` stays in the values-template data in both modes. Add an extraction comment `<!-- Extracted from specs/023-ingress-class-post-render on <date> -->` like the neighbouring sections
- [ ] T023 [P] Create `dev/adr/0070-ingress-class-set-by-post-render.md` in the format of `dev/adr/0069-container-command-args-by-post-render.md` (Status Accepted, Date, Source `specs/023-ingress-class-post-render/` and issue #471, Related ADR-057, ADR-069, ADR-066). Decisions: (1) in dedicated mode Styrmin removes `spec.ingressClassName` with a strategic merge patch that sets it to `null`, instead of giving the dedicated ingress controller its own IngressClass (#464), with the JSON6902 `remove` failure as the reason for the patch type (research D-001); (2) `ingress_class` stays in the template data in both modes (D-004); (3) with no class resolved, Styrmin leaves the chart's class unchanged (D-003). Consequences: driver templates set no class; a chart's own class no longer breaks dedicated mode; templates that read `ingress_class` get a value in dedicated mode (spec A-001); the design depends on the `kubernetes.io/ingress.class` annotation, because the `DefaultIngressClass` admission plugin skips annotated Ingresses (D-001). Add the ADR to the ADR list in `dev/README.md` after ADR-069
- [ ] T024 [P] Create the changelog fragment with `uv run towncrier create -c "<text>" 471.changed.md` (creates `changelog/471.changed.md`). The text says: driver templates no longer need to set the Ingress class, because Styrmin sets it, or removes it with a dedicated ingress controller, after the chart renders; with a dedicated ingress controller, a class that the chart sets on its own is now removed, so such a chart deploys there; templates now read the resolved `ingress_class` with a dedicated ingress controller too, where it was empty before (research D-007). Follow `dev/guidelines/changelog.md`
- [ ] T025 Run the SC-001 checks of `specs/023-ingress-class-post-render/quickstart.md` §3 (`grep` over the three example templates and the two driver documentation pages); the first command prints nothing and the second prints no `className:` line (no file change)
- [ ] T026 Run `uv run invoke format lint`, then `uv run pytest backend/tests/integration/test_ingress_class_post_render.py -v` (no test `SKIPPED`), then `uv run invoke test`; fix failures
- [ ] T027 If any file under `backend/styrmin_backend/` or `driver/examples/` changed after T014 and T015 passed, re-run both E2E tests as in T014 and T015 and update `specs/023-ingress-class-post-render/e2e-evidence.md` with the final passing runs; otherwise add a line to that file saying no production or driver file changed after the recorded runs (Constitution §V)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependency.
- **Foundational (Phase 2)**: T002 → T003, T004; T004 → T005 (T005 after T003, same file); T006 → T007. T002–T005 and T006–T007 are independent chains. Blocks every story.
- **US1 (Phase 3)**: after Phase 2. T008 → T011; T008 → T014 → T015 (one E2E session at a time). T009, T010, T012, T013 have no dependency inside the phase.
- **US2 (Phase 4)**: after T011 (it reuses the integration test helpers). T016 → T017.
- **US3 (Phase 5)**: after T011. T018 can run in parallel with Phase 4 only if the two tasks do not edit `test_ingress_class_post_render.py` at the same time; run them in sequence by default.
- **Polish (Phase 6)**: T020–T024 after Phase 2 (they describe the final behavior). T025 after T008–T010 and T012–T013. T026 after every code and test task. T027 last.

### User Story Dependencies

- US1 needs only the foundation.
- US2 and US3 need the foundation and the integration test module from US1 (T011). They add no production code.

### Parallel Opportunities

- Phase 2: T003 and T007 in parallel after T002 and T006; the T002 chain and the T006 chain in parallel.
- US1: T008, T009, T010, T012, T013 in parallel.
- Polish: T020–T024 in parallel.
- The E2E runs (T014, T015) take a long time; run them while doing US2, US3 and T020–T024, which do not touch production code or the `simple-app` driver.

## Parallel Example: User Story 1

```text
T008 drop the class line from simple-app
T009 drop the class line from semaphore
T010 drop the class line from slurpit
T012 creating-a-driver.md
T013 context.md
```

## Implementation Strategy

1. Phase 1 and Phase 2: the removal patch, the ingress utility change and the renderer change, with unit tests. All production code is done here.
2. US1: example drivers and driver documentation without the class line, the integration test module, and both E2E tests green with recorded evidence. This is the first state worth reviewing.
3. US2 and US3: integration test cases for a chart that sets its own class and for a template that still sets the class.
4. Polish: documentation, ADR-070, changelog fragment, full verification.
