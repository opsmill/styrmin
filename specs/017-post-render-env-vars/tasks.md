---
description: "Task list for 017-post-render-env-vars"
---

# Tasks: Platform-Owned Env Var Injection via Post-Render

**Input**: Design documents from `specs/017-post-render-env-vars/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md),
[critique](critiques/critique-20261002.md)

**Tests**: Required. Every FR names its verification, and the constitution mandates unit,
propagation (§V), and E2E coverage with local PASS evidence. Write each test before the code it
covers and confirm it fails first.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested
independently. Paths are repository-relative.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: User story from spec.md (US1–US5)

---

## Phase 1: Setup

**Purpose**: Pin the data every later task depends on.

- [X] T001 Render every in-repo driver chart with its driver's values (`helm template` with the `fullnameOverride` from each `driver/examples/*/values.j2.yml`) and, for each of the 30 components, record the identifier label, the matched `Deployment`/`StatefulSet` names, and the container name to declare in `specs/017-post-render-env-vars/driver-containers.md` (one table row per component, plus the exact `helm template` command per driver). Start from research.md D-010; flag any component whose label matches a workload lacking that container.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The component container field, available end to end. Blocks every story.

- [X] T002 [P] Write failing unit tests in `backend/tests/unit/services/driver/test_component_container.py`: a driver spec with `components.server.container: simple-app` loads and exposes the value; omitting `container` loads with `None`; `Simple_App`, `-bad`, `""`, and a 64-char name each fail registration with a validation error naming the component (FR-001).
- [X] T003 [P] Write a failing unit test in `backend/tests/unit/context/test_component_context_container.py`: a `ContextInput` whose component config carries `container` yields `ComponentContext.config.container`; a stored instance context without the key still validates with `container is None`.
- [X] T004 Add `container: str | None = None` with DNS-1123 label validation (`^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`, ≤ 63 chars) to `ArbitrarySectionModel` in `backend/styrmin_backend/services/driver/models/resources/driver.py`; add the `container` example to the module docstring. Make T002 pass.
- [X] T005 Add the same typed `container: str | None = None` field to `ArbitrarySectionModel` in `backend/styrmin_backend/context/models/components.py` (no validation beyond type; load-time validation is T004's). Make T003 pass.

**Checkpoint**: `components.<name>.container` loads, validates, and reaches `ComponentContext`.

---

## Phase 3: User Story 1 — Component-scope env var merges into the chart's rendered env (P1) 🎯 MVP

**Goal**: A component-scope env var reaches the component container by post-render; chart
entries survive; same-name entries (including `valueFrom`) are replaced; clearing restores the
chart default, including on deployments created before the change (FR-002, FR-009, FR-010,
FR-011).

**Independent Test**: quickstart.md §4 on simple-app, both `[api-chromium]` and `[ui-chromium]`.

### Tests for User Story 1

- [X] T006 [P] [US1] Write failing unit tests in `backend/tests/unit/agent/test_container_env_patch.py` for `ContainerEnvPatch.render_value()` per contracts/post-render-patch.md: `apiVersion: apps/v1`, `kind` as given (`Deployment`/`StatefulSet`), `metadata.name: any`, one container named after the component container, env entries `{name, value, valueFrom: null}` in input order; `yaml.safe_load` of the output returns strings for `"true"`, `"null"`, `"0123"`, `""`, a multi-line value, and `"$(OTHER)"` (critique E5).
- [X] T007 [P] [US1] Write failing unit tests in `backend/tests/unit/services/env_vars/test_patch_builder.py` for `build_env_var_patches(context)`: two patches (`Deployment`, `StatefulSet`) targeted by the identifier label selector for a component with a container and env vars; none for a component with `container=None`; none when `env_vars` is `None` or `config` is empty; disabled components still get patches; no components → empty list; a serialisation failure raises a typed `OPERATION_FAILED` error carrying `kind` and `label_selector`.
- [X] T008 [P] [US1] Write a failing unit test in `backend/tests/unit/agent/test_application_builder_env_vars.py`: `ApplicationHelmReleaseBuilder.build()` on a context with scheduling (resources) and env vars places every env patch after every scheduling patch in `spec.postRenderers[0].kustomize.patches`, and emits no env patch when no component has env vars (research D-002).
- [X] T009 [P] [US1] Write failing unit tests in `backend/tests/unit/agent/test_upsert_custom_resource_replace_spec.py`: with `replace_spec_on_update=True`, a 409 on create triggers one `application/json-patch+json` patch whose ops are `add /spec` with `None` pruned plus per-key `add` ops for each `metadata.labels`/`metadata.annotations` key (RFC 6901 escaping of `/` as `~1`); no op touches `metadata.finalizers` or keys the body does not set (kopf annotations survive); with the flag off, the merge-patch path is unchanged (FR-011, critique E3). Model on `backend/tests/unit/agent/test_upsert_custom_resource_prune.py`.
- [X] T010 [US1] Add `set_component_env_vars(*, deployment_id: str, component: str, env_vars: dict[str, str]) -> None` to the scenario-driver protocol in `backend/tests/e2e/drivers/protocol.py` (empty dict = clear the component's env vars), and to the conformance expectations in `backend/tests/e2e/drivers/test_conformance.py`.
- [X] T011 [P] [US1] Implement `set_component_env_vars` in `backend/tests/e2e/drivers/api_driver.py` via the SDK `update_deployment` with `config.components[<component>].env_vars`, preserving other stored component blocks.
- [X] T012 [P] [US1] Implement `set_component_env_vars` in `backend/tests/e2e/drivers/ui_driver.py` and a page-object method in `backend/tests/e2e/pages/deployment_detail.py` that opens the Configuration tab edit drawer, expands `component-override-trigger-<component>`, adds/edits/removes env var rows to match `env_vars`, saves, and confirms the redeploy diff dialog (selectors from `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx` and `ConfigEditDrawer.tsx`).
- [X] T013 [US1] Write the E2E `test_component_env_var_merges_into_chart_env` in `backend/tests/e2e/test_deployment_env_vars.py` (marked `@pytest.mark.ci`, inherits the module's `shard_env`, **no** `api_only` — dual-entrypoint), reusing `env_vars_deployment`: (1) `set_component_env_vars(server, {LOG_LEVEL: debug})` → `simple-app` container has `LOG_LEVEL=debug`, `STYRMIN_CHART_DEFAULT=marker`, and `STYRMIN_CHART_DEFAULT_FROM` with its `fieldRef`; (2) add `STYRMIN_CHART_DEFAULT=override` and `STYRMIN_CHART_DEFAULT_FROM=literal` → both literals, no `valueFrom` on `STYRMIN_CHART_DEFAULT_FROM`; (3) seed a stray `extraEnv: [{name: STALE_VALUES_ENV, value: x}]` into the live HelmRelease `spec.values` via kr8s, then `set_component_env_vars(server, {})` → `LOG_LEVEL` and `STALE_VALUES_ENV` absent from the container and from HelmRelease `spec.values`, both chart defaults restored (US1 Sc.1–3, FR-011). Read env from the live pod template with the module's `_wait_for_pod_template` helper; assert outcomes, not full env order (critique E9).

### Implementation for User Story 1

- [X] T014 [P] [US1] Add `ContainerEnvPatch(Patch)` to `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py` (fields: `container: str`, `env: dict[str, str]`, `kind: str = "Deployment"`, `api_version: str = "apps/v1"`, `name: str = "any"`), rendering the strategic-merge document from T006 via `yaml.dump(..., sort_keys=False)`. Make T006 pass.
- [X] T015 [US1] Create `backend/styrmin_backend/services/env_vars/patch_builder.py` with `build_env_var_patches(context: GlobalContext) -> list[TargetPatch]` per research D-009, eager render validation, and one info log per component with patches (`component`, `container`, env var count — never values, critique E8). Make T007 pass.
- [X] T016 [US1] In `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py`, add `build_env_var_post_rendering_patches()` delegating to T015 and extend `build()` to append its patches **after** `build_scheduling_post_rendering_patches()`, with a one-line comment pointing at research D-002. Update the `render_value_template` docstring: env vars stay in the context as read-only data, injection is post-render. Make T008 pass.
- [X] T017 [US1] Add a `replace_spec_on_update: bool = False` parameter to `upsert_custom_resource` in `backend/styrmin_backend/agent/service/kubernetes/primitives.py`: on 409 with the flag set, send the T009 JSON Patch (`application/json-patch+json`) instead of the merge-patch; keep create-path pruning. Make T009 pass.
- [X] T018 [US1] In `backend/styrmin_backend/operator/pipeline.py` Step 3, pass `replace_spec_on_update=True` to the HelmRelease `upsert_custom_resource` call and update the adjacent comment (null markers now behave as absent on both paths; see the new ADR from T055).
- [X] T019 [US1] Migrate simple-app: in `driver/examples/simple-app/driver.styrmin.yml` add `container: simple-app` to `server` and `container: postgresql` to `database` (verify against T001), bump `spec.version`, and update the `env_vars` doc descriptions ("operator" → "user"); in `driver/examples/simple-app/values.j2.yml` remove both `component_env_vars` lines (`extraEnv`, `postgresql…extraEnvVars`) and their comments — no clearing marker is needed because FR-011 replaces `spec.values`; in `driver/examples/simple-app/src/helm/templates/deployment.yaml` add a `STYRMIN_CHART_DEFAULT_FROM` entry with `valueFrom.fieldRef.fieldPath: metadata.name` next to `STYRMIN_CHART_DEFAULT` and update the "DO NOT REMOVE" comment to cite the T013 test. Keep the chart's generic `extraEnv` support (T013 seeds it to simulate a pre-migration deployment); reword the `extraEnv` comment in `driver/examples/simple-app/src/helm/values.yaml` so it no longer says the driver template populates it.
- [X] T020 [US1] Update `test_us1_deployment_level_env_var` in `backend/tests/e2e/test_deployment_env_vars.py`: rewrite the docstring and the FR-014a comment to describe post-render injection (the assertion that `STYRMIN_CHART_DEFAULT` survives stays), and assert `LOG_LEVEL` lands on the `simple-app` container specifically rather than "every container".
- [X] T021 [US1] Run `uv run pytest backend/tests/unit -k "container_env_patch or patch_builder or application_builder_env_vars or replace_spec" -v`, then `sleep infinity | uv run pytest "backend/tests/e2e/test_deployment_env_vars.py" -k "component_env_var_merges_into_chart_env or test_us1" -v -s --pdb 2>&1 | tee /tmp/us1.log` until both `[api-chromium]` and `[ui-chromium]` PASS; record node IDs, command, ISO 8601 timestamp, vcluster id + kubeconfig path, and the verbatim `PASSED` lines in `specs/017-post-render-env-vars/e2e-evidence.md`.

**Checkpoint**: US1 delivers the #385 fix on simple-app end to end (MVP).

---

## Phase 4: User Story 2 — Deployment- and environment-scope env vars reach every component (P2)

**Goal**: Broad scopes reach every component container with deepest-wins precedence; components
without a container are skipped silently (FR-004).

**Independent Test**: existing `test_us2` / `test_us3` E2Es on the migrated simple-app.

### Tests for User Story 2

- [X] T022 [P] [US2] Add failing cases to `backend/tests/unit/services/env_vars/test_patch_builder.py`: a context with env-scope `LOG_LEVEL=info`, deployment-scope `LOG_LEVEL=warn`, and component-scope `LOG_LEVEL=debug` on one of two contained components → that component's patch carries `debug`, the other's `warn`; a mixed driver (one component with a container, one without) given a deployment-scope var → patches for the first only, no error (US2 Sc.1–3, FR-004).

### Implementation for User Story 2

- [X] T023 [US2] Confirm T015 satisfies T022 without changes (resolution already merges env → deployment → component into `ComponentContext.env_vars`); fix the builder if a case fails.
- [X] T024 [US2] Update `test_us2_environment_level_env_var_propagates_to_all_deployments` and `test_us3_per_component_env_var_overrides_deployment_level` in `backend/tests/e2e/test_deployment_env_vars.py`: replace comments/docstrings that describe values-template (`extraEnv`) consumption with post-render injection; keep assertions, narrowing "every container" assertions to the component containers (`simple-app`, `postgresql`).
- [X] T025 [US2] Run `sleep infinity | uv run pytest backend/tests/e2e/test_deployment_env_vars.py -k "us2 or us3" -v -s --pdb 2>&1 | tee /tmp/us2.log` to PASS and append the evidence to `specs/017-post-render-env-vars/e2e-evidence.md`.

**Checkpoint**: US1 + US2 cover every env var scope.

---

## Phase 5: User Story 3 — Driver author declares a component container (P2)

**Goal**: The declaration is the whole driver contract; the old filter fails loudly; every
in-repo driver is migrated; the driver detail view shows the container (FR-001, FR-007, FR-008,
SC-002, SC-003).

**Independent Test**: quickstart.md §2 and §5 (SC-003), plus loading every in-repo driver.

### Tests for User Story 3

- [X] T026 [P] [US3] Rewrite `backend/tests/unit/agent/test_render_value_template_env_vars.py` to the new contract (critique E6): a template calling `component_env_vars` raises `RetiredTemplateFilterError` with `error_code == "RETIRED_TEMPLATE_FILTER"` and metadata `{filter, migration_guide}`, message per contracts/errors.md; templates reading `instance.config.env_vars` and `components.<name>.env_vars.config` still render (FR-009); keep the `model_dump` shape test.
- [X] T027 [P] [US3] Write a failing unit test in `backend/tests/unit/services/driver/test_example_drivers_container.py` that loads every `driver/examples/*/driver.styrmin.yml`, asserts every component declares a `container` matching `specs/017-post-render-env-vars/driver-containers.md`, and asserts no `driver/examples/*/values.j2.yml` contains `component_env_vars` (FR-008, SC-002).
- [X] T028 [P] [US3] Write a failing unit test in `backend/tests/unit/agent/test_infrahub_values_prefect_env.py` that renders `driver/examples/infrahub/values.j2.yml` and `driver/examples/infrahub-enterprise/values.j2.yml` with a representative context and asserts no `prefect-server.server.env` key is emitted and `PREFECT_SERVER_ANALYTICS_ENABLED` is set under `global.prefect.env` (SC-003, research D-010).
- [X] T029 [P] [US3] Write a failing propagation test in `backend/tests/functional/graphql/test_application_driver_version_propagation.py`: load a driver whose components declare/omit `container`; `applicationDriverVersion { componentConfigs { name container } }` returns the declared value and `null` (contracts/graphql-deltas.md).
- [X] T030 [P] [US3] Write a failing frontend test in `frontend/src/__tests__/drivers/ComponentsTab.test.tsx`: each component row shows its container, and a component without one shows an explicit "none declared" state (critique P4).
- [ ] T031 [US3] Extend `test_infrahub_task_manager_service_exposes_prefect_ui` in `backend/tests/e2e/test_infrahub_services.py` (read-only, on `deployed_infrahub_enterprise_app`): the `prefect-server` Deployment's pods are Ready and its `prefect-server` container env contains `PREFECT_UI_SERVE_BASE=/` and `PREFECT_SERVER_ANALYTICS_ENABLED` (SC-003; research D-011).

### Implementation for User Story 3

- [X] T032 [US3] Add `RetiredTemplateFilterError(ServiceError)` to `backend/styrmin_backend/services/exceptions.py` next to `SchedulingPatchRenderingError` (code `RETIRED_TEMPLATE_FILTER`, metadata `filter`, `migration_guide`, message per contracts/errors.md).
- [X] T033 [US3] In `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py`, replace the `component_env_vars` implementation with a stub that raises `RetiredTemplateFilterError` (keep it registered in `get_jinja_environment()`), and update the `component_command` docstring that references the env-vars convention. Make T026 pass.
- [X] T034 [P] [US3] Migrate `driver/examples/infrahub/`: add each component's `container` from T001 to `driver.styrmin.yml` and bump `spec.version`; in `values.j2.yml` remove every `component_env_vars` loop and its comment, keep the hard-coded map entries (`PREFECT_API_URL`, `INFRAHUB_WORKFLOW_ADDRESS`), drop the `prefect-server.server.env` override, and set `PREFECT_SERVER_ANALYTICS_ENABLED` under `global.prefect.env`; drop `extraEnvVars`/`env` keys that only carried user env vars.
- [X] T035 [P] [US3] Apply the T034 migration to `driver/examples/infrahub-enterprise/` (`driver.styrmin.yml`, `values.j2.yml`; note the extra `infrahub.` nesting).
- [X] T036 [P] [US3] Migrate `driver/examples/semaphore/` (`driver.styrmin.yml` containers + version bump; remove both `component_env_vars` lines from `values.j2.yml`).
- [X] T037 [P] [US3] Migrate `driver/examples/slurpit/` (six containers from T001 incl. `styrmin-slurpit-warehouse` / `styrmin-slurpit-mongodb`; remove every `component_env_vars` loop from `values.j2.yml`, keeping hard-coded credentials and wiring).
- [X] T038 [P] [US3] Migrate `driver/examples/db-test/` (three containers; remove `component_env_vars` from `values.j2.yml` incl. the mariadb/mongodb loops; keep hard-coded credentials).
- [X] T039 [P] [US3] Add `container: infrahub-mcp` to `driver/examples/infrahub-mcp/driver.styrmin.yml` and bump `spec.version`. Make T027 and T028 pass.
- [X] T040 [US3] Add a `container: str | None` field to the `ComponentConfig` Strawberry type in `backend/styrmin_backend/api/definitions/application_driver/model.py` resolving `config["container"]`, with the description from contracts/graphql-deltas.md. Make T029 pass.
- [X] T041 [US3] Regenerate: `uv run styrmin export graphql-schema schema.graphql`; add `container` under `componentConfigs` in `python_sdk/src/styrmin_sdk/graphql/load_version.graphql` and `load_local_version.graphql` and in `frontend/src/graphql/get_driver.graphql`; run `uv run invoke validate-graphql` and `uv run invoke generate`.
- [X] T042 [US3] Show the component container in `frontend/src/pages/drivers/driver-detail/tabs/ComponentsTab.tsx`. Make T030 pass.
- [ ] T043 [US3] Run T031 with `sleep infinity | uv run pytest backend/tests/e2e/test_infrahub_services.py -v -s --pdb 2>&1 | tee /tmp/sc003.log` to PASS and append the evidence to `specs/017-post-render-env-vars/e2e-evidence.md`.

**Checkpoint**: every in-repo driver injects env vars by post-render; unmigrated drivers fail
loudly with a pointer to the guide.

---

## Phase 6: User Story 4 — Writes to components that can't receive env vars are rejected (P3)

**Goal**: New or changed component-scope env vars on a containerless component are rejected
before reconcile; the frontend does not offer editing for such components (FR-003, FR-006).

**Independent Test**: quickstart.md §3 (mutation matrix) and §6 (frontend).

### Tests for User Story 4

- [ ] T044 [P] [US4] Write failing tests in `backend/tests/functional/graphql/test_update_deployment_input_errors.py` for `COMPONENT_CONTAINER_NOT_DECLARED` on a driver with one containerless component: add → error code + metadata `{componentName, componentsWithContainer}` + no task submitted; change value → same; remove a key → accepted; unchanged re-submission → accepted; repeat the four cases on a write that also switches to a driver version where the component gains / loses its container (validated against the target version; critique E1, E2, X1). Cover `deploy` with a component-scope block on a containerless component → rejected.
- [ ] T045 [P] [US4] Write a failing propagation test in `backend/tests/functional/graphql/test_env_vars_propagation.py`: `deployment { components { name container } }` returns the pinned driver version's value and `null` after switching to a version without it (contracts/graphql-deltas.md).
- [ ] T046 [P] [US4] Write failing frontend tests in `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.test.tsx`: for a component with `container: null`, no add/edit env var control is rendered and an explanation is shown; stored env vars on it render read-only with a working remove control; components with a container are unchanged (FR-006).

### Implementation for User Story 4

- [ ] T047 [US4] Add `ComponentContainerNotDeclaredError(ServiceError)` to `backend/styrmin_backend/services/env_vars/exceptions.py` per contracts/errors.md.
- [ ] T048 [US4] Add `_validate_component_env_var_containers(submitted_config, stored_config, containers_by_component)` to `backend/styrmin_backend/services/deployment.py` implementing the research D-007 table; call it in `update_deployment` after the target driver version is resolved and before any task is submitted (building `containers_by_component` from the target version's `component_configs`), and in `deploy` against the selected version. Keep `_validate_component_env_var_targets` as is. Make T044 pass.
- [ ] T049 [US4] Add `container: str | None` to the deployment `Component` Strawberry type in `backend/styrmin_backend/api/definitions/deployment/model.py` (`from_instance` reads `instance.config.get("container")`); update the `ComponentConfigInput.name`/`.envVars` descriptions to mention `COMPONENT_CONTAINER_NOT_DECLARED`. Make T045 pass.
- [ ] T050 [US4] Regenerate the schema and types (`uv run styrmin export graphql-schema schema.graphql`; add `container` under `components` in `frontend/src/graphql/get_deployment.graphql`; `uv run invoke validate-graphql`; `uv run invoke generate`).
- [ ] T051 [US4] Gate the env var editor in `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx` on `component.container`, with stored values read-only and removable (orphan-row precedent in the same file). Make T046 pass; run `cd frontend && pnpm test && pnpm lint`.

**Checkpoint**: no silent no-op path remains for component-scope writes.

---

## Phase 7: User Story 5 — Stored env vars survive a driver upgrade that drops a component container (P3)

**Goal**: Upgrades keep stored values, the read surface flags them, and they never reach a
container (FR-005).

**Independent Test**: propagation test on a deployment whose stored component env vars target a
component that lost its container.

### Tests for User Story 5

- [ ] T052 [P] [US5] Write failing propagation tests in `backend/tests/functional/graphql/test_env_vars_propagation.py`: (a) container declared → `componentEnvVars { component isOrphaned isApplicable envVars }` returns `isApplicable: true`; (b) upgrade the deployment to a driver version without that component's container (no config in the call) → upgrade succeeds, values returned, `isOrphaned: false`, `isApplicable: false`; (c) component dropped → `isOrphaned: true`, `isApplicable: false`. Add a builder assertion in `backend/tests/unit/services/env_vars/test_patch_builder.py` that case (b)'s context emits no env patch (FR-005).

### Implementation for User Story 5

- [ ] T053 [US5] Add `is_applicable: bool` to `ComponentEnvVars` in `backend/styrmin_backend/api/definitions/deployment/model.py` and compute it in the `component_env_vars` resolver as `not is_orphaned and container is not None`, reading containers from the deployment's pinned driver-version component configs (research D-005); update the type description per contracts/graphql-deltas.md ("operator" → "user"). Make T052 pass.
- [ ] T054 [US5] Regenerate the schema and types (`uv run styrmin export graphql-schema schema.graphql`; add `isApplicable` to `python_sdk/src/styrmin_sdk/graphql/get_deployment_component_env_vars_full.graphql`; `uv run invoke validate-graphql`; `uv run invoke generate`).

**Checkpoint**: all five stories functional.

---

## Phase 8: Polish & Cross-Cutting Concerns (documentation is blocking, §VII)

- [ ] T055 [P] Write `dev/adr/0055-post-render-component-overrides.md`: decision (component container + post-render strategic merge for env vars, images next via #20), supersedes ADR-013 §1 and its FR-026 non-feature, narrows ADR-045 §2 (HelmRelease `spec` replace on update — research D-003), ordering facts (D-002), consequences (platform rollback stops injection — critique E7; silently skipped containerless components, UI hint deferred — critique P1; `get_component_env` name-based selection follow-up), alternatives from research. Add "Superseded in part by ADR-055" notes to `dev/adr/0013-driver-env-var-consumption.md` and `dev/adr/0045-container-override-no-layering-and-omit-marker.md`.
- [ ] T056 [P] Rewrite `dev/guides/driver-env-var-consumption.md` for driver authors: declare `components.<name>.container`, no template wiring, ordering and `$(VAR)` rules, the wrong-name failure mode, Deployment/StatefulSet-only scope, read-only context fields; replace "operator" with "user" for humans.
- [ ] T057 [P] Create `docs/docs/drivers/migrating-env-vars.md` (the URL the FR-007 error names): ordered steps — load migrated drivers, upgrade every deployment before editing environment env vars (fan-out fails old-version deployments), declare containers, remove `component_env_vars`, move hard-coded chart env to non-list slots instead of copying defaults; behaviour changes — env vars reach only the component container (not chart Jobs or init containers), ordering, `COMPONENT_CONTAINER_NOT_DECLARED` (critique P2, P3). Link it from `docs/docs/drivers/_category_.json` ordering if needed.
- [ ] T058 [P] Update `docs/docs/drivers/creating-a-driver.md` (replace the `component_env_vars` section with `container` declaration) and `docs/docs/drivers/context.md` (env var fields are read-only data; injection is post-render); review `docs/docs/reference/configuration.md` and update any env var injection statement.
- [ ] T059 [P] Update `dev/knowledge/backend/deployment-env-vars.md` ("Driver-side consumption (010+)" → post-render injection, `isApplicable`, `COMPONENT_CONTAINER_NOT_DECLARED`, implementation pointers), `dev/knowledge/frontend/deployment-configuration.md` (FR-006 gating), and `dev/guides/driver-container-override-consumption.md` (drop the `component_env_vars` table row; note env vars moved to post-render).
- [ ] T060 [P] Update `CONTEXT.md`: keep the drafted **Component container** entry, point **Component overrides** at post-render patches for env vars, and sweep "operator" → "user" for humans in touched entries.
- [ ] T061 [P] Add towncrier fragments: `changelog/385.removed.md` (the `component_env_vars` filter; deployments on unmigrated driver versions fail rendering until upgraded) and `changelog/385.changed.md` (env vars injected by post-render into the component container; chart env defaults preserved; HelmRelease spec replaced on update) via `uv run towncrier create -c "..." 385.<type>.md`; follow `dev/guidelines/changelog.md`.
- [ ] T062 Verify `dev/knowledge/architecture.md` and `docs/docs/concepts-and-architecture/` contain no env var injection statement made stale by this change; update any found.
- [ ] T063 Run `uv run invoke format lint`, `uv run invoke validate-graphql`, `uv run invoke test`, `cd frontend && pnpm test && pnpm lint`, and `cd docs && pnpm build`; fix every failure.
- [ ] T064 Run the full `backend/tests/e2e/test_deployment_env_vars.py` module (`sleep infinity | uv run pytest backend/tests/e2e/test_deployment_env_vars.py -v -s --pdb 2>&1 | tee /tmp/env-vars-module.log`) to PASS, plus any other E2E module that deploys a migrated driver and was touched; complete `specs/017-post-render-env-vars/e2e-evidence.md` with the five constitution fields per test.
- [ ] T065 Walk quickstart.md §1–§7 and correct any step that drifted from the implementation.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001)**: none. Feeds T019, T027, T034–T039.
- **Foundational (T002–T005)**: after Setup; blocks all stories.
- **US1 (T006–T021)**: after Foundational. MVP.
- **US2 (T022–T025)**: after T015 (builder) and T019 (simple-app migrated).
- **US3 (T026–T043)**: after Foundational; T033 must land with or after T019 and before T034–T039 are tested end to end (otherwise unmigrated templates fail). Driver migrations T034–T039 are mutually parallel.
- **US4 (T044–T051)**: after Foundational; independent of US1–US3 except the shared `schema.graphql` (serialise T041 → T050 → T054).
- **US5 (T052–T054)**: after Foundational and T015; T054 after T050.
- **Polish (T055–T065)**: docs (T055–T062) can start once the corresponding behaviour is settled; T063–T065 last.

### Within Each Story

- Tests first, confirmed failing; then implementation; then the story's E2E run with evidence.
- GraphQL field → schema export → `.graphql` query edits → `invoke generate` → frontend.

### Parallel Opportunities

- T002 ∥ T003.
- US1 tests T006 ∥ T007 ∥ T008 ∥ T009; T011 ∥ T012 after T010; T014 ∥ T017.
- US3 tests T026–T030 in parallel; driver migrations T034–T039 in parallel.
- US4 tests T044 ∥ T045 ∥ T046.
- Docs T055–T061 in parallel.
- US4 and US5 can proceed in parallel with US1 once Foundational is done (different files), sharing only the schema regeneration order.

## Parallel Example: User Story 1

```text
T006 test_container_env_patch.py      T007 test_patch_builder.py
T008 test_application_builder_env_vars.py   T009 test_upsert_custom_resource_replace_spec.py
→ then T014 ContainerEnvPatch ∥ T017 upsert replace-spec
→ T015 → T016 → T018 → T019 → T013 E2E (driver methods T011 ∥ T012 after T010) → T021
```

## Implementation Strategy

### MVP (User Story 1)

1. T001–T005 (container field end to end).
2. T006–T021: simple-app injects env vars by post-render, clearing restores chart defaults,
   stale values-template entries are removed.
3. Stop and validate with the T021 evidence before migrating other drivers.

### Incremental Delivery

1. US1 → MVP on simple-app.
2. US2 → broad scopes confirmed.
3. US3 → filter retired, every driver migrated, SC-003 on infrahub-enterprise.
4. US4 → write-path guard and frontend gating.
5. US5 → upgrade orphan flag.
6. Polish → docs, changelog, full gates, E2E evidence.

Note: until T033 (US3) lands, migrated and unmigrated drivers coexist and unmigrated ones
double-inject (values template + post-render). Land US1 and US3 in the same PR.
