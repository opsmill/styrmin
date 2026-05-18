# Implementation Plan: CRD Status Reporting

**Branch**: `001-crd-status-reporting` | **Date**: 2026-04-15 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `/specs/001-crd-status-reporting/spec.md`

## Summary

Extend the existing status reporting agent to also read StyrminDeployment CRD status from Kubernetes and report it to the backend. The backend stores the latest CRD status snapshot per deployment and uses the CRD phase to update the Deployment's status, closing the observability gap between task-initiated deployments and actual cluster state.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: Strawberry (GraphQL), SQLModel, kubernetes-asyncio, fast-depends  
**Storage**: SQLite/PostgreSQL via SQLModel + Alembic migrations  
**Testing**: pytest (unit + integration)  
**Target Platform**: Linux container (Kubernetes agent) + Linux server (backend)  
**Project Type**: Web application (backend only)  
**Performance Goals**: CRD collection adds <2s overhead per poll cycle for up to 100 deployments  
**Constraints**: Must not interfere with existing pod status reporting  
**Scale/Scope**: Up to 100 deployments per cluster  

**Prerequisite**: The agent-status-reporting feature (`001-agent-status-reporting`) must be merged first. This feature extends the reporter and follows the same patterns.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | PASS | CRD status is a read-only observation of the existing reconciliation state. |
| II. Driver-Based Deployment | PASS | Feature does not modify deployment behavior. |
| III. Layered Architecture | PASS | Agent -> GraphQL mutation -> Service -> Repository -> Database. |
| IV. Type Safety and Typed Errors | PASS | Typed models, `ServiceError` subclasses for errors. |
| V. Test-First Development | PASS | Tests included in plan. |
| VI. Format and Lint Before Commit | PASS | Standard workflow. |

**Governance Gates Triggered**:
- **Database schema change**: New `DeploymentCrdStatus` table + Alembic migration
- **GraphQL schema modification**: New types, mutation, and resolver

**Post-Design Re-check**: All principles still satisfied. Design follows the exact same layered pattern as the pod status reporting feature.

## Project Structure

### Documentation (this feature)

```text
specs/001-crd-status-reporting/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: architectural decisions
├── data-model.md        # Phase 1: entity model design
├── quickstart.md        # Phase 1: developer overview
├── contracts/           # Phase 1: API contracts
│   └── graphql-schema.md
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (via /speckit.tasks)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── db/
│   ├── models.py                          # Add DeploymentCrdStatus model
│   └── migrations/versions/
│       └── xxxx_add_deployment_crd_status.py  # New Alembic migration
├── repository/
│   └── deployment_crd_status.py           # New: repository + SQLModel impl
├── services/
│   ├── unit_of_work.py                    # Register deployment_crd_statuses repository
│   └── deployment_crd_status.py           # New: upsert + deployment status mapping
├── api/
│   ├── definitions/
│   │   └── deployment_crd_status/
│   │       └── model.py                   # New: Strawberry types + input types
│   ├── schema/
│   │   └── mutation.py                    # Add reportCrdStatuses mutation
├── api/definitions/deployment/
│   └── model.py                           # Add crdStatus resolver field
├── agent/
│   └── status/
│       └── reporter.py                    # Extend to collect CRD status

python_sdk/src/styrmin_sdk/graphql/
├── report_crd_statuses.graphql            # New: agent mutation query file
└── get_deployment_crd_status.graphql      # New: SDK query file

backend/tests/unit/services/
├── test_deployment_crd_status_service.py  # New: service unit tests
└── fakes.py                               # Update with FakeDeploymentCrdStatusRepository
```

**Structure Decision**: Backend-only feature extending the existing agent-status-reporting code. Same directory conventions.

## Complexity Tracking

No constitution violations to justify. The design follows all existing patterns established by the pod status reporting feature.
