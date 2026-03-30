# Data Model: Name-Based Resource Lookup

**Feature**: 001-graphql-name-lookup
**Date**: 2026-03-29

## Entity Changes

### Cluster (no changes)

| Field | Type | Constraint | Notes |
|-------|------|-----------|-------|
| id | UUID | PK | Unchanged |
| name | str | UNIQUE | Already globally unique -- used as alternative identifier |
| config | JSON | nullable | Unchanged |
| created_on | datetime | server default | Unchanged |
| updated_on | datetime | server default | Unchanged |

**Relationships**: One-to-many with Environment (unchanged)

### Environment (constraint change)

| Field | Type | Constraint | Notes |
|-------|------|-----------|-------|
| id | UUID | PK | Unchanged |
| name | str | UNIQUE(name, cluster_id) | **Changed from global UNIQUE to composite** |
| config | JSON | nullable | Unchanged |
| cluster_id | UUID | FK → cluster.id, NOT NULL | Unchanged |
| backup_storage_location_id | UUID | FK → backupstoragelocation.id, nullable | Unchanged |
| created_on | datetime | server default | Unchanged |
| updated_on | datetime | server default | Unchanged |

**Relationships**: Belongs to Cluster, has many Deployments (unchanged)

**Constraint change detail**:
- **Before**: `name` has `unique=True` (global uniqueness)
- **After**: `UniqueConstraint("name", "cluster_id")` via `__table_args__` (per-cluster uniqueness)
- **Impact**: Allows `("staging", cluster_A)` and `("staging", cluster_B)` to coexist. Prevents duplicate names within the same cluster.

## New Repository Methods

### EnvironmentRepository

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `get_by_name_in_cluster` | `name: str, cluster_id: UUID` | `Environment \| None` | New -- scoped lookup |

**Remove**: `get_by_name(name: str)` becomes incorrect after constraint change. Replace all call sites with `get_by_name_in_cluster`.

## New Service Layer Functions

### clusters.py

| Function | Parameters | Returns | Notes |
|----------|-----------|---------|-------|
| `resolve_cluster` | `uow, cluster_id: UUID \| None, cluster_name: str \| None` | `Cluster` | New -- validates mutual exclusivity, resolves by ID or name |

### environments.py

| Function | Parameters | Returns | Notes |
|----------|-----------|---------|-------|
| `resolve_environment` | `uow, environment_id: UUID \| None, environment_name: str \| None, cluster_id: UUID \| None, cluster_name: str \| None` | `Environment` | New -- resolves environment, first resolving cluster if needed |

## New Exceptions

### exceptions.py

| Exception | Error Code | Message Pattern |
|-----------|-----------|----------------|
| `AmbiguousIdentifierError` | `VALIDATION_ERROR` | "Provide either {resource}_id or {resource}_name, not both" / "Either {resource}_id or {resource}_name is required" |

## Validation Rules

1. For any operation: exactly one of (id, name) must be provided per resource
2. For environment by name: cluster context (id or name) is required
3. For environment by name: cluster context also follows the exactly-one rule
4. Environment name + cluster_id must be unique (DB-level composite constraint)
