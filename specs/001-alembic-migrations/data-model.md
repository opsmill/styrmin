# Data Model: Alembic Migration Integration

**Feature**: 001-alembic-migrations | **Date**: 2026-04-04

## Overview

This feature does not introduce new application-level entities. It adds Alembic's internal tracking table and manages the existing 15+ SQLModel models through versioned migrations.

## Alembic Internal Table

Alembic automatically creates and manages an `alembic_version` table:

| Column | Type | Description |
|--------|------|-------------|
| version_num | VARCHAR(32) | Current migration revision hash (primary key) |

This table is managed entirely by Alembic and should never be modified directly.

## Existing Models (Unchanged)

The following models are captured in the baseline migration. No schema changes are made:

| Model | Table Name | Key Fields |
|-------|-----------|------------|
| Cluster | cluster | name (unique), config (JSON), capabilities (JSON) |
| BackupStorageLocation | backupstoragelocation | name (unique), endpoint, bucket, region |
| Environment | environment | name, config (JSON), cluster_id (FK), backup_storage_location_id (FK) |
| HelmRepository | helmrepository | url (unique) |
| HelmChart | helmchart | name, version, values_template, repository_id (FK) |
| ApplicationDriver | applicationdriver | name (unique) |
| ApplicationDriverVersion | applicationdriverversion | version, source_type, components (JSON), parameters (JSON) |
| ComponentConfig | componentconfig | name, config (JSON), application_driver_version_id (FK) |
| Action | action | name, description, location, image, hook, mode |
| Utility | utility | kind, resource_template |
| Deployment | deployment | name (unique), status (enum), config (JSON), parameters (JSON) |
| Component | component | name, enabled (bool), config (JSON), deployment_id (FK) |
| DeployedService | deployedservice | driver_service_name, resolved_name, kind, scope, port |
| ApplicationInstance | applicationinstance | name (unique), status (enum), context (JSON) |
| Backup | backup | name (unique), status (enum), component_statuses (JSON) |
| Restore | restore | name (unique), status (enum), component_statuses (JSON) |
| BackupSchedule | backupschedule | name (unique), cron_expression, retention_count |
| Task | task | status (enum), type (enum), message, prefect_flow_run_id |

## Migration Version Chain

```
(empty) → 0001_initial_schema (baseline - creates all tables above)
```

Future migrations will extend this chain as models evolve.
