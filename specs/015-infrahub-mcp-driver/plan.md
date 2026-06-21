# Implementation Plan: Infrahub MCP Server Application Driver

**Branch**: `015-infrahub-mcp-driver` | **Date**: 2026-06-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/015-infrahub-mcp-driver/spec.md`

## Summary

Add a new example Application Driver, `infrahub-mcp`, under `driver/examples/infrahub-mcp/`. The Driver stands up the upstream Infrahub MCP server as a managed, reconciled Styrmin Deployment: one `server` Component and one internal `http` Service (`infrahub-mcp`, port 8001). It runs in fixed **token-passthrough** auth mode — the calling AI client forwards its own Infrahub token per request, so Styrmin never stores or surfaces a credential. Operators supply `infrahub_address` (required) and optionally `mcp_read_only` (default `false`) and `mcp_log_level` (enum, default `info`). The Driver connects to an existing Infrahub; it does not deploy Infrahub.

Technical approach: this is a **driver-layer + docs change only**. It reuses the existing manifest schema (`DRIVERS.md`), parameter model (`DriverParameterDefinition`), parameter validator, and Component/Service/reconciliation machinery unchanged — no backend service, GraphQL, SDK, CLI, or frontend code. The manifest declares **no `actions`** (no `actions.py`). Coverage is unit-level: extend `backend/tests/unit/services/driver/test_deserializer.py` and the parameter-validator suite to assert the manifest deserializes to the expected Component/Service/parameter set and that `values.j2.yml` renders the three target keys with `mcp.authMode: token-passthrough` and no `apiToken`. E2E is intentionally omitted (owner-approved).

## Technical Context

**Language/Version**: Python 3.14+ (driver manifest model, deserializer, parameter validator, tests); driver artifacts are YAML + Jinja2.

**Primary Dependencies**: Pydantic v2 (`DriverParameterDefinition`, `DriverSpec`), Jinja2 (values template render), PyYAML (manifest parse), pytest (tests). Upstream runtime dependency (owner-approved): the `infrahub-mcp` Helm chart at `oci://registry.opsmill.io/opsmill/chart/infrahub-mcp` and image `registry.opsmill.io/opsmill/infrahub-mcp`.

**Storage**: N/A — no database schema change. Driver definitions live on the filesystem under `driver/examples/`.

**Testing**: pytest unit tests only (`backend/tests/unit/services/driver/`). E2E intentionally omitted (owner-approved deviation from Constitution §V; recorded in spec Assumptions and below).

**Target Platform**: Kubernetes (the rendered chart deploys the MCP server); Styrmin backend on Linux.

**Project Type**: Driver authoring within the existing web-service monorepo (backend + frontend); this feature touches only `driver/` and docs, plus backend unit tests.

**Performance Goals**: N/A — authoring a Driver, no runtime performance target. Driver load + render are sub-second operations exercised in unit tests.

**Constraints**: Manifest must validate cleanly per `DRIVERS.md` (zero validation errors, no `actions.py`). Rendered values must never contain an `apiToken` key. Transport (streamable-HTTP) and port (8001) are fixed, not parameterised.

**Scale/Scope**: Two new driver files (`driver.styrmin.yml`, `values.j2.yml`), two doc edits (`driver/DRIVERS.md`, `docs/docs/drivers/loading-drivers.md`), and additions to two backend unit-test modules. ~3 parameters, 1 Component, 1 Service.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Declarative State Reconciliation** | ✅ Pass | The Driver is pure desired-state config. Re-applying the same parameters renders identical values → idempotent. No reconciliation-engine change. |
| **II. Driver-Based Deployment** | ✅ Pass | All behaviour flows through the new versioned Driver. No ad-hoc deployment logic. Self-contained and independently versionable (`supported_versions: >=1.1,<2.0`). |
| **III. Layered Architecture** | ✅ Pass | Only the driver layer (+ docs + unit tests) is touched. No GraphQL/service/repository/DB changes, so no cross-layer concerns introduced. |
| **IV. Type Safety & Typed Errors** | ✅ Pass | No new code paths or errors. Invalid parameters are rejected by the existing `validate_parameter_values` → `ServiceError` path (missing required, wrong type, unknown name, out-of-enum). |
| **V. Test-First / E2E required** | ⚠️ Justified deviation | E2E intentionally omitted — **owner-approved this session** (recorded in spec Assumptions + Out of Scope, and in Complexity Tracking below). Substitute: unit deserialize + render + parameter-validator coverage. |
| **V. GraphQL ↔ DB Propagation Tests** | ✅ N/A | No schema change under `api/schema/`. No propagation test required. |
| **VI. Format & Lint Before Commit** | ✅ Pass | `uv run invoke format lint` will run before commit; new Python test code obeys 120-col / ruff. |
| **VII. Documentation Accuracy** | ✅ Pass | New user-visible Driver → docs updated in the same change: `driver/DRIVERS.md` Examples list + `docs/docs/drivers/loading-drivers.md` example-driver list. |

**New dependency gate**: the upstream `infrahub-mcp` Helm chart + image is a new external dependency — **owner-approved this session** (spec Assumptions). Not re-litigated.

**Gate result**: PASS with one justified deviation (E2E skip), documented in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/015-infrahub-mcp-driver/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── driver-manifest.md   # The infrahub-mcp manifest contract
│   └── rendered-values.md   # The values.j2.yml render contract
├── checklists/
│   └── requirements.md  # From /speckit-specify
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
driver/
├── DRIVERS.md                        # EDIT: add infrahub-mcp to the Examples list
└── examples/
    └── infrahub-mcp/                 # NEW driver directory
        ├── driver.styrmin.yml        # NEW: manifest (metadata, helm, 1 Component, 1 Service, 3 parameters, NO actions)
        └── values.j2.yml             # NEW: Helm values template (fullnameOverride, fixed authMode, param mapping)

docs/docs/drivers/
└── loading-drivers.md                # EDIT: add infrahub-mcp to the example-driver list

backend/tests/unit/services/driver/
├── test_deserializer.py              # EXTEND: deserialize the infrahub-mcp manifest, assert Component/Service/parameters
└── (parameter-validator test module) # EXTEND: assert required/enum/type/unknown handling for the 3 params
                                      #   + a Jinja2 render test asserting target keys and no apiToken
```

**Structure Decision**: No new top-level structure. The feature lives entirely under `driver/examples/infrahub-mcp/` (the two driver artifacts), two documentation files, and additive backend unit tests. This mirrors the existing `driver/examples/infrahub/` and `driver/examples/simple-app/` Drivers, which are the reference implementations.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Skipping the Constitution §V E2E requirement | This is a standalone example Driver whose only platform-side behaviour (deserialize + parameter validation + values render) is fully exercisable at the unit level; an E2E would require a running upstream Infrahub + the MCP chart published to the registry, which is disproportionate for a config-only Driver. **The owner explicitly approved skipping E2E this session.** | A full E2E (per §V) was rejected by the owner as disproportionate for a config-only example Driver with no new platform code path. Unit-level deserialize + render + validator coverage exercises the entire contract this Driver introduces. |
