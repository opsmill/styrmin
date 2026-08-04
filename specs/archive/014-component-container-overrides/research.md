# Phase 0 Research: Component-Scope `command` / `args` Overrides

The spec mandates that behaviour, error shapes, input shape, and orphan semantics **mirror the deployment env-vars precedent** (008 / 010, ADR-013). Research therefore focused on (a) confirming the exact env-vars implementation at every layer so the port is faithful, and (b) resolving the handful of places where `command`/`args` legitimately diverge from env-vars. There were no open `NEEDS CLARIFICATION` items in the Technical Context; the decisions below close the design questions the port surfaces.

Reference map of the existing env-vars implementation (used as the template throughout):

| Layer | Env-vars anchor (mirror this) |
|-------|-------------------------------|
| Per-component storage | `context/models/config.py` — `ComponentConfigBlock.env_vars`, `DeploymentConfig.components` |
| Resolved context | `context/models/components.py` — `ResolvedComponentEnvVars`, attached to `ComponentContext` |
| Resolution + orphan | `services/env_vars/resolver.py` — `EnvVarsResolver.resolve_for_deployment` |
| Write validation | `services/deployment.py` — `_validate_component_env_var_targets`, `_prevalidate_deployment_env_vars` |
| Typed errors | `services/env_vars/exceptions.py`, `services/env_vars/validator.py` |
| GraphQL input | `api/definitions/deployment/inputs.py` — `ComponentConfigInput`, `update_deployment_input_to_dict`, `_flatten_components` |
| GraphQL output | `api/definitions/deployment/model.py` — `ComponentEnvVars`, `Deployment.component_env_vars` |
| Driver doc decl | `services/driver/models/resources/env_vars.py` — `DriverEnvVarDoc`; materialised in `services/applications.py`; column `ApplicationDriverVersion.env_vars` |
| Template filter | `agent/.../builders/application.py` — `component_env_vars` + `get_jinja_environment` |
| Reference driver | `driver/examples/simple-app/{driver.styrmin.yml,values.j2.yml}` |
| Frontend | `components/deployment/configuration/sections/{edit,read}/ComponentOverrides*.tsx`, `lib/deployment-input.ts` |
| SDK/CLI | `python_sdk/.../graphql/*`, `cli/.../commands/deployments.py` |
| E2E | `backend/tests/e2e/test_deployment_env_vars.py`, `drivers/protocol.py`, `helpers/workloads.py` |

---

## D1 — Storage: extend `ComponentConfigBlock`, no DB migration

- **Decision**: Add two fields to the existing `ComponentConfigBlock` (`context/models/config.py`): `command: list[str] | None = None` and `args: list[str] | None = None`. They persist inside the existing `Deployment.config` JSON column under `components[<name>]`. No new table, no Alembic migration.
- **Rationale**: ADR-029 — additive operator-tunable config rides existing `JSON` columns; the only code change is the Pydantic class. `ComponentConfigBlock` already exists precisely as the per-component extension point ("future per-component knobs slot into this same block"). `model_config = ConfigDict(extra="forbid")` catches misspelled keys; existing rows omitting the keys deserialize to `None` (no-op).
- **Alternatives considered**:
  - *Promote to typed columns* — rejected: not queried/filtered in SQL; JSON round-trip is sufficient and avoids the migration governance hit.
  - *New `ContainerOverrideBlock` sub-model under the component* — rejected as premature nesting; flat `command`/`args` on `ComponentConfigBlock` matches the env-vars flat-field precedent (ADR-029 "stay flat until 2–3 related knobs").

## D2 — No layering: component-scope only (the big divergence from env-vars)

- **Decision**: `command`/`args` exist **only** at the component scope. There is no environment- or deployment-wide override (FR-003). The resolver does **not** reuse the env-vars `_merge_env_vars` deepest-wins primitive; the resolved value is simply the component block's `command`/`args` (or "unset"). A new `ContainerOverridesResolver` (in `services/container_overrides/resolver.py`) walks the driver's declared components, emits one resolved entry per component (live), and emits orphan entries for stored blocks whose component is no longer declared — mirroring `EnvVarsResolver`'s **orphan** structure but not its **merge** structure.
- **Rationale**: Heterogeneous component entrypoints make a single broad-scope `command`/`args` semantically meaningless (spec Out-of-Scope). Skipping the merge keeps resolution trivial and removes provenance bookkeeping that has no meaning here.
- **Alternatives considered**:
  - *Reuse `EnvVarsResolver` and pass only the component layer* — rejected: the dict-keyed deepest-wins merge does not model scalar `list[str]` slots; bending it in would obscure both features. A small parallel resolver is clearer and keeps env-vars untouched (SC-004).
  - *Allow deployment-scope `command`/`args` as a convenience* — rejected by FR-003 and Out-of-Scope.

