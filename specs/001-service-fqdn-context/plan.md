# Implementation Plan: Include Service FQDNs in Deployment Context

**Branch**: `001-service-fqdn-context` | **Date**: 2026-03-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-service-fqdn-context/spec.md`

## Summary

Centralize FQDN computation for deployed services so that pre-computed FQDNs are available as first-class fields in the deployment context (for drivers) and through the GraphQL API (for the frontend UI). This eliminates duplicated inline FQDN construction from driver templates, ensures consistency, and lets users view service access addresses directly in the UI.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: Strawberry (GraphQL), Pydantic, SQLModel, Jinja2
**Frontend**: React 19, TypeScript, Vite, urql (GraphQL)
**Storage**: PostgreSQL via SQLModel — no schema changes required (FQDNs are computed, not stored)
**Testing**: pytest (backend), Vitest (frontend)
**Target Platform**: Kubernetes deployment orchestration platform (web application)
**Project Type**: Web application (backend + frontend + driver templates)
**Performance Goals**: N/A — FQDN computation is trivial string manipulation
**Constraints**: DNS label compliance (RFC 1035: max 63 chars, lowercase alphanumeric + hyphens)
**Scale/Scope**: ~10 files modified across backend, frontend, and driver examples

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | **PASS** | FQDNs are derived deterministically from existing state. No new state reconciliation needed. |
| II. Driver-Based Deployment | **PASS** | Centralizing FQDN computation into context model reduces driver complexity. Deployment behavior still flows from driver specs. |
| III. Layered Architecture | **PASS** | FQDN computation in context/service layer. GraphQL exposure through API layer. No cross-layer violations. |
| IV. Type Safety and Typed Errors | **PASS** | New fields use proper type hints (`str | None`), Pydantic models, and Strawberry types. FQDNs are nullable when suffix is unconfigured. |
| V. Test-First Development | **REQUIRED** | Must write tests for: DNS sanitization, FQDN computation, missing suffix handling, API resolution, context generation. |
| VI. Format and Lint Before Commit | **PASS** | Standard requirement applies. |

### Governance Gates

| Gate | Triggered | Justification |
|------|-----------|---------------|
| Database schema changes | **NO** | FQDNs are computed at runtime, not stored. No migration needed. |
| GraphQL schema modifications | **YES** | Adding `primaryFqdn` and `humanReadableFqdn` fields to `DeployedService` type. Required by FR-005 to expose FQDN data to the frontend. |
| New dependencies | **NO** | Uses only existing libraries. |
| CI/CD workflow changes | **NO** | No changes needed. |
| Auth/authz changes | **NO** | No changes needed. |

## Project Structure

### Documentation (this feature)

```text
specs/001-service-fqdn-context/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: Research findings
├── data-model.md        # Phase 1: Entity model changes
├── quickstart.md        # Phase 1: Implementation guide
├── contracts/           # Phase 1: GraphQL contract changes
│   └── deployed-service.graphql
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── context/
│   │   ├── models/
│   │   │   └── services.py              # ADD: primary_fqdn, human_readable_fqdn to ServiceReference
│   │   └── fqdn.py                      # NEW: Shared FQDN computation + sanitization utilities
│   ├── services/
│   │   └── context.py                   # MODIFY: Compute FQDNs during context generation
│   ├── api/
│   │   └── definitions/
│   │       └── service/
│   │           └── model.py             # ADD: primaryFqdn, humanReadableFqdn resolver fields
│   └── agent/
│       └── service/
│           └── kubernetes/
│               └── resources/
│                   └── builders/
│                       └── application.py  # MODIFY: Import to_fqdn_label from shared location
└── tests/
    └── unit/
        └── context/
            └── test_fqdn.py             # NEW: FQDN computation and sanitization tests

frontend/
├── src/
│   ├── pages/
│   │   └── deployments/
│   │       └── DeploymentDetailPage.tsx  # MODIFY: Display service FQDNs
│   └── generated/
│       └── graphql.ts                    # REGENERATED: Updated types

driver/
└── examples/
    ├── infrahub/chart_values.j2.yaml     # MODIFY: Use pre-computed FQDNs
    ├── semaphore/chart_values.j2.yaml    # MODIFY: Use pre-computed FQDNs
    ├── simple-app/chart_values.j2.yaml   # MODIFY: Use pre-computed FQDNs
    └── slurpit/chart_values.j2.yaml      # MODIFY: Use pre-computed FQDNs
```

**Structure Decision**: Existing web application structure (backend + frontend + driver). New code follows existing conventions. The only new file is `context/fqdn.py` to house shared FQDN utilities extracted from the builder module, and `tests/unit/context/test_fqdn.py` for tests.

## Complexity Tracking

No constitution violations to justify. All changes follow existing patterns and architecture.
