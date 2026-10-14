# Research: Container `command` and `args` Overrides Applied by Post-Render

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-14

Every unknown in the plan's Technical Context is resolved below. Each decision lists what was chosen, why, and what was rejected.

## D-001: Which post-render patch carries `command` and `args`

**Decision**: Extend the strategic-merge container patch that already carries env vars ([`ContainerEnvPatch`](../../backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py)) with optional `command` and `args` lists, and rename it `ContainerMergePatch`. The patch names the component container and writes `env`, `command` and `args` next to each other. A field that does not apply is left out of the patch body, so the chart's value stays. The JSON6902 guard ([`ComponentContainerPatch`](../../backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py)) does not change.

**Rationale**:

- `command` and `args` are lists of strings with no `patchMergeKey` in the Kubernetes schema. kustomize's strategic merge (kyaml `merge2`) replaces a list that has no merge key. This was checked on 2026-10-14 with `kubectl kustomize` (kustomize v5.7.1) on a Deployment with an init container, a sidecar and the component container, with the real guard ops applied after the merge:
  - an `args` patch replaced the whole `args` list of the component container;
  - the chart's `command` stayed;
  - the sidecar and the init container were unchanged;
  - the component container moved to `containers[0]`;
  - the strings `'yes'`, `'8000'`, `''`, `'null'` and `$(HOME)` came out as the same strings, because PyYAML quotes them in the patch;
  - a wrong container name failed the render at the guard's `remove .../image` op, which `parse_guard_failure` turns into `COMPONENT_CONTAINER_NOT_FOUND`.
- One patch per container for every "value" override keeps one ordering rule (ADR-057 §3) and one place where the container is named.
- A clear needs no marker: with no stored value the field is absent from the patch, so the chart's rendered value reaches the pod (Constitution §I, the same output for the same config).

**Alternatives considered**:

- JSON6902 `add` ops for `/command` and `/args` inside the guard patch. RFC 6902 `add` replaces an existing member, so this also works and does not depend on strategic-merge list rules. Rejected because it puts value overrides into the guard, which today only moves the container and checks it, and because the PRD chose the merge patch.
- A separate strategic-merge patch per field. Rejected: more patches per workload and no gain.
- Keeping `ContainerEnvPatch` as the name. Rejected: the name would describe one of three fields.

**Open risk**: the version of kustomize inside helm-controller v1.6.5, which the agent chart installs, is not known. The E2E in [quickstart.md](quickstart.md) reads the pod's container spec and confirms the behaviour on the real post-renderer (assumption A-001 in the spec).

## D-002: One rule for "this override applies"

**Decision**: In [`services/component_container/overrides.py`](../../backend/styrmin_backend/services/component_container/overrides.py):

- `override_applies(container: str | None, is_orphaned: bool) -> bool` is the single rule: true only when the component declares a component container and the override is not orphaned.
- `ApplicableOverrides` is a frozen dataclass with `env: dict[str, str]`, `image: str | None`, `command: list[str] | None`, `args: list[str] | None` and an `is_empty` property.
- `applicable_overrides(name, component, version) -> ApplicableOverrides` builds that value from a `ComponentContext`, using `override_applies` for each override. It replaces `applicable_env` and `applicable_image`.

The patch builder and the action primitives call `applicable_overrides`. The GraphQL read fields `ComponentEnvVars.isApplicable`, `ComponentImageOverride.isApplicable` and the new `ComponentContainerOverrides.isApplicable` call `override_applies` with the deployment's component container and the entry's orphan flag.

**Rationale**: the PRD asks for the rule in one place. The read path has no `ComponentContext`, only the component container map and the orphan flag, so the rule takes those two inputs and the bundle builder calls it.

**Alternatives considered**:

- Add `applicable_command` and `applicable_args` next to the two existing functions. Rejected: four copies of the same condition.
- Make the read fields build a `ComponentContext`. Rejected: the read path would need the whole rendering context for one boolean.

