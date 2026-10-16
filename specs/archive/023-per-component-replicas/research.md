# Research: Per-Component Replica Counts

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-15

Every unknown in the plan's Technical Context is resolved below. Each decision lists what was chosen, why, and what was rejected. File references are to `develop` at `ef9101d6` plus this branch.

## D-001: Where the replica override is stored

**Decision**: Add `replicas: int | None = None` to [`ComponentConfigBlock`](../../backend/styrmin_backend/context/models/config.py) (the per-component block of `DeploymentConfig.components`). A `mode="before"` validator rejects a value that is not an integer, a `bool`, or an integer below 1 with the typed `InvalidReplicaCountError` (`INVALID_REPLICA_COUNT`), the way the `command`, `args` and `image` validators raise their typed errors before type conversion. `None` (or omitting the key) means "no override". Values above 2147483647 are rejected with the same error, because Kubernetes `spec.replicas` is an `int32` and a larger value would fail only when helm-controller applies the release (critique E3).

**Rationale**:

- The block already stores every other per-component override (`env_vars`, `command`, `args`, `image`), and `Deployment.config` is a JSON column, so the change needs no table and no migration ([ADR-029](../../dev/adr/0029-config-additions-via-baseconfigsection-no-migration.md)). Rows written before the change have no `replicas` key and read as `None`.
- A `before` validator is the only way to keep `True` (a `bool` is an `int` in Python) and `"2"` out of the stored config with a typed error rather than a Pydantic `VALIDATION_ERROR`.
- The `test_component_config_input_field_coverage` guard requires `ComponentConfigInput` to have the same fields as the block plus `name`, so the input gains `replicas` in the same change (D-009).

**Alternatives considered**:

- A `replicas` column on the `component` table, as the issue proposed. Rejected by the PRD: it needs a migration and splits per-component overrides across two stores.
- Storing `0` as "stopped". Rejected: `Component.enabled` already records the stopped state, and the PRD keeps scaling and stopping separate (FR-004, FR-005).

## D-002: Where the driver default and the singleton flag are declared and parsed

**Decision**: Add two typed fields to [`ArbitrarySectionModel`](../../backend/styrmin_backend/services/driver/models/resources/driver.py) (the component model of the driver specification file): `replicas: StrictInt | None = Field(default=None, ge=1, le=2147483647)` and `singleton: StrictBool = False`, plus a `model_validator(mode="after")` that raises `ValueError` when `singleton` is true and `replicas` is greater than 1. A Pydantic error becomes a `DriverLoadingError` with the field path (for example `spec.components.database`), as `container` errors do today, so the driver version is not stored.

**Rationale**:

- `ArbitrarySectionModel` uses `extra="allow"`. Today a `replicas` key is accepted and stored untyped, with no check. Typed fields make the load fail early (FR-006, user need 12) and give readers a typed default.
- `StrictInt` rejects `true`, `"2"` and `2.0`; `ge=1` rejects `0` and negative values.
- The declaration reaches the agent unchanged: `ComponentContext.config` is the same `ArbitrarySectionModel`, so the patch builder reads `component.config.replicas` and `component.config.singleton` with no new context field for the driver side.
- Storage is JSON in two places, `ApplicationDriverVersion.components` and `ComponentConfig.config` ([`db/models.py`](../../backend/styrmin_backend/db/models.py)). Rows of driver versions loaded before the change have no keys; the typed model and the GraphQL resolvers default them to `None` and `false`, as the `container` resolver defaults a missing container. No migration.

**Serialisation** (critique E1): `ArbitrarySectionModel` serialises `replicas` only when it is not `None` and `singleton` only when it is `true` (a `model_serializer(mode="wrap")` that removes the two keys at their defaults). Without this, every `model_dump()` of every component would gain `replicas: null, singleton: false`: the stored declaration of new driver versions, the `ComponentContext.config` written into the `StyrminDeployment` resource, and the instance that `_update_is_noop` compares. The first update after a Styrmin upgrade would then differ from the stored instance only by these keys and start a HelmRelease upgrade that changes nothing, against SC-006. A unit test checks that a declaration without the keys dumps to the same dict as before the change.

