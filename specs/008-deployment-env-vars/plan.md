# Implementation Plan: Deployment Env Vars (Free-Form, Post-Render Injected)

**Branch**: `008-deployment-env-vars` | **Date**: 2026-05-06 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/008-deployment-env-vars/spec.md`

## Summary

Add a free-form `dict[str, str]` of environment variables to the Styrmin configuration model, settable at three scopes (environment, deployment, per-component) with **per-key deepest-wins** precedence, and auto-injected into every container of every pod-template-bearing workload via the existing post-render injection pipeline. The feature plugs into three already-load-bearing systems and adds nothing new of its own:

1. **Configuration model** — `env_vars: dict[str, str] | None` is added to `EnvironmentConfig`, `DeploymentConfig`, and the per-component config block. The merge is the same `_merge_*` machinery that resolves `SchedulingConfig`; the resolver pre-computes a `ResolvedComponentEnvVars` (mirror of `ResolvedComponentScheduling`) per component, including provenance.
2. **Driver-side documentation** — `Specification.env_vars: list[DriverEnvVarDoc] | None` is added to the driver schema. It is doc-only: the loader validates name regex, name uniqueness, `level=component → components non-empty`, and that every `components` reference exists in the driver's component map. It does **not** validate, default, or constrain user-set values.
3. **Post-render injection** — `PostRenderInjection.env_vars: bool | None` is added (three-valued, mirroring the existing flags). A new `build_env_vars_post_rendering_patches()` aggregator is wired into `ApplicationBuilder.build()` next to `build_scheduling_post_rendering_patches()`. Component-level patches narrow by the component's identifier label selector; when the driver declares no components, the deployment-level patch applies broadly.

The GraphQL surface gains read-only types (`EnvVar`, `ComponentEnvVars`, `DriverEnvVarDoc`) and read-only fields on `Deployment` (`envVars`, `componentEnvVars`) and the driver type (`envVars`). Writes flow through the existing `config: JSON` argument on `deploy()` / `updateDeployment()` (matching scheduling's precedent — see Research §1); no new mutation is added and no new typed mutation argument is required.

Conflict detection between operator-set env vars and chart-rendered env entries runs inside the patch builder. When a collision is detected, the patch builder records a `ChartEnvCollision` record on the patch result; the agent layer surfaces these as deployment-timeline `context_diff` entries (the existing `context_diff` channel naturally surfaces config changes including env vars; conflicts piggy-back as a structured field on the same per-task entry). When timeline emission degrades, a structured `logger.warning` is the fallback (per FR-028).

Driver upgrades that orphan stored per-component env vars succeed without user intervention. Orphan detection runs inside `EnvVarsResolver` at resolution time: any stored `componentEnvVars` block targeting a component the current driver does not declare is exposed via `ComponentEnvVars.isOrphaned = true` and is **not** injected. The orphan transition is naturally captured by the existing `context_diff` machinery — no new event type is introduced.

**Known v1 asymmetry** (acknowledged in critique 20260506-065007 §X1): the driver-side documentation (`spec.env_vars` block + `ApplicationDriverVersion.envVars` query field) and the orphan-tracking surface (`ComponentEnvVars.isOrphaned`) ship in v1, but the frontend UI that surfaces them is explicitly out of scope (PRD §"Out of Scope"). This is a deliberate trade-off: the driver loader and resolver have to know about both paths, and splitting them across two tickets would force the loader/resolver work to live on a half-finished branch. SDK and GraphQL consumers benefit immediately; UI consumers benefit when the UI ticket lands.

## Technical Context

**Language/Version**: Python 3.12+ (backend), TypeScript 5+ / React 19 (frontend; UI changes deferred per spec FR-036 and PRD "Out of Scope")
**Primary Dependencies**: Pydantic v2, Strawberry GraphQL, SQLModel, Prefect, FluxCD `HelmRelease.spec.postRenderers` (Kustomize patches), kr8s
**Storage**: Existing `Environment.config` and `ApplicationInstance.context` JSON columns — env vars merge into the same Pydantic models that already serialise into those columns (FR-022). No new column.
**Testing**: pytest unit tests under `backend/tests/unit/{context,services,agent}/`; one E2E scenario under `backend/tests/e2e/` marked `api_only`; one mandatory GraphQL propagation test per new field/argument (Constitution §V; `dev/guides/graphql-propagation-tests.md`)
**Target Platform**: Linux server (Kubernetes 1.28+ on Kind/vCluster for E2E)
**Project Type**: Web service (backend + frontend; this feature is backend-only in v1)
**Performance Goals**: Resolution and patch build are part of the existing reconcile pipeline; the feature MUST NOT regress reconcile latency by more than 5% on the existing benchmark suite
**Constraints**: Per-value cap 64 KiB; per-scope dict cap 100 entries / 256 KiB total; env var name regex `^[A-Za-z_][A-Za-z0-9_]*$` (POSIX-portable identifiers, matching standard practice across Helm and Kubernetes tooling)
**Scale/Scope**: Estimated ~25 source files touched (Pydantic models + resolver + patch builder + GraphQL types + driver loader + tests); ~5 new modules

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Declarative State Reconciliation** | ✅ Pass | Env vars are part of the desired config; resolution is idempotent (pure merge), and the post-render patch is deterministic given the same inputs. |
| **II. Driver-Based Deployment** | ✅ Pass | Driver-side `spec.env_vars` is doc-only and validated at load time; nothing in the env var machinery short-circuits driver behaviour. |
| **III. Layered Architecture** | ✅ Pass | GraphQL types → service-layer resolver/validator → repository (UnitOfWork) → DB. The agent layer consumes the resolved config as a read-only input. |
| **IV. Type Safety and Typed Errors** | ✅ Pass | All new structures are Pydantic + Strawberry types. New error types extend `ServiceError` (`InvalidEnvVarNameError`, `EnvVarSizeLimitExceededError`, `UnknownComponentEnvVarError`, `DuplicateEnvVarNameError`, `OrphanedEnvVarError`'s only used as informational). |
| **V. Test-First Development** | ✅ Pass | Six unit-test bundles, one E2E scenario, and one propagation test per new GraphQL field/argument are scheduled in `tasks.md` (see [research.md §6](./research.md#6-testing-strategy)). |
| **VI. Format and Lint Before Commit** | ✅ Pass | Standard `uv run invoke format lint` gate; no new tooling. |

**Governance gates triggered**:

- **Database schema or migration changes** — none. Env vars merge into the existing JSON config columns (FR-022, Research §3).
- **GraphQL schema modifications** — yes. Surface enumerated in `contracts/graphql.md`. Mandatory propagation tests per new field/argument (Constitution §V; non-negotiable).
- **New dependencies** — none.
- **CI/CD workflow changes** — none.
- **Authentication/authorization changes** — none.

No constitution violations require justification; **Complexity Tracking** stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/008-deployment-env-vars/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 — decisions, alternatives, prior art
├── data-model.md        # Phase 1 — entity shapes and merge semantics
├── quickstart.md        # Phase 1 — manual validation walk-through
├── contracts/
│   └── graphql.md       # Phase 1 — GraphQL surface contract
├── checklists/
│   └── requirements.md  # spec validation checklist
└── tasks.md             # Phase 2 (/speckit-tasks command output)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── context/
│   ├── models/
│   │   ├── config.py             # +EnvVarsConfig fields on EnvironmentConfig/DeploymentConfig
│   │   │                         # +env_vars flag on PostRenderInjection
│   │   └── components.py         # +ResolvedComponentEnvVars (mirror of ResolvedComponentScheduling)
│   └── resolvers.py              # +_merge_env_vars, +effective_inject_flag handles env_vars
├── services/
│   ├── env_vars/                 # NEW
│   │   ├── __init__.py
│   │   ├── validator.py          # name regex, size caps, duplicate-name rejection
│   │   ├── resolver.py           # per-component effective dict + provenance + orphan detection
│   │   ├── patch_builder.py      # build_env_vars_post_rendering_patches + collision detection
│   │   └── exceptions.py         # InvalidEnvVarNameError, etc.
│   ├── driver/
│   │   ├── models/resources/
│   │   │   ├── env_vars.py       # NEW: DriverEnvVarDoc, level enum, validators
│   │   │   └── driver.py         # +env_vars field on Specification
│   │   └── validators.py         # +validate_env_var_doc_components_exist
│   └── deployment.py             # validate component env vars target known components on mutate
├── api/
│   ├── definitions/
│   │   ├── deployment/
│   │   │   └── model.py          # +EnvVar, +ComponentEnvVars + isOrphaned + envVars/componentEnvVars resolvers
│   │   └── application_driver/
│   │       └── model.py          # +DriverEnvVarDoc + envVars resolver
│   └── schema/
│       ├── mutation.py           # (no surface change — env vars ride config: JSON)
│       └── errors.py             # +error codes for the new ServiceError subclasses
└── agent/service/kubernetes/resources/
    ├── blocks/patches.py         # +EnvVarsPatch (strategic-merge env injection)
    └── builders/application.py   # +build_env_vars_post_rendering_patches() invocation

backend/tests/
├── unit/
│   ├── services/env_vars/
│   │   ├── test_validator.py
│   │   ├── test_resolver.py
│   │   └── test_patch_builder.py
│   ├── services/driver/
│   │   └── test_env_var_doc_validator.py
│   ├── api/schema/
│   │   └── test_env_vars_propagation.py   # mandatory GraphQL ↔ DB propagation
│   └── agent/
│       └── test_application_builder_env_vars.py
└── e2e/
    └── test_deployment_env_vars.py        # @pytest.mark.api_only, exercises FR-001..FR-033

dev/adr/
└── adr-019-deployment-env-vars.md          # rationale, drafted alongside implementation

driver/examples/simple-app/
└── driver.styrmin.yml                      # +spec.env_vars block (smoke test for loader)
```

**Structure Decision**: This feature reuses the existing layered architecture exactly. The new `services/env_vars/` package is a small parallel to the existing `services/scheduling/` package — same shape (validator + resolver + patch builder + exceptions), same intra-package boundaries. The patch builder lives under `services/env_vars/` rather than under `services/scheduling/` because they describe orthogonal concerns even though their patch *outputs* are similar in shape; co-locating them would be premature.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations. Section intentionally empty.