## D3 — `command` and `args` are independent slots

- **Decision**: Each field is independently optional and nullable. Setting/clearing one never touches the other (FR-007, US2/US3). Storage, validation, the resolved context, the filters, and the GraphQL surface treat them as two parallel slots throughout.
- **Rationale**: Mirrors the Kubernetes container API where `command` (entrypoint) and `args` are distinct. Independence is the property that makes partial edits safe (US2 Scenario 2: `command` set, `args` falls through to chart default).
- **Alternatives considered**: *Single combined `containerOverride` object that must be set/cleared atomically* — rejected: forces read-modify-write to change one field and breaks the "clear `args`, keep `command`" story (US3 Scenario 2).

## D4 — Validation: list-of-string, non-empty when set, empty-string elements OK

- **Decision**: A new `validate_container_override(field, value)` in `services/container_overrides/validator.py` enforces: every element is a string (`isinstance(x, str)`); the list is **non-empty** when present; **empty-string elements are accepted** (`["sh","-c",""]` is valid, mirroring Kubernetes — FR-006/US4 Scenario 4). An empty list `[]` is **rejected** with a typed error distinct per field. Clearing is null/omit, never `[]` (FR-007). Validation runs at the mutation boundary **before** any reconcile (US4), as a pre-Pydantic dict check so the typed error reaches GraphQL intact (matching `_prevalidate_deployment_env_vars`), and is also expressed as Pydantic `field_validator`s on `ComponentConfigBlock` for defence-in-depth.
- **Rationale**: Matches the env-vars validator structure (`validate_env_vars_dict`) and the "fail fast at write, never restart a workload into a broken state" safety goal (US4). Distinct-per-field errors satisfy US4 Scenario 3 ("identifying the offending field").
- **Alternatives considered**:
  - *Treat `[]` as "clear"* — rejected by FR-007 (clear = null/omit; `[]` is an explicit, rejected, invalid value). Keeps "clear" unambiguous and prevents an accidental empty-entrypoint container.
  - *Allow non-string coercion (e.g. ints → str)* — rejected by FR-014 (verbatim pass-through, no coercion); a non-string element is a typed `INVALID_CONTAINER_*` error (US4 Scenario 3).

## D5 — Typed errors: new per-field + per-feature classes

- **Decision**: New `ServiceError` subclasses in `services/container_overrides/exceptions.py`:
  - `InvalidContainerCommandError` — `error_code = "INVALID_CONTAINER_COMMAND"`
  - `InvalidContainerArgsError` — `error_code = "INVALID_CONTAINER_ARGS"`
  - `UnknownComponentContainerOverrideError` — `error_code = "UNKNOWN_COMPONENT_CONTAINER_OVERRIDE"`, payload carries `component_name` + sorted `known_components`.
  Duplicate component names within the input list continue to raise the existing `DuplicateComponentNameError` (`DUPLICATE_COMPONENT_NAME`) from the shared `_flatten_components` helper — unchanged.
- **Rationale**: The env-vars feature uses scope/feature-specific error classes (`UnknownComponentEnvVarError`, `InvalidEnvVarValueError`). Keeping `UnknownComponentEnvVarError` untouched preserves env-vars behaviour exactly (SC-004) while giving `command`/`args` its own precise, machine-readable codes (Constitution §IV). All inherit `ServiceError` and surface via `StructuredErrorExtension`.
- **Alternatives considered**:
  - *Generalise to one `UnknownComponentError` shared across env-vars and overrides* — rejected for v1: would change the existing `UNKNOWN_COMPONENT_ENV_VAR` code (a breaking, regression-risky rename for no operator benefit). Recorded as possible future consolidation.
  - *Reuse `INVALID_ENV_VAR_VALUE`* — rejected: the offending field must be identifiable as `command` vs `args` (US4 Scenario 3).

## D6 — Write-side unknown-component rejection extends the existing check

