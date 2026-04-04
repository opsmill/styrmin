# Implementation Plan: Deployment History Timeline

**Branch**: `001-deployment-history-timeline` | **Date**: 2026-04-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-deployment-history-timeline/spec.md`

## Summary

Add a deployment history timeline to the deployment detail page showing all operations (create, update, upgrade, etc.) with timestamps, application version, and context diffs between consecutive operations. The backend already stores all required data (Task model with timestamps, ApplicationInstance with context JSON) — the work is exposing it through GraphQL and rendering it in the frontend.

## Technical Context

**Language/Version**: Python 3.12+ (backend), TypeScript 5.9.3 (frontend)  
**Primary Dependencies**: Strawberry GraphQL, SQLModel, SQLAlchemy (async), Pydantic (backend); React 19, urql, Radix UI (frontend)  
**Storage**: PostgreSQL via SQLModel — no schema changes required  
**Testing**: pytest (backend); Vitest, React Testing Library (frontend)  
**Target Platform**: Web application (SPA + GraphQL API)  
**Project Type**: Web (backend + frontend)  
**Performance Goals**: Timeline loads within 2 seconds (SC-001)  
**Constraints**: No new database tables or columns. Additive GraphQL changes only.  
**Scale/Scope**: Typical deployment has <50 tasks. No pagination needed for v1.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | Read-only feature, no state mutations |
| II. Driver-Based Deployment | N/A | Not modifying deployment behavior |
| III. Layered Architecture | PASS | New code follows GraphQL → Service → Repository → DB pattern |
| IV. Type Safety and Typed Errors | PASS | All new types fully typed; Strawberry types for GraphQL |
| V. Test-First Development | PASS | Tests planned for service logic, GraphQL query, and frontend components |
| VI. Format and Lint Before Commit | PASS | Will run `uv run invoke format lint` before commits |

**Governance Gates triggered**:
- GraphQL schema modifications (additive: new fields on Task, new query, new types) — addressed in research.md R7

**Post-Phase 1 re-check**: PASS — design uses layered architecture, all types are defined, no schema changes needed.

## Project Structure

### Documentation (this feature)

```text
specs/001-deployment-history-timeline/
├── spec.md
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── schema-additions.graphql
│   └── query-deployment-timeline.graphql
└── tasks.md             # Phase 2 output (via /speckit.tasks)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── api/
│   │   ├── definitions/
│   │   │   ├── task/model.py                    # MODIFY: add createdOn, updatedOn fields
│   │   │   └── deployment_timeline/             # NEW: timeline types
│   │   │       ├── __init__.py
│   │   │       └── model.py                     # DeploymentTimelineEntry, ContextDiff, ContextChange
│   │   └── schema/
│   │       └── query.py                         # MODIFY: add deploymentTimeline query
│   ├── services/
│   │   ├── tasks.py                             # MODIFY: add get_tasks_by_deployment
│   │   └── deployment_timeline.py               # NEW: timeline assembly + context diffing
│   └── repository/
│       └── tasks.py                             # MODIFY: add find_by_deployment method
└── tests/
    ├── unit/
    │   └── services/
    │       └── test_deployment_timeline.py       # NEW: version correlation + context diff tests
    └── integration/
        └── test_deployment_timeline_query.py     # NEW: GraphQL query contract test

frontend/
├── src/
│   ├── graphql/
│   │   └── queries/
│   │       └── get_deployment_timeline.graphql   # NEW: timeline query
│   ├── pages/
│   │   └── deployments/
│   │       └── DeploymentDetailPage.tsx          # MODIFY: add History section
│   └── components/
│       └── deployment/
│           ├── DeploymentTimeline.tsx             # NEW: timeline list component
│           └── ContextDiffView.tsx                # NEW: expandable diff display
└── tests/
    └── components/
        └── deployment/
            └── DeploymentTimeline.test.tsx        # NEW: timeline component tests
```

**Structure Decision**: Web application structure (backend + frontend). All new backend code follows the existing layered architecture. Frontend adds a new section to the existing deployment detail page plus two reusable components.

## Complexity Tracking

No constitution violations — table not needed.
