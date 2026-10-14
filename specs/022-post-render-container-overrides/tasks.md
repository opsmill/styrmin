---

description: "Tasks for 022: container command and args overrides applied by post-render"
---

# Tasks: Container `command` and `args` Overrides Applied by Post-Render

**Input**: Design documents from `specs/022-post-render-container-overrides/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required. The spec names a verification for every FR and SC (spec "Verification Approach"), and Constitution §V requires an E2E with local PASS evidence and a GraphQL propagation test.

**Organization**: One phase per user story. All three stories ship in one release (spec Context); the phases give the build order and a checkpoint after each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1, US2 or US3 (spec user stories)
- Paths are relative to the repository root

---

## Phase 1: Setup

**Purpose**: Record a green baseline and keep a copy of the pre-migration templates before any driver changes.

- [X] T001 Run `uv sync`, `cd frontend && pnpm install`, then `uv run pytest backend/tests/unit/services/component_container backend/tests/unit/agent/test_container_env_patch.py backend/tests/integration/test_component_container_kustomize.py -q` and note the result as the baseline (no file change)
- [X] T002 Copy the current (pre-migration) `driver/examples/simple-app/values.j2.yml`, `driver/examples/infrahub/values.j2.yml` and `driver/examples/infrahub-enterprise/values.j2.yml` unchanged into `backend/tests/integration/fixtures/legacy_drivers/<driver-name>/values.j2.yml`, with a `README.md` in `backend/tests/integration/fixtures/legacy_drivers/` that says these are the templates that called `component_command`/`component_args`, kept for the SC-005 parity test (research D-011). This MUST happen before T012–T014 change the drivers

---

## Phase 2: Foundational (blocks every story)

**Purpose**: The merge patch carries `command`/`args`, one rule decides what applies, and the patch builder builds patches when `command` or `args` is the only override (research D-001 to D-003).

- [X] T003 Rename `ContainerEnvPatch` to `ContainerMergePatch` in `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py` and add `command: list[str] | None = None` and `args: list[str] | None = None`. `render_value()` writes `command` and `args` into the container dict only when not `None`, keeps `env` behaviour unchanged, and builds the document with `yaml.dump` only (never string formatting). Update the class docstring and doctest, and the `ComponentContainerPatch` docstring reference. Update every import of the old name (`backend/styrmin_backend/services/component_container/patch_builder.py`, `backend/tests/integration/test_component_container_kustomize.py`, `backend/tests/unit/services/component_container/test_patch_builder.py`)
- [X] T004 [P] Rename `backend/tests/unit/agent/test_container_env_patch.py` to `backend/tests/unit/agent/test_container_merge_patch.py`, update it to the new class name, and add tests: `command` only, `args` only, both with env, neither (container name only, unchanged output); the strings `yes`, `8000`, `""`, `null`, `$(HOME)` round-trip through `yaml.safe_load` as the same strings; a value `"x\n- op: remove\n  path: /spec"` stays one list element after `yaml.safe_load` (contracts/post-render-patch.md)
- [X] T005 In `backend/styrmin_backend/services/component_container/overrides.py` add `override_applies(container: str | None, is_orphaned: bool) -> bool`, the frozen dataclass `ApplicableOverrides` (`env`, `image`, `command`, `args`, property `is_empty`) and `applicable_overrides(name: str, component: ComponentContext, version: str) -> ApplicableOverrides`; every override goes through `override_applies`; the image keeps `validate_reference(..., version=version, component_name=name)`. Delete `applicable_env` and `applicable_image` and rewrite the module docstring (data-model.md "Applicable overrides")
- [X] T006 [P] Create `backend/tests/unit/services/component_container/test_overrides.py`: `override_applies` truth table; `applicable_overrides` returns each of env, image, `command`, `args` when the component has a container and the override is not orphaned; returns empty for no container, for orphaned env/image/container overrides; `is_empty` true only when all four are empty; image token substitution and the `InvalidImageReferenceError` path still behave as before
- [X] T007 Change `build_component_container_patches` in `backend/styrmin_backend/services/component_container/patch_builder.py` to call `applicable_overrides`, skip the component only when `is_empty`, pass `command`/`args` to `ContainerMergePatch`, and log `command_set` and `args_set` booleans (never the values). Update the module docstring
- [X] T008 Switch `backend/styrmin_backend/actions/primitives.py` (`get_component_images`, `execute_commands`) from `applicable_env`/`applicable_image` to `applicable_overrides(...).env` / `.image`, keeping behaviour; update `backend/tests/unit/agent/test_action_target_overrides.py` if it patches or imports the old helpers, and run it
- [X] T009 Extend `backend/tests/unit/services/component_container/test_patch_builder.py`: a component with only `args` (and only `command`) gets one merge patch and one guard per kind, with the list in the merge body; a component with stored `command`/`args` that is orphaned or has no container gets no patch; a cleared override (both `None`, no env, no image) gets no patch; env + image + `command` + `args` together produce one merge patch with all three fields; existing env/image cases still pass

**Checkpoint**: `uv run pytest backend/tests/unit/services/component_container backend/tests/unit/agent -q` passes.

---

## Phase 3: User Story 1 — Set, change and clear a container override without template code (Priority: P1)

**Goal**: A `command`/`args` override on a component with a component container reaches the pod through post-render, for every in-repo driver, with no template code; a clear brings back the chart's values.

**Independent Test**: Deploy migrated `simple-app`, set/change/clear `command` and `args` on `server`, read the pod's container spec after each step (quickstart §6).

### Tests for User Story 1

- [ ] T010 [P] [US1] Add a `TestCommandArgs` class to `backend/tests/integration/test_component_container_kustomize.py` that renders the builder's real patches with `kubectl kustomize` over a fixture whose component container has a chart `command` and `args`, plus a sidecar and an init container: `args`-only replaces the whole `args` list and keeps the chart `command`; `command` + `args` replace both; sidecar and init container are byte-for-byte unchanged; the component container is at `containers[0]`; works for `Deployment` and `StatefulSet` (FR-002, spec edge case 1)
- [ ] T011 [P] [US1] Create `backend/tests/unit/services/component_container/test_example_driver_overrides.py`: for each `driver/examples/*/driver.styrmin.yml`, build a `GlobalContext` whose components come from the file, set `command` and `args` on every component that declares `container`, run `build_component_container_patches`, and assert each such component gets a `ContainerMergePatch` naming its container with both lists. Include an explicit assertion for `command` on infrahub `server` (`infrahub-server`) and `task-worker` (`infrahub-task-worker`) (SC-001, critique E6)

### Implementation for User Story 1

- [ ] T012 [P] [US1] Migrate `driver/examples/simple-app`: in `values.j2.yml` delete the `component_command`/`component_args` lines and their comment (lines 7–10); in `driver.styrmin.yml` delete the `container_overrides` block and its comment, and change `spec.version` from `"2"` to `"3"` (contracts/driver-format.md)
- [ ] T013 [P] [US1] Migrate `driver/examples/infrahub`: in `values.j2.yml` delete the `{%- if components | component_args("server") %} ... args: null {%- endif %}` block for `server`, the same block for `task-worker`, and the `command`/`args` blocks for `task-manager`, keeping the surrounding YAML valid; in `driver.styrmin.yml` delete the `container_overrides` block and its comments, and change `spec.version` from `"3"` to `"4"`
- [ ] T014 [P] [US1] Migrate `driver/examples/infrahub-enterprise` the same way as T013, and change `spec.version` from `"2"` to `"3"`
- [ ] T015 [US1] Render each migrated `values.j2.yml` with `ApplicationHelmReleaseBuilder.render_value_template` in a quick check (or an existing driver render test) to confirm valid YAML, then search `backend/tests`, `tasks/`, `helm/` and `docs/` for pins of the old example driver versions (`simple-app` "2", `infrahub` "3", `infrahub-enterprise` "2") and update any that must follow the migrated versions (research D-009)
- [ ] T016 [US1] Extend `backend/tests/e2e/test_deployment_container_overrides.py` (shard `shard_configuration`, keep `api_only` markers, add no test node):
  - rewrite the module docstring for the post-render path (no filters, no `container_overrides` block);
  - in the `container_overrides_deployment` fixture, after the deployment runs, read the `server` Deployment's `simple-app` container and store its `command` and `args` as the baseline;
  - in `test_us1_override_args_on_server` keep the exact-`args` assertion on the pod template;
  - in `test_us2_command_independent_of_args` add a step that changes `command` and asserts the new value on the pod template after the reconcile;
  - in `test_us3_clear_override_falls_back_to_chart_default`, after the clear, wait until the container's `command` and `args` equal the baseline (FR-003, SC-003) and keep the read-surface assertion; update its docstring;
  - delete `test_us6_driver_declares_overridable_component` and its `load_query("get_driver_container_override_docs")` use
- [ ] T017 [US1] Run the E2E with `sleep infinity | uv run pytest backend/tests/e2e/test_deployment_container_overrides.py -k api-chromium -v -s --pdb` until it passes. If the clear does not roll the workload, follow the operator log while paused and fix the change detection in the same change (research D-012). Record the evidence (node IDs, command, ISO 8601 timestamp, vcluster id and kubeconfig path, verbatim `PASSED` lines) in `specs/022-post-render-container-overrides/e2e-evidence.md`

**Checkpoint**: US1 works on `simple-app` end to end; infrahub components produce the right patches.

---

## Phase 4: User Story 2 — Move driver versions off the retired filters (Priority: P2)

**Goal**: Old templates fail with an error that names the filter and the guide; `spec.container_overrides` is gone from the file format, the database and the API; stored overrides give the same pod after the move.

**Independent Test**: Render a template that calls `component_args`; load a driver file with `spec.container_overrides`; run the parity test (quickstart §1, §3).

### Tests for User Story 2

- [ ] T018 [P] [US2] Rewrite `backend/tests/unit/agent/test_render_value_template_container_overrides.py` as retired-filter tests, following `TestRetiredComponentEnvVarsFilter` in `backend/tests/unit/agent/test_render_value_template_env_vars.py`: each of `component_command` and `component_args` raises `RetiredTemplateFilterError` with `error_code == "RETIRED_TEMPLATE_FILTER"`, metadata `{"filter": <name>, "migration_guide": "https://styrmin.pages.dev/docs/drivers/migrating-container-overrides"}` and a message that contains the filter name and the URL; it raises with an override set, with no override and inside `{% if %}`; both filters stay registered in `get_jinja_environment()`; the operator pipeline records the message and applies no HelmRelease; the `component_env_vars` message and URL are unchanged (FR-005)
- [ ] T019 [P] [US2] Replace `backend/tests/unit/services/driver/test_container_override_doc_validator.py` with `backend/tests/unit/services/driver/test_container_overrides_block_rejected.py`: a driver file whose `spec` contains `container_overrides` fails to load with the same exception type and `extra_forbidden` detail as a file with another unknown `spec` key (FR-006)
- [ ] T020 [P] [US2] Create `backend/tests/unit/db/test_drop_container_overrides_migration.py` following `backend/tests/unit/db/test_driver_info_migration.py`: upgrade to the new revision removes `applicationdriverversion.container_overrides` and keeps existing rows; downgrade adds the column back nullable and empty (FR-010)
- [ ] T021 [P] [US2] Create `backend/tests/unit/test_drivers_have_no_override_wiring.py`: no file under `driver/` contains `component_command`, `component_args` or `container_overrides` (SC-002)
- [ ] T022 [P] [US2] Create `backend/tests/integration/test_container_override_migration_parity.py` (SC-005, research D-011). Keep a copy of the old `component_command`/`component_args` filter functions in the test module. For each driver in `backend/tests/integration/fixtures/legacy_drivers/` and a stored config with `command`/`args` on the components the old template wired: render the legacy template with the old filters, render the migrated driver's template with `get_jinja_environment()`, build the post-render patches, and assert the component container's `command`/`args` are equal. For `simple-app` compare the full container after `helm template driver/examples/simple-app/src/helm` + `kubectl kustomize`; for `infrahub` and `infrahub-enterprise` compare the list the old template sent to the chart with the list in the merge patch (A-002). Skip with a clear reason when `helm` or `kubectl` is missing

### Implementation for User Story 2

- [ ] T023 [US2] In `backend/styrmin_backend/services/exceptions.py` add `CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL = "https://styrmin.pages.dev/docs/drivers/migrating-container-overrides"` and make `RetiredTemplateFilterError` build its message from `filter_name`: the existing env var text for `component_env_vars`, and for `component_command`/`component_args` the text in contracts/errors.md; `migration_guide` defaults per filter
- [ ] T024 [US2] In `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` replace `component_command` and `component_args` with stubs that raise `RetiredTemplateFilterError(filter_name=..., migration_guide=CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL)`, delete `_resolved_container_override`, keep both names registered in `get_jinja_environment()`
- [ ] T025 [US2] Remove `spec.container_overrides`: delete the field and `validate_container_override_doc_components` from `Specification` in `backend/styrmin_backend/services/driver/models/resources/driver.py`; delete `backend/styrmin_backend/services/driver/models/resources/container_overrides.py`; delete `validate_driver_container_override_docs` from `backend/styrmin_backend/services/driver/validators.py` and its call in `backend/styrmin_backend/services/driver/loaders.py`; delete `DriverContainerOverrideDocComponentMismatchError` from `backend/styrmin_backend/services/container_overrides/exceptions.py` (and any export)
- [ ] T026 [US2] Stop persisting the block: delete `container_overrides_payload` and the `container_overrides=` argument in `backend/styrmin_backend/services/applications.py`; delete the `container_overrides` field and its comment from `ApplicationDriverVersion` in `backend/styrmin_backend/db/models.py`
- [ ] T027 [US2] Create `backend/styrmin_backend/db/migrations/versions/<rev>_drop_driver_version_container_overrides.py` with `down_revision = "9548830f81cd"`: `upgrade()` runs `op.drop_column("applicationdriverversion", "container_overrides")`; `downgrade()` runs `op.add_column("applicationdriverversion", sa.Column("container_overrides", sa.JSON(), nullable=True))` (data-model.md). Confirm `backend/tests/unit/db/test_migration_heads.py` passes
- [ ] T028 [US2] Remove `ApplicationDriverVersion.container_overrides` and the `DriverContainerOverrideDoc` type from `backend/styrmin_backend/api/definitions/application_driver/model.py`; delete `python_sdk/src/styrmin_sdk/graphql/get_driver_container_override_docs.graphql` and `backend/tests/functional/graphql/operations/get_driver_container_override_docs.graphql`; delete `test_driver_container_override_docs_projected` and `test_driver_container_overrides_empty_when_unset` from `backend/tests/functional/graphql/test_container_overrides_propagation.py`; then run `uv run styrmin export graphql-schema schema.graphql` and `uv run invoke generate` and `uv run invoke validate-graphql` (contracts/graphql.md)

**Checkpoint**: `uv run pytest backend/tests/unit backend/tests/integration/test_container_override_migration_parity.py -q` passes; a template calling either filter fails with the new message.

---

## Phase 5: User Story 3 — Reject and report overrides that cannot reach the pod (Priority: P3)

**Goal**: `command`/`args` writes on a component without a component container are rejected; stored values report `isApplicable: false` and are read-only and removable in the editor; a wrong container name fails the reconcile with only `args` set.

**Independent Test**: quickstart §1 (write check), §2 (wrong name), §4 (propagation), §5 (frontend).

### Tests for User Story 3

- [ ] T029 [P] [US3] Add to `TestComponentContainerNotDeclaredError` in `backend/tests/unit/services/env_vars/test_validator.py`: `override="command"` and `override="args"` give metadata `override` with that value and a message that names the field and the component
- [ ] T030 [P] [US3] Add a wrong-container-name case to `TestCommandArgs` in `backend/tests/integration/test_component_container_kustomize.py`: with only `args` applicable and a declared container missing from the workload, `kubectl kustomize` fails and `parse_guard_failure` on the error returns `(component, container)` (FR-004)
- [ ] T031 [P] [US3] Extend the `COMPONENT_CONTAINER_NOT_DECLARED` matrix in `backend/tests/functional/graphql/test_update_deployment_input_errors.py` with `command` and `args`: adding or changing either on a containerless component through `updateDeployment` is rejected with `override` metadata and starts no task; `deploy` with a first value is rejected; removing the value (`null` or omitted) and sending the same list again are accepted (FR-007)
- [ ] T032 [P] [US3] Extend `backend/tests/functional/graphql/test_container_overrides_propagation.py` and `python_sdk`/test operations as needed: `isApplicable` is `true` for an override on a component with a component container, `false` with `isOrphaned: false` for a component without one (stored before a driver version change), and `false` with `isOrphaned: true` for an orphaned block (FR-007, contracts/graphql.md)
- [ ] T033 [P] [US3] Add tests to `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.test.tsx`: a component without `container` shows no Command or Args editor; a stored `command`/`args` there shows read-only rows with a "not applied" badge and a Remove button that clears the value on submit; a component with `container` keeps the editors (FR-008)

### Implementation for User Story 3

- [ ] T034 [US3] In `backend/styrmin_backend/services/env_vars/exceptions.py` widen `ComponentContainerNotDeclaredError.override` to `Literal["env_vars", "image", "command", "args"]` and add the message for `command`/`args` from contracts/errors.md
- [ ] T035 [US3] In `backend/styrmin_backend/services/deployment.py` widen `ComponentContainerSlot` to the four slots, make the default `slots` of `_validate_component_container_targets` include `command` and `args`, and make `_slot_adds_or_changes` treat `command`/`args` like `image` (`submitted is not None and submitted != stored`); update the docstrings (research D-005)
- [ ] T036 [US3] In `backend/styrmin_backend/api/definitions/deployment/model.py` add `is_applicable: bool` to `ComponentContainerOverrides` with the description from contracts/graphql.md, update the type and resolver descriptions for the post-render path, compute it in `component_container_overrides` from `_component_containers(deployment)` and `override_applies`, and switch the `is_applicable` computations of `component_env_vars` and `component_image_overrides` to `override_applies`. Update the `command`/`args` descriptions in `backend/styrmin_backend/api/definitions/deployment/inputs.py` to name `COMPONENT_CONTAINER_NOT_DECLARED`
- [ ] T037 [US3] Add `isApplicable` to `python_sdk/src/styrmin_sdk/graphql/get_deployment_component_container_overrides_full.graphql`, then run `uv run styrmin export graphql-schema schema.graphql`, `uv run invoke generate` and `uv run invoke validate-graphql`
- [ ] T038 [US3] In `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx` render the Command and Args editors only when `hasContainer`; when it is false and a value is stored, render a new `ContainerlessContainerOverride` block (style of `ContainerlessImage`: read-only `command`/`args`, "not applied" badge, Remove sets the field to `[]`, which the submit boundary omits); update the component docstring (research D-010)

**Checkpoint**: functional, unit and frontend suites pass; `schema.graphql` and generated types are current.

---

## Phase 6: Polish — Documentation, Changelog and Verification

**Purpose**: Constitution §VII documentation in the same change, then full verification.

- [ ] T039 [P] Create `docs/docs/drivers/migrating-container-overrides.md` (`sidebar_position: 6`) with the sections of `docs/docs/drivers/migrating-env-vars.md`: what changed; if you run deployments (load migrated drivers, review stored `command`/`args` overrides first because some apply for the first time, then `styrminctl deployments update-version <id> <current-version>`; pods on an unmigrated driver version keep running while the render fails); if you write drivers (declare `components.<name>.container`, delete the filter calls, delete `spec.container_overrides`, bump `spec.version`); behaviour differences (`containers[0]`, only `Deployment`/`StatefulSet`, empty list still rejected)
- [ ] T040 [P] Rewrite the "Container `command` / `args` overrides (optional)" section of `docs/docs/drivers/creating-a-driver.md` (no template code, no `spec.container_overrides`; the component container is the only declaration; link the migration guide) and remove its link to the deleted dev guide
- [ ] T041 [P] Update `docs/docs/drivers/context.md` (the `component_command`/`component_args` entry becomes "retired, raises `RETIRED_TEMPLATE_FILTER`"), the **Component overrides** and **Component container** entries in `docs/docs/concepts-and-architecture/glossary.md`, and the apply note on component override checks in `docs/docs/reference/styrminctl.md` (`command`/`args` need a component container)
- [ ] T042 [P] Add a section to `docs/docs/changelog.md` in the style of the env var entry ("What's new" and "Migration"), and create the towncrier fragments with `uv run towncrier create -c "..." 457.changed.md` (command/args applied by post-render to the component container; infrahub `server`/`task-worker` accept `command`; `isApplicable` added; containerless writes rejected) and `457.removed.md` (filters retired, `spec.container_overrides` removed, `ApplicationDriverVersion.containerOverrides`, `DriverContainerOverrideDoc`, the SDK `get_driver_container_override_docs` method and `DRIVER_CONTAINER_OVERRIDE_DOC_COMPONENT_MISMATCH` removed; review stored overrides before moving)
- [ ] T043 [P] Create `dev/adr/0069-container-command-args-by-post-render.md` (MADR): supersedes ADR-045 §2 and §5, extends ADR-058 to `command`/`args`, keeps ADR-045 §1, §3, §4; records research D-001 to D-005. Update the status note of `dev/adr/0045-container-override-no-layering-and-omit-marker.md` and its links to the deleted guide, and add a "see ADR-069" line to `dev/adr/0058-image-overrides-and-component-container-guard.md`
- [ ] T044 [P] Delete `dev/guides/driver-container-override-consumption.md` and remove its links in `dev/README.md`, `dev/guides/driver-env-var-consumption.md` and any other page found by `grep -rn driver-container-override-consumption --include=*.md . | grep -v specs/archive`
- [ ] T045 [P] Update `CONTEXT.md` entries **Component overrides**, **Component container** and **Container override** (applied by post-render to the component container; filters retired; `spec.container_overrides` removed; containerless rule and `isApplicable`)
- [ ] T046 [P] Update `dev/knowledge/backend/services.md` (error tree, `component_container` module), `dev/knowledge/backend/data-models.md` (column removed), `dev/knowledge/backend/api.md` (GraphQL changes), `dev/knowledge/backend/deployment-env-vars.md` (`ContainerMergePatch` name), `dev/knowledge/backend/hooks-and-actions.md` (`applicable_overrides`) and `dev/knowledge/frontend/deployment-configuration.md` (editor gating)
- [ ] T047 Update docstrings that still describe template consumption or the empty-list marker: `backend/styrmin_backend/services/container_overrides/__init__.py`, `backend/styrmin_backend/services/container_overrides/resolver.py`, `backend/styrmin_backend/context/models/components.py` (`ResolvedComponentContainerOverride`), `backend/styrmin_backend/context/models/config.py` (`ComponentConfigBlock`), `backend/styrmin_backend/services/component_container/__init__.py`, `backend/styrmin_backend/services/context.py` (`_populate_component_container_overrides`)
- [ ] T048 Run `uv run invoke format lint`, `uv run invoke validate-graphql`, frontend `pnpm lint` and `pnpm test` (Node 22), and `uv run invoke test`; fix failures
- [ ] T049 Re-run the E2E of T017 after all phases and update `specs/022-post-render-container-overrides/e2e-evidence.md` with the final passing run (Constitution §V)
- [ ] T050 Walk through `specs/022-post-render-container-overrides/quickstart.md` §1–§8 and confirm each expected result, including the manual retired-filter check in §7

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T002 before T012–T014 (the fixtures must be the pre-migration templates).
- **Foundational (Phase 2)**: T003 → T007; T005 → T007, T008. Blocks all stories.
- **US1 (Phase 3)**: after Phase 2. T012–T014 → T015 → T016 → T017.
- **US2 (Phase 4)**: after Phase 2 and T012–T014 (the migrated drivers must no longer call the filters before T024 retires them, or the US1 E2E breaks). T023 → T024; T025 → T026 → T027; T028 after T025–T026.
- **US3 (Phase 5)**: after Phase 2. T034 → T035; T036 → T037. T037 after T028 when both run (one schema export at the end is enough if done in order).
- **Polish (Phase 6)**: after the stories; T048–T050 last.

### User Story Dependencies

- US1 needs only the foundation.
- US2 needs US1's driver migration (T012–T014).
- US3 needs only the foundation; its schema regeneration shares `schema.graphql` with US2.

### Parallel Opportunities

- T004 and T006 in parallel after T003 and T005.
- US1: T010, T011, T012, T013, T014 in parallel.
- US2: T018–T022 in parallel; T023/T024 and T025–T027 in parallel with each other.
- US3: T029–T033 in parallel; T038 in parallel with T034–T037.
- Polish: T039–T046 in parallel.

## Parallel Example: User Story 1

```text
T010 integration tests on kustomize (command/args)
T011 SC-001 test over every example driver
T012 migrate simple-app
T013 migrate infrahub
T014 migrate infrahub-enterprise
```

## Implementation Strategy

1. Phase 1 and Phase 2: the merge patch and the applicability rule, with unit tests.
2. US1: drivers migrated, overrides applied by post-render, E2E green. This is the first state worth reviewing.
3. US2: retire the filters and remove the block, with the parity test proving SC-005.
4. US3: write check, `isApplicable`, frontend.
5. Documentation and full verification. The three stories ship together in one release; do not release after US1 alone, because the old filters would still be live next to the post-render path.
