---

description: "Tasks for 023: per-component replica counts"
---

# Tasks: Per-Component Replica Counts

**Input**: Design documents from `specs/023-per-component-replicas/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md), [critiques/critique-2026-10-15.md](critiques/critique-2026-10-15.md)

**Tests**: Required. Constitution §V requires an E2E with local PASS evidence and a GraphQL propagation test for every new field and input; research D-014 lists the unit, integration and functional tests.

**Organization**: One phase per user story, in priority order: US1 (P1), US2 (P2), US4 (P2), US3 (P3). All stories ship in one change; each phase ends at a checkpoint.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US4 (spec user stories)
- Paths are relative to the repository root

---

## Phase 1: Setup

**Purpose**: Record a green baseline and keep the pre-change infrahub drivers for the upgrade tests.

- [X] T001 Run `uv sync`, then `uv run pytest backend/tests/unit/agent backend/tests/unit/services/component_container backend/tests/unit/services/driver backend/tests/integration/test_component_container_kustomize.py -q` and note the result as the baseline (no file change)
- [X] T002 Copy `driver/examples/infrahub/` (version 4: `driver.styrmin.yml`, `values.j2.yml`, `actions.py`) unchanged into `backend/tests/functional/fixtures/legacy_drivers/infrahub-v4/`, and `driver/examples/infrahub-enterprise/` (version 3) into `backend/tests/functional/fixtures/legacy_drivers/infrahub-enterprise-v3/`, with a `README.md` in `backend/tests/functional/fixtures/legacy_drivers/` that says these are the driver versions that declared `replicas_server` and `replicas_task_worker`, kept for the retired-parameter upgrade tests (research D-014). This MUST happen before T046 and T047 change the example drivers

---

## Phase 2: Foundational (blocks every story)

**Purpose**: The stored override, the typed driver declaration, the errors, the resolver and the context field (research D-001 to D-003, data-model.md).

- [X] T003 Create the package `backend/styrmin_backend/services/replicas/` with `__init__.py` (module docstring only) and `exceptions.py` defining `InvalidReplicaCountError` (`INVALID_REPLICA_COUNT`, metadata `component_name`, `requested_replicas`), `UnknownComponentReplicaOverrideError` (`UNKNOWN_COMPONENT_REPLICA_OVERRIDE`, metadata `component_name`, `known_components` sorted, `checked_against`) and `SingletonReplicaOverrideError` (`SINGLETON_REPLICA_OVERRIDE`, metadata `component_name`, `requested_replicas`, `checked_against`), each a `ServiceError` subclass with the messages in contracts/errors.md, following `backend/styrmin_backend/services/image_overrides/exceptions.py`
- [X] T004 Add `replicas: int | None = None` to `ComponentConfigBlock` in `backend/styrmin_backend/context/models/config.py`, with a `field_validator("replicas", mode="before")` that raises `InvalidReplicaCountError` (component name from the validation context or the enclosing dict key, as the existing `image`/`command` validators get it) for a `bool`, a non-`int`, a value below 1 or above 2147483647; `None` passes. Update the class docstring
- [X] T005 [P] Add unit tests for T004 in `backend/tests/unit/context/test_component_config_block_replicas.py` (or the existing `ComponentConfigBlock` test module if one exists): `None`, `1`, `3`, `2147483647` accepted; `0`, `-1`, `2147483648`, `True`, `"2"`, `2.0` rejected with `INVALID_REPLICA_COUNT` and the metadata; a stored config without the key reads as `None`
- [X] T006 In `backend/styrmin_backend/services/driver/models/resources/driver.py` add to `ArbitrarySectionModel`: `replicas: StrictInt | None = Field(default=None, ge=1, le=2147483647)`, `singleton: StrictBool = False`, a `model_validator(mode="after")` that raises `ValueError` naming the problem when `singleton` is true and `replicas` is greater than 1, and a `model_serializer(mode="wrap")` that removes `replicas` when `None` and `singleton` when `False` (critique E1). In the same module add `parse_stored_component_declaration(raw: dict, *, driver_version: str, component: str) -> ArbitrarySectionModel` that, when validation fails only on `replicas`/`singleton`, drops both keys, logs a warning naming the driver version and component, and parses again (research D-002)
- [X] T007 [P] Create `backend/tests/unit/services/driver/test_component_replicas.py` following `backend/tests/unit/services/driver/test_component_container.py` (load from `tmp_path` with `get_local_driver_loader`): `replicas: 2` and `singleton: true` load; `singleton: true` + `replicas: 1` loads; `singleton: true` + `replicas: 3` fails with `DriverLoadingError` naming `spec.components.<name>`; `replicas` `0`, `2147483648`, `"2"`, `true`, `2.0` and `singleton: "yes"` fail with the field path; a declaration without the keys dumps (`model_dump()`) to the same dict as before the change (no `replicas`, no `singleton` key); `parse_stored_component_declaration` with `{"replicas": "3", ...}` returns a model without `replicas` and logs a warning
- [X] T008 Create `backend/styrmin_backend/services/replicas/resolver.py` with `ReplicaSource` (`StrEnum`: `OVERRIDE`, `DRIVER_DEFAULT`, `CHART`), the frozen dataclass `ResolvedReplicas(count: int | None, source: ReplicaSource, override_applies: bool)`, `resolve_replicas(*, declared_replicas: int | None, singleton: bool, override: int | None, is_orphaned: bool) -> ResolvedReplicas` implementing the table in data-model.md (including the defensive singleton case), and `replica_patch_count(resolved: ResolvedReplicas, *, enabled: bool) -> int | None` (0 when stopped)
- [X] T009 [P] Create `backend/tests/unit/services/replicas/__init__.py` and `backend/tests/unit/services/replicas/test_resolver.py`: one parametrized case per row of the data-model.md precedence table, plus `replica_patch_count` with `enabled=False` (0 for every row) and `enabled=True` (`count`, or `None` for `CHART`)
- [X] T010 Add `replica_override: int | None = None` to `ComponentContext` in `backend/styrmin_backend/context/models/components.py`, fill it in `resolve_global_context` (`backend/styrmin_backend/context/resolvers.py`) from `DeploymentConfig.components[<name>].replicas` for declared components only, and make every place that builds `ComponentContext.config` from a stored declaration call `parse_stored_component_declaration` (search for `ArbitrarySectionModel.model_validate` / `ArbitrarySectionModel(` in `backend/styrmin_backend/context/` and `backend/styrmin_backend/services/context.py`)
- [X] T011 [P] Add unit tests for T010 next to the existing context resolver tests (search `backend/tests/unit` for `resolve_global_context`): the override reaches `ComponentContext.replica_override`; an override on an undeclared component does not create a component context; a stored declaration with an invalid `replicas` still resolves

**Checkpoint**: `uv run pytest backend/tests/unit/services/replicas backend/tests/unit/services/driver backend/tests/unit/context -q` passes.

---

## Phase 3: User Story 1 — Set a component's replica count, with the singleton guard (Priority: P1) 🎯 MVP

**Goal**: A user sets a replica override through create, update, `updateDeploymentVersion` (and so `styrminctl deployments apply`) or the UI; the component runs that many ready pods; a singleton component cannot go above 1; a count below 1 is rejected; a stopped component stays at 0.

**Independent Test**: On a `simple-app` deployment whose driver marks `database` as singleton, scale `server` to 2 and back, check `database` stays at 1, and check that `database` set to 2 is rejected (quickstart §4).

### Tests for User Story 1

- [X] T012 [P] [US1] Create `backend/tests/unit/services/replicas/test_patch_builder.py` modelled on `backend/tests/unit/services/component_container/test_patch_builder.py` (`_component`/`_context` helpers): stopped component → one `SpecPatch` with `replicas: 0` per kind (`Deployment`, `StatefulSet`) whatever the override; running with override 3 → `value: 3`; driver default 2 → `value: 2`; singleton without `replicas` → `value: 1`; no override and no declaration → no patch; component without `container` still patched; target label selector equals `identifier.label.label_selectable()`; the rendered patch text has an integer `value`; at most one patch per kind per component
- [X] T013 [P] [US1] Create `backend/tests/unit/agent/test_application_builder_replicas.py` modelled on `TestComponentContainerPatchOrdering` in `backend/tests/unit/agent/test_application_builder_env_vars.py`: the replica patches sit after the component label patches and before the backup, scheduling and component container patches in `postRenderers[0].kustomize.patches`; a deployment with no override and no declaration renders the same patch list as before the change (SC-006)
- [X] T014 [P] [US1] Add a `TestReplicaPatches` class to `backend/tests/integration/test_component_container_kustomize.py` that runs the builder's real patches through `kubectl kustomize` on a `Deployment` whose chart renders `replicas: 3`, one that renders no `replicas`, and a `StatefulSet`: override 2 → `spec.replicas: 2` on each; stopped → 0; no override and no declaration → unchanged; a component container merge patch on the same workload still applies
- [X] T015 [P] [US1] Create `backend/tests/unit/services/replicas/test_validator.py`: unknown component with a new override → `UNKNOWN_COMPONENT_REPLICA_OVERRIDE`; unchanged stored override on an undeclared component → accepted; override 2 on a singleton → `SINGLETON_REPLICA_OVERRIDE`, also when equal to the stored value; override 1 on a singleton → accepted; removal (`None`) → accepted
- [X] T016 [P] [US1] Create `backend/tests/functional/graphql/test_replica_overrides_propagation.py` with operation files under `backend/tests/functional/graphql/operations/` (one operation per file, named like `get_deployment_component_replicas.graphql`), modelled on `test_image_overrides_propagation.py`: `updateDeployment` stores `config.components.server.replicas` and `componentReplicas` returns `count: 2`, `source: OVERRIDE`, `isApplicable: true`; `deploy(config:)` stores it on create; `updateDeploymentVersion(input:)` stores it with the version change; omitting `replicas` clears it
- [X] T017 [P] [US1] In the same file as T016 add the rejection tests: `INVALID_REPLICA_COUNT` for `0` on `updateDeployment`; `UNKNOWN_COMPONENT_REPLICA_OVERRIDE`; `SINGLETON_REPLICA_OVERRIDE` on `deploy`, `updateDeployment`, `updateDeploymentVersion(input:)` (the `styrminctl deployments apply` path) and on a version change to a driver version that marks the component singleton while a stored override of 2 exists; for each, assert the error code and metadata, no task, no flow run and an unchanged deployment row (SC-003); the same version change succeeds when `input` lowers the override to 1 or clears it

### Implementation for User Story 1

- [X] T018 [US1] Create `backend/styrmin_backend/services/replicas/patch_builder.py` with `build_component_replica_patches(context: GlobalContext) -> list[TargetPatch]` per contracts/post-render-patch.md (calls `resolve_replicas` and `replica_patch_count`; logs component name, count and source at debug level). In `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` delete `build_components_state_post_rendering_patches` and call the new builder at the same place in `build()`; update the docstrings that mention the stop patch
- [X] T019 [US1] Create `backend/styrmin_backend/services/replicas/validator.py` with `validate_replica_overrides(config: dict | None, *, components: Mapping[str, ArbitrarySectionModel], stored_config: dict | None, checked_against: str) -> None` implementing research D-005 (unknown component with an added or changed value; singleton above 1, changed or not)
- [X] T020 [US1] Call `validate_replica_overrides` from `_validate_config_write` in `backend/styrmin_backend/services/deployment.py` (bound driver version on `update_deployment`, target driver version on `update_deployment_version`) and from the create path in `deploy_application` (with `stored_config=None`), before any task, flow run or ingress dispatch. Load the components' declarations through the driver version's component configs
- [X] T021 [US1] Add `replicas: int | None = None` with the description in contracts/graphql.md to `ComponentConfigInput` in `backend/styrmin_backend/api/definitions/deployment/inputs.py`; make sure `_flatten_components` passes it through; run `backend/tests/functional/graphql/test_update_deployment_input_introspection.py` (field coverage and description guards)
- [X] T022 [US1] In `backend/styrmin_backend/api/definitions/deployment/model.py` add the `ReplicaSource` Strawberry enum, the `ComponentReplicas` type and `Deployment.component_replicas` (GraphQL `componentReplicas`) per contracts/graphql.md: one row per component of the bound driver version plus one per orphaned override, sorted by component name, computed with `resolve_replicas`
- [X] T023 [US1] Regenerate: `uv run styrmin export graphql-schema schema.graphql` and `uv run invoke generate` (frontend codegen needs `pnpm install --ignore-workspace` in `frontend/` inside a Node 22 container in this worktree); commit `schema.graphql`, `python_sdk/src/styrmin_sdk/graphql/_generated/` and the frontend generated types; run `uv run invoke validate-graphql`
- [X] T024 [P] [US1] In `driver/examples/simple-app/driver.styrmin.yml` set `spec.version` to `"4"` and add `singleton: true` to `components.database` (research D-013); search `backend/tests` and `frontend/src` for the string `simple-app` with version `"3"` pins and update any that break
- [X] T025 [US1] Frontend edit drawer in `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx`: a "Replicas" number field per component bound to `components.<i>.replicas` (`aria-label="Replicas for <component>"`, `data-testid="comp-replicas-<component>"`), placeholder from `componentReplicas` (`2 (driver default)` / `set by the chart`), error "Must be 1 or more. To run no pods, stop the component." for values below 1; a singleton component shows a read-only `1 (singleton)` field and a stored override above 1 can only be removed; remove "replicas" from the `FutureExtensionPlaceholder` text and the comments that list it; add `replicas` to `componentOverridesSchema`, `summariseOverrideRow`, `componentsFormToInput` and `componentsDictToList` in `frontend/src/lib/deployment-input.ts` (empty field → `null`), and to `diffComponents` in `frontend/src/lib/config-diff.ts` (path `components[<name>].replicas`); select `componentReplicas` in `frontend/src/graphql/get_deployment.graphql`
- [X] T026 [P] [US1] Frontend tests for T025: extend `ComponentOverridesSection.test.tsx` (field renders, placeholder by source, below-1 error, singleton read-only, stored override above 1 removable), `frontend/src/lib/deployment-input.test.ts` and `frontend/src/lib/config-diff.test.ts`
- [X] T027 [US1] Frontend create form in `frontend/src/pages/deployments/DeployFormPage.tsx`: a "Component replicas" section that lists the selected driver version's components (select `componentConfigs { name replicas singleton }` in the driver query the page uses) with the same field and singleton handling as T025, and sends `config.components` (only components with a value) through `frontend/src/graphql/deploy.graphql`; extend `frontend/src/__tests__/deploy-form/DeployFormPage.test.tsx`
- [X] T028 [P] [US1] E2E driver surface: add `set_component_replicas(self, *, deployment_id: str, component: str, replicas: int | None) -> None` to `backend/tests/e2e/drivers/protocol.py`; implement it in `backend/tests/e2e/drivers/api_driver.py` through `_replace_component_slots(slots={"replicas": replicas})` and add `replicas` to the `ComponentConfigInput(...)` built in `update_deployment`; implement it in `backend/tests/e2e/drivers/ui_driver.py` and `DeploymentDetailPage.set_component_replicas` in `backend/tests/e2e/pages/deployment_detail.py` (open the component block, fill or clear `comp-replicas-<component>`, apply the drawer); add the keyword-only conformance check in `backend/tests/unit/test_e2e_driver_conformance.py`
- [X] T029 [P] [US1] Add `read_workload_replicas(apps_api, *, namespace: str, kind: str, name: str) -> dict[str, int]` to `backend/tests/e2e/helpers/workloads.py`: one read returning `spec`, `status`, `updated`, `ready` and `available` counts (missing status fields as 0)
- [ ] T030 [US1] Add `test_scale_server_and_singleton_guard` (marked `ci`, no `api_only`) to `backend/tests/e2e/test_deployment_image_override.py`, reusing the module-scoped `image_override_deployment` fixture, with a finalizer that clears the `server` replica override; update the module docstring. The test does research D-012 steps 1 to 4: after each update task completes, call `read_workload_replicas` **once** (no polling) and assert all counts equal N (critique E7); assert `componentReplicas` rows; in the UI variant assert the drawer shows `database` fixed at 1; send `database` replicas 2 through the SDK client in both variants and assert `SINGLETON_REPLICA_OVERRIDE`, no new task and an unchanged config
- [ ] T031 [US1] Run the E2E, one variant per session, after `docker compose build server`: `sleep infinity | uv run pytest backend/tests/e2e/test_deployment_image_override.py -m "ci and shard_configuration" -k "api-chromium" -v -s --pdb` (the whole module, so the image tests run after the replica test on the shared deployment), then the same with `-k ui-chromium`. Stop a paused run by PID, not `pkill -f`. Record for each variant in `specs/023-per-component-replicas/e2e-evidence.md`: node ID, exact command, ISO 8601 time of the passing run, vcluster id and kubeconfig path, and the verbatim `PASSED` line (Constitution §V)

**Checkpoint**: US1 works end to end on `simple-app`; `uv run pytest backend/tests/unit/services/replicas backend/tests/unit/agent backend/tests/functional/graphql/test_replica_overrides_propagation.py -q` passes and T031 has PASS evidence for both variants.

---

## Phase 4: User Story 2 — A driver author declares a default replica count (Priority: P2)

**Goal**: `components.<name>.replicas` and `singleton` in a driver version set the count without an override, are refused when contradictory, and are visible on the driver version page and through the API.

**Independent Test**: Load a driver version with `components.server.replicas: 2`, create a deployment with no override, check `componentReplicas` reports 2 / `DRIVER_DEFAULT` and the patch is `value: 2`.

### Tests for User Story 2

- [ ] T032 [P] [US2] In `backend/tests/functional/graphql/test_application_driver_version_propagation.py` (with operation files such as `operations/get_driver_component_replicas.graphql`) add: a driver loaded with `server.replicas: 2` and `database.singleton: true` returns `ComponentConfig.replicas` 2 / `singleton` true and `null` / false for the others; a `ComponentConfig` row stored without the keys returns `null` / false; a driver with `singleton: true` and `replicas: 3` fails `loadLocalApplicationDriverVersion` and stores no row
- [ ] T033 [P] [US2] In `backend/tests/functional/graphql/test_replica_overrides_propagation.py` add: a deployment of a driver version with `server.replicas: 2` and no override reports `componentReplicas` `count: 2`, `source: DRIVER_DEFAULT`; a singleton without `replicas` reports 1 / `DRIVER_DEFAULT` / `singleton: true`; a component with neither reports `count: null`, `source: CHART`
- [ ] T034 [P] [US2] Create `backend/tests/unit/services/replicas/test_example_drivers.py`: for every `driver/examples/*/driver.styrmin.yml`, build a context from the file with no override and run `build_component_replica_patches`; components that declare neither `replicas` nor `singleton` get no patch (SC-006); declared ones get their count; every component that does not declare `singleton` accepts an override of 2 through `validate_replica_overrides` (SC-001)

### Implementation for User Story 2

- [ ] T035 [US2] Add `replicas: int | None` and `singleton: bool` resolvers to `ComponentConfig` in `backend/styrmin_backend/api/definitions/application_driver/model.py`, reading `config["replicas"]` / `config["singleton"]` with defaults `None` / `False`, like the `container` resolver; regenerate as in T023. Note: the two resolvers and the regenerated `schema.graphql` landed early with T027, which selects them in the create form; the propagation test T032 still covers them
- [ ] T036 [US2] Frontend driver version page: select `replicas singleton` under `componentConfigs` in `frontend/src/graphql/get_driver.graphql`; in `frontend/src/pages/drivers/driver-detail/tabs/ComponentsTab.tsx` render "Replicas" (`not set` when null) and "Singleton" (`yes` / `no`) rows in `ComponentRow`, and skip `replicas` and `singleton` in `flattenDecl`; extend `frontend/src/__tests__/drivers/ComponentsTab.test.tsx`

**Checkpoint**: T032 to T034 pass; the driver version page shows the two rows.

---

## Phase 5: User Story 4 — Move the infrahub drivers to the replica mechanism (Priority: P2)

**Goal**: New `infrahub` and `infrahub-enterprise` versions retire the two replica parameters; a deployment with default values moves without a manual step; a changed value is rejected with the parameter and its value; an override on a removed component is kept and not applied.

**Independent Test**: Functional tests that load the version 4 fixture and the version 5 example and run `updateDeploymentVersion` with default and changed parameter values (quickstart §2).

### Tests for User Story 4

- [ ] T037 [P] [US4] Create `backend/tests/unit/services/parameters/__init__.py` (if missing) and `backend/tests/unit/services/parameters/test_retired.py`: a key declared by the current version and not by the target, equal to the current default → dropped; changed value → `RetiredParameterValueError` with `parameter_name`, `value`, `default`, `checked_against`; `"1"` and `1.0` against default `1` → error; `True` against default `1` → error; a key declared by both → kept; a key declared by neither → left for `validate_parameter_values`; the rule runs over the merged map (stored or `parameters` argument plus `input.parameters`)
- [ ] T038 [P] [US4] Create `backend/tests/functional/graphql/test_retired_parameters_propagation.py`: with two generic driver versions written to `tmp_path` (version 1 declares `p` with default 5; version 2 does not), `updateDeploymentVersion` to version 2 succeeds and drops `p` when the stored value is 5; fails with `RETIRED_PARAMETER_VALUE` (metadata, no task, unchanged row) when it is 7; succeeds when the request passes `parameters` without `p`; succeeds when `input.parameters` resubmits `p: 5`; a typo parameter declared by neither version still fails with `OPERATION_FAILED`
- [ ] T039 [P] [US4] Create `backend/tests/functional/graphql/test_infrahub_replica_parameter_upgrade.py`: load `backend/tests/functional/fixtures/legacy_drivers/infrahub-v4/` and the `driver/examples/infrahub/` version 5 (copy each to `tmp_path`); a deployment on version 4 with default parameters moves to version 5, its stored parameters no longer contain `replicas_server`/`replicas_task_worker`, and `componentReplicas` reports `server` 1 and `task-worker` 2 (`DRIVER_DEFAULT`) and `database`, `task-manager-db`, `cache` as singleton (SC-004); with `replicas_task_worker: 4` the change fails with `RETIRED_PARAMETER_VALUE` naming `replicas_task_worker` and `4` and the deployment stays on version 4 (SC-005); resubmitting with `input.components` `task-worker` `replicas: 4` and `parameters` without `replicas_task_worker` succeeds and reports 4 / `OVERRIDE`; an override set on version 4 for `task-worker` then moved to version 5 stays applied; repeat the default-values case for `infrahub-enterprise` (fixture version 3 → example version 4)
- [ ] T040 [P] [US4] In `backend/tests/functional/graphql/test_infrahub_replica_parameter_upgrade.py` add the upgrade hook path (critique E4): after the outer `updateDeploymentVersion` to version 5 with default parameters, a second `updateDeploymentVersion` with the same target and no `parameters` (what the `upgrade_deployment_version` primitive sends) succeeds and changes nothing; and the two-step UI path: on version 4, `updateDeployment` sets the `task-worker` override to 4 and resets `replicas_task_worker` to 2, then `updateDeploymentVersion` to version 5 succeeds and `task-worker` reports 4 / `OVERRIDE`
- [ ] T041 [P] [US4] In `backend/tests/functional/graphql/test_replica_overrides_propagation.py` add the orphan case (FR-009): a `cache` override of 2 on a driver version that declares `cache`, then a version change to one that does not declare it: the change succeeds, the override is still stored, and `componentReplicas` has a `cache` row with `override: 2`, `isOrphaned: true`, `isApplicable: false`, `count: null`; the rendered patches contain no `cache` replica patch
- [ ] T042 [P] [US4] Create `backend/tests/unit/services/replicas/test_infrahub_driver_defaults.py`: for `infrahub` and `infrahub-enterprise`, the version 5 / 4 `server.replicas` and `task-worker.replicas` equal the version 4 / 3 defaults of `replicas_server` / `replicas_task_worker` read from the legacy fixtures, so no pod count changes (SC-004); `values.j2.yml` no longer references either parameter

### Implementation for User Story 4

- [ ] T043 [US4] Add `RetiredParameterValueError` (`RETIRED_PARAMETER_VALUE`, metadata and message per contracts/errors.md, including the migration guide URL `https://styrmin.pages.dev/docs/drivers/migrating-replica-parameters`) to `backend/styrmin_backend/services/parameters/exceptions.py`
- [ ] T044 [US4] Create `backend/styrmin_backend/services/parameters/retired.py` with `drop_retired_parameters(values: dict, *, current_definitions: list[DriverParameterDefinition], target_definitions: list[DriverParameterDefinition], checked_against: str) -> dict` (research D-007; strict equality `type(v) is type(d) and v == d`)
- [ ] T045 [US4] In `update_deployment_version` in `backend/styrmin_backend/services/deployment.py`, call `drop_retired_parameters` on the merged parameter map before `validate_parameter_values` runs against the target version, only when the target driver version differs from the bound one; before any task or ingress dispatch
- [ ] T046 [US4] In `driver/examples/infrahub/driver.styrmin.yml` set `spec.version` to `"5"`, remove the `replicas_server` and `replicas_task_worker` parameters, add `replicas: 1` to `server`, `replicas: 2` to `task-worker`, and `singleton: true` to `database`, `task-manager-db` and `cache`; in `driver/examples/infrahub/values.j2.yml` remove the two `replicas:` lines
- [ ] T047 [US4] Same as T046 for `driver/examples/infrahub-enterprise/` with `spec.version` `"4"`
- [ ] T048 [US4] Search `backend/tests`, `frontend/src`, `tasks/` and `docs/` for `replicas_server` and `replicas_task_worker` and update every use that is not a legacy fixture or a test of the retired-parameter rule (for example E2E manifests or seeds that set them)
- [ ] T049 [US4] Write `docs/docs/drivers/migrating-replica-parameters.md` and add it to `docs/sidebars.ts`: what changed in `infrahub` 5 / `infrahub-enterprise` 4; the retired-parameter rule; how to resolve a `RETIRED_PARAMETER_VALUE` rejection in one API, SDK or `styrminctl deployments apply` request, and in the UI in two steps (edit drawer: set the override and reset the parameter; then upgrade); the singleton components; the `ReadWriteOnce` limit for scaling `server` (critique P5)

**Checkpoint**: T037 to T042 pass.

---

## Phase 6: User Story 3 — Clear a replica override and view the source of each count (Priority: P3)

**Goal**: Clearing returns the component to the next value in the order of precedence; the configuration view and `styrminctl deployments get` show each count and its source.

**Independent Test**: With an override of 3 and a driver default of 2, clear the override; `componentReplicas` reports 2 / `DRIVER_DEFAULT` and the view shows "2 (driver default)".

### Tests for User Story 3

- [ ] T050 [P] [US3] In `backend/tests/functional/graphql/test_replica_overrides_propagation.py` add: override 3 with driver default 2, cleared → 2 / `DRIVER_DEFAULT`; override 3 with no default, cleared → `null` / `CHART`; a stopped component keeps its stored override and reports the resolved count, and the rendered patch is 0 (FR-005)
- [ ] T051 [P] [US3] Extend `python_sdk/tests/test_deployments.py` (an apply with a stored replica override that does not apply lists it in `inapplicable_overrides` with kind `replicas`; a manifest with `components[].replicas` builds the right input) and `cli/tests/test_deployments.py` (`deployments get` shows the `Replicas` column for override, driver default, singleton, chart, stopped and orphaned rows per contracts/cli-and-ui.md; `apply` prints the inapplicable warning for `replicas`)
- [ ] T052 [P] [US3] Extend `frontend/src/components/deployment/configuration/sections/read/ComponentOverridesSummary.test.tsx`: "Replicas" line for each source, "not applied" badge, "stopped: 0 pods", orphaned row

### Implementation for User Story 3

- [ ] T053 [US3] SDK: select `componentReplicas { component count source override singleton isOrphaned isApplicable }` in `python_sdk/src/styrmin_sdk/graphql/get_deployment.graphql` and `get_deployment_override_applicability.graphql`; add `"replicas"` to `OverrideKind` in `python_sdk/src/styrmin_sdk/models/deployment_manifest.py`; cover replicas in `_inapplicable_overrides` and `_override_kinds` in `python_sdk/src/styrmin_sdk/resources/deployments.py`; regenerate as in T023
- [ ] T054 [US3] CLI: in `cli/src/styrminctl/commands/deployments.py` add the `Replicas` column to the `get` Components table (format per contracts/cli-and-ui.md, including `stopped: 0 pods` and orphaned rows) and a `replicas` label in `_OVERRIDE_KIND_LABELS`
- [ ] T055 [US3] Frontend configuration view: in `frontend/src/components/deployment/configuration/sections/read/ComponentOverridesSummary.tsx` add a "Replicas" line per component from `componentReplicas` (`3 (override)`, `2 (driver default)`, `set by the chart`, `AppliedBadge` for `isApplicable: false`, `stopped: 0 pods` from `components[].enabled`, orphaned rows); pass the data from `ConfigurationTab.tsx`

**Checkpoint**: T050 to T052 pass.

---

## Phase 7: Polish and Cross-Cutting Concerns

**Purpose**: Documentation (Constitution §VII), changelog and verification.

- [ ] T056 [P] Write `docs/docs/concepts-and-architecture/replica-overrides.md` modelled on `image-overrides.md` (what it is, order of precedence, singleton components, stop and start, orphaned overrides, the UI, the API, `styrminctl deployments apply`, the rolling-update limit of a singleton, the `ReadWriteOnce` limit) and add it to `docs/sidebars.ts`; add "Replica override" and "Singleton component" to `docs/docs/concepts-and-architecture/glossary.md`
- [ ] T057 [P] Document `replicas` and `singleton` in `driver/DRIVERS.md` (schema block and `## Components`) and in `docs/docs/drivers/creating-a-driver.md` (Step 3 components), with the load errors from contracts/driver-format.md
- [ ] T058 [P] Update `docs/docs/reference/styrminctl.md`: `components[].replicas` in manifests, the `Replicas` column of `deployments get`, the `replicas` kind in the apply warning
- [ ] T059 [P] Write `dev/adr/0070-replica-overrides-and-retired-parameters.md` (MADR, like `dev/adr/0069-container-command-args-by-post-render.md`): order of precedence (FR-002), one replica patch per kind per component that also carries the stop state (research D-004), singleton semantics, and the retired-parameter rule (D-007); link it from ADR-057
- [ ] T060 [P] Update `dev/knowledge/backend/api.md` (the four new error codes and the new fields), `dev/knowledge/backend/services.md` (`services/replicas/`, `services/parameters/retired.py`), `dev/knowledge/backend/data-models.md` (`ComponentConfigBlock.replicas`, driver `replicas`/`singleton`, `ComponentContext.replica_override`), `dev/knowledge/frontend/deployment-configuration.md` and `dev/knowledge/frontend/driver-pages.md`
- [ ] T061 [P] Check `CONTEXT.md` against the final behaviour (replica override, singleton component, parameter rule, component overrides note) and adjust only what drifted
- [ ] T062 [P] Add `changelog/202.added.md` and `changelog/202.changed.md` with `uv run towncrier create` (content per research D-015, including the notes for a driver that already declares `components.<name>.replicas`, the agent chart upgrade and clearing overrides before a downgrade)
- [ ] T063 Run `uv run styrmin export graphql-schema schema.graphql`, `uv run invoke generate`, `uv run invoke validate-graphql` and `uv run invoke format lint`; fix any failure
- [ ] T064 Run `uv run invoke test` (backend unit, functional, integration) and, in a Node 22 container, `cd frontend && pnpm test && pnpm lint`; fix any failure
- [ ] T065 Run the rest of `shard_configuration` once per variant, because `simple-app` moves to version 4: `sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_configuration" -k api-chromium -v -s --pdb`, then `-k ui-chromium`; record the summary lines in `specs/023-per-component-replicas/e2e-evidence.md`
- [ ] T066 Walk through `specs/023-per-component-replicas/quickstart.md` sections 1 to 4 and tick each expected result

---

## Dependencies and Execution Order

### Phase dependencies

- **Setup (Phase 1)**: none. T002 before T046/T047.
- **Foundational (Phase 2)**: after Setup; blocks every story.
- **US1 (Phase 3)**: after Phase 2. MVP.
- **US2 (Phase 4)**: after Phase 2; T033 and T034 use the US1 patch builder and validator (T018, T019).
- **US4 (Phase 5)**: after Phase 2 and US1's write path (T020, T022); T039 to T041 read `componentReplicas`.
- **US3 (Phase 6)**: after US1 (T022 read field); independent of US2 and US4.
- **Polish (Phase 7)**: after the stories it documents; T063 to T066 last.

### Within each story

Tests are written first and fail; then the implementation tasks in ID order. Regeneration (T023) follows every GraphQL change (T021, T022, T035, T053).

### Parallel opportunities

- Phase 2: T005, T007, T009, T011 in parallel once their implementation task is done.
- US1: T012 to T017 in parallel; T024, T028, T029 in parallel with the backend implementation; T026 after T025.
- US4: T037 to T042 in parallel; T046 and T047 in parallel.
- US3: T050 to T052 in parallel.
- Polish: T056 to T062 in parallel.

## Parallel Example: User Story 1

```text
Task: "T012 patch builder unit tests in backend/tests/unit/services/replicas/test_patch_builder.py"
Task: "T013 post-renderer ordering test in backend/tests/unit/agent/test_application_builder_replicas.py"
Task: "T014 kustomize integration cases in backend/tests/integration/test_component_container_kustomize.py"
Task: "T015 validator unit tests in backend/tests/unit/services/replicas/test_validator.py"
Task: "T028 E2E driver surface in backend/tests/e2e/drivers/ and pages/deployment_detail.py"
Task: "T029 read_workload_replicas in backend/tests/e2e/helpers/workloads.py"
```

## Implementation Strategy

### First deliverable (US1)

1. Phases 1 and 2.
2. Phase 3: a user can scale any component on any example driver, singleton components are guarded, and the E2E proves the task waits for the pods.
3. Stop and validate with T031's evidence.

### Incremental delivery

1. US2: driver defaults and the driver version page.
2. US4: retired-parameter rule and the new infrahub driver versions.
3. US3: clear and view the source in the configuration view and the CLI.
4. Polish: documentation, changelog, full verification.

All four stories ship in one change; the order above is the build order.
