# Implementation Plan: Name-Based Resource Lookup

**Branch**: `001-graphql-name-lookup` | **Date**: 2026-03-29 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-graphql-name-lookup/spec.md`

## Summary

Add optional name-based alternatives to all GraphQL queries/mutations that accept cluster or environment UUIDs. Change environment uniqueness from global to per-cluster. Propagate name-based parameters through the SDK to the CLI, where names become the default positional arguments.

## Technical Context

**Language/Version**: Python 3.12+ (backend, SDK, CLI)
**Primary Dependencies**: Strawberry GraphQL, SQLModel, SQLAlchemy (async), Pydantic, Cyclopts (CLI), httpx (SDK transport)
**Storage**: PostgreSQL via SQLModel/SQLAlchemy (async). No Alembic -- schema managed via `metadata.create_all()`.
**Testing**: pytest (backend unit + integration tests)
**Target Platform**: Linux server (backend), cross-platform CLI
**Project Type**: Web application (backend + SDK + CLI)
**Performance Goals**: N/A -- small resource count, no latency concerns
**Constraints**: Backward-compatible with all existing UUID-based API and CLI usage
**Scale/Scope**: Small number of clusters/environments; 4 GraphQL operations gain name params, 6+ CLI commands updated, SDK resource classes updated

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Notes |
|------|--------|-------|
| III. Layered Architecture | PASS | Changes follow GraphQL → Service → Repository → DB path. No cross-layer shortcuts. |
| IV. Type Safety and Typed Errors | PASS | All new parameters will have type hints. Validation errors use existing `ServiceError` pattern with structured error codes. |
| V. Test-First Development | PASS | Tests required for name-based lookups, validation errors, and scoped uniqueness at unit and integration levels. |
| VI. Format and Lint Before Commit | PASS | Standard workflow: `uv run invoke format lint` before commits. |
| Governance: DB schema changes | TRIGGERED | Environment uniqueness constraint changes from global to per-cluster composite. Spec explicitly calls for this (FR-012). |
| Governance: GraphQL schema changes | TRIGGERED | All cluster/environment queries and mutations gain optional name parameters. `schema.graphql` must be regenerated. |
| Governance: New dependencies | PASS | No new dependencies required. |

**Governance gates resolved**: Both triggered gates (DB schema, GraphQL schema) are core to the feature and explicitly approved via the spec. No additional discussion needed.

## Project Structure

### Documentation (this feature)

```text
specs/001-graphql-name-lookup/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── api/
│   │   ├── schema/
│   │   │   ├── query.py            # Add name params to cluster/environment queries
│   │   │   └── mutation.py         # Add name params to delete/create/deploy mutations
│   │   └── definitions/            # No changes needed (Strawberry types unchanged)
│   ├── db/
│   │   └── models.py               # Change Environment.name from unique=True to composite constraint
│   ├── repository/
│   │   ├── cluster.py              # No changes (get_by_name already exists)
│   │   └── environment.py          # Add get_by_name_in_cluster(name, cluster_id) method
│   └── services/
│       ├── clusters.py             # Add resolve_cluster(id, name) helper
│       ├── environments.py         # Add resolve_environment(id, name, cluster_id, cluster_name) helper
│       ├── deployment.py           # Update deploy_application to accept name-based env params
│       └── exceptions.py           # Add AmbiguousIdentifierError for both-provided / neither-provided
│
python_sdk/
├── src/styrmin_sdk/
│   ├── graphql/
│   │   ├── get_cluster.graphql           # Add clusterName variable
│   │   ├── delete_cluster.graphql        # Add clusterName variable
│   │   ├── get_environment.graphql       # Add environmentName + cluster context variables
│   │   ├── delete_environment.graphql    # Add environmentName + cluster context variables
│   │   ├── create_environment.graphql    # Add clusterName variable
│   │   └── deploy.graphql               # Add environmentName + cluster context variables
│   ├── resources/
│   │   ├── clusters.py                   # Add name params to get/delete
│   │   └── environments.py              # Add name + cluster context params to get/delete/create
│   └── _generated/                       # Regenerated via `uv run invoke generate`
│
cli/
├── src/styrminctl/
│   ├── types.py                    # Add ClusterName, EnvironmentName types; rework ID types
│   └── commands/
│       ├── clusters.py             # Name as positional, --id flag for UUID
│       ├── environments.py         # Name as positional, --cluster/--cluster-id flags
│       ├── deployments.py          # Environment name + cluster context for create
│       └── backup_storage_locations.py  # Environment name + cluster context for assign/unassign
```

**Structure Decision**: Existing multi-package structure (backend, python_sdk, cli) is preserved. Changes are distributed across all three packages following the layered architecture.

## Complexity Tracking

No constitution violations to justify.
