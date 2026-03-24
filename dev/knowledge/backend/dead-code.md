# Backend Dead Code Analysis

## Summary

This document tracks dead, unused, and deprecated code in the backend. Items are resolved as they get cleaned up.

## Remaining Items

### 1. Repository FIXME Comments — Domain Model Refactoring

Four files contain FIXME comments indicating incomplete domain model refactoring for ApplicationDriver:

| File | Line | Comment |
|------|------|---------|
| `repository/application_driver.py` | 16 | `# FIXME: Update repository for ApplicationDriver to support domain models` |
| `repository/application_driver_version.py` | 13 | `# FIXME: Update repository for ApplicationDriverVersion to support domain models` |
| `domain/models.py` | 12 | `# FIXME: Add domain model for application driver and application driver version` |
| `api/definitions/application_driver/model.py` | 19 | `# FIXME: Support domain models serialization instead` |

**Action:** Either complete the domain model refactoring or update comments to reflect current architecture.

### 2. `domain/payloads.py` — Obsolete Docstring

**Location:** `domain/payloads.py:1`

```python
"""Obsolete payloads models. To be removed when extracted properly."""
```

The module is actively used by `services/instances.py` and `services/utilities/utilities.py`. The docstring is misleading.

**Action:** Update the docstring to reflect current usage.

### 3. `styrmin_backend/__init__.py` — Commented Version

**Location:** `styrmin_backend/__init__.py:4`

```python
# __version__ = importlib.metadata.version("styrmin-backend")
```

**Action:** Minor — remove if hardcoded version is intentional.

## Resolved Items

The following items from the original analysis have been cleaned up:

- `workflows/initialization.py` — deleted
- `agent/tasks/shared.py` commented functions — removed
- `services/instances.py` commented functions — removed
- `api/schema/mutation.py` commented upgrade mutation — removed
- `ApplicationInstantiationInProgress` / `ApplicationInstantiationFailed` response types — removed
- `InstantiateApplicationResponse` union — removed
- `UpgradeApplicationInstanceResponse` types — removed
- `context/models/contexts.py` commented ingress property — removed
