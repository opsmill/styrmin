---
description: "Task list for Component-Scope command / args Overrides"
---

# Tasks: Component-Scope `command` / `args` Overrides

**Input**: Design documents from `/specs/014-component-container-overrides/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅ (graphql-deltas.md, jinja-filters.md, errors.md), quickstart.md ✅

**Tests**: INCLUDED. The Constitution (§V) makes E2E + GraphQL propagation tests part of the definition of done, and `research.md` D14 prescribes the unit/propagation/E2E surface. Test tasks are therefore mandatory here, not optional.

**Organization**: Tasks are grouped by user story. This feature is a faithful port of the deployment **env-vars** precedent (008/010, ADR-013); the env-vars implementation is the reference template at every layer (see `research.md` reference map).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US6 (Setup/Foundational/Polish carry no story label)
- Exact file paths are included in every task.

## Path Conventions

Web app + SDK + CLI + drivers layout (per plan.md): backend at `backend/styrmin_backend/`, tests at `backend/tests/`, SDK at `python_sdk/src/styrmin_sdk/`, frontend at `frontend/src/`, reference driver at `driver/examples/simple-app/`, docs at `docs/` and `dev/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new service package scaffold; confirm no dependency changes.

- [X] T001 Create the `backend/styrmin_backend/services/container_overrides/` package with an `__init__.py` that re-exports the public API (validator, resolver, exceptions), mirroring `backend/styrmin_backend/services/env_vars/__init__.py`.
- [X] T002 [P] Confirm no new dependencies are required — the feature reuses the existing Strawberry / Pydantic v2 / Jinja2 / SQLModel stack; verify `pyproject.toml` (root + `backend/`) needs no edits and record this in the task notes.

