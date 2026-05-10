# Implementation Plan: Driver-Side Env Var Consumption via Values Template

**Branch**: `010-driver-env-var-consumption` | **Date**: 2026-05-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/010-driver-env-var-consumption/spec.md`

## Summary

Course-correct 008-deployment-env-vars by pivoting from broken platform-side post-render injection to driver-side template consumption. The work is concentrated in three small concerns:

1. **Verify the rendering context already exposes env vars.** `ApplicationBuilder.render_value_template` (`backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py:185`) calls `context.model_dump(exclude_none=True)` and feeds the dump to Jinja. The `GlobalContext` Pydantic model already carries `instance.config.env_vars` (post-008 deployment-effective dict) and `components[<name>].env_vars.config` (post-008 per-component effective dict). **The exposure for FR-001/FR-002 likely works out of the box** — this phase verifies via tests.

2. **Delete the broken injection layer cleanly.** `EnvVarsPatch`, `build_env_vars_post_rendering_patches`, the `ApplicationBuilder.build_env_vars_post_rendering_patches()` method + invocation, the `PostRenderInjection.env_vars` flag, the `EnvVarCollision` Strawberry type, the `ChartEnvCollision` dataclass, the `DeploymentTimelineEntry.envVarCollisions` GraphQL field, and every test asserting against any of them. The schema regenerates, the SDK regenerates, the frontend types regenerate — `grep` confirms zero source-code references remain.

3. **Update the simple-app driver to demo consumption.** `driver/examples/simple-app/values.j2.yml` gains an `env:` block on the simple-app container that consumes `instance.config.env_vars`. The simple-app Helm chart's container spec is extended (if needed) to accept the env list. The 008/009 E2E asserting "operator sets `LOG_LEVEL=debug`, pod has it" continues to pass via this driver-side consumption path.

The configuration model (env_vars at three scopes), validators, resolution pipeline, GraphQL read surface, driver-side `spec.env_vars` doc, typed error codes, 009's `UpdateEnvironmentInput` + fanout + frontend Configuration tab + edit form — all stay untouched.

## Technical Context

**Language/Version**: Python 3.12+ (backend), TypeScript 5+ / React 19 (frontend; only generated types touched)
**Primary Dependencies**: Pydantic v2, Strawberry GraphQL, Jinja2 (existing `SilentUndefined` policy), SQLModel, Prefect, FluxCD `HelmRelease.spec.postRenderers`
**Storage**: No schema changes. Existing `Environment.config` / `ApplicationInstance.context` JSON columns carry the same shape.
**Testing**: pytest unit tests; mandatory propagation tests preserved for retained schema; mandatory E2E for "operator sets env var → pod has it" continues to pass via driver-side consumption.
**Target Platform**: Linux server (Kubernetes 1.28+ on Kind/vCluster for E2E)
**Project Type**: Web service. Backend changes are deletion-heavy + a small simple-app driver update; frontend changes are codegen-only.
**Performance Goals**: Removing the post-render env-vars patch shrinks the per-reconcile patch set. Net positive on reconcile latency.
**Constraints**: Clean replace (FR-026); no platform-side injection in any form; no deprecation window.
**Scale/Scope**: Estimated ~15 source files touched (mostly deletions) + ~3 new files. Roughly +500 / −1500 lines (deletion-heavy net negative).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Declarative State Reconciliation** | ✅ Pass | Removing the buggy injection layer brings reconciliation closer to its declarative promise: the chart's rendered manifest is the desired state; the platform doesn't mutate it post-render. |
| **II. Driver-Based Deployment** | ✅ Pass | This feature *strengthens* the driver-based principle — driver authors regain control over the env-var surface their charts expose. |
| **III. Layered Architecture** | ✅ Pass | No layer boundaries change; the deletion removes code that incorrectly straddled the agent and chart-rendering layers. |
| **IV. Type Safety / Typed Errors** | ✅ Pass | The remaining error catalogue is unchanged. The deleted `EnvVarCollision` type wasn't a `ServiceError` — it was a derived data type with no associated error code. |
| **V. Test-First Development** | ✅ Pass | Mandatory E2E for US1 retained; mandatory propagation tests for the retained schema retained; the deleted-injection tests are deleted (not skipped). New unit test verifies template-context exposure. |
| **VI. Format and Lint Before Commit** | ✅ Pass | Standard `uv run invoke format lint` gate; no new tooling. |

**Governance gates triggered**:

- **Database schema or migration changes** — none.
- **GraphQL schema modifications** — yes (deletion-only). `EnvVarCollision`, `DeploymentTimelineEntry.envVarCollisions`, and `PostRenderInjectionInput.envVars` are removed from the schema. The change is a strict subset removal; CI's GraphQL freshness check confirms regenerated outputs match.
- **New dependencies** — none.
- **CI/CD workflow changes** — none.
- **Authentication/authorization changes** — none.

No constitution violations require justification; **Complexity Tracking** stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/010-driver-env-var-consumption/
├── plan.md              # This file
├── research.md          # Phase 0 — verify context exposure, deletion sweep, simple-app update
├── data-model.md        # Phase 1 — what changes, what stays
├── quickstart.md        # Phase 1 — manual validation walk-through
├── contracts/
│   └── graphql.md       # Phase 1 — what's removed, what's preserved (no new fields)
├── checklists/
│   └── requirements.md  # spec validation checklist
└── tasks.md             # Phase 2 (/speckit-tasks command output)
```