**Behaviour note**: `execute_commands(env_from_component=...)` now also resolves the image override when it reads the env vars. An image reference that cannot resolve is already rejected on write and before a version change (018 FR-009), and the same context renders the HelmRelease before actions run, so this adds no new failure in practice.

## D-003: When the component container patches are built

**Decision**: `build_component_container_patches` builds the merge patch and the guard for a component when `applicable_overrides(...).is_empty` is false, so a component whose only override is `command` or `args` gets both patches. The log line gains `command_set` and `args_set` booleans.

**Rationale**: FR-004 requires `COMPONENT_CONTAINER_NOT_FOUND` also when `command` or `args` is the only override. The guard runs only when the patches are built.

## D-004: Retiring the `component_command` and `component_args` filters

**Decision**:

- Both filters stay registered in `get_jinja_environment()` as stubs that raise `RetiredTemplateFilterError`, as `component_env_vars` does ([ADR-057](../../dev/adr/0057-post-render-component-overrides.md) §4). The helper `_resolved_container_override` is deleted.
- `RetiredTemplateFilterError` builds its message from the filter name. For `component_command` and `component_args` the message tells deployment users to move the deployment to a driver version that no longer calls the filter, tells driver authors to remove the filter call from `values.j2.yml` and to declare `components.<name>.container`, and links `CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL = "https://styrmin.pages.dev/docs/drivers/migrating-container-overrides"`. Metadata stays `filter` and `migration_guide`. The `component_env_vars` message and URL do not change.
- The stub raises whatever the context holds, so an unmigrated driver fails on its next render even when no override is set (spec edge case).

**Rationale**: the operator records `Failed to create HelmRelease: <message>` on the deployment and the typed code does not survive the CR hop (ADR-057 §4), so the message itself must name the filter and the guide (spec P2 scenario 1).

**Alternatives considered**: unregistering the filters. Rejected: Jinja would fail at compile time with "No filter named ...", which names no guide.

## D-005: Write check for components without a component container

**Decision**: In [`services/deployment.py`](../../backend/styrmin_backend/services/deployment.py):

- `ComponentContainerSlot` becomes `Literal["env_vars", "image", "command", "args"]`, and the default `slots` of `_validate_component_container_targets` covers all four.
- `_slot_adds_or_changes` treats `command` and `args` like `image`: a write adds or changes the slot when the submitted value is not `None` and differs from the stored value. A removal (`None` or an omitted key) and the same list sent again pass.
- `ComponentContainerNotDeclaredError.override` accepts `"command"` and `"args"`, and its message names the field ("Container command override targets component ...").

The existing order stays: unknown component and list shape first (`_validate_component_container_overrides`), the container check last, on both `deploy` and `updateDeployment` (and so on `styrminctl apply` and the UI, which call them).

**Rationale**: FR-007 asks for the same rule as env vars and images. The check reads the driver version the deployment is pinned to after the write, so a write that moves to a driver version without the container is checked against that version.

## D-006: Removing `spec.container_overrides`

**Decision**:

- Delete the `container_overrides` field from `Specification` in [`driver.py`](../../backend/styrmin_backend/services/driver/models/resources/driver.py). `Specification` has `extra="forbid"`, so a file that still contains the key fails to load with the same error as any other unknown key (FR-006).
- Delete [`models/resources/container_overrides.py`](../../backend/styrmin_backend/services/driver/models/resources/container_overrides.py), `validate_driver_container_override_docs` in [`validators.py`](../../backend/styrmin_backend/services/driver/validators.py), its call in [`loaders.py`](../../backend/styrmin_backend/services/driver/loaders.py), the payload in [`applications.py`](../../backend/styrmin_backend/services/applications.py) and `DriverContainerOverrideDocComponentMismatchError` (`DRIVER_CONTAINER_OVERRIDE_DOC_COMPONENT_MISMATCH`) in [`container_overrides/exceptions.py`](../../backend/styrmin_backend/services/container_overrides/exceptions.py).

