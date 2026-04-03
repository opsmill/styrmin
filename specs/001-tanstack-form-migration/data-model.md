# Data Model: TanStack Form Migration

**Feature Branch**: `001-tanstack-form-migration`
**Date**: 2026-04-03

## Overview

This is a frontend-only library migration. There are no database, API, or data model changes. The data model here documents the form data shapes (Zod schemas) that must be preserved exactly during migration.

## Form Data Schemas (Preserved As-Is)

### AddDriverPage

Two separate form schemas for local and remote driver loading:

**localSchema**:
- `path`: string, required, min(1)

**remoteSchema**:
- `repositoryUrl`: string, required, min(1)
- `branch`: string, required, defaults to "main"

### CreateBackupStorageLocationDialog

**createBslSchema**:
- `name`: string, required, min(1)
- `endpoint`: string, required, min(1)
- `bucket`: string, required, min(1)
- `region`: string, required, min(1)
- `accessKeyId`: string, required, min(1)
- `secretAccessKey`: string, required, min(1)

### BackupStorageLocationDetailPage

**updateCredentialsSchema**:
- `accessKeyId`: string, required, min(1)
- `secretAccessKey`: string, required, min(1)

### DeployFormPage

**deployFormSchema**:
- `name`: string, required, min(1)
- `applicationDriverVersionId`: string, required, min(1)
- `applicationVersion`: string, optional

Note: Dynamic driver parameters are managed via `useState`, not the form schema.

### CreateClusterDialog

**createClusterSchema** (with `.refine()` cross-field validation):
- `name`: string, required, min(1)
- `ingress_class`: string, optional
- `fqdn_suffix`: string, optional
- `runtime_class`: string, optional
- `dedicated_ingress_enabled`: boolean, default false
- `dedicated_ingress_implementation`: string
- `dedicated_ingress_type`: string
- `standard_storage_enabled`: boolean, default false
- `standard_storage_class`: string, optional

Cross-field rule: when `standard_storage_enabled` is true, `standard_storage_class` must be non-empty.

### CreateEnvironmentDialog

**createEnvironmentSchema**:
- `name`: string, required, min(1)
- `clusterId`: string, required, min(1)
- `ingress_class`: string, optional
- `db_size`: string, optional
- `fqdn_suffix`: string, optional
- `ip_whitelist`: string, optional (comma-separated, split into array at submission)
- `dedicated_ingress_enabled`: boolean, default false
- `dedicated_ingress_implementation`: string
- `dedicated_ingress_type`: string

## Entity Relationships

```
Form Component
  └── has many → Form Fields
  └── validates via → Zod Schema (unchanged)
  └── submits to → GraphQL Mutation Hook (unchanged)
  └── invalidates → TanStack Query Cache (unchanged)
```

## State Transitions

No state transitions change. All forms follow:

```
Idle → Editing → Validating → Submitting → Success/Error
                                             ↓
                                          Reset → Idle
```

The only change is which library manages the Idle→Editing→Validating→Submitting lifecycle. TanStack Form replaces React Hook Form as the state machine driver.