### Source Code (repository root) — deletions vs additions

**Deletions** (US2 / FR-005..FR-011):

```text
backend/styrmin_backend/
├── agent/service/kubernetes/resources/blocks/patches.py
│   └── EnvVarsPatch class                                  # DELETE
├── services/env_vars/patch_builder.py
│   ├── build_env_vars_post_rendering_patches               # DELETE
│   └── ChartEnvCollision dataclass                         # DELETE
│   (entire file becomes stub or is deleted if no other content)
├── agent/service/kubernetes/resources/builders/application.py
│   ├── build_env_vars_post_rendering_patches method        # DELETE
│   └── invocation in build()                               # DELETE
├── context/models/config.py
│   └── PostRenderInjection.env_vars field                  # DELETE
├── api/definitions/environment/inputs.py
│   └── PostRenderInjectionInput.envVars field              # DELETE
└── api/definitions/deployment_timeline/model.py
    ├── EnvVarCollision Strawberry type                     # DELETE
    └── DeploymentTimelineEntry.envVarCollisions field      # DELETE

backend/tests/
├── unit/services/env_vars/test_patch_builder.py            # DELETE (entire file)
└── unit/agent/test_application_builder_env_vars.py
    └── env-vars-injection assertion sections               # DELETE in place
```

**Additions / modifications**:

```text
backend/tests/unit/agent/
└── test_render_value_template_env_vars.py                  # NEW: verify FR-001/FR-002 context exposure

driver/examples/simple-app/
├── values.j2.yml                                            # MODIFY: consume instance.config.env_vars
└── (helm chart at driver/charts/simple-app/* — possibly extended to accept env list)

dev/guides/
└── driver-env-var-consumption.md                            # NEW: driver-author guide (FR-021/FR-022)

dev/knowledge/backend/
└── deployment-env-vars.md                                   # MODIFY: replace injection paragraph
                                                              # with consumption paragraph (FR-023)

dev/adr/
└── adr-021-driver-env-var-consumption.md                    # NEW: durable record of the pivot
```

**Codegen regeneration** (automatic via `uv run invoke generate` after the schema change):

```text
schema.graphql                                                  # auto-regen
python_sdk/src/styrmin_sdk/graphql/_generated/                  # auto-regen
frontend/src/generated/graphql.ts                               # auto-regen
```

**Structure Decision**: This feature is dominated by deletions in lockstep across patches, builder, schema, SDK, and frontend types. The clean-replace contract (FR-026) means there's no transitional state — the deletion happens in one PR. The new files are: one driver-author guide, one ADR, one verification test. The simple-app driver gets a small `values.j2.yml` modification + possibly a chart update.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations. Section intentionally empty.