**Rationale**: the block only documented which components accept an override. The component container now answers that question.

**Note**: removing the error code is not a new code (FR-011). It is listed in the `removed` changelog fragment.

## D-007: Database column removal

**Decision**: one Alembic revision after the current head `9548830f81cd` that drops `applicationdriverversion.container_overrides`. Its downgrade adds the column back as nullable `JSON`, empty. The `container_overrides` field is removed from `ApplicationDriverVersion` in [`db/models.py`](../../backend/styrmin_backend/db/models.py). A migration unit test follows [`test_driver_info_migration.py`](../../backend/tests/unit/db/test_driver_info_migration.py): upgrade drops the column, downgrade restores it empty, `test_migration_heads.py` still sees one head.

**Rationale**: the PRD's governance gate approves this change. Tests build fresh databases with `create_all()`, so a green suite does not prove the revision exists; the migration test does.

**Alembic gap check**: `op.drop_column` and `op.add_column` cover the need. No extension is required.

## D-008: GraphQL and SDK surface

**Decision**:

- Remove `ApplicationDriverVersion.containerOverrides` and the `DriverContainerOverrideDoc` type from [`application_driver/model.py`](../../backend/styrmin_backend/api/definitions/application_driver/model.py).
- Add `ComponentContainerOverrides.isApplicable: Boolean!` in [`deployment/model.py`](../../backend/styrmin_backend/api/definitions/deployment/model.py). The resolver reads `_component_containers(deployment)` once and calls `override_applies` (D-002). The type and field descriptions stop saying the values go through the template.
- SDK: delete `get_driver_container_override_docs.graphql` and its test copy, add `isApplicable` to `get_deployment_component_container_overrides_full.graphql`, export `schema.graphql`, run `uv run invoke generate` (SDK and frontend types).

**Strawberry gap check**: removing a field and adding a non-null boolean are plain Strawberry changes. No extension is required.

## D-009: Example drivers

**Decision**: in `simple-app`, `infrahub` and `infrahub-enterprise`:

- remove every `component_command` and `component_args` call and the `command`/`args` keys they fed in `values.j2.yml`, so the chart's own values apply;
- remove `spec.container_overrides` and its comment from `driver.styrmin.yml`;
- bump `spec.version` (`simple-app` 2 → 3, `infrahub` 3 → 4, `infrahub-enterprise` 2 → 3), as the env var migration did ([Migrating Env Var Wiring](../../docs/docs/drivers/migrating-env-vars.md) step 4), so a loaded old version and the migrated version are separate driver versions.

All their components that accepted an override already declare a component container (`server` → `simple-app`; `server` → `infrahub-server`, `task-worker` → `infrahub-task-worker`, `task-manager` → `prefect-server`), so stored overrides keep a target (SC-005).

**Check during implementation**: tests or fixtures that pin these driver version strings must move to the new versions.

## D-010: Frontend editor

**Decision**: in [`ComponentOverridesSection.tsx`](../../frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx), render the Command and Args editors only when `hasContainer` is true. When it is false and a value is stored, render a `ContainerlessContainerOverride` block in the style of `ContainerlessImage`: the stored `command` and `args` as read-only rows with a "not applied" badge and a Remove button that sets the field to `[]` (the submit boundary already turns an empty list into "omit", which clears it). Tests go in `ComponentOverridesSection.test.tsx`.

**Rationale**: same pattern as env vars and images (ADR-057 §5, ADR-058). The editor already knows `hasContainer` from `components[].container`, so no new query is needed.

**Not in scope**: the read summary `ComponentOverridesSummary` keeps showing command/args counts without an applied badge. The PRD does not ask for it, and SC-004 holds because the summary claims nothing about applicability.

## D-011: Tests that prove the outcomes

**Decision**:

