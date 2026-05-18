# Implementation Plan: Cluster & Environment Capability Declarations

**Branch**: `001-cluster-env-capabilities` | **Date**: 2026-04-01 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-cluster-env-capabilities/spec.md`

## Summary

Add a persisted, hierarchical capability model to Cluster and Environment entities. Capabilities are derived from existing configuration (storage classes, backup storage locations, ingress/DNS settings), stored as JSON columns, exposed via GraphQL, and injected into the Jinja2 template rendering context for Application Drivers. Three initial categories: storage, backup, and ingress.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: Strawberry GraphQL, SQLModel, SQLAlchemy (async), Pydantic, Jinja2
**Storage**: PostgreSQL via SQLModel — new JSON columns on Cluster and Environment tables
**Testing**: pytest (unit + integration)
**Target Platform**: Linux server (backend API)
**Project Type**: Web application (backend focus for this feature)
**Performance Goals**: N/A — capability computation is cheap; queries read persisted JSON
**Constraints**: No Alembic — schema managed via `metadata.create_all()`. Must follow layered architecture (GraphQL → Service → Repository → DB).
**Scale/Scope**: Small feature — ~10 files modified, 2 new JSON columns, 3 capability categories

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | PASS | Capabilities are derived state, consistent with reconciliation model. No side effects on re-computation. |
| II. Driver-Based Deployment | PASS | Capabilities are exposed in GlobalContext for driver templates. Drivers remain self-contained. |
| III. Layered Architecture | PASS | Capability computation lives in service layer. GraphQL resolvers call services. Repository handles persistence. |
| IV. Type Safety and Typed Errors | PASS | Pydantic models for capability structure. Type hints on all functions. JSON scalar for GraphQL (consistent with config pattern). |
| V. Test-First Development | PASS | Unit tests for capability computation. Integration tests for GraphQL queries. Context rendering tests for template access. |
| VI. Format and Lint Before Commit | PASS | Standard compliance — no exceptions needed. |

**Governance Gates**:
- **Database schema changes**: New JSON columns on Cluster and Environment. Low risk — additive change, nullable, no migration needed (`metadata.create_all()` handles it).
- **GraphQL schema modifications**: New `capabilities` field on Cluster and Environment types. Additive, non-breaking.

## Project Structure

### Documentation (this feature)

```text
specs/001-cluster-env-capabilities/
├── spec.md
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── capabilities.graphql
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── db/
│   │   └── models.py                          # Add capabilities JSON column to Cluster, Environment
│   ├── context/
│   │   └── models/
│   │       ├── config.py                      # (read-only reference for derivation)
│   │       ├── contexts.py                    # Add capabilities to ClusterContext, EnvironmentContext
│   │       └── capabilities.py                # NEW: Pydantic models for capability structure
│   ├── services/
│   │   ├── clusters.py                        # Add capability computation on create/update
│   │   ├── environments.py                    # Add capability computation on create/update
│   │   ├── backup_storage_locations.py        # Trigger env capability recalc on assign/unassign
│   │   ├── context.py                         # Populate capabilities in GlobalContext generation
│   │   └── capabilities.py                    # NEW: Capability derivation logic
│   ├── api/
│   │   └── definitions/
│   │       ├── cluster/model.py               # Add capabilities resolver field
│   │       └── environment/model.py           # Add capabilities resolver field
│   └── repository/                            # (no changes — existing CRUD handles JSON columns)
└── tests/
    ├── unit/
    │   └── test_capabilities.py               # NEW: Unit tests for derivation logic
    └── integration/
        └── test_capabilities_graphql.py       # NEW: Integration tests for GraphQL queries

```

**Structure Decision**: Backend-only changes following the existing layered architecture. Two new files (`capabilities.py` for models and service logic), modifications to ~8 existing files. No frontend changes in this feature scope.

## Complexity Tracking

No constitution violations to justify.