- **Decision**: Extend the deployment write path (`services/deployment.py`) so a `components[<name>]` block that carries `command` and/or `args` targeting a name **not** declared by the deployment's pinned driver version raises `UnknownComponentContainerOverrideError`, naming the driver's known components, **before** any reconcile is planned (FR-004, US4 Scenario 1). The driver's declared set remains the source of truth: `[cc.name for cc in (adv.component_configs or [])]`. The check runs alongside the existing `_validate_component_env_var_targets` (each fires for its own field independently); ahead of Pydantic so the typed error survives. It MUST be wired at **both** `deployment.py` validation call sites — the `deploy`/create path (~L274/281) and the `updateDeployment` path (~L866/873) — so overrides submitted at create time via the `deploy` mutation's `config` JSON are validated identically (FR-002 covers both flows), mirroring how `_prevalidate_deployment_env_vars` is invoked at both.
- **Rationale**: Reuses the proven write-boundary location and source-of-truth. A block with only `command`/`args` (no `env_vars`) on an unknown component is currently *not* rejected by the env-vars check (it only inspects `env_vars`); the new check closes that gap for the new fields.
- **Alternatives considered**: *Validate at resolve/render time only* — rejected by FR-004 (must reject at the **write** boundary; a malformed override must never reach reconcile).

## D7 — Render-side orphan tolerance (read-vs-write asymmetry)

- **Decision**: At resolve/render (`ContainerOverridesResolver`), a stored block whose component is no longer declared by the current driver version is **preserved**, flagged `is_orphaned=True`, and **skipped** by the renderer so no override reaches a container (FR-005, FR-015, US5). The GraphQL read surface returns it with the orphan flag. This mirrors `EnvVarsResolver`'s orphan branch (sorted, empty/None blocks dropped, provenance-free).
- **Rationale**: A driver upgrade that renames/removes a component must not be blocked by a stale override, must not silently strand it, and must not apply it (US5). The asymmetry — reject-on-write, tolerate-on-read — is the same load-bearing design as env-vars (ADR-013 / resolver docstring).
- **Alternatives considered**: *Auto-prune orphans on upgrade* — rejected by FR-015 (must not silently discard; operator audits and removes via the standard update flow).

## D8 — Driver consumption: two filters returning an omit/none marker (divergence from env-vars)

> **CORRECTED DURING IMPLEMENTATION (see [ADR-045](../../dev/adr/adr-045-container-override-no-layering-and-omit-marker.md) §2).** The omit-marker below (filter returns `None`; template omits the key when unset) **breaks clearing**: the operator applies HelmRelease `spec.values` via JSON merge-patch (RFC 7386), where an *omitted* key is left unchanged — so a cleared override never reaches the pod. The shipped design is the **empty-list marker**: the filters return `[]` when unset, the driver template emits the key **unconditionally**, and the chart guards consumption with `{{- with .Values.command }}` (which skips `[]`, letting the image/chart default apply). Operator-visible behaviour is identical (unset → default); clearing now propagates. The rest of D8 (no post-render injection, unwired-driver silent no-op) stands.

- **Decision**: Add two Jinja filters in `agent/.../builders/application.py`, registered in `get_jinja_environment`:
  - `component_command(components, name) -> list[str] | None`
  - `component_args(components, name) -> list[str] | None`
  Each returns the resolved list for the component, or **`None`** when no override is set (component absent, no override block, or the slot is unset). Driver templates guard with a conditional so the chart default flows through when unset, e.g.:
  ```jinja
  {%- set _cmd = components | component_command("server") %}
  {%- if _cmd is not none %}
  command: {{ _cmd | tojson }}
  {%- endif %}
  ```