- Unit tests:
  - `applicable_overrides` and `override_applies` (all four overrides, orphaned, no container);
  - the patch builder (`command`/`args` only builds merge + guard, clear builds nothing, both lists land in the merge body);
  - `ContainerMergePatch.render_value` (field omitted when `None`, tricky strings quoted);
  - the retired filters (each raises with its name and the new URL, also inside `{% if %}`, also with no override set; the operator records the message and applies no HelmRelease);
  - the write check (`command`/`args` add or change rejected with `override` metadata, removal and same value accepted);
  - the driver loader (a file with `spec.container_overrides` fails like any unknown key);
  - the migration revision.
- Integration tests in [`test_component_container_kustomize.py`](../../backend/tests/integration/test_component_container_kustomize.py) on real `kubectl kustomize`: `args`-only keeps the chart `command`; `command` + `args` replace both; other containers and init containers unchanged; wrong container name with only `args` fails with a guard key that `parse_guard_failure` reads (FR-002, FR-004).
- Contract test for SC-005: render the same stored config with the pre-migration `values.j2.yml` of each example driver (vendored as test fixtures, with the old filter code kept in the test) and with the migrated driver plus the post-render patches, and compare the component container's `command` and `args`. For `simple-app` the comparison runs `helm template` on the local chart (`driver/examples/simple-app/src/helm`) and `kubectl kustomize`. For `infrahub` and `infrahub-enterprise` the chart is not in the repository, so the test compares the value the old template sends to the chart with the list in the merge patch, which A-002 makes equivalent.
- GraphQL propagation test in [`test_container_overrides_propagation.py`](../../backend/tests/functional/graphql/test_container_overrides_propagation.py): `isApplicable` true, false for a component without a container, false for an orphan; `COMPONENT_CONTAINER_NOT_DECLARED` for `command` and `args` through `updateDeployment` and `deploy`; the two driver-doc tests are deleted.
- E2E: extend [`test_deployment_container_overrides.py`](../../backend/tests/e2e/test_deployment_container_overrides.py) on `shard_configuration` (see [quickstart.md](quickstart.md)).

**Rationale**: the PRD's testing decisions; tests read rendered workloads or pod specs, not patch text, except where the unit under test is the patch text itself.

## D-012: Reconcile after a clear

**Context**: the current `test_us3` docstring says that, on the values path, clearing an override inside the reconcile window did not roll the workload, so the test only checked the API.

**Decision**: no special handling. With post-render, a clear removes the `command`/`args` fields from the merge patch (or removes both patches), so `spec.postRenderers` of the HelmRelease changes. The operator replaces each spec key it writes on update (ADR-057 §6), and helm-controller upgrades the release when `spec` changes. The extended `test_us3` reads the pod's container spec after the clear and compares it with the spec captured before any override was set.

**Risk**: if the E2E shows that the clear does not roll the workload, the cause is in the operator's change detection, not in this feature. The implementer follows the operator log during the paused E2E ([`e2e-testing.md`](../../dev/knowledge/backend/e2e-testing.md)) and fixes the detection in the same change, because FR-003 requires the restore.

## Research directive: third-party dependencies

The feature needs no capability that a dependency lacks:

| Dependency | Need | Finding | Decision |
|------------|------|---------|----------|
| kustomize (helm-controller post-renderer) | Replace a container's `command`/`args` list | Strategic merge replaces lists with no merge key (kyaml `merge2` non-associative list rule); checked with kustomize v5.7.1 | Use as is (D-001). The helm-controller copy is checked by the E2E |
| Jinja2 | A filter that fails with a typed error | `Environment.filters` takes any callable, the existing `component_env_vars` stub works this way | Use as is (D-004) |
| Strawberry GraphQL | Remove a field and type, add a boolean | Plain schema change | Use as is (D-008) |
| Alembic | Drop a column with a reversible downgrade | `op.drop_column` / `op.add_column` | Use as is (D-007) |

No extension mechanism or upstream contribution was needed, so none was evaluated further.
