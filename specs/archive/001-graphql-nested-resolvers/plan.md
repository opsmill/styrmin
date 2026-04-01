# Implementation Plan: Add Nested Object Resolvers to GraphQL Schema

**Branch**: `001-graphql-nested-resolvers` | **Date**: 2026-03-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-graphql-nested-resolvers/spec.md`

## Summary

Add 8 nested object resolvers to the GraphQL schema so clients can traverse entity relationships (e.g., Deployment → Environment, Task → Deployment) in a single query without follow-up requests. The implementation uses Strawberry's `@strawberry.field` async resolvers with the existing UnitOfWork pattern for on-demand relationship loading, plus one synchronous resolver where the relationship is already eager-loaded.

## Technical Context

**Language/Version**: Python 3.11+, Strawberry GraphQL
**Primary Dependencies**: Strawberry, SQLModel, SQLAlchemy (async), Pydantic
**Storage**: PostgreSQL via SQLModel/SQLAlchemy (no schema changes — relationships already exist)
**Testing**: pytest (functional tests with in-memory SQLite, unit tests)
**Target Platform**: Linux server (API backend)
**Project Type**: Web application (backend-only changes for this feature)
**Performance Goals**: N/A for this iteration (lazy-loading accepted per spec assumptions)
**Constraints**: Must not break existing queries; must preserve all `*Id` fields
**Scale/Scope**: 8 new resolver fields across 7 GraphQL types

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | No reconciliation logic affected |
| II. Driver-Based Deployment | N/A | No driver logic changes |
| III. Layered Architecture | PASS | Resolvers → UoW → Repository → DB. No cross-layer violations |
| IV. Type Safety and Typed Errors | PASS | All resolvers fully typed. Non-nullable resolvers raise GraphQL field errors on integrity violations (FR-013) |
| V. Test-First Development | PASS | Tests required for all 8 resolvers |
| VI. Format and Lint Before Commit | PASS | Standard workflow applies |

**Governance Gates:**

| Gate | Status | Notes |
|------|--------|-------|
| GraphQL schema modifications | ACKNOWLEDGED | This feature modifies the GraphQL schema by adding 8 new fields. No existing fields are removed or modified — additive only. Schema regeneration required via `uv run styrmin export graphql-schema schema.graphql` and `uv run invoke generate` |
| Database schema changes | N/A | No DB changes — all foreign keys and relationships already exist |
| New dependencies | N/A | No new dependencies |

**Post-Phase 1 Re-check**: Design uses existing patterns (async UoW resolvers, `from_instance` conversions). No constitution violations introduced.

## Project Structure

### Documentation (this feature)

```text
specs/001-graphql-nested-resolvers/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── schema-additions.graphql
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
backend/styrmin_backend/api/definitions/
├── deployment/model.py          # Add environment + applicationDriverVersion resolvers
├── application_driver/model.py  # Add applicationDriver resolver on ADV type
├── task/model.py                # Add deployment resolver
├── backup/
│   ├── backup.py                # Add instance resolver
│   ├── restore.py               # Add backup resolver
│   └── schedule.py              # Add deployment resolver

backend/tests/
├── functional/test_api.py       # Add nested resolver functional tests
```

**Structure Decision**: Backend-only changes. All modifications are in the existing GraphQL type definition files under `backend/styrmin_backend/api/definitions/`. No new files needed for the resolvers themselves — each resolver is added as a method on its existing Strawberry type class.

## Complexity Tracking

> No constitution violations to justify.