- **Rationale**: Unlike env-vars (where `[]` + chart-append is harmless), an empty/`[]` `command` would *blank the container entrypoint*. The filter must therefore distinguish "unset" (→ omit, chart default wins) from "set". Returning `None` + a template `if` is the minimal, explicit contract and keeps the platform from ever injecting into a container the driver didn't wire (FR-009, mirrors ADR-013 consumption boundary). An unwired driver stores-but-never-applies (FR-009 / US6 silent no-op).
- **Alternatives considered**:
  - *Return `[]` like `component_env_vars`* — rejected: indistinguishable from a real empty list; would force the chart to special-case, and risks a blanked entrypoint.
  - *Platform-side post-render injection of `command`/`args`* — rejected for the same reasons ADR-013 killed env-var post-render injection (the platform doesn't know container names; the chart does).

## D9 — Doc-only driver declaration mirrors `DriverEnvVarDoc`

- **Decision**: Add a `DriverContainerOverrideDoc` model (`services/driver/models/resources/container_overrides.py`) parsed from an optional `spec` block, validated at driver-load time (component references must exist), materialised onto a new `ApplicationDriverVersion.container_overrides` JSON column (`services/applications.py`), and exposed via `ApplicationDriverVersion.containerOverrides` in GraphQL. It is **informational only** — the platform does not require a declared component to actually consume the override (FR-010, US6 Scenario 3), mirroring `DriverEnvVarDoc`.
- **Rationale**: Gives operators a discoverable "this component advertises overridable `command`/`args`, targeting container X" surface (FR-011) without coupling declaration to consumption (ADR-013 §5 migration-responsibility / no-enforcement policy). v1 may also record which container the override targets (doc string), since multi-container targeting is out of scope.
- **Alternatives considered**: *Enforce that declared ⇒ consumed* — rejected by FR-010 (matches env-vars "doc-only, no enforcement").

## D10 — Input shape: extend `ComponentConfigInput`; deploy rides JSON; updateDeployment is typed

- **Decision**: Add `command: list[str] | None` and `args: list[str] | None` to `ComponentConfigInput` (`api/definitions/deployment/inputs.py`). `_flatten_components` passes them through unchanged (they need no flatten; `_convert_value` already recurses lists and omits `None`). Full-replacement semantics with explicit-clear-via-null match the rest of the input (ADR-018): omitting a field = "do not touch"; `null` = clear; `components: []` clears all blocks. The untyped `deploy` mutation (`config: JSON`) carries `command`/`args` automatically inside `components[<name>]` of the config blob, validated server-side at Pydantic deserialization + the pre-validation hook (FR-002 covers both deploy and update flows).
- **Rationale**: ADR-018's list-of-`{name, …}` convention is the mandated shape for named-dict-typed config fields; `command`/`args` slot into the existing per-component entry with no new grammar. The deploy path needs no schema change because it is already loose-typed JSON (ADR-029).
- **Alternatives considered**: *Add `command`/`args` as top-level `UpdateDeploymentInput` fields* — rejected by FR-003 (overrides are component-scoped; they belong on the component entry, not the deployment root).

## D11 — Read surface: a dedicated `ComponentContainerOverrides` output type

- **Decision**: Add a GraphQL output type `ComponentContainerOverrides { component: String!, command: [String!], args: [String!], isOrphaned: Boolean! }` and a `Deployment.componentContainerOverrides: [ComponentContainerOverrides!]!` resolver (**non-null list**, matching the env-vars precedent `model.py` `-> list[ComponentEnvVars]`) mirroring `Deployment.component_env_vars` (orphans always surfaced; live components with no override omitted to keep the surface tidy). Cleared fields are absent (`null` list) from the read (FR-007 Scenario 3 / FR-013).
- **Rationale**: A distinct type keeps `command`/`args` (`[String!]` lists) cleanly separated from `ComponentEnvVars` (`[EnvVar!]`) and lets the orphan flag be read independently. FR-013 requires per-component reads including orphaned entries with the flag.
- **Alternatives considered**: *Fold `command`/`args` into `ComponentEnvVars`* — rejected: conflates two unrelated shapes and forces clients fetching only env-vars to over-select.

## D12 — Frontend reuses the per-component override editor

- **Decision**: Extend the existing `ComponentOverridesSection.tsx` (edit) to add a `command`/`args` list editor per component beside the env-vars rows, and `ComponentOverridesSummary.tsx` (read) to display them. The submit-boundary transform `componentsDictToList` in `lib/deployment-input.ts` (ADR-015) carries `command`/`args` from the persisted dict into the list-shaped `ComponentConfigInput`. Zod validation rejects empty lists (mirrors backend). Orphaned-block handling already exists in the edit section and extends to the new fields.
- **Rationale**: The per-component override UI and the documented submit-boundary transform already exist for env-vars; extending them keeps a single editor and a single transform (ADR-015 the documented site for persisted-dict → list-input conversion).
- **Alternatives considered**: *Separate dialog for command/args* — rejected: duplicates the component-iteration, orphan-handling, and diff/confirm machinery already in `ComponentOverridesSection`.

## D13 — SDK/CLI: regen carries the fields; CLI needs only docs

- **Decision**: After the schema change, `uv run invoke generate` regenerates the SDK `ComponentConfigInput` (gaining `command`/`args`) and the read types. Add an SDK read `.graphql` operation for `componentContainerOverrides` (mirrors `get_deployment_component_env_vars_full.graphql`). The CLI `deployments update --config` already accepts an arbitrary `UpdateDeploymentInput` JSON payload, so `command`/`args` ride through with no command-code change — only `cli/README.md` / examples need updating.
- **Rationale**: ADR-037 outer-wrapper/facade + ariadne-codegen means typed inputs regenerate from the schema; the CLI is a thin JSON client.
- **Alternatives considered**: *Add bespoke CLI flags `--command`/`--args`* — rejected for v1: the JSON-config path is the established CLI surface for typed-input fields (matches how component env-vars are passed today).

## D14 — Testing: E2E + propagation + unit, reusing env-vars scaffolding

- **Decision**:
  - **E2E** `backend/tests/e2e/test_deployment_container_overrides.py` mirrors `test_deployment_env_vars.py`: deploy `simple-app`, set `args` on a component (US1), set `command` independently (US2), clear and fall back (US3), reject invalid overrides (US4), orphan after upgrade (US5). Asserts the rendered pod's container `command`/`args` via the `_wait_for_pod_template` / container-introspection helpers in `helpers/workloads.py`. Runs **dual-entrypoint** (NOT `api_only`): because this feature ships the frontend Command/Args editor, the UI scenario driver (`UiScenarioDriver.update_deployment`) is extended to drive that editor through the deployment-detail Configuration form, so the `[ui-chromium]` variant exercises real frontend coverage. (This is the one place we diverge from the env-vars E2E, which stayed `api_only` precisely because its UI driver only drives the `scheduling` sub-tree.) Carries `@pytest.mark.ci` + one shard marker.
  - **Shard**: `shard_configuration` (deployment-config behaviour; `shard_env` is reserved for env precedence/fan-out). No new shard ⇒ no CI-workflow governance gate.
  - **Propagation** (`backend/tests/functional/graphql/`): per-field GraphQL→DB→resolver round-trips for `command`/`args` set/clear/orphan; **extend** the schema-walking field-coverage test to assert `ComponentConfigInput` fields == `ComponentConfigBlock.model_fields` (camel↔snake normalised) so future drift fails CI (ADR-014).
  - **Unit**: `ContainerOverridesResolver` (live + orphan), `validate_container_override` (empty-list reject, empty-string accept, non-string reject), and Jinja filter render tests asserting the **omit-marker** behaviour (unset → field absent → chart default).
  - **Reference driver**: wire `simple-app` `values.j2.yml` to consume `component_command`/`component_args`; add the doc-only declaration to its `driver.styrmin.yml`.
- **Rationale**: Constitution §V (E2E + local PASS evidence) and the GraphQL propagation-test mandate. Reusing the env-vars E2E scaffolding (scenario driver, workloads helper, simple-app) minimises new surface.
- **Alternatives considered**: *Defer E2E to a follow-up* — forbidden by Constitution §V.

## D15 — Documentation surface

- **Decision**: In the same change: a new `dev/guides/driver-container-override-consumption.md` (mirrors `driver-env-var-consumption.md`, documenting the filters, the omit-marker `if` guard, and the no-enforcement policy); `docs/` driver-author + how-it-works updates; a new ADR recording the **no-layering** + **omit-marker filter** + **per-field typed errors** decisions (the non-obvious divergences from ADR-013); and a new `CONTEXT.md` term **"container override"** (the per-component `command`/`args` slot) with the synonyms to avoid.
- **Rationale**: Constitution §VII (non-negotiable). The divergences from the env-vars pattern are exactly the decisions a future maintainer would relitigate, so they warrant an ADR.

---

## Resolved unknowns

All Technical-Context items were known from the env-vars precedent; no `NEEDS CLARIFICATION` remained. The port-specific design questions (layering? empty-list semantics? filter return shape? error reuse? read type?) are resolved in D2/D4/D8/D5/D11 above. Ready for Phase 1.