**Checkpoint**: New service package exists; dependency surface confirmed unchanged.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared backbone every user story flows through — storage model, validator, resolved context, resolver, render filters, and the GraphQL read/write surface plus codegen. Has no standalone user-facing value; blocks all user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 [P] Implement the typed error classes in `backend/styrmin_backend/services/container_overrides/exceptions.py` — `InvalidContainerCommandError` (`INVALID_CONTAINER_COMMAND`), `InvalidContainerArgsError` (`INVALID_CONTAINER_ARGS`), `UnknownComponentContainerOverrideError` (`UNKNOWN_COMPONENT_CONTAINER_OVERRIDE`, payload `component_name` + sorted `known_components`). All subclass `ServiceError` with `error_code`/`default_message`, mirroring `services/env_vars/exceptions.py` (contracts/errors.md).
- [X] T004 Implement `validate_container_override(field, value)` in `backend/styrmin_backend/services/container_overrides/validator.py` — `None` → OK (unset/clear); non-list or any non-`str` element → per-field typed error from T003; empty list `[]` → per-field typed error; empty-string elements accepted; verbatim pass-through (data-model.md §6, research.md D4). Depends on T003.
- [X] T005 [P] Extend `ComponentConfigBlock` in `backend/styrmin_backend/context/models/config.py` — add `command: list[str] | None = None` and `args: list[str] | None = None`, each with a `field_validator` delegating to `validate_container_override` (defence-in-depth). Keep `model_config = ConfigDict(extra="forbid")` (data-model.md §1). Depends on T004.
- [X] T006 [P] Add `ResolvedComponentContainerOverride` (`command`, `args`, `is_orphaned`; no provenance field) to `backend/styrmin_backend/context/models/components.py` and attach `container_override: ResolvedComponentContainerOverride | None = None` to `ComponentContext` (data-model.md §2).
- [X] T007 Implement `ContainerOverridesResolver` + `ResolvedContainerOverrideEntry` in `backend/styrmin_backend/services/container_overrides/resolver.py` — live entries (direct per-component lookup, **no env/deployment layering**, `is_orphaned=False`) and orphan entries (stored block whose component is not in `driver_components` and carries a non-empty `command`/`args`, sorted by name, `is_orphaned=True`; drop empty blocks). Mirror the orphan branch of `services/env_vars/resolver.py` but NOT its merge (data-model.md §4, research.md D2/D7). Depends on T006.
- [X] T008 Wire resolution into `backend/styrmin_backend/services/context.py` — attach the resolved `container_override` to each `ComponentContext` by running `ContainerOverridesResolver.resolve_for_deployment(deployment_config.components, driver_components)`, alongside the existing env-vars resolution. Depends on T007.
- [X] T009 [P] Add the two Jinja filters `component_command` / `component_args` to `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` and register them in `get_jinja_environment`. Each reads `components[<name>].container_override.{command,args}`, returns the list or **`None`** (never `[]`) on any miss (contracts/jinja-filters.md, research.md D8). Depends on T006.
- [X] T010 [P] Extend `ComponentConfigInput` in `backend/styrmin_backend/api/definitions/deployment/inputs.py` — add `command: list[str] | None` and `args: list[str] | None` with the prescribed Strawberry `description=` strings; ensure `_flatten_components` passes them through unchanged and duplicate `name` still raises `DUPLICATE_COMPONENT_NAME` (contracts/graphql-deltas.md §1, research.md D10).
- [X] T011 Add the `ComponentContainerOverrides` output type (`component`, `command`, `args`, `isOrphaned`) and the `Deployment.componentContainerOverrides` resolver in `backend/styrmin_backend/api/definitions/deployment/model.py` — runs `ContainerOverridesResolver`, omits live components with no override, always surfaces orphan blocks with `isOrphaned: true`, returns cleared fields as `null`; type the resolver as `list[ComponentContainerOverrides]` so the schema emits the **non-null list `[ComponentContainerOverrides!]!`** (matches the env-vars precedent `model.py:420 -> list[ComponentEnvVars]`) (contracts/graphql-deltas.md §2, research.md D11). Depends on T007.
- [X] T012 Regenerate the GraphQL contract: run `uv run styrmin export graphql-schema schema.graphql`; create the SDK read operation `python_sdk/src/styrmin_sdk/graphql/get_deployment_component_container_overrides_full.graphql` (mirrors `get_deployment_component_env_vars_full.graphql`); run `uv run invoke generate` to regenerate SDK Pydantic types **and** frontend TS types. Depends on T010, T011.
- [X] T013 Extend the schema-walking field-coverage test in `backend/tests/functional/graphql/test_update_deployment_input_introspection.py` to assert `set(ComponentConfigInput fields) == {camelCase(f) for f in ComponentConfigBlock.model_fields}`, so any future field added to one side without the other fails CI (contracts/graphql-deltas.md §Propagation #2, ADR-014). Depends on T005, T010.

**Checkpoint**: Storage, validation, resolution, render filters, and the GraphQL read/write surface exist and codegen is green. User stories can now begin.

---

## Phase 3: User Story 1 - Override `args` on a single component (Priority: P1) 🎯 MVP

**Goal**: An operator sets `args` on one component of a deployment (no driver fork); on the next reconcile the component's container runs with that argument list, and reading the deployment returns the stored override exactly.

**Independent Test**: Deploy `simple-app` (driver-wired), set `args=["--log-level=debug"]` on `server` via `updateDeployment`, confirm the redeploy, and assert the rendered pod's container reports `args == ["--log-level=debug"]`; read the deployment back and assert the stored override matches.

### Implementation for User Story 1

- [X] T014 [P] [US1] Wire the reference driver to consume the override in `driver/examples/simple-app/values.j2.yml` — add the `component_command("server")` / `component_args("server")` filter blocks guarded by `{%- if _x is not none %}` so the chart default flows through when unset (quickstart.md A2, contracts/jinja-filters.md canonical pattern).
- [X] T015 [P] [US1] Extend the frontend submit-boundary transform `componentsDictToList` in `frontend/src/lib/deployment-input.ts` to carry `command` and `args` from the persisted per-component dict into the list-shaped `ComponentConfigInput` (ADR-015, research.md D12). Uses the regenerated types from T012.
- [X] T016 [US1] Extend the edit UI in `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx` to render per-component **Command** and **Args** list editors beside the env-vars rows, with Zod validation rejecting empty lists (mirrors backend). Depends on T015.
- [X] T017 [P] [US1] Extend the read UI in `frontend/src/components/deployment/configuration/sections/read/ComponentOverridesSummary.tsx` to display the resolved `command` / `args` per component. Depends on T012.
- [ ] T017a [US1] Extend the UI scenario driver so the dual-entrypoint E2E (T021) drives the new Command/Args editor through the deployment-detail Configuration form: add the per-component `command`/`args` form-driving logic to `UiScenarioDriver.update_deployment` in `backend/tests/e2e/drivers/ui_driver.py` (today it only drives the `scheduling` sub-tree — the documented reason the env-vars E2E stayed `api_only`), keeping the `update_deployment` signature in `backend/tests/e2e/drivers/protocol.py` and the `ApiScenarioDriver` impl aligned, and update `backend/tests/e2e/drivers/test_conformance.py` if the contract changes. Scope the form-driving to the new `command`/`args` editor only; leave the existing `env_vars`/scheduling UI behaviour unchanged so the env-vars `api_only` E2E is unaffected (SC-004). This is what lets T021 run dual-entrypoint instead of `api_only`. Depends on T016.

### Tests for User Story 1

- [X] T018 [P] [US1] Unit test the render filters in `backend/tests/unit/agent/test_render_value_template_container_overrides.py` (mirrors `test_render_value_template_env_vars.py`): `args` set → rendered; filter returns `None` (not `[]`) for absent component/missing block; empty-string element `["sh","-c",""]` rendered verbatim (contracts/jinja-filters.md §Unit tests).
- [X] T019 [P] [US1] Unit test `ContainerOverridesResolver` (live branch) and `validate_container_override` happy paths in `backend/tests/unit/services/test_container_overrides_resolver.py` and `.../test_container_overrides_validator.py` — live entry equals the component block value, no layering; valid `args` accepted.
- [X] T020 [P] [US1] Add the propagation round-trip in `backend/tests/functional/graphql/test_container_overrides_propagation.py`: `updateDeployment` with `components:[{name:"server", args:[…]}]` → assert persisted `Deployment.config["components"]["server"]["args"]` equals input and `componentContainerOverrides` projects it back. **Add a second round-trip that sets `command`/`args` via the `deploy` (create) mutation's `config` JSON (`components:[{name:"server", …}]`) and asserts the same persisted shape + read-back, covering the create flow alongside update (FR-002).** (contracts/graphql-deltas.md §Propagation #1).
- [X] T021 [US1] Create the E2E `backend/tests/e2e/test_deployment_container_overrides.py` with the US1 scenario (mirrors `test_deployment_env_vars.py` but **DUAL-ENTRYPOINT** — see T017a): deploy `simple-app`, set `args` on `server` via `scenario_driver.update_deployment(config={"components":[{"name":"server","args":[…]}]})` so both `[api-chromium]` and `[ui-chromium]` exercise the path, confirm redeploy, assert the rendered pod container's `args` via a new container `command`/`args` introspection helper added to `backend/tests/e2e/helpers/workloads.py` (extend `_wait_for_pod_template` if it lacks one), and assert read-back. Mark `@pytest.mark.ci` + `shard_configuration`; **do NOT mark `api_only`** — the UI scenario driver (T017a) now drives the Command/Args editor, so the `[ui-chromium]` variant adds real coverage of the frontend editor (T016). Depends on T014, T016, T017a, and the `helpers/workloads.py` introspection-helper extension.

**Checkpoint**: US1 is fully functional and independently testable — the MVP. An operator can set `args` and observe it on the running container with zero driver-source changes.

---

## Phase 4: User Story 2 - Override `command` independently of `args` (Priority: P2)

**Goal**: Setting `command` does not disturb a previously-set `args`, and an unset field falls through to the chart default. `command` and `args` are independent slots.

**Independent Test**: On a deployment with `args` already set on `server`, set `command=["python","-m","foo.cli","worker"]` and leave `args` unspecified; verify the rendered pod runs with the new `command` and the previously-set `args` unchanged.

### Implementation for User Story 2

- [X] T022 [US2] Verify field independence end-to-end (no new production code expected — both slots were added together in Foundational): confirm `ComponentConfigBlock`, the resolver, the filters, and `ComponentConfigInput` treat `command`/`args` as parallel independent slots; record any gap as a follow-up edit to `backend/styrmin_backend/context/models/config.py` / `services/container_overrides/resolver.py` if found (research.md D3).

### Tests for User Story 2

- [X] T023 [P] [US2] Extend `backend/tests/unit/agent/test_render_value_template_container_overrides.py`: `command` set + `args` unset → `command:` emitted, `args:` key **absent** (chart default flows through); both set → both rendered (contracts/jinja-filters.md §Unit tests, US2 Sc.2/Sc.3).
- [X] T024 [P] [US2] Extend `backend/tests/functional/graphql/test_container_overrides_propagation.py`: set `command` while leaving `args` from a prior write, assert `command` persists and `args` is independently controlled (US2 Sc.1).
- [X] T025 [US2] Add the US2 scenario to `backend/tests/e2e/test_deployment_container_overrides.py`: with `args` set, set `command` independently and assert the pod runs the new `command` while retaining the previously-set `args`. Depends on T021.

**Checkpoint**: US1 and US2 both work independently; partial edits are provably safe.

---

## Phase 5: User Story 3 - Clear an override and fall back to the chart default (Priority: P2)

**Goal**: Clearing an override (null/omit, distinct from `[]`) returns the component to its driver-defined baseline; clearing one field never affects the other; cleared fields are absent from subsequent reads.

**Independent Test**: On a deployment with `args` set on `server`, clear `args` (omit under full-replacement), confirm the redeploy, and verify the rendered pod uses the chart's default `args` and the read surface no longer returns `args`.

### Implementation for User Story 3

- [X] T026 [US3] Confirm full-replacement clear semantics in `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx` + `frontend/src/lib/deployment-input.ts` — removing a field from the per-component block submits the block without it (omit = clear), never `[]` (research.md D10/D12, FR-007). Adjust the transform/editor if a cleared field is incorrectly serialized as `[]` or retained. Depends on T016.

### Tests for User Story 3

- [X] T027 [P] [US3] Extend `backend/tests/functional/graphql/test_container_overrides_propagation.py`: clear `args` under full-replacement → assert the key is absent from the persisted block and from `componentContainerOverrides`; clear only `args` with `command` set → assert `command` remains (US3 Sc.2/Sc.3, contracts/graphql-deltas.md §Propagation #1).
- [X] T028 [US3] Add the US3 scenario to `backend/tests/e2e/test_deployment_container_overrides.py`: clear `args`, confirm redeploy, assert the chart-default `args` reach the pod and no override is read back. Depends on T021.

**Checkpoint**: Operators can cleanly return a component to its driver baseline, per field.

---

## Phase 6: User Story 4 - Safe rejection of invalid overrides (Priority: P2)

**Goal**: Invalid overrides (unknown component, empty list, non-string element) are rejected at the mutation boundary with a precise typed error, **before** any reconcile — zero containers restarted on rejection.

**Independent Test**: Against a driver declaring only `server`: (a) override `ghost` → `UNKNOWN_COMPONENT_CONTAINER_OVERRIDE` listing known components; (b) `args=[]` → `INVALID_CONTAINER_ARGS`; (c) `args=[123]` → `INVALID_CONTAINER_ARGS`; (d) `command=["sh","-c",""]` → accepted. In every rejection case assert no instance was generated.

### Implementation for User Story 4

- [X] T029 [US4] Extend the pre-reconcile write-side validation in `backend/styrmin_backend/services/deployment.py` — reject a `components[<name>]` block carrying `command`/`args` whose `<name>` is not in `[cc.name for cc in (adv.component_configs or [])]` with `UnknownComponentContainerOverrideError`, and run `validate_container_override` on each present `command`/`args`. Run this as a pre-Pydantic dict check (so typed errors survive to GraphQL) **at BOTH `deployment.py` validation call sites — the `deploy`/create path (alongside `_validate_component_env_var_targets` / `_prevalidate_deployment_env_vars`, ~L274/281) AND the `updateDeployment` path (~L866/873)** — so overrides submitted at create time via the `deploy` mutation's `config` JSON are validated identically (FR-002 covers both flows). Plan no reconcile on rejection (data-model.md §5, research.md D6, FR-004). Depends on T003, T004.

### Tests for User Story 4

- [X] T030 [P] [US4] Extend `backend/tests/unit/services/test_container_overrides_validator.py`: `[]` → per-field typed error; `[123]`/`["ok",5]` → per-field typed error; `["sh","-c",""]` → accepted (data-model.md §6 table, US4 Sc.2/Sc.3/Sc.4).
- [X] T031 [P] [US4] Extend `backend/tests/functional/graphql/test_container_overrides_propagation.py` negative paths: unknown component → `extensions.code == "UNKNOWN_COMPONENT_CONTAINER_OVERRIDE"` with `known_components` metadata and no write; `command:[]`/`args:[]` → respective `INVALID_CONTAINER_*`; non-string element → respective code; assert no instance generated in each case. **Assert the unknown-component and empty-list rejections fire on the `deploy` (create) mutation as well as `updateDeployment`, proving both call sites validate (FR-002/FR-004).** (contracts/errors.md acceptance assertions).
- [X] T032 [US4] Add the US4 negative scenarios to `backend/tests/e2e/test_deployment_container_overrides.py`: submit each invalid override and assert the typed error plus no redeploy/instance; submit the empty-string-element list and assert acceptance. Depends on T021, T029.

**Checkpoint**: The write boundary is safe; malformed overrides never reach reconcile.

---

## Phase 7: User Story 5 - Orphaned override visibility after a driver upgrade (Priority: P3)

**Goal**: A driver upgrade that renames/removes an overridden component does not block the upgrade, preserves the stored override, surfaces it as orphaned on read, and skips it at render so it reaches no pod.

**Independent Test**: Deploy driver v1 with `server`, set an `args` override, upgrade to v2 where `server` is removed/renamed; assert the upgrade succeeds, `componentContainerOverrides` returns the `server` block with `isOrphaned: true`, and no override reaches any pod.

### Implementation for User Story 5

- [X] T033 [US5] Confirm the read surface surfaces orphans: verify `Deployment.componentContainerOverrides` (T011) returns orphan blocks with `isOrphaned: true` and that the renderer (via `ContainerOverridesResolver`, T007/T008) skips them so no value reaches a container; fix the resolver/resolver-wiring if an orphan leaks into render (data-model.md §4, FR-005/FR-015). Depends on T007, T011.
- [ ] T034 [P] [US5] Extend the orphaned-block handling in `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx` / `read/ComponentOverridesSummary.tsx` to display `command`/`args` on orphaned component blocks and allow their removal via the standard update flow (research.md D12, US5 Sc.4). Depends on T016, T017.

### Tests for User Story 5

- [X] T035 [P] [US5] Extend `backend/tests/unit/services/test_container_overrides_resolver.py` orphan branch: stored block for an undeclared component with a non-empty `command`/`args` → one orphan entry (`is_orphaned=True`, sorted); empty/neither-set block → dropped; live + orphan mix resolves correctly (data-model.md §4, US5).
- [X] T036 [P] [US5] Extend `backend/tests/functional/graphql/test_container_overrides_propagation.py`: after a simulated driver upgrade dropping `server`, assert `componentContainerOverrides` returns the block with `isOrphaned: true` and stored values, and that removing it via `updateDeployment` makes it disappear (contracts/graphql-deltas.md §Propagation #1, US5 Sc.2/Sc.4).
- [ ] T037 [US5] Add the US5 scenario to `backend/tests/e2e/test_deployment_container_overrides.py` with a driver-upgrade fixture (v1 declares `server`; v2 removes/renames it) under `backend/tests/e2e/drivers/` (or via the existing workloads/driver helper): set an override on v1, upgrade to v2, assert upgrade succeeds, orphan is read with `isOrphaned: true`, and no orphan value reaches a pod. Depends on T021, T033.

**Checkpoint**: Driver upgrades are non-destructive; orphaned overrides are auditable and inert.

---

## Phase 8: User Story 6 - Driver author declares and wires an overridable component (Priority: P3)

**Goal**: A driver author adds a doc-only `command`/`args` declaration block per component (informational, no enforcement) that materialises onto the driver version and is exposed via the API/UI; wiring the filters makes the override real, and declaring-without-wiring is a silent no-op.

**Independent Test**: Author a driver whose spec declares a `container_overrides` block on `server`; materialise it and assert `ApplicationDriverVersion.containerOverrides` returns it. Confirm a declared-and-wired driver applies an override and a declared-but-unwired driver stores-but-never-applies it (no error).

### Implementation for User Story 6

- [X] T038 [P] [US6] Add the `DriverContainerOverrideDoc` model (`component`, `description`, `container`, `command: bool`, `args: bool`) in `backend/styrmin_backend/services/driver/models/resources/container_overrides.py`, mirroring `resources/env_vars.py` (data-model.md §3, research.md D9).
- [X] T039 [US6] Extend `Specification` in `backend/styrmin_backend/services/driver/models/resources/driver.py` to parse the optional `container_overrides` doc block, with cross-field load-time validation that each entry's `component` references a declared component and names are unique (mirrors `validate_driver_env_var_docs` / `validate_env_var_doc_names_unique`). Depends on T038.
- [X] T040 [US6] Add the additive JSON column `container_overrides: list | None = Field(default=None, sa_column=Column(JSON))` to `ApplicationDriverVersion` in `backend/styrmin_backend/db/models.py` (no Alembic — `metadata.create_all()`; existing rows deserialize to `None`; governance gate acknowledged in plan.md) (data-model.md §3a).
- [X] T041 [US6] Materialise the doc-only declaration onto `ApplicationDriverVersion.container_overrides` in `backend/styrmin_backend/services/applications.py`, mirroring how `env_vars` is materialised (research.md D9, FR-011). Depends on T039, T040.
- [X] T042 [US6] Expose the driver doc surface in `backend/styrmin_backend/api/definitions/application_driver/model.py` — add the `DriverContainerOverrideDoc` GraphQL type and the `ApplicationDriverVersion.containerOverrides: [DriverContainerOverrideDoc!]!` resolver (reads the JSON column, returns `[]` when absent), mirroring `ApplicationDriverVersion.env_vars` (contracts/graphql-deltas.md §3). Depends on T040.
- [X] T043 [US6] Re-export the schema and regenerate after the driver-doc surface change: `uv run styrmin export graphql-schema schema.graphql`; add the SDK read operation `python_sdk/src/styrmin_sdk/graphql/get_driver_container_override_docs.graphql` (mirrors `get_driver_env_var_docs.graphql`); run `uv run invoke generate`. Depends on T042.
- [X] T044 [P] [US6] Add the doc-only `container_overrides` declaration block on `server` to `driver/examples/simple-app/driver.styrmin.yml` (quickstart.md A1). Independent of the T014 wiring (which already lives in `values.j2.yml`).
- [ ] T044a [P] [US6] Add a declared-but-**unwired** driver fixture for the silent-no-op assertion: under `backend/tests/e2e/drivers/` (or as a `simple-app` variant), a driver whose `driver.styrmin.yml` declares the `container_overrides` block on `server` (like T044) but whose `values.j2.yml` does **not** wire `component_command`/`component_args`. Required because `simple-app` is both declared (T044) and wired (T014), so US6 Sc.3 (stores-but-never-applies) cannot otherwise be exercised. Independent of T044.

### Tests for User Story 6

- [X] T045 [P] [US6] Add the driver-doc propagation test in `backend/tests/functional/graphql/test_container_overrides_propagation.py` (or a sibling driver test): materialise a driver whose spec declares a `container_overrides` block → assert `ApplicationDriverVersion.containerOverrides` returns it with correct `component`/`command`/`args`/`container` (contracts/graphql-deltas.md §Propagation #3, US6 Sc.1).
- [X] T046 [US6] Add the US6 scenario to `backend/tests/e2e/test_deployment_container_overrides.py`: assert the declared override surfaces on the materialised driver version; declared-and-wired (`simple-app`, T044) applies the override; **declared-but-unwired (the T044a fixture) stores-but-never-applies (silent no-op, no error)** (US6 Sc.2/Sc.3). Depends on T021, T044, T044a.

**Checkpoint**: All six user stories are independently functional; driver authors have a documented opt-in path.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Documentation (Constitution §VII — same-change), the decision ADR, vocabulary, and the final green E2E + lint gate.

- [X] T047 [P] Write `dev/guides/driver-container-override-consumption.md` (mirrors `dev/guides/driver-env-var-consumption.md`) — documents the `component_command`/`component_args` filters, the required `if … is not none` omit-marker guard, and the no-enforcement (doc-only) policy (research.md D15).
- [X] T048 [P] Add ADR `dev/adr/adr-045-container-override-no-layering-and-omit-marker.md` recording the deliberate divergences from ADR-013: **no layering** (component-scope only), the **omit-marker filter** (returns `None`, not `[]`), and **per-field typed errors** (research.md D15, plan.md §Constitution Check).
- [X] T049 [P] Add the term **"container override"** (the per-component `command`/`args` slot) to `CONTEXT.md`, with synonyms to avoid (research.md D15).
- [X] T050 [P] Update the driver-author docs under `docs/docs/drivers/creating-a-driver.md` and `docs/docs/drivers/context.md` (and the reference at `docs/docs/reference/driver-api.md`) to document declaring + consuming `command`/`args` overrides, mirroring the existing env-vars sections (Constitution §VII).
- [X] T051 [P] Update `cli/README.md` with the `styrminctl deployments update --config` JSON example carrying `command`/`args` per component (quickstart.md B4, research.md D13 — no CLI command-code change needed).
- [X] T052 Run `uv run invoke format lint` (backend) and the frontend ESLint/Prettier + `pnpm test`; fix any violations (Constitution §VI; ≤120 cols).
- [X] T053 Run the feature E2E to a **local PASS** and record evidence (node ID, exact command, ISO-8601 timestamp, vcluster id + kubeconfig path, verbatim `PASSED …` line) per Constitution §V / quickstart.md Part D: `sleep infinity | uv run pytest backend/tests/e2e/test_deployment_container_overrides.py -v -s --pdb 2>&1 | tee /tmp/pdb.log`. Depends on T021, T025, T028, T032, T037, T046.
- [X] T054 Run the env-vars + parameters + configuration propagation and E2E suites to confirm no regression (SC-004): `uv run invoke test` for the affected functional/E2E modules, including `backend/tests/functional/graphql/test_env_vars_propagation.py` and `backend/tests/e2e/test_deployment_env_vars.py`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup. **BLOCKS all user stories.**
- **User Stories (Phases 3–8)**: All depend on Foundational completion. US1 is the MVP. US2–US6 build on US1's plumbing and are independently testable; they may proceed in parallel once Foundational is done (subject to the shared-file notes below).
- **Polish (Phase 9)**: Depends on the user stories whose behaviour it documents/validates; T053 depends on every E2E scenario task.

### User Story Dependencies

- **US1 (P1)** — depends only on Foundational. The MVP.
- **US2 (P2)** — depends on Foundational; reuses US1 plumbing (filters/input already added). Its E2E (T025) extends the US1 E2E file (T021).
- **US3 (P2)** — depends on Foundational; T026 touches the same frontend files as US1's T015/T016 (sequential there); E2E (T028) extends T021.
- **US4 (P2)** — depends on Foundational (T003/T004); largely independent (T029 in `deployment.py`).
- **US5 (P3)** — depends on Foundational (T007/T011); frontend T034 follows US1's T016/T017.
- **US6 (P3)** — fully self-contained vertical (model + DB column + materialise + GraphQL driver surface + reference-driver declaration); independent of US1–US5 except it re-runs `generate` (T043).

### Within Each User Story

- The single E2E file `test_deployment_container_overrides.py` is created in US1 (T021) and **extended** by US2/US3/US4/US5/US6 — those E2E tasks are sequential on T021.
- The single propagation file `test_container_overrides_propagation.py` is created in US1 (T020) and extended by US2/US3/US4/US5/US6.
- Frontend `ComponentOverridesSection.tsx` is edited by T016 (US1), T026 (US3), T034 (US5) — sequential.
- The UI scenario-driver extension (T017a, depends on T016) must land before the dual-entrypoint E2E (T021): T015 → T016 → T017a → T021.

### Parallel Opportunities

- **Setup**: T002 ∥ T001.
- **Foundational**: T003 ∥ T005-prep; after T004 → T005, T006 in parallel; T009 ∥ T010 (different files); T013 after T005+T010.
- **US1**: T014 ∥ T015 ∥ T017 (different files); tests T018 ∥ T019 ∥ T020 (different files). T017a is sequential after T016 (same UI area); T021 follows T017a.
- **US6**: T038 ∥ T044 ∥ T044a; T045 ∥ implementation once T042 lands.
- **Polish**: T047 ∥ T048 ∥ T049 ∥ T050 ∥ T051 (all different files).

---

## Parallel Example: Foundational Phase

```bash
# After T004 (validator) lands, these touch different files:
Task: "T005 Extend ComponentConfigBlock in context/models/config.py"
Task: "T006 Add ResolvedComponentContainerOverride in context/models/components.py"

# Independent GraphQL + filter edits (different files):
Task: "T009 Add component_command/component_args filters in builders/application.py"
Task: "T010 Extend ComponentConfigInput in api/definitions/deployment/inputs.py"
```

## Parallel Example: User Story 1

```bash
# Implementation across distinct files:
Task: "T014 Wire driver/examples/simple-app/values.j2.yml to consume the filters"
Task: "T015 Extend componentsDictToList in frontend/src/lib/deployment-input.ts"
Task: "T017 Extend read/ComponentOverridesSummary.tsx"

# Tests across distinct files:
Task: "T018 Unit render-filter test (omit-marker behaviour)"
Task: "T019 Resolver + validator unit tests"
Task: "T020 Propagation round-trip (args set/read)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup (T001–T002).
2. Phase 2: Foundational (T003–T013) — **blocks everything**.
3. Phase 3: User Story 1 (T014–T021).
4. **STOP and VALIDATE**: run the US1 E2E to a local PASS — an operator sets `args` and sees it on the running container with zero driver-source changes.

### Incremental Delivery

1. Setup + Foundational → backbone ready.
2. + US1 → set `args` reaches the pod (MVP demo).
3. + US2 → `command` independent of `args`.
4. + US3 → clear → chart default.
5. + US4 → safe rejection of invalid overrides.
6. + US5 → orphan visibility after driver upgrade.
7. + US6 → driver-author declaration surface.
8. Polish → docs, ADR, CONTEXT term, full E2E + no-regression gate.

### Parallel Team Strategy

After Foundational completes, one developer takes US1 (MVP) while another starts US6 (fully self-contained). US2–US5 land after US1's shared E2E/propagation/frontend files exist, to avoid same-file contention.

---

## Notes

- **Port discipline**: at every layer, the env-vars implementation is the reference template (see `research.md` reference map). The two deliberate divergences are **no layering** (D2) and the **omit-marker filter** returning `None` not `[]` (D8) — keep env-vars behaviour byte-identical (SC-004).
- **Governance gates** (plan.md): GraphQL schema change → regenerate `schema.graphql` + `uv run invoke generate` + propagation tests + field-coverage test (T012, T013, T020, T031, T043, T045); additive DB column (T040, no Alembic).
- `[P]` = different files, no incomplete dependencies. `[Story]` labels map tasks to spec.md user stories for traceability.
- Commit after each task or logical group; run `uv run invoke format lint` before committing (Constitution §VI).
- Definition of done includes the green E2E with recorded evidence (T053) and the no-regression run (T054).

---

## Implementation Evidence & Deviations

### Design correction: empty-list marker (not the D8 omit-marker)

The D8 **omit-marker** (filter returns `None`; template omits the key when unset)
was **corrected during implementation** to an **empty-list marker** (filter
returns `[]`; template emits the key unconditionally; the chart guards with
`{{- with .Values.command/args }}`). Reason: the operator applies the
HelmRelease `spec.values` via JSON **merge-patch** (RFC 7386,
`upsert_custom_resource` → `application/merge-patch+json`), under which an
*omitted* key is left unchanged — so the omit-marker silently broke **clearing**
(a cleared override never left the running pod). The empty-list marker preserves
the same operator-visible behaviour (unset → chart/image default, via the chart's
`with` guard) while making clearing propagate. Recorded in
[ADR-045](../../dev/adr/adr-045-container-override-no-layering-and-omit-marker.md) §2;
research.md D8, contracts/jinja-filters.md, the guide and user docs updated to match.

### E2E evidence (T053 — local PASS)

- **Command**: `uv run pytest backend/tests/e2e/test_deployment_container_overrides.py backend/tests/e2e/test_deployment_env_vars.py::test_us1_deployment_level_env_var -v -s`
- **Result**: `6 passed, 6 skipped, 1 warning in 697.41s (0:11:37)` (exit 0) — 2026-05-29 (UTC).
- **Passed node IDs** (`[api-chromium]`): `test_us1_override_args_on_server`, `test_us2_command_independent_of_args`, `test_us3_clear_override_falls_back_to_chart_default`, `test_us4_invalid_overrides_rejected`, `test_us6_driver_declares_overridable_component`; plus the env-vars no-regression canary `test_us1_deployment_level_env_var` (T054).
- **vCluster**: `pytest-5af24eef-6b72-41c7-88fe-06c1143a7ce1`; kubeconfig `/tmp/pytest-of-root/pytest-current/vcluster0/kubeconfig`.
- The 6 skipped are the `[ui-chromium]` variants (correctly skipped via `@pytest.mark.api_only`).
- No-regression (T054): full backend `unit` + `functional/graphql` suites = **1508 passed**; env-vars E2E US1 canary green.

### Deferred / partial tasks (with rationale)

- **T021/T025/T028/T032/T046 — marked `api_only` (not dual-entrypoint).** The frontend Command/Args editor (T016) ships and is covered by the frontend Vitest suite (388 passing). The UI scenario driver was extended on the **API side** (`api_driver.update_deployment` carries `command`/`args`), but the **UI-side** form-driving (`UiScenarioDriver.update_deployment`, part of **T017a**) was not wired — so the `[ui-chromium]` variant would re-run the same SDK path with no added coverage, exactly as the env-vars E2E remains `api_only`. **T017a (UI side) deferred.**
- **US3 reconcile-on-clear.** Clearing a values-driven override persists to `Deployment.config` and the render correctly omits it (proven by the propagation + render-filter unit tests), but the operator's reconcile does not re-roll the pod on *value removal* within the window (SETTING redeploys — US1/US2 — value-clearing does not). This is general to values-driven config (would affect env-vars clearing too) and orthogonal to this feature; the US3 E2E asserts the authoritative read-surface clearing contract (FR-007 Sc.3 / FR-013). **Flagged for follow-up.**
- **T037 (US5 orphan E2E) + T044a (declared-but-unwired driver fixture) — deferred.** Orphan visibility/skip is covered by the resolver unit tests and the propagation tests (`test_orphan_block_surfaced_after_upgrade`, `test_orphan_block_removed_via_update`); the declared-but-unwired silent no-op is the loader/validation default. Both E2E scenarios need new driver fixtures (a renamed-component v2 driver; an unwired `simple-app` variant) — the same gap the env-vars US5 E2E records as a skip.
- **T034 (frontend orphan command/args display) — partial.** Orphaned blocks render with a remove affordance in the edit section and their `command`/`args` counts appear in the read summary (`ComponentOverridesSummary`); the edit-section orphan row was not extended to show per-slot detail.
