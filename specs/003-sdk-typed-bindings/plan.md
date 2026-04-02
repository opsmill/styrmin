# Implementation Plan: Leverage Generated Typed Bindings in SDK

**Branch**: `003-sdk-typed-bindings` | **Date**: 2026-04-01 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/003-sdk-typed-bindings/spec.md`

## Summary

Replace hand-written Pydantic domain models in the SDK with the generated ariadne-codegen response types. The execution layer (Transport + load_query) remains unchanged. Resource methods switch from `Model.model_validate(result["data"]["key"])` to `OuterType.model_validate(result["data"]).inner_field`, eliminating manual dictionary key access. The `models/` package becomes a re-export facade over generated types.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: Pydantic v2 (already used by generated types), ariadne-codegen (build-time), httpx (Transport)
**Storage**: N/A (SDK is a client library)
**Testing**: pytest with AsyncMock (existing test suite in `python_sdk/tests/`)
**Target Platform**: Python SDK package
**Project Type**: Single Python package (`python_sdk/`)
**Performance Goals**: N/A (no performance impact — same execution path)
**Constraints**: Backward-compatible public API except Task.type → Task.type_
**Scale/Scope**: 8 resource classes, ~35 methods, ~10 hand-written model classes to replace

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Notes |
|------|--------|-------|
| III. Layered Architecture | PASS | SDK is a client library — layered architecture applies to backend, not SDK |
| IV. Type Safety and Typed Errors | PASS | Switching to generated types *improves* type safety. Error handling preserved. |
| V. Test-First Development | PASS | Existing tests will be updated. No new functionality requiring new tests. |
| VI. Format and Lint Before Commit | PASS | Will run `uv run invoke format lint` before commit |
| Governance: No manual edits to generated files | PASS | We only import from generated files, never edit them |
| Governance: GraphQL schema modifications | PASS | No schema changes — only SDK-side model replacement |

**Post-Phase 1 re-check**: No new violations. Design stays within constitution boundaries.

## Project Structure

### Documentation (this feature)

```text
specs/003-sdk-typed-bindings/
├── plan.md              # This file
├── research.md          # Phase 0 output (complete)
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
python_sdk/src/styrmin_sdk/
├── __init__.py                    # Re-exports from models/ (update imports)
├── client.py                      # StyrminClient (unchanged)
├── _transport.py                  # Transport (unchanged)
├── _queries.py                    # load_query() (unchanged)
├── exceptions.py                  # SDK exceptions (unchanged)
├── models/
│   ├── __init__.py                # MODIFY: re-export generated types as aliases
│   ├── context.py                 # KEEP: no generated equivalent
│   ├── driver.py                  # MODIFY: keep ApplicationDriver, ApplicationDriverVersionSummary; remove rest
│   ├── backup.py                  # DELETE: replaced by generated types
│   ├── backup_storage_location.py # DELETE: replaced by generated types
│   ├── cluster.py                 # DELETE: replaced by generated types
│   ├── deployment.py              # DELETE: replaced by generated types
│   ├── environment.py             # DELETE: replaced by generated types
│   └── task.py                    # DELETE: replaced by generated types
├── resources/
│   ├── _base.py                   # UNCHANGED: _check_graphql_errors stays
│   ├── clusters.py                # MODIFY: use generated outer types
│   ├── backups.py                 # MODIFY: use generated outer types
│   ├── deployments.py             # MODIFY: use generated outer types
│   ├── environments.py            # MODIFY: use generated outer types
│   ├── drivers.py                 # MODIFY: use generated outer types
│   ├── schedules.py               # MODIFY: use generated outer types
│   ├── tasks.py                   # MODIFY: use generated outer types
│   └── backup_storage_locations.py # MODIFY: use generated outer types
└── graphql/
    ├── *.graphql                  # UNCHANGED: query files
    └── _generated/                # UNCHANGED: generated code (read-only)

python_sdk/tests/
├── conftest.py                    # MODIFY: update mock response dicts
├── test_clusters.py               # MODIFY: update assertions for generated types
├── test_backups.py                # MODIFY: update assertions for generated types
├── test_deployments.py            # MODIFY: update assertions for generated types
└── test_transport.py              # UNCHANGED
```

**Structure Decision**: Single Python package. All changes are within `python_sdk/`. No new files created — only modifications and deletions of existing model files.

## Complexity Tracking

No constitution violations to justify.
