# Quickstart: Consolidate Driver Format

**Feature Branch**: `001-consolidate-driver-format`  
**Date**: 2026-04-02

## Overview

This feature consolidates the driver file format from 4 files to at most 3, merging `styrmin_driver.yaml` and `actions.yaml` into a single `driver.styrmin.yml` file and renaming `chart_values.j2.yaml` to `values.j2.yml`.

## Before / After

### Before (current)
```
my-driver/
├── styrmin_driver.yaml      # Driver spec
├── chart_values.j2.yaml     # Helm values template
├── actions.yaml             # Action declarations
└── actions.py               # Action implementations
```

### After (new)
```
my-driver/
├── driver.styrmin.yml       # Consolidated driver spec + actions
├── values.j2.yml            # Helm values template (renamed)
└── actions.py               # Action implementations (unchanged)
```

## Implementation Order

### Step 1: Pydantic Model Changes
1. Add `actions: list[ActionDefinition] = []` to `Specification` in `models/resources/driver.py`
2. Remove `ACTIONS_SPEC` from `Role` enum in `models/structure/resource.py`
3. Update `DriverResource` type alias to remove `ActionsSpec`
4. Remove `actions_spec` field from `ApplicationDriver` dataclass

### Step 2: Config Changes
1. Update `DriverSettings` in `config.py`:
   - `spec_file` default: `"styrmin_driver.yaml"` → `"driver.styrmin.yml"`
   - Rename `chart_values_template` → `values_template`, default: `"values.j2.yml"`
   - Remove `actions_spec_file`
   - Keep `actions_code_file` as `"actions.py"`

### Step 3: Directory Model Changes
1. Update `DriverDirectory` in `models/structure/directory.py`:
   - Remove `actions_spec` resource file
   - Update paths to use new config defaults
   - Make `values_template` optional

### Step 4: Loader Pipeline Changes
1. Update `loaders.py`:
   - Remove `actions_spec` loading step from `load_driver()`
   - Remove `actions_spec` from `ApplicationDriver` construction
   - Add post-deserialization validation: if `driver_spec.spec.actions` is non-empty, validate that `actions.py` exists and all referenced functions are defined
2. Update `deserializers.py`:
   - Remove `ActionsSpecDeserializer`
   - Update `get_deserializer()` factory
3. Update `validators.py`:
   - Update `get_validator()` factory to remove `ACTIONS_SPEC` case
   - Integrate `UserActionsValidator` as a post-load step

### Step 5: Error Handling
1. Add `DeprecatedDriverFormatError` and `AmbiguousDriverFormatError`
2. Add old-format detection logic in the loader

### Step 6: Migrate Example Drivers
1. For each driver in `driver/examples/`:
   - Merge `styrmin_driver.yaml` + `actions.yaml` → `driver.styrmin.yml`
   - Rename `chart_values.j2.yaml` → `values.j2.yml`
   - Delete old files

### Step 7: Update Tests
1. Update test fixtures in `backend/tests/unit/services/driver/fixtures/`
2. Update loader, deserializer, validator, parser tests
3. Add tests for error cases (deprecated format, ambiguous format)

### Step 8: Update Documentation
1. Update `driver/DRIVERS.md` with new file structure and examples

## Key Decisions

| Decision | Choice | See |
|----------|--------|-----|
| Schema design | Inline `actions` in `spec` section | research.md R1 |
| File extension | `.yml` (not `.yaml`) | research.md R2 |
| Backward compat | None — clean break | research.md R3 |
| Config settings | 3 settings (was 4) | research.md R4 |
| Model strategy | Extend `Specification`, reuse `ActionDefinition` | research.md R5 |
| Loader pipeline | 3 resource files (was 4) | research.md R6 |

## Governance Gates

This feature touches:
- **GraphQL schema**: No — driver models are internal, not exposed via GraphQL
- **Database schema**: No — drivers are loaded from filesystem/git, not stored in DB
- **New dependencies**: No
- **CI/CD**: No — existing test infrastructure sufficient
- **Auth/authz**: No

No governance gates triggered.
