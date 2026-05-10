# Phase 0 Research: Driver-Side Env Var Consumption

## 1. Verify env vars already reach the rendering context

**Finding**: They do, modulo verification.

`ApplicationBuilder.render_value_template` at `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py:185` is:

```python
@staticmethod
@task
def render_value_template(values_template: str, context: GlobalContext) -> dict:
    context_dict: dict = context.model_dump(exclude_none=True)
    # ...
    template = environment.from_string(values_template)
    values = template.render(context_dict)
```

The `GlobalContext` Pydantic model carries:

- `instance: InstanceContext` → `instance.config: ResolvedConfig` → `ResolvedConfig.env_vars: dict[str, str] | None` (added in 008-deployment-env-vars / Phase 2 / T010, T011)
- `components: ComponentsContext` → per-component `ComponentContext` → `ComponentContext.env_vars: ResolvedComponentEnvVars | None` → `ResolvedComponentEnvVars.config: dict[str, str]` (added in 008 / Phase 2 / T013, T014)

`model_dump(exclude_none=True)` carries both fields into the rendering dict whenever the env vars are non-None and non-empty. Driver authors access them as `instance.config.env_vars` and `components[<name>].env_vars.config` in Jinja.

**Decision**: No platform-side wiring change is required for FR-001/FR-002. A new unit test (`test_render_value_template_env_vars.py`) verifies the exposure by feeding a synthetic `GlobalContext` with env vars set at deployment + per-component scopes through `render_value_template` with a probe template that reads both fields, and asserting the rendered output contains the expected values.

**Alternatives considered**:

- Adding a dedicated top-level `env_vars` rendering field outside `instance.config` for terser driver-side access (e.g., `{{ env_vars.LOG_LEVEL }}` instead of `{{ instance.config.env_vars.LOG_LEVEL }}`). Rejected for v1 — the `instance.config.*` namespace is consistent with how every other resolved config field is exposed (scheduling, ip_whitelist, etc.). Driver authors learn one namespace, not two.

## 2. Deletion sweep — what gets removed and how

**Decision**: Delete in one coordinated commit (or a small commit chain) so no transitional state ships. The order matters because the schema regen depends on the Strawberry type deletions; the SDK/frontend codegen depends on the schema regen.

**Sweep checklist** (in execution order, from leaves inward):

