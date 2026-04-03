# Implementation Plan: Consolidate Driver Format

**Branch**: `001-consolidate-driver-format` | **Date**: 2026-04-02 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-consolidate-driver-format/spec.md`

## Summary

Consolidate the driver file format from 4 files (`styrmin_driver.yaml`, `actions.yaml`, `chart_values.j2.yaml`, `actions.py`) to at most 3 (`driver.styrmin.yml`, `values.j2.yml`, `actions.py`), merging declarative configuration into a single YAML file and renaming the values template. This simplifies driver authoring, eliminates cross-file sync errors, and reduces loader pipeline complexity.

## Technical Context

**Language/Version**: Python 3.12+  
**Primary Dependencies**: Pydantic v2, PyYAML, Jinja2, Prefect  
**Storage**: Filesystem and Git (driver sources) — no database changes  
**Testing**: pytest (unit tests for loader pipeline, integration tests for driver loading)  
**Target Platform**: Linux server (backend service)  
**Project Type**: Web application (backend component only)  
**Performance Goals**: N/A — driver loading is an infrequent operation  
**Constraints**: Must maintain all existing driver functionality; no data loss during format migration  
**Scale/Scope**: 5 example drivers to migrate; ~10 source files to modify; ~7 test files to update

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Phase 0 Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | No deployment state changes |
| II. Driver-Based Deployment | PASS | Preserves driver self-containment; improves it by reducing file count |
| III. Layered Architecture | PASS | Changes are within the service layer (driver loading) |
| IV. Type Safety and Typed Errors | PASS | All models remain typed Pydantic models with mypy enforcement |
| V. Test-First Development | PASS | Tests will be updated alongside implementation |
| VI. Format and Lint Before Commit | PASS | Standard workflow applies |

### Governance Gates

| Gate | Triggered? | Notes |
|------|-----------|-------|
| Database schema changes | No | Drivers are filesystem/git-sourced |
| GraphQL schema modifications | No | Driver models are internal, not exposed via GraphQL |
| New dependencies | No | All existing dependencies sufficient |
| CI/CD workflow changes | No | Existing test infrastructure covers this |
| Auth/authz changes | No | No security boundary changes |

### Post-Phase 1 Re-check

All principles remain satisfied. The consolidated format better aligns with Principle II (drivers are more self-contained with fewer files to keep in sync).

## Project Structure

### Documentation (this feature)

```text
specs/001-consolidate-driver-format/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Phase 0: research decisions
├── data-model.md        # Phase 1: model changes
├── quickstart.md        # Phase 1: implementation guide
├── contracts/           # Phase 1: schema contracts
│   └── driver-schema.yaml
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── config.py                                    # DriverSettings (filename defaults)
│   └── services/driver/
│       ├── __init__.py                              # ApplicationDriver dataclass
│       ├── loaders.py                               # DriverLoader, ResourceFileLoader
│       ├── parsers.py                               # No changes expected
│       ├── validators.py                            # UserActionsValidator integration
│       ├── deserializers.py                         # Remove ActionsSpecDeserializer
│       ├── models/
│       │   ├── resources/
│       │   │   ├── driver.py                        # Add actions field to Specification
│       │   │   ├── actions.py                       # Remove ActionsSpec envelope, keep ActionDefinition
│       │   │   └── __init__.py                      # Update DriverResource type alias
│       │   └── structure/
│       │       ├── directory.py                     # Remove actions_spec resource
│       │       └── resource.py                      # Remove ACTIONS_SPEC Role
│       └── errors.py                                # New error types (or add to existing)
└── tests/
    └── unit/services/driver/
        ├── test_loaders.py
        ├── test_parsers.py
        ├── test_validators.py
        ├── test_deserializer.py
        └── fixtures/local_driver_directory/         # Migrate fixture files

driver/
├── examples/
│   ├── simple-app/                                  # Migrate to new format
│   ├── infrahub/                                    # Migrate to new format
│   ├── slurpit/                                     # Migrate to new format
│   ├── semaphore/                                   # Migrate to new format
│   └── db-test/                                     # Migrate to new format
└── DRIVERS.md                                       # Update documentation
```

**Structure Decision**: This is a backend-only refactor within the existing `backend/styrmin_backend/services/driver/` module. No new directories or modules are introduced. The driver examples directory under `driver/examples/` is also modified.

## Complexity Tracking

No constitution violations to justify. All changes are within existing architectural boundaries.
