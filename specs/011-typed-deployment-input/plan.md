# Implementation Plan: Typed `UpdateDeploymentInput` GraphQL Surface

**Branch**: `011-typed-deployment-input` | **Date**: 2026-05-14 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/011-typed-deployment-input/spec.md`

## Summary

Replace the four loose arguments on the `updateDeployment` mutation (`name`, `config: JSON`, `parameters: JSON`, `serviceNameOverrides: [ServiceNameOverride!]`) with a single typed `input: UpdateDeploymentInput!` argument that mirrors the deployment-configuration shape field-for-field plus the four deployment-only fields. The conversion happens at the resolver boundary via a new helper `update_deployment_input_to_dict(...)` that follows the same rules as the existing `update_environment_input_to_dict(...)`, with two additions: a `parameters` list-to-dict flatten (raising new `DuplicateParameterNameError`) and a `components` list-to-dict flatten (raising new `DuplicateComponentNameError`). The shared leaf inputs (env-var entry, scheduling block, dedicated-ingress configuration, etc.) currently in `api/definitions/environment/inputs.py` are extracted into a new `api/definitions/config/inputs.py` module and reused unchanged across both top-level inputs. Hard cutover — the old arguments are removed in the same release. SDK, CLI, frontend, and in-tree tests are retargeted via codegen + targeted edits. No service-layer changes, no DB changes, no behaviour change to the reconciliation pipeline.

## Technical Context

**Language/Version**: Python 3.14+ (backend); TypeScript 5.9.3 (frontend)
**Primary Dependencies**: Strawberry GraphQL (input types + resolver); Pydantic v2 (`DeploymentConfig` model unchanged); SQLModel (`Deployment` row unchanged); urql + `@graphql-codegen/typescript-react-query` (frontend); httpx + ariadne-codegen (SDK)
**Storage**: PostgreSQL via SQLModel — **no schema changes**, no migration
**Testing**: pytest (backend unit, functional, E2E); Vitest (frontend); the propagation-test matrix in `contracts/graphql.md` §4 (22 tests) and the error-propagation matrix in §5 (9 tests); one new E2E `test_update_deployment_typed_input_propagates_component_env_var_and_scheduling` (`api_only`)
**Target Platform**: Backend on Linux (containerised); SDK runs on any host with Python 3.14+; frontend is a SPA in evergreen browsers
**Project Type**: Web application (backend + frontend + Python SDK + CLI)
**Performance Goals**: No new performance targets — this feature is a pure typing/surface change with zero impact on request handling, reconciliation latency, or codegen build time
**Constraints**: Hard cutover (no transitional dual-signature period); merge semantics for `parameters` preserved deliberately; full-replacement everywhere else on the input
**Scale/Scope**: Single mutation; one new top-level input (~17 fields); two new leaf inputs (`ComponentConfigInput`, `ParameterValueInput`); one new auxiliary leaf (`StandardStorageInput`); two new typed errors

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### §I Declarative State Reconciliation — PASS

Pure GraphQL-surface change. The input still resolves down to the existing `update_deployment` service function which writes a desired-state dict to `Deployment.config`. Idempotent properties are unchanged; no new imperative side effects introduced. The reconciliation pipeline is untouched.

### §II Driver-Based Deployment — N/A

The change is at the API surface above drivers. No driver model changes, no driver-rendering changes, no helm chart or values template changes. New per-component knobs (e.g. #202 replicas) will slot into `ComponentConfigInput` later but this feature ships only the slot.

### §III Layered Architecture — PASS

GraphQL API layer (`api/`) absorbs all new code: input definitions under `api/definitions/deployment/` and `api/definitions/config/`, resolver edit at `api/schema/mutation.py`. The service-layer function `update_deployment(...)` keeps its signature; the resolver derives the four legacy arguments from the converted dict. The repository layer is untouched. The UnitOfWork pattern continues to coordinate the transaction. No cross-layer shortcuts.

### §IV Type Safety and Typed Errors — PASS (with new errors)

Two new `ServiceError` subclasses (`DuplicateParameterNameError`, `DuplicateComponentNameError`) carry stable `error_code` values (`DUPLICATE_PARAMETER_NAME`, `DUPLICATE_COMPONENT_NAME`) and reach the GraphQL boundary via the existing `StructuredErrorExtension` middleware. All existing typed env-var errors (`INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`, `UNKNOWN_COMPONENT_ENV_VAR`) continue to surface for both top-level and `components.*` scopes. Python type hints remain mandatory; `ty` will check the new modules.

### §V Test-First Development — PASS

One new E2E `test_update_deployment_typed_input_propagates_component_env_var_and_scheduling` ships with the feature, marked `@pytest.mark.api_only(reason="SDK-driven; no UI flow exercised — the [ui-chromium] variant would just re-run the same SDK call.")`. The propagation-test matrix in `contracts/graphql.md` §4 covers all 22 new input fields with one unit test each per `dev/guides/graphql-propagation-tests.md`; the error-propagation matrix in §5 covers all 9 typed-error paths. Combined with the introspection assertions in §6 and the retargeted existing functional tests, every constitutional §V requirement is met without exception or skip request.

### §VI Format and Lint Before Commit — PASS

`uv run invoke format lint` on the backend, `pnpm lint` + `pnpm test` on the frontend, and `uv run invoke validate-graphql` on the new `.graphql` operations are all part of the implementation tasks. Pre-commit hooks enforce this locally.

### Governance Gates

- **GraphQL schema modifications** — explicitly crossed. The cutover plan in `research.md` §6 lists every in-tree consumer and confirms zero external callers (verified by repo-wide grep at planning time). The cutover is documented and the hard-cutover decision is justified by the codegen-forces-regen reality of the SDK + frontend pipelines.
- Database schema, new dependencies, CI/CD, auth — **none crossed**.

**Verdict**: All gates pass. No violations to track in the Complexity Tracking table below.

## Project Structure

### Documentation (this feature)

```text
specs/011-typed-deployment-input/
├── plan.md              # This file
├── spec.md              # Phase -1 output (/speckit-specify)
├── research.md          # Phase 0 output (/speckit-plan)
├── data-model.md        # Phase 1 output (/speckit-plan)
├── quickstart.md        # Phase 1 output (/speckit-plan)
├── contracts/
│   └── graphql.md       # Phase 1 output (/speckit-plan) — schema + test matrices
├── checklists/
│   └── requirements.md  # Phase -1 output (/speckit-specify) — quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks) — not created yet
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── api/
│   │   ├── definitions/
│   │   │   ├── config/                       # NEW MODULE — shared leaf inputs
│   │   │   │   ├── __init__.py
│   │   │   │   └── inputs.py                 # NEW — extracted shared leaves + _convert_value
│   │   │   ├── deployment/
│   │   │   │   ├── inputs.py                 # NEW — UpdateDeploymentInput, ComponentConfigInput,
│   │   │   │   │                             #       ParameterValueInput, StandardStorageInput,
│   │   │   │   │                             #       update_deployment_input_to_dict()
│   │   │   │   └── model.py                  # unchanged
│   │   │   ├── environment/
│   │   │   │   └── inputs.py                 # EDIT — re-export shared leaves from config/
│   │   │   └── service/
│   │   │       └── model.py                  # EDIT — rename ServiceNameOverride → ServiceNameOverrideInput
│   │   └── schema/
│   │       └── mutation.py                   # EDIT — updateDeployment resolver signature change
│   └── services/
│       ├── env_vars/
│       │   └── exceptions.py                 # EDIT — add DuplicateComponentNameError
│       ├── parameters/
│       │   └── exceptions.py                 # EDIT (or add) — DuplicateParameterNameError
│       └── deployment.py                     # unchanged
└── tests/
    ├── e2e/
    │   ├── drivers/
    │   │   ├── api_driver.py                 # EDIT — entrypoint signature
    │   │   ├── ui_driver.py                  # EDIT — entrypoint signature
    │   │   └── protocol.py                   # EDIT — entrypoint signature
    │   ├── test_pod_scheduling.py            # EDIT — call-site retarget
    │   ├── test_deployment_env_vars.py       # EDIT — call-site retarget
    │   └── test_deployment_typed_input.py    # NEW — feature E2E
    └── functional/
        ├── graphql/
        │   ├── operations/
        │   │   ├── update_deployment.graphql        # EDIT — input shape
        │   │   └── update_deployment_config.graphql # EDIT — input shape
        │   ├── test_deployment.py                                   # EDIT — call sites
        │   ├── test_env_vars_propagation.py                         # EDIT — call sites
        │   ├── test_update_deployment_input_propagation.py          # NEW — propagation matrix (22 tests)
        │   ├── test_update_deployment_input_errors.py               # NEW — error matrix (9 tests)
        │   └── test_update_deployment_input_introspection.py        # NEW — schema-coverage assertions (2 tests)
        ├── test_api_scheduling_config.py                            # EDIT — call sites
        └── helpers.py                                               # EDIT — helper update

