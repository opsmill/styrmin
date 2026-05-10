# Implementation Plan: Env-Config Input Completeness + Validator Hardening + UI Test Infrastructure

**Branch**: `011-env-config-input-hardening` | **Date**: 2026-05-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/011-env-config-input-hardening/spec.md`

## Summary

Hardening pass on 008+009+010 fixing four review-found bugs that cluster naturally:

1. **`UpdateEnvironmentInput` completeness** (US1): add `ingressClass` + `dbSize` to the typed input + a schema-walking propagation test that prevents future drift.
2. **Frontend enum runtime-value transform** (US2): replace TypeScript-only `as`-casts in `buildFullReplacementInput` with a real value-mapping layer that translates persisted Pydantic strings (`"https"`, `"NodeExternalIP"`) to GraphQL enum literals (`HTTPS`, `NODE_EXTERNAL_IP`).
3. **Validator type-check** (US3): a 3-line type guard on `validate_env_vars_dict` + a new typed `InvalidEnvVarValueError` (code `INVALID_ENV_VAR_VALUE`) so non-string values surface as typed errors instead of 500s.
4. **UI E2E + marker cleanup** (US4): extend the existing UI driver (`backend/tests/e2e/drivers/ui_driver.py`) with `update_environment_via_form` — this is the project's established pattern, NOT a separate `EnvironmentDetailPage` class. Unskip T061. Audit 9 `api_only` markers across 008+009+010 E2Es; remove the misapplied ones; document the retained ones inline.

The work is concentrated in five small concerns, none of which require new packages, dependencies, migrations, or architectural decisions:

- Two new Strawberry input fields + the schema-walk test (US1).
- A value-transform helper in `EnvironmentConfigurationTab.tsx` + Vitest coverage (US2).
- A typed error subclass + entry-point type guard (US3).
- A new method on the existing UI driver + the marker audit (US4).

The 008+009+010 surfaces (configuration model, validators, resolver pipeline, mutation, fanout, frontend Configuration tab read view, simple-app driver consumption) all stay untouched.

## Technical Context

**Language/Version**: Python 3.12+ (backend), TypeScript 5+ / React 19 (frontend).
**Primary Dependencies**: Pydantic v2, Strawberry GraphQL, urql, Playwright (existing E2E infra).
**Storage**: No schema/DB changes.
**Testing**: pytest unit + propagation tests; Vitest for the frontend transform; Playwright `[ui-chromium]` E2E for T061.
**Target Platform**: Linux server (Kind/vCluster for E2E).
**Project Type**: Web service. Backend changes are minimal; frontend changes are localised to `EnvironmentConfigurationTab.tsx` and the Playwright UI driver.
**Performance Goals**: No production-path performance impact. Marker cleanup roughly doubles the run-time of the affected E2Es (now run under both `[api-chromium]` and `[ui-chromium]`) — accepted per AGENTS.md dual-entrypoint policy.
**Constraints**: Clean schema additions (no deprecation window); SDK regenerates; existing callers keep working.
**Scale/Scope**: ~10-15 source files touched + 4-5 new files. Roughly +600 / −150 lines.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Declarative State Reconciliation** | ✅ Pass | No reconciliation changes; only API surface + validator + frontend + tests. |
| **II. Driver-Based Deployment** | ✅ Pass | No driver-side changes. |
| **III. Layered Architecture** | ✅ Pass | Each fix lands in its own layer with no cross-layer leakage. |
| **IV. Type Safety / Typed Errors** | ✅ Pass | US3 *strengthens* the typed-error contract by adding `InvalidEnvVarValueError`; US1 *strengthens* type safety on the GraphQL input boundary. |
| **V. Test-First Development** | ✅ Pass | Mandatory propagation + E2E + Vitest coverage scheduled per FR set. The schema-walking propagation test (US1) is novel — covered in research §1. |
| **VI. Format and Lint** | ✅ Pass | Standard gates. |

**Governance gates triggered**:

- **Database schema or migration changes** — none.
- **GraphQL schema modifications** — yes, additive. `UpdateEnvironmentInput` gains 2 fields. Mandatory propagation tests per Constitution §V; covered in `contracts/graphql.md`.
- **New dependencies** — none.
- **CI/CD workflow changes** — none.
- **Authentication/authorization changes** — none.

No constitution violations require justification; **Complexity Tracking** stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/011-env-config-input-hardening/
├── plan.md              # This file
├── research.md          # Phase 0 — schema-walk approach, page-object-vs-driver-method, audit landscape
├── data-model.md        # Phase 1 — input field shapes, transform mapping, error class
├── quickstart.md        # Phase 1 — manual validation walk-through
├── contracts/
│   └── graphql.md       # Phase 1 — added input fields + propagation matrix delta
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks output)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── api/definitions/environment/inputs.py                   # +2 input fields (ingressClass, dbSize)
├── services/env_vars/exceptions.py                          # +InvalidEnvVarValueError class
├── services/env_vars/validator.py                           # +entry-point type guard
└── api/errors.py                                            # +INVALID_ENV_VAR_VALUE in ErrorCode enum

backend/tests/
├── unit/services/env_vars/test_validator.py                # +type-check unit tests for non-string values
├── functional/graphql/test_environment_update_propagation.py
│   ├── +propagation rows for ingressClass / dbSize round-trip
│   └── +schema-walking input completeness test
├── functional/graphql/test_env_vars_propagation.py
│   └── +propagation row: INVALID_ENV_VAR_VALUE rejection on JSON config write paths
└── e2e/drivers/ui_driver.py                                 # +update_environment_via_form method

frontend/src/
├── pages/environments/EnvironmentConfigurationTab.tsx      # +enum value-transform layer in buildFullReplacementInput
└── __tests__/EnvironmentConfigurationTab.test.tsx          # +Vitest cases for the transform

backend/tests/e2e/
├── test_environment_update.py                              # un-skip T061 + use ui_driver.update_environment_via_form + marker audit
└── test_deployment_env_vars.py                             # marker audit (remove misapplied api_only markers)
```

**Structure Decision**: This feature is dominated by small, surgical edits across the existing surface. No new modules; no new directories. The schema-walking propagation test (US1) is the only genuinely new test pattern; everything else extends existing test files. The UI driver method (US4) reuses the established `ui_driver.py` pattern rather than introducing a separate `EnvironmentDetailPage` class — see research §2 for the rationale.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations. Section intentionally empty.
