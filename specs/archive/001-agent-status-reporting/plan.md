# Implementation Plan: Agent Status Reporting

**Branch**: `001-agent-status-reporting` | **Date**: 2026-04-12 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `/specs/001-agent-status-reporting/spec.md`

## Summary

Add periodic pod status polling to the Styrmin K8s agent. A new async loop runs alongside the existing Kopf operator and Prefect worker, collecting pod health data from managed namespaces and reporting it to the backend via a new GraphQL mutation. The backend stores only the latest snapshot per pod and exposes it through the public GraphQL API with filtering by deployment, environment, or cluster.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: Strawberry (GraphQL), SQLModel, kubernetes-asyncio, Prefect, kopf, fast-depends  
**Storage**: SQLite/PostgreSQL via SQLModel + Alembic migrations  
**Testing**: pytest (unit + integration + E2E with vcluster)  
**Target Platform**: Linux container (Kubernetes agent) + Linux server (backend)  
**Project Type**: Web application (backend only — frontend out of scope)  
**Performance Goals**: Poll completes within 5 seconds for up to 500 managed pods  
**Constraints**: Must not interfere with agent's primary responsibilities (deployment orchestration, drift detection)  
**Scale/Scope**: Dozens of deployments per cluster, up to 500 pods total

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | PASS | Pod status is read-only observation, not state reconciliation. No conflict. |
| II. Driver-Based Deployment | PASS | Feature does not modify deployment behavior. Purely observational. |
| III. Layered Architecture | PASS | Design follows GraphQL API -> Service Layer -> Repository -> Database. Agent communicates via GraphQL mutation. |
| IV. Type Safety and Typed Errors | PASS | New `PodPhase` enum, typed models, `ServiceError` subclasses for error handling. No union types for errors. |
| V. Test-First Development | PASS | Plan includes unit tests (service/repository), integration tests (API), and guidance for E2E. |
| VI. Format and Lint Before Commit | PASS | Standard workflow applies. |

**Governance Gates Triggered**:
- **Database schema change**: New `PodStatus` table + Alembic migration (requires discussion)
- **GraphQL schema modification**: New types, query, and mutation (requires discussion)

**Post-Design Re-check**: All principles still satisfied. The design adds a new data path (agent -> mutation -> service -> repository -> DB -> query) that follows the existing layered architecture exactly.

## Project Structure

### Documentation (this feature)

```text
specs/001-agent-status-reporting/
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
│   ├── models.py                          # Add PodStatus model + PodPhase enum
│   └── migrations/versions/
│       └── xxxx_add_pod_status.py         # New Alembic migration
├── repository/
│   └── pod_status.py                      # New: PodStatusRepository + SQLModel impl
├── services/
│   ├── unit_of_work.py                    # Register pod_statuses repository
│   └── pod_status.py                      # New: upsert_pod_statuses, get_pod_statuses, cleanup
├── api/
│   ├── definitions/
│   │   └── pod_status/
│   │       └── model.py                   # New: Strawberry PodStatus + ContainerStatus types
│   ├── schema/
│   │   ├── query.py                       # Add podStatuses query
│   │   └── mutation.py                    # Add reportPodStatuses mutation
├── agent/
│   ├── service/kubernetes/
│   │   └── primitives.py                  # Add list_pods() function
│   └── status/
│       └── reporter.py                    # New: status polling loop + K8s collection logic
├── entrypoint/
│   └── combined.py                        # Add run_status_reporter() to asyncio.gather()

python_sdk/src/styrmin_sdk/graphql/
├── report_pod_statuses.graphql            # New: agent mutation query file
└── get_pod_statuses.graphql               # New: SDK query file

tasks/graphql/
└── get_pod_statuses.graphql               # New: dev task query file (if needed)

tests/
├── unit/
│   ├── test_pod_status_service.py         # Service layer tests
│   └── test_pod_status_repository.py      # Repository tests
└── integration/
    └── test_pod_status_api.py             # GraphQL query + mutation tests
```

**Structure Decision**: Backend-only feature following the existing web application structure. No frontend changes. New files follow the established directory conventions for repositories, services, API definitions, and agent components.

## Complexity Tracking

No constitution violations to justify. The design follows all existing patterns.
