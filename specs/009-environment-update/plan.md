# Implementation Plan: Environment-Config Update with Deployment Fanout

**Branch**: `009-environment-update` | **Date**: 2026-05-07 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/009-environment-update/spec.md`

## Summary

Replace the JSON-blob `updateEnvironment(environmentId: UUID!, config: JSON)` mutation introduced in 008-deployment-env-vars with a structured `updateEnvironment(environmentId: UUID!, input: UpdateEnvironmentInput!)` mutation, and have it dispatch a per-deployment redeploy Task for every non-tombstoned, non-internal deployment in the environment whenever the input changes the persisted env-config. The work plugs into three already-load-bearing systems and introduces almost nothing new of its own:

1. **GraphQL input layer** — `UpdateEnvironmentInput` is a Strawberry input mirror of the existing `EnvironmentConfig` Pydantic model. Nested typed inputs (`EnvVarInput`, `DedicatedIngressInput`, `SchedulingInput`, `AffinityBlockInput`, `ResourceRequirementsInput`, `TolerationInput`, `TopologySpreadInput`) mirror the corresponding Pydantic types. The mutation handler converts the typed input into the existing `EnvironmentConfig` Pydantic model on the way in, then reuses the post-008 validation pipeline (including the `_prevalidate_environment_env_vars` helper) so typed error codes survive the GraphQL boundary.
2. **Service-layer fanout** — `update_environment` (in `services/environments.py`) gains a fanout step after persisting the new config. It iterates over the environment's non-tombstoned, non-internal deployments and for each one invokes the same `generate_instance_from_deployment` + `apply_state` pipeline that `update_deployment_version` already uses. The result is one new `ApplicationInstance` version per deployment plus one `Task` per deployment; the mutation returns when all Tasks are dispatched (not when they complete).
3. **Frontend environment detail page** — extends the existing `EnvironmentDetailPage.tsx` with a new "Configuration" tab rendering the typed config (US3) and an env-var edit form within that tab (US4). The form reads existing config, mediates edits, builds a full-replacement `UpdateEnvironmentInput`, and submits via the regenerated SDK / generated GraphQL hook. A confirmation dialog explicitly names the deployment count that will be redeployed.

The mutation surface is a **clean replace**: `config: JSON` is removed from the schema, the SDK, the frontend's generated TypeScript client, and any documentation references. There is no deprecation window; a future incremental-update mutation may be added if a real workload demands it (out of scope for v1).

No-op detection compares the canonical-serialized form of the input against the canonical-serialized persisted config. When equal, the platform persists the row (so updated-at timestamps still tick) but skips the fanout — no spurious Tasks, no spurious timeline entries.

Per-deployment failure isolation rides the existing Task machinery: a redeploy Task that fails is recorded on its deployment's timeline like any other Task failure, and peer deployments' Tasks are independent. The `update_environment` mutation result does not depend on Task outcomes.

## Technical Context

**Language/Version**: Python 3.12+ (backend), TypeScript 5+ / React 19 (frontend)
**Primary Dependencies**: Pydantic v2, Strawberry GraphQL, SQLModel, Prefect, FluxCD `HelmRelease.spec.postRenderers`, urql (frontend GraphQL client), TanStack Router/Query, Base UI / Tailwind
**Storage**: Existing `Environment.config` JSON column — no schema change. `ApplicationInstance` rows continue to be the per-deployment versioning record. No new columns or migrations.
**Testing**: pytest unit tests under `backend/tests/unit/services/`, mandatory propagation tests under `backend/tests/functional/graphql/`, mandatory E2E tests under `backend/tests/e2e/` covering US1's headline scenario AND its failure-isolation variant. Vitest + React Testing Library for the frontend form's client-side validation. Playwright for `[ui-chromium]` E2E coverage of the form.
**Target Platform**: Linux server (Kubernetes 1.28+ on Kind/vCluster for E2E)
**Project Type**: Web service (backend + frontend; both touched in this feature)
**Performance Goals**: The fanout is N-deployment-times the cost of a single redeploy. The mutation MUST return within the same envelope as the existing `update_deployment_version` mutation — fanout dispatch is sequential but does not block on Task completion.
**Constraints**: Reuses post-008 size caps for env vars (64 KiB per value, 100 entries / 256 KiB per scope, 256 KiB resolved per-component, 1 MiB total resolved per deployment). No optimistic concurrency control on the mutation (see spec Assumptions).
**Scale/Scope**: Estimated ~30 source files touched (backend mutation + service + GraphQL types; frontend page extension + form + GraphQL hook regen; tests). Roughly +1500 / −300 lines.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Declarative State Reconciliation** | ✅ Pass | The fanout is desired-state propagation: env-config row is the desired state; per-deployment redeploy Tasks reconcile each deployment to it. Idempotent (no-op detection skips spurious Tasks). |
| **II. Driver-Based Deployment** | ✅ Pass | The fanout uses each deployment's already-bound driver version; no driver-side change. |
| **III. Layered Architecture** | ✅ Pass | GraphQL → service → repository → DB. The fanout dispatches Tasks through the existing `apply_state` Prefect path; nothing crosses layers. |
| **IV. Type Safety / Typed Errors** | ✅ Pass | The whole point of this feature is to push the write surface onto typed Strawberry inputs. Existing `ServiceError` subclasses (`InvalidEnvVarNameError`, etc.) propagate unchanged. One new error type (`EnvironmentNotFoundError` already exists; reused). |
| **V. Test-First Development** | ✅ Pass | Mandatory E2E for US1 + failure-isolation variant explicitly scheduled in tasks.md. Mandatory propagation tests for every new schema field/argument (the typed input has many; each row of the matrix gets one assertion). Frontend form has Vitest coverage for client-side validation rules. |
| **VI. Format and Lint Before Commit** | ✅ Pass | Standard `uv run invoke format lint` gate; new frontend code goes through ESLint + Prettier; no new tooling. |

**Governance gates triggered**:

- **Database schema or migration changes** — none. Existing `Environment.config` column carries the same shape; the feature only changes how the input is shaped at the GraphQL boundary.
- **GraphQL schema modifications** — yes, substantial. New input types, removed `config: JSON` argument. Surface enumerated in `contracts/graphql.md`. Mandatory propagation tests per Constitution §V.
- **New dependencies** — none.
- **CI/CD workflow changes** — none.
- **Authentication/authorization changes** — none.

No constitution violations require justification; **Complexity Tracking** stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/009-environment-update/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 — input shape, fanout strategy, no-op detection
├── data-model.md        # Phase 1 — entity shapes and conversion semantics
├── quickstart.md        # Phase 1 — manual validation walk-through
├── contracts/
│   └── graphql.md       # Phase 1 — GraphQL surface contract + propagation matrix
├── checklists/
│   └── requirements.md  # spec validation checklist
└── tasks.md             # Phase 2 (/speckit-tasks command output)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── api/
│   ├── definitions/
│   │   └── environment/
│   │       ├── inputs.py             # NEW: UpdateEnvironmentInput + nested input types
│   │       └── model.py              # (unchanged in this feature; read-side already in place)
│   └── schema/
│       └── mutation.py               # update_environment switches to typed input; config: JSON removed
├── services/
│   ├── environments.py               # +fanout step, +no-op detection helper
│   └── deployment.py                 # +redeploy_for_environment_update helper extracted from update_deployment_version
└── (no other backend files changed)

frontend/src/
├── pages/
│   └── environments/
│       ├── EnvironmentDetailPage.tsx       # +Configuration tab
│       └── EnvironmentConfigurationTab.tsx # NEW: read-side render of full config
├── components/
│   └── environment/
│       ├── EnvVarsForm.tsx                 # NEW: env-var edit form (US4)
│       └── RedeployConfirmDialog.tsx       # NEW: confirmation dialog with deployment count
└── graphql/
    └── update_environment.graphql          # rewritten to use typed UpdateEnvironmentInput

backend/tests/
├── unit/
│   └── services/
│       ├── test_environments.py            # +fanout dispatch + no-op detection unit tests
│       └── test_environment_update_inputs.py  # NEW: typed-input → EnvironmentConfig conversion tests
├── functional/
│   └── graphql/
│       └── test_environment_update_propagation.py  # NEW: propagation per new field/argument
└── e2e/
    └── test_environment_update.py          # NEW: US1 fanout + failure-isolation E2E

frontend/src/__tests__/
└── EnvVarsForm.test.tsx                    # NEW: client-side validation Vitest coverage
```

**Structure Decision**: This feature reuses existing infrastructure across all three layers (mutation, service, frontend page). The new files are: one input-types module on the backend (`inputs.py`), three new frontend components (configuration tab + env-vars form + confirmation dialog), three new test modules. The bulk of the work is wiring through existing seams (the typed input at the GraphQL boundary, the existing `apply_state` machinery for the fanout, the existing `EnvironmentDetailPage` for the UI extension).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations. Section intentionally empty.
