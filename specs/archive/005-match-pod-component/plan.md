# Implementation Plan: Match Pod Statuses to Driver Components

**Branch**: `005-match-pod-component` | **Date**: 2026-04-29 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-match-pod-component/spec.md`

## Summary

The agent's pod-status reporter currently has no link from a reported pod back to the driver component that produced it. We extend the wire model and the persisted record with a single nullable `component_name` field, populated by reading the existing `styrmin/component` label off pod metadata during `_extract_pod_data()`. The server stores the value as observed — no per-deployment lookup, no validation against the deployment's declared components — and exposes it on the `PodStatus` GraphQL type. A nullable column on `podstatus` requires one Alembic migration; everything else is additive.

The change deliberately avoids server-side gatekeeping: drivers and components evolve independently, the agent reports observed runtime state, and the server records it as-is. This keeps the boundary between "what we observed" and "what the driver declares" explicit, and avoids brittle joins between rapidly-changing reconciliation state and slow-moving declared state.

## Technical Context

**Language/Version**: Python 3.11+ (backend, agent, SDK)
**Primary Dependencies**: SQLModel, Pydantic, Strawberry GraphQL, Alembic, ariadne-codegen (for SDK regen), kubernetes-asyncio
**Storage**: PostgreSQL via SQLModel; one new nullable column `podstatus.component_name`
**Testing**: pytest (unit + e2e), AnyIO async runner, FakePodStatusRepository for service-layer unit tests
**Target Platform**: Linux server / Kubernetes vcluster (E2E)
**Project Type**: Web service (backend) — single project layout under `backend/styrmin_backend/`
**Performance Goals**: No new performance constraint; the field is read from already-fetched pod metadata
**Constraints**: Must keep existing `_extract_pod_data` shape; the agent and server still ship together so cross-version skew is not a concern
**Scale/Scope**: Tens to low hundreds of pods per deployment, polled every ~5 s — adding one string field per pod is negligible

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Declarative State Reconciliation**: ✅ The change is additive to an existing reconciliation/reporting cycle; idempotency is preserved (the same pod observed again writes the same value).
- **II. Driver-Based Deployment**: ✅ No driver-level changes — components are already labelled by the application builder (`build_target_for_component_labels`). This feature only consumes the existing label.
- **III. Layered Architecture**: ✅ Changes flow through the established layering: agent (collection) → GraphQL mutation input → service (`report_pod_statuses`) → repository (`FakePodStatusRepository.upsert`) → DB model. No cross-layer shortcut.
- **IV. Type Safety and Typed Errors**: ✅ Field is `str | None` on every layer (Pydantic, SQLModel, Strawberry). No new error types needed; absent label is data, not an error.
- **V. Test-First Development**: ✅ Plan ships unit tests for label extraction (set / missing / blank / unknown) and an E2E scenario that deploys a multi-component driver and asserts `component_name` attribution on each reported pod. E2E coverage is part of done.
- **VI. Format and Lint Before Commit**: ✅ All Python touched will be formatted and linted via `uv run invoke format lint`.

**Governance gates (Ask First)**:
- Database migration: yes — one Alembic revision adding a nullable column to `podstatus`. The migration is in scope of this issue and was explicitly called out in #133. No further approval needed.
- GraphQL schema modifications: yes — adding `componentName` to `type PodStatus` and `input PodStatusInput`. Same: explicitly in scope.

**Result**: PASS — no constitution violations. Complexity Tracking section is intentionally absent.

## Project Structure

### Documentation (this feature)

```text
specs/005-match-pod-component/
├── spec.md
├── plan.md              # This file
├── research.md          # Phase 0 — alternatives considered
├── data-model.md        # Phase 1 — entity/field changes
├── quickstart.md        # Phase 1 — developer manual-verify
├── contracts/
│   ├── graphql-schema.md  # Phase 1 — schema additions
│   └── pydantic-models.md # Phase 1 — agent wire model additions
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 — produced by /speckit.tasks
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── agent/
│   │   └── status/
│   │       ├── models.py             # Add component_name to PodStatusData
│   │       └── reporter.py           # Read styrmin/component label in _extract_pod_data
│   ├── api/
│   │   └── definitions/
│   │       └── pod_status/
│   │           └── model.py          # Add component_name to PodStatus + PodStatusInput
│   ├── db/
│   │   ├── models.py                 # Add component_name nullable column to PodStatus
│   │   └── migrations/versions/
│   │       └── XXXX_add_component_name_to_pod_status.py   # New Alembic revision
│   └── services/
│       └── pod_status.py             # Pass component_name through to PodStatus model
└── tests/
    ├── unit/
    │   ├── agent/test_status_reporter.py    # Add label extraction tests
    │   └── services/test_pod_status_service.py  # Add component_name persistence tests
    └── e2e/
        └── test_pod_component_attribution.py # NEW — multi-component driver E2E

python_sdk/src/styrmin_sdk/graphql/
├── get_pod_statuses.graphql                  # Add componentName
├── get_deployment_pod_statuses.graphql       # Add componentName
└── report_pod_statuses.graphql               # Unchanged (response shape stays the same)
                                              # but PodStatusInput consumers may set componentName

schema.graphql                                # Regenerated
```

**Structure Decision**: Single backend project. The change touches one vertical slice (agent → GraphQL → service → DB) plus the SDK queries that surface the new field. No new packages, no new directories beyond a single E2E test file.

## Phase 0 — Research

See [research.md](./research.md). Two design questions resolved upfront:

1. **Where to read the label** — at `_extract_pod_data()` in the agent. The reporter already has the V1Pod object in hand; no extra k8s API call.
2. **Whether the server validates the label against declared components** — no. Reasons captured in `research.md` §2.

## Phase 1 — Design

- [data-model.md](./data-model.md) — the single field added to `PodStatus` (DB model), `PodStatusData` (agent wire model), and the GraphQL `PodStatus`/`PodStatusInput` types.
- [contracts/graphql-schema.md](./contracts/graphql-schema.md) — the exact diff to `schema.graphql` after regeneration.
- [contracts/pydantic-models.md](./contracts/pydantic-models.md) — the new field on the agent's Pydantic models with alias semantics.
- [quickstart.md](./quickstart.md) — local-loop manual verification.

## Phase 2 — Tasks

Generated by `/speckit.tasks` into `tasks.md` (not produced here).

## Complexity Tracking

> No constitution violations — section intentionally omitted.