**Reading stored declarations**: the agent and operator parse each component's stored declaration into `ArbitrarySectionModel` when they build `ComponentContext`. A driver version stored before this change may hold an untyped `replicas` or `singleton` extra that the new typed fields reject (for example `replicas: "3"`). So that such a deployment keeps rendering, the context resolver parses the stored declaration with a helper `parse_stored_component_declaration(raw)` that, on a validation error limited to `replicas` or `singleton`, drops both keys, logs a warning naming the driver version and component, and parses again. The driver load path does not use the helper, so new driver versions are always checked strictly.

**Alternatives considered**:

- A validator in [`services/driver/validators.py`](../../backend/styrmin_backend/services/driver/validators.py) that reads `__pydantic_extra__["replicas"]`, like the backup validator. Rejected: the backup config is a free-form block; `replicas` and `singleton` are two scalars that the model can type directly.

**Risk recorded**: a third-party driver version that already declares an undocumented `components.<name>.replicas` key starts to have it applied after the upgrade. `driver/DRIVERS.md` documents "Additional fields allowed", and no in-repo driver uses the key. The changelog fragment states this (Risks table in [plan.md](plan.md)).

## D-003: One replica resolver for the patch, the write checks and the read field

**Decision**: A new package `services/replicas/` with [`resolver.py`](../../backend/styrmin_backend/services/replicas/resolver.py):

- `ReplicaSource` is a `StrEnum` with `OVERRIDE`, `DRIVER_DEFAULT` and `CHART`.
- `ResolvedReplicas` is a frozen dataclass: `count: int | None` (`None` only when the source is `CHART`), `source: ReplicaSource`, `override_applies: bool`.
- `resolve_replicas(*, declared_replicas: int | None, singleton: bool, override: int | None, is_orphaned: bool) -> ResolvedReplicas` implements FR-002 and FR-007:
  1. An orphaned override never applies. The read field reports it; there is no component to patch.
  2. A valid override wins: source `OVERRIDE`.
  3. Otherwise the driver default: `declared_replicas`, or `1` when `singleton` is true and `replicas` is not declared. Source `DRIVER_DEFAULT`.
  4. Otherwise `count=None`, source `CHART`: no patch.
  5. Defence in depth: an override above 1 on a singleton component cannot be stored (D-005, D-006), but if one is read, it does not apply, and the singleton's count of 1 is used.
- `replica_patch_count(resolved: ResolvedReplicas, *, enabled: bool) -> int | None` returns `0` for a stopped component, otherwise `resolved.count`.

The patch builder (D-004), the write validator (D-005) and the GraphQL read field (D-009) call these two functions, so the order of precedence lives in one place.

**Rationale**: the PRD asks for one function that "the patch builder, the write validation and the GraphQL read field all call". Keeping the stopped state out of `resolve_replicas` lets the read field report the count the component returns to when it is started (user need 8) while the patch still writes 0.

**Alternatives considered**: a `STOPPED` source. Rejected: the PRD lists three sources, and `Deployment.components[].enabled` already reports the stopped state.

## D-004: How the replica patch reaches the workloads