1. **Backend Python deletions**:
   - `agent/.../blocks/patches.py:EnvVarsPatch` class.
   - `services/env_vars/patch_builder.py` — entire file. Verify nothing else imports from it (008's content was the patch builder + the `ChartEnvCollision` dataclass; both are deleted).
   - `agent/.../builders/application.py` — `build_env_vars_post_rendering_patches` method + the `target_patches.extend(self.build_env_vars_post_rendering_patches())` invocation in `build()`.
   - `context/models/config.py:PostRenderInjection.env_vars` field (and any references in resolver code).
   - `context/resolvers.py:_INJECT_FIELDS` — drop the `"env_vars"` entry.
   - `api/definitions/environment/inputs.py:PostRenderInjectionInput.envVars` (Strawberry input field).
   - `api/definitions/deployment_timeline/model.py:EnvVarCollision` type + `DeploymentTimelineEntry.envVarCollisions` field.
   - `services/deployment_timeline.py:TimelineEntry.env_var_collisions` (dataclass field + any populating code).
   - `api/errors.py` — review whether any error codes were introduced specifically for the deleted surface; remove if so.
2. **Backend test deletions**:
   - `backend/tests/unit/services/env_vars/test_patch_builder.py` — entire file.
   - `backend/tests/unit/agent/test_application_builder_env_vars.py` — env-vars-injection assertions only (whatever non-injection assertions remain stay).
   - `backend/tests/functional/graphql/test_env_vars_propagation.py` — propagation rows for `DeploymentTimelineEntry.envVarCollisions` and `PostRenderInjection.envVars`.
3. **Schema + codegen regeneration**:
   - `uv run styrmin export graphql-schema schema.graphql` — diff confirms the removed types/fields are gone.
   - `uv run invoke generate` — SDK and frontend types regenerate without the deleted surface.
4. **Spec-archive update** (light touch): `specs/008-deployment-env-vars/` documents stay as historical record; the "removed in 010" status is captured in 010's ADR and in `dev/knowledge/backend/deployment-env-vars.md`. No back-edits to 008's spec.

**Verification gate**: after the sweep,

```bash
grep -rn "EnvVarsPatch\|build_env_vars_post_rendering_patches\|ChartEnvCollision\|envVarCollisions\|PostRenderInjection.*env_vars\|env_var_collisions" \
    backend/ python_sdk/ frontend/src/ schema.graphql 2>&1 | grep -v "^Binary file"
```

returns zero hits. Archived spec docs (`specs/008-...`, `specs/009-...`) may still reference the removed surface — that's historical, don't sweep.

**Alternatives considered**:

- Phased deletion (mark deprecated in one release, delete in the next). Rejected — the surface was always broken; nothing legitimate uses it. There is no "deprecation period" worth honouring.
- Leave the surface in place but add a runtime warning. Rejected — the deletion FRs are explicit (FR-005..FR-011); leaving the code in degrades the architecture and continues to confuse driver authors.
- **Fix the injection layer in place via per-container strategic-merge by chart-known container names.** Rejected. Strategic-merge requires knowing the target container's `name` (the merge key) — that information lives in the chart's templates, not at the platform layer. The platform can't synthesise a strategic-merge patch that names every chart's containers without the driver author providing the names. Implementing this properly would require the platform to either (a) re-render the chart server-side and inspect the rendered manifest before patching (heavy; couples the platform to chart internals), or (b) require driver authors to declare every container name in `driver.styrmin.yml` (significant new contract; more intrusive than driver-side template consumption). Driver-side consumption avoids the entire question.

## 3. simple-app driver update

**Decision**: Add an `env:` block to the simple-app container in `driver/examples/simple-app/values.j2.yml`, consuming `instance.config.env_vars` defensively.

**Concrete shape** (illustrative; final form lives in the values template at implementation time):

```yaml
# driver/examples/simple-app/values.j2.yml
fullnameOverride: styrmin-simple-app

image:
  repository: simple-app
  tag: "{{ app.version }}"

# Operator-supplied env vars from instance.config.env_vars, rendered as
# Helm chart env entries. Empty list when no env vars are set anywhere.
env:
{%- for name, value in (instance.config.env_vars or {}).items() %}
  - name: {{ name }}
    value: "{{ value }}"
{%- else %}
  []
{%- endfor %}

# ... rest of the existing values template unchanged ...
```

**Helm chart concerns**: the simple-app chart's container template needs to consume the rendered `env:` array on the container spec. Most charts already accept this shape (`.Values.env`). If the simple-app chart doesn't, extend it minimally — this is a project-controlled chart, not external.

**Edge case — empty env vars**: `instance.config.env_vars or {}` returns `{}` when the field is absent or `None`; the loop emits zero entries; the chart's `env:` field is the empty list `[]`. The chart template handles "no env vars set" without rendering the section.

**Safety — value escaping**: the simple-app demo (and the driver-author guide, FR-022) MUST emit values via Jinja's `tojson` filter or equivalent quoting, so an operator-supplied value containing newlines, quotes, leading dashes, or other YAML-significant characters does NOT silently produce broken values.yaml. The illustrative shape becomes:

```yaml
env:
{%- for name, value in (instance.config.env_vars or {}).items() %}
  - name: {{ name | tojson }}
    value: {{ value | tojson }}
{%- else %}
  []
{%- endfor %}
```

`tojson` produces JSON-encoded strings that are valid YAML scalars and round-trip safely under Helm's templating. The platform does NOT escape values for drivers — driver authors choose the escaping shape that fits their chart. Skipping escaping is a recipe for silent breakage when an operator submits a value like `"hello\nworld"`; FR-022 mandates the guide demonstrates the safe form.

**Alternatives considered**:

- Use `{{- include "common.env" . }}` style helpers from the chart's own helpers. Rejected for v1 — keeps the example simple and self-contained.
- Render via the chart's `extraEnvs` or similar bypass. Rejected — the example should demonstrate the canonical pattern, not chart-specific shortcuts.

## 4. Driver-author guide (US4 / FR-021 + FR-022)

**Decision**: Create `dev/guides/driver-env-var-consumption.md` with three sections:

1. **What env vars reach your template** — covers `instance.config.env_vars` and `components[<name>].env_vars.config` shapes, when they're populated, and the merge order operators control through 008+009's mutation surface.
2. **How to render them** — three worked examples:
   - Single-component driver (simple-app pattern).
   - Multi-component driver (per-component scoping via `components[<name>].env_vars.config`).
   - Driver that combines chart-default env entries with operator-set ones (driver author chooses ordering and dedup policy in Jinja).
3. **What the platform doesn't do** — explicit non-policy: no enforcement of which env vars drivers expose, no validation that operator-set env vars are actually consumed, no automatic chart-default merging. Drivers own the consumption shape.

The guide cross-links to `dev/knowledge/backend/deployment-env-vars.md` (operator-facing) and `specs/010-driver-env-var-consumption/spec.md` (canonical contract).

## 5. ADR-021 — durable record

**Decision**: New ADR at `dev/adr/adr-021-driver-env-var-consumption.md` records:

1. **Why post-render injection failed** — Kubernetes strategic-merge has no container-wildcard; JSON-patch `replace` wipes the chart's env list. Documented in 008's review history; the ADR captures the root cause concisely.
2. **Why driver-side consumption is the right boundary** — drivers know their charts; the platform shouldn't fight the chart-rendering contract. Closer to how typed parameters already work.
3. **Why we ship merged dicts (not layered)** — simpler API; layered access is a future addition.
4. **Why we ship without helper macros** — drivers know their charts' env-list shape; v1 minimum surface area, helpers can land when patterns emerge.
5. **Migration responsibility** — driver authors must update templates to consume operator-set env vars. The platform doesn't do automatic migration.
6. **Relationship to ADR-019 (008's env-vars ADR) and ADR-020 (009's env-config-fanout ADR)** — 010 supersedes the post-render-injection portions of ADR-019; ADR-020 is unaffected (env-config fanout is orthogonal).

## 6. Testing strategy

| Test bundle | Layer | Coverage |
|---|---|---|
| `test_render_value_template_env_vars.py` (NEW) | Unit | Verify FR-001/FR-002: feed a synthetic `GlobalContext` with env vars set at deployment + per-component scopes through `render_value_template` with a probe Jinja template; assert `instance.config.env_vars` and `components[<name>].env_vars.config` render correctly. Cover the absent-key case (no env vars set anywhere → defensive `or {}` handles it). |
| `test_application_builder_env_vars.py` (MODIFY) | Unit | Delete the env-vars-injection assertions; keep any non-injection assertions. If the entire file was about injection, delete the file entirely. |
| `test_patch_builder.py` (DELETE) | Unit | The whole 008 env-vars patch-builder file goes away. |
| `test_env_vars_propagation.py` (MODIFY) | Propagation | Delete propagation rows for `DeploymentTimelineEntry.envVarCollisions` and `PostRenderInjection.envVars`. Keep all other rows. |
| `test_us1_deployment_level_env_var` (UNCHANGED) | E2E | The test body stays. The render path differs (driver-side consumption). The assertion ("operator sets `LOG_LEVEL=debug`, pod has it") is the same. |

**Prior art**: 008's E2E shape and the existing context-resolution unit tests in `backend/tests/unit/context/`.

## 7. Out of scope (explicit)

- **Layered template context** (drivers reading raw env / dep / comp layers separately). Future feature if a driver author asks.
- **Opinionated render macros** (Jinja `render_env_vars()` helper). Drivers consume `dict[str, str]` directly in v1.
- **Driver-side `spec.env_vars` semantic shift**. The doc-only declaration stays advisory; nothing about its wire shape, validators, or registration semantics changes.
- **Frontend changes**. The 009 Configuration tab + edit form work unchanged. No new UI surfaces.
- **Backwards-compatibility shim for old `EnvVarsPatch` injection**. Clean replace; no shim.
- **Reintroducing platform-side post-render injection in any form**. Codified as FR-026.
- **Auto-migration of existing drivers**. Driver authors update their values templates as needed; the simple-app reference shows how.

## 8. Branching + PR coordination (note for the implementer)

010 branches from 009's tip. The 008 branch (PR #197) currently contains the broken injection commits. At PR-merge time, two paths are workable:

- **Rebase 008 in place to drop the broken-injection commits**: cleaner mainline history; requires force-push of 008's branch before merge.
- **Land 008 → 009 → 010 as one stack**: the broken injection lands transiently; 010 deletes it before any mainline release sees it.

The spec doesn't mandate either path — both produce the same `develop` final state. The implementer chooses based on review-process preferences when the time comes.