python_sdk/
├── src/styrmin_sdk/
│   ├── graphql/
│   │   ├── update_deployment.graphql         # EDIT — new query shape
│   │   └── _generated/                       # regenerated by `uv run invoke generate`
│   └── resources/
│       └── deployments.py                    # EDIT — update(...) signature change
└── tests/
    └── test_deployments.py                   # EDIT — call sites

frontend/
├── src/
│   ├── graphql/
│   │   └── update_deployment.graphql         # EDIT — new query shape
│   ├── generated/
│   │   └── graphql.ts                        # regenerated by `pnpm run codegen`
│   ├── lib/
│   │   └── deployment-input.ts               # NEW — deploymentConfigToInput() helper
│   └── components/deployment/scheduling/
│       └── SchedulingConfigDialog.tsx        # EDIT — call-site retarget

schema.graphql                                # regenerated by `uv run styrmin export graphql-schema`
```

**Structure Decision**: Standard web-application layout — backend + frontend + python_sdk are existing roots in this repo. New code lives in three places: backend `api/definitions/{config,deployment}/`, frontend `lib/`, and new test modules. No new top-level directories.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified.

No violations. Section intentionally empty.

## Phase 2 hand-off

The next phase is `/speckit-tasks`, which will read this plan plus `contracts/graphql.md` (§4 + §5 + §6 matrices) and `data-model.md` and produce a dependency-ordered `tasks.md`. The tasks are largely enumerable from the matrices:

- 1 task: extract shared leaf inputs into `api/definitions/config/inputs.py`
- 1 task: define `UpdateDeploymentInput`, `ComponentConfigInput`, `ParameterValueInput`, `StandardStorageInput` under `api/definitions/deployment/inputs.py`
- 1 task: implement `update_deployment_input_to_dict()` with the rules from `data-model.md` §4
- 2 tasks: add `DuplicateParameterNameError` and `DuplicateComponentNameError` typed errors
- 1 task: rename `ServiceNameOverride` → `ServiceNameOverrideInput`
- 1 task: rewrite the `updateDeployment` resolver to take `input: UpdateDeploymentInput!` and derive the four legacy arguments
- 1 task: regenerate `schema.graphql` and SDK types
- 1 task: regenerate frontend codegen + add `deploymentConfigToInput()` helper + retarget `SchedulingConfigDialog`
- 22 tasks: one per propagation-matrix row (parallelisable in groups)
- 9 tasks: one per error-matrix row
- 2 tasks: introspection assertions
- 1 task: new E2E `test_update_deployment_typed_input_propagates_component_env_var_and_scheduling`
- N tasks: retarget the existing functional + E2E + SDK + helpers call sites enumerated in `research.md` §6

`/speckit-tasks` will sequence these so the schema + helper + resolver land first, codegen runs once both sides of the SDK/frontend boundary are ready to consume the new shape, and tests land in their natural dependency order (introspection → propagation → errors → behaviour-regression → E2E).