**Decision**: Replace `ApplicationHelmReleaseBuilder.build_components_state_post_rendering_patches` in [`builders/application.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py) with a component replica patch builder (new module [`services/replicas/patch_builder.py`](../../backend/styrmin_backend/services/replicas/patch_builder.py), `build_component_replica_patches(context) -> list[TargetPatch]`, called from the same place in `build()`). For each component and each kind in `("Deployment", "StatefulSet")` it emits at most one patch:

- stopped component: `SpecPatch(specs={"replicas": 0})` (today's behaviour);
- running component with `replica_patch_count(...)` not `None`: `SpecPatch(specs={"replicas": N})`;
- otherwise no patch.

The target is the component's label selector (`identifier.label.label_selectable()`) and the kind, as today. The patch keeps the fourth position in the post-renderer list, before the backup, scheduling and component container patches.

**Rationale**:

- One patch per kind per component means no two patches write `/spec/replicas` on the same workload, so the result does not depend on kustomize's list order (the research found no test of two scalar writes to the same path).
- `SpecPatch` renders a JSON6902 `add` op on `/spec/replicas`. RFC 6902 `add` replaces an existing member and creates a missing one, so it works whether or not the chart renders `replicas`.
- Only `Deployment` and `StatefulSet` are targeted: ADR-057 §2 excludes `Job`, `CronJob` and `DaemonSet` because chart Jobs often share the component label. A selector that matches no workload is a no-op (`test_kind_matching_nothing_is_a_no_op`), which covers the spec edge case of a component without a `Deployment` or `StatefulSet`.
- No component container is involved (FR-003), so a component without `container` gets the patch.
- Today no unit test covers the stop patch. The new builder gets unit tests for every branch, and the integration test on real `kubectl kustomize` gets a stopped case and a scaled case.

**Where it runs**: the operator builds the HelmRelease from the context in the `StyrminDeployment` resource ([`operator/pipeline.py`](../../backend/styrmin_backend/operator/pipeline.py)), and the agent's direct-apply flows use the same builder. `postRenderers` is replaced as a whole key on every update (ADR-057 §6), so clearing an override removes its patch and Helm applies the chart's count again.

**Alternatives considered**:

- A second builder that emits a replica patch next to the stop patch and relies on list order. Rejected: two writes to one field, and the order is kyaml behaviour, not a documented contract (ADR-057 §3).
- Writing the count into the values template. Rejected by the PRD (ADR-057).

## D-005: Write checks for a replica override

**Decision**: A new [`services/replicas/validator.py`](../../backend/styrmin_backend/services/replicas/validator.py) with `validate_replica_overrides(config, *, driver_version, stored_config, checked_against)`, called from `_validate_config_write` in [`services/deployment.py`](../../backend/styrmin_backend/services/deployment.py) (used by `update_deployment` with the bound driver version and by `update_deployment_version` with the target driver version) and from the create path in `deploy_application`, which repeats the checks with `stored_config=None`. It checks each component block's `replicas`:

1. `INVALID_REPLICA_COUNT`: raised by the `ComponentConfigBlock` validator (D-001) for a value below 1 or not an integer. The message tells the user to stop the component instead (FR-004).
2. `UNKNOWN_COMPONENT_REPLICA_OVERRIDE`: an added or changed override on a component the driver version does not declare. An unchanged stored override on such a component is accepted and kept (FR-009), as for image overrides.
3. `SINGLETON_REPLICA_OVERRIDE`: an override greater than 1 on a component that the driver version marks `singleton: true`. This check does **not** skip an unchanged stored value (spec edge case), because the stored count breaks the rule of the version the deployment is bound to after the write. An override of exactly 1 is accepted (FR-008).

All checks run before any task, flow run or ingress dispatch, as the image override checks do.

**Rationale**:

- `styrminctl deployments apply` has no separate server path: the SDK sends `updateDeploymentVersion(input:)`, so the checks cover it (SC-003).
- Every other per-component override kind has its own unknown-component code (`UNKNOWN_COMPONENT_ENV_VAR`, `UNKNOWN_COMPONENT_IMAGE_OVERRIDE`, `UNKNOWN_COMPONENT_CONTAINER_OVERRIDE`). A fourth code for replicas follows that pattern; the PRD's list of new codes covers only the rules it introduces, and this check is the existing rule applied to the new slot.
- `COMPONENT_CONTAINER_NOT_DECLARED` does not apply: the replica patch targets the workload, not a container (FR-003). `_validate_component_container_targets` keeps its slot list (`env_vars`, `image`, `command`, `args`).

**Error metadata** (see [contracts/errors.md](contracts/errors.md)): `component_name`, `requested_replicas`, and for the unknown-component code `known_components` and `checked_against`.

## D-006: A replica override on a driver version change

**Decision**: `update_deployment_version` already validates the submitted config (or the stored config when nothing is submitted) against the **target** driver version through `_validate_config_write`. D-005's checks run there with the target version's components, so:

- a stored override above 1 on a component the target marks as singleton rejects the change with `SINGLETON_REPLICA_OVERRIDE` (spec Story 4 scenario 6), unless the same request lowers it to 1 or clears it;
- an override on a component the target no longer declares is kept and reported as not applicable (FR-009), and does not fail the change.

**Rationale**: the image override check before a version change ([ADR-058](../../dev/adr/0058-image-overrides-and-component-container-guard.md)) set this pattern; the replica check uses the same call site, so no new hook is needed.

## D-007: Rule for parameters the target driver version no longer declares (FR-010)

**Decision**: In `update_deployment_version`, before `validate_parameter_values` runs against the target version, apply `drop_retired_parameters(effective, *, current_definitions, target_definitions)` from a new [`services/parameters/retired.py`](../../backend/styrmin_backend/services/parameters/retired.py). `effective` is the parameter map the service already builds: the `parameters` argument (or the stored values when it is null) merged with `input.parameters`. For each key that the current driver version declares and the target version does not:

- if the value equals the current version's default (same type and same value: `type(v) is type(d) and v == d`), drop the key;
- otherwise raise `RetiredParameterValueError` (`RETIRED_PARAMETER_VALUE`) with `parameter_name`, `value`, `default`, `driver_version` (the target) and a message that says how to resolve it (FR-010a).

Keys that neither version declares are left to `validate_parameter_values`, which rejects them as unknown parameters as it does today. `update_deployment` and `deploy_application` do not change, because they do not change the driver version.

**Rationale**:

- Today the change is rejected for any retired key with `OPERATION_FAILED` "Unknown parameter: 'X'" ([`services/parameters/validator.py`](../../backend/styrmin_backend/services/parameters/validator.py)). The only way around it is to pass the top-level `parameters` map, which the UI upgrade dialog cannot do.
- `validate_parameter_values` fills in every default, so every stored parameter map holds `replicas_server` and `replicas_task_worker`, even when the user never set them. Without the rule, every `infrahub` deployment would need a manual step (SC-004).
- The rule applies to the merged map, not only to the stored values, so a `styrminctl deployments apply` manifest that still lists `replicas_server: 1` moves to the new version, and one that lists `replicas_server: 3` gets the error that names the parameter and the value instead of "Unknown parameter". The PRD states the rule for stored values; applying it to a resubmitted default gives the same result as omitting it.
- Strict type equality keeps `"1"` and `1.0` from matching an integer default (spec edge case).
- A value is dropped only when it equals the **current** version's default, which is the value the chart rendered when the user never changed it. Comparing with any default the target may have does not apply: the target no longer declares the parameter.
- The rule is generic: it applies to any driver that retires a parameter, not only to the replica parameters.

**Alternatives considered**:

- Dropping every retired value silently. Rejected by the PRD: a changed value would change a pod count without the user's knowledge (user need 14).
- A driver format feature that maps a retired parameter to a replica override. Out of scope in the PRD.

## D-008: How the update task waits for the new count

**Decision**: No change. The PRD's statement holds for both paths that apply a deployment:

- The direct-apply flows poll each `Deployment` and `StatefulSet` against its own `spec.replicas` (`poll_kubernetes_deployments_status`, `poll_kubernetes_stateful_sets_status` in [`agent/tasks/shared.py`](../../backend/styrmin_backend/agent/tasks/shared.py)).
- The `UPDATE_INSTANCE` path writes the `StyrminDeployment` resource; the operator applies the HelmRelease and marks the rollout steps complete only when FluxCD reports the HelmRelease `Ready` ([`operator/handlers/styrmin_deployment.py`](../../backend/styrmin_backend/operator/handlers/styrmin_deployment.py)). helm-controller waits for the release's workloads with kstatus, which treats a `Deployment` as current only when `updatedReplicas`, `readyReplicas` and `availableReplicas` equal `spec.replicas` and `status.replicas` is not above it (so a scale-down waits for the extra pods to terminate). The post-rendered `spec.replicas` is the value it waits for.

The existing wait limit is the HelmRelease `timeout` (`5m`, E2E value from `STYRMIN_OPERATOR_HELM_RELEASE_TIMEOUT`). A scale-up that leaves pods `Pending` fails the task when it runs out (spec edge case).

**Verification**: the E2E (D-012) asserts the workload's counts after the update task completes, for a scale-up and a scale-down.

## D-009: GraphQL surface

**Decision** (full shapes in [contracts/graphql.md](contracts/graphql.md)):

- `ComponentConfigInput.replicas: Int = null`. Full-replacement semantics like the other slots: `null` or omitting it clears the override.
- `Deployment.componentReplicas: [ComponentReplicas!]!`: one row per component the bound driver version declares, plus one row per orphaned override, sorted by component name. Fields: `component`, `count: Int` (null when the source is `CHART`), `source: ReplicaSource!`, `override: Int` (the stored value, applied or not), `singleton: Boolean!`, `isOrphaned: Boolean!`, `isApplicable: Boolean!` (false only when a stored override is not applied).
- `enum ReplicaSource { OVERRIDE DRIVER_DEFAULT CHART }`.
- `ComponentConfig.replicas: Int` and `ComponentConfig.singleton: Boolean!` on a driver version, resolved from the stored config with defaults for older rows, like `container`.

**Rationale**: a dedicated list field follows `componentImageOverrides` and `componentContainerOverrides`, which also report orphaned overrides. Adding the count to `Deployment.components` would leave orphaned overrides out, because those rows exist only for declared components. The resolver calls `resolve_replicas` (D-003).

**Alternatives considered**: reading the chart's rendered count from the cluster to fill `count` for `CHART`. Rejected: the PRD says Styrmin does not patch the chart's count, and the read field must not depend on cluster access. The UI shows "set by the chart" without a number.

## D-010: SDK and `styrminctl`

**Decision**:

- Regenerate the SDK. `ComponentConfigInput.replicas` reaches the manifest model automatically, because `_Spec.config` is validated against the generated input types. `components[].replicas` in a manifest needs no CLI code.
- Add `"replicas"` to `OverrideKind` and to `_inapplicable_overrides`, so `styrminctl deployments apply` warns about an override that is kept but not applied, as it does for the other kinds.
- `get_deployment.graphql` selects `componentReplicas`. `styrminctl deployments get` adds a `Replicas` column to its Components table: `3 (override)`, `2 (driver default)`, `chart`, and `not applied` next to a stored override that does not apply (FR-014). A stopped component adds `stopped: 0 pods` to the cell (critique P4). Orphaned overrides get a row with `no longer declared`.

## D-011: Frontend

**Decision**:

- **Edit drawer** ([`ComponentOverridesSection.tsx`](../../frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx)): add a "Replicas" number field per component, bound to `components.<i>.replicas`, with the resolved value as placeholder text ("2 (driver default)", "set by the chart"). A value below 1 shows "Must be 1 or more. To run no pods, stop the component." A singleton component shows a read-only "1 (singleton)" field; a stored override above 1 on it can only be removed. The `FutureExtensionPlaceholder` text drops "replicas" and keeps CPU and memory. `componentsFormToInput` and `diffComponents` handle `replicas` (empty field means `null`).
- **Create form** ([`DeployFormPage.tsx`](../../frontend/src/pages/deployments/DeployFormPage.tsx)): today it has no per-component section and never sends `config.components`. Add a "Component replicas" section that lists the components of the selected driver version with the same field, and sends `config.components` with only the components that have a value.
- **Configuration view** ([`ComponentOverridesSummary.tsx`](../../frontend/src/components/deployment/configuration/sections/read/ComponentOverridesSummary.tsx)): a "Replicas" line per component, from `componentReplicas`: "3 (override)", "2 (driver default)", "set by the chart", with the existing "not applied" badge for `isApplicable: false`, and "stopped: 0 pods" when the component is stopped (critique P4).
- **Driver version page** ([`ComponentsTab.tsx`](../../frontend/src/pages/drivers/driver-detail/tabs/ComponentsTab.tsx)): explicit "Replicas" and "Singleton" rows from `componentConfigs { replicas singleton }`, and `flattenDecl` skips the two keys so they are not shown twice.
- **Upgrade dialog**: no change (spec Clarifications, question 2). It already shows the mutation's error message, which names the parameter and how to resolve it.

## D-012: E2E coverage

**Decision**: Extend [`backend/tests/e2e/test_deployment_image_override.py`](../../backend/tests/e2e/test_deployment_image_override.py) (`shard_configuration`) with one dual-entrypoint `ci` test node, `test_scale_server_and_singleton_guard`, that reuses its module-scoped `simple-app` deployment `image_override_deployment` (PRD Testing Decisions: "this extends an existing test that already deploys `simple-app`"). A finalizer clears the `server` override so the module's image tests see one replica whatever the order and outcome. The steps:

1. `scenario_driver.set_component_replicas(component="server", replicas=2)` (new protocol method: API through `_replace_component_slots(slots={"replicas": 2})`, UI through `DeploymentDetailPage.set_component_replicas`); wait for the update task to complete; then read the `styrmin-simple-app` `Deployment` **once** (no polling) and assert `updatedReplicas`, `readyReplicas`, `availableReplicas` and `status.replicas` all equal 2, and `componentReplicas` reports `2`/`OVERRIDE`. Reading once after the task, instead of waiting for the counts, is what proves that the task itself waited for the pods (SC-002, critique E7).
2. Assert the `database` `StatefulSet` has 1 ready replica and `componentReplicas` reports `1`/`DRIVER_DEFAULT`/`singleton: true`. In the UI variant, assert the drawer shows `database` fixed at 1.
3. Through the SDK client in both variants, submit `database` replicas 2 and assert `SINGLETON_REPLICA_OVERRIDE`, no new task, and the stored config unchanged.
4. `set_component_replicas(component="server", replicas=None)` (clear); wait for the update task; read the `Deployment` once and assert all counts equal 1 (so the scale-down finished before the task completed), and the source is `CHART`.

To have a singleton component, the `simple-app` example driver marks `database` as `singleton: true` and its version goes from `3` to `4` (D-013). A new helper `read_workload_replicas(apps_api, *, namespace, kind, name)` in [`helpers/workloads.py`](../../backend/tests/e2e/helpers/workloads.py) returns the four status counts and `spec.replicas` in one read.

**Rationale**:

- CI excludes the `api / configuration` cell, so an `api_only` test in this shard never runs in CI ([`ci.yml`](../../.github/workflows/ci.yml) matrix). A dual-entrypoint node runs in the `ui / configuration` cell in CI and in the `api` cell locally. The singleton rejection goes through the SDK client in both variants, so it runs in CI too.
- Reusing `image_override_deployment` follows "reuse before you boot" and the PRD; no new deployment is booted. The image override tests read the pod template of the same workload, which a replica change does not alter, and the test ends at the starting count (step 4 and the finalizer).
- `test_deployment_container_overrides.py` was the other candidate; its fixture records the original `command`/`args` and its tests change the container spec, so the image override module, whose fixture is a plain `simple-app` deployment, is the simpler host.
- The conformance test in `backend/tests/unit/test_e2e_driver_conformance.py` gets a keyword-only check for the new protocol method, as for `set_component_image`.

**Not covered by E2E** (spec Clarifications, question 3): the `infrahub` driver upgrade (SC-004, SC-005) and the stop/start interaction (FR-005). D-014 lists their functional and unit tests.

## D-013: Example drivers

**Decision**:

- `infrahub` version `4` → `5` and `infrahub-enterprise` version `3` → `4`: remove the `replicas_server` and `replicas_task_worker` parameters and the two `replicas:` lines in `values.j2.yml`; declare `server: replicas: 1`, `task-worker: replicas: 2`, and `singleton: true` on `database`, `task-manager-db` and `cache` (FR-011 and spec Clarifications; critique P2). The charts' own defaults are the same counts (`infrahubServer.replicas | default 1`, `infrahubTaskWorker.replicas | default 2`), so the rendered chart and the patch agree.
- `simple-app` version `3` → `4`: `database: singleton: true` (the chart runs a single PostgreSQL primary). The chart already renders 1 replica for it, so every E2E that deploys `simple-app` keeps the same pod count.
- Other example drivers are unchanged. SC-001 holds for them because the override needs nothing from the driver.

**Rationale**: no test pins the example driver version strings; `test_driver_version_reselection.py` computes `int(version) + offset`, so versions stay integer strings.

## D-014: Tests below E2E

| Area | Tests |
|------|-------|
| Resolver | `tests/unit/services/replicas/test_resolver.py`: every row of the order of precedence, singleton without `replicas`, singleton with override 1, defensive singleton with stored override 3, orphaned, `replica_patch_count` with `enabled=False` |
| Patch builder | `tests/unit/services/replicas/test_patch_builder.py`: one patch per kind, stopped → 0, chart → none, no container required; `tests/unit/agent/test_application_builder_replicas.py`: position in the post-renderer list |
| Kustomize | `tests/integration/test_component_container_kustomize.py` (or a sibling): stop patch and replica patch on a chart that renders `replicas: 3` and one that renders none |
| Driver fields | `tests/unit/services/driver/test_component_replicas.py`: valid, `replicas: 0`, `"2"`, `true`, above 2147483647, singleton with `replicas: 3`, singleton with `replicas: 1`, old row without keys, dump without the keys equals the dump before the change, `parse_stored_component_declaration` with an invalid stored value |
| Write checks | `tests/functional/graphql/test_replica_overrides_propagation.py`: round trip on update and create, clear, read field projection (all sources, orphan, singleton), `INVALID_REPLICA_COUNT`, `UNKNOWN_COMPONENT_REPLICA_OVERRIDE`, `SINGLETON_REPLICA_OVERRIDE` on create, update, `updateDeploymentVersion(input:)` (the apply path) and a version change that marks a component singleton, with no task and an unchanged row |
| Retired parameters | `tests/unit/services/parameters/test_retired.py` and functional `test_retired_parameters_propagation.py`: default dropped, changed value rejected with metadata, `"1"` vs `1`, merged `input.parameters`, unknown key still `OPERATION_FAILED` |
| Upgrade hook path | functional test: the infrahub upgrade path (the outer `updateDeploymentVersion`, then the hook primitive's nested `upgrade_deployment_version` on the already-bound target) succeeds with default parameter values and does not apply the retired-parameter rule twice (critique E4) |
| Infrahub upgrade | functional `test_infrahub_replica_parameter_upgrade.py`: loads `infrahub` version 4 from a fixture copy (`tests/fixtures/legacy_drivers/infrahub-v4/`) and version 5 from `driver/examples/`; a deployment with default values moves and resolves `server` to 1 and `task-worker` to 2 (SC-004); one with `replicas_task_worker: 4` is rejected (SC-005); resubmitting with a `task-worker` override of 4 succeeds |
| No change for other drivers | unit test over every example driver except the singleton ones: with no override, the builder emits no replica patch (SC-006) |
| Propagation | one per new field and input: `ComponentConfigInput.replicas`, `Deployment.componentReplicas`, `ComponentConfig.replicas`, `ComponentConfig.singleton` |
| SDK and CLI | `python_sdk/tests/test_deployments.py` (inapplicable replicas), `cli/tests/test_deployments.py` (`get` Replicas column, apply warning) |
| Frontend | Vitest: `ComponentOverridesSection.test.tsx`, `ComponentOverridesSummary.test.tsx`, `DeployFormPage.test.tsx`, `ComponentsTab.test.tsx`, `deployment-input.test.ts`, `config-diff.test.ts` |

## D-015: Documentation

**Decision**: in the same change (Constitution §VII):

- `docs/docs/concepts-and-architecture/replica-overrides.md` (new), modelled on `image-overrides.md`, in `docs/sidebars.ts`; it states that a singleton component can run 2 pods for a short time during a rolling update, and that a component whose pods mount a `ReadWriteOnce` volume (such as the infrahub `server`) can leave extra pods `Pending` on other nodes (critique P5).
- `driver/DRIVERS.md` (schema block and `## Components`) and `docs/docs/drivers/creating-a-driver.md` (Step 3): `replicas`, `singleton`, the load error.
- `docs/docs/drivers/migrating-replica-parameters.md` (new): the infrahub upgrade note: the rule for retired parameters and the two ways to resolve a rejection (one API request, or the edit drawer then the upgrade).
- `docs/docs/concepts-and-architecture/glossary.md`: replica override, singleton component.
- `docs/docs/reference/styrminctl.md`: `deployments get` Replicas column; `components[].replicas` in manifests.
- `dev/adr/0070-replica-overrides-and-retired-parameters.md` (new): FR-002 order of precedence, the single replica patch per kind (D-004), and the rule for retired parameters (D-007).
- `dev/knowledge/backend/api.md` (error codes), `dev/knowledge/backend/services.md`, `dev/knowledge/backend/data-models.md`, `dev/knowledge/frontend/deployment-configuration.md`.
- `CONTEXT.md` (drafted on this branch).
- `changelog/202.added.md` (replica overrides, driver `replicas` and `singleton`), `changelog/202.changed.md` (infrahub drivers retire the two parameters; retired parameters with default values are dropped on a version change; a driver that already declares `components.<name>.replicas` starts to apply it; the agent chart must be upgraded with the server; clear replica overrides before downgrading Styrmin, because an older server rejects the stored key; critique E2, E9).

## Dependency evaluation (research directive)

The feature needs nothing that its third-party dependencies lack, so no extension mechanism or upstream contribution is used.

| Dependency | Needed capability | Supported? |
|------------|-------------------|------------|
| FluxCD helm-controller `postRenderers` (kustomize) | A JSON6902 `add` on `/spec/replicas` for targets selected by kind and label selector | Yes. The stop patch uses exactly this today. |
| helm-controller release wait (kstatus) | Wait for the post-rendered replica count, including scale-down | Yes. kstatus compares status counts with `spec.replicas` of the applied object (D-008). |
| Helm | Render the chart unchanged; no value needed | Yes. The override does not touch values. |
| Pydantic v2 | Strict integer with a lower bound; cross-field check | Yes: `StrictInt`, `Field(ge=1)`, `model_validator`. |
| Strawberry GraphQL | Enum output type, nullable `Int` input slot | Yes: `@strawberry.enum`, `int | None`. |
| TanStack Form / Zod | Optional number field per array item | Yes: the same `form.Field` pattern as `image`. |

The one capability outside Styrmin's control that the design relies on is helm-controller's kstatus wait. It is behaviour the operator already depends on for every rollout, and the E2E checks it for a scale-up and a scale-down.
