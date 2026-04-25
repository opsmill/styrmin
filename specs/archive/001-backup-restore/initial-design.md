# Archived Design Note: Instance Backup & Restore for Styrmin

This archived design note captured the initial backup and restore feature direction. The maintained backend reference now lives in `dev/knowledge/backend/backup-restore.md`.

## Overview

Implement backup and restore capabilities for Styrmin instances. Backups are tied to instances and driven entirely by the Application Driver configuration. The underlying implementation leverages Velero for Kubernetes volume snapshots, with support for pre-packaged backup strategies for common workloads.

## Goals

- Enable users to back up and restore application instances
- Backup configuration is defined in the Application Driver (user-facing)
- Support multiple backup strategies: simple disk snapshots, database-aware backups, and fully custom workflows
- Automatically inject Velero configuration into Kubernetes manifests
- Keep implementation extensible for future backup backends

## Architecture Overview

### Backup Types (Hierarchy)
```
BackupStrategy
├── DiskSnapshot         # Simple Velero volume backup
├── DatabaseBackup       # Disk snapshot + pre/post commands
│   ├── PostgresBackup   # Pre-packaged: pg_dump before snapshot
│   └── Neo4jBackup      # Pre-packaged: neo4j-admin dump before snapshot
└── ActionBackup         # Fully custom user-defined sequence
```

### 1. DiskSnapshot (Base Implementation)

The simplest backup type - uses Velero to snapshot persistent volumes.

**What it does:**
- Identifies target volume(s) on the component
- Injects Velero pod annotations into K8s manifests
- Triggers Velero backup/restore operations

**Velero Integration:**
Styrmin automatically injects the following annotation into pod specs:
```yaml
podAnnotations:
  backup.velero.io/backup-volumes:
```

For multiple volumes, comma-separated:
```yaml
podAnnotations:
  backup.velero.io/backup-volumes: data-volume,config-volume
```

### 2. DatabaseBackup (Pre-packaged Strategies)

Extends DiskSnapshot with database-specific pre/post commands.

**PostgresBackup workflow:**
1. Execute `pg_dump` to create consistent database export
2. Perform Velero volume snapshot
3. (Optional) Clean up dump files post-backup

**Neo4jBackup workflow:**
1. Execute `neo4j-admin database dump`
2. Perform Velero volume snapshot  
3. (Optional) Clean up dump files post-backup

These are pre-packaged because Postgres/Neo4j are common in many applications - users just select the type without defining commands.

### 3. ActionBackup (Fully Custom)

Users define a sequence of tasks similar to upgrade workflows:
- Pre-backup actions (commands, scripts)
- Volume snapshot(s)
- Post-backup actions
- Custom restore sequence

This mirrors the existing Action pattern used for upgrades.

## Driver Configuration (User-Facing)

Backup configuration lives in the Application Driver, on each component that requires backup:
```yaml
components:
  - name: database
    # ... existing component config ...
    backup:
      enabled: true
      kind: postgres  # Options: disk | postgres | neo4j | action
      specs:
        volume: data    # Which volume to snapshot (required if multiple volumes)

  - name: cache
    backup:
      enabled: true
      kind: disk
      specs:
        volume: data    # Which volume to snapshot (required if multiple volumes)


  - name: app-server
    backup:
      enabled: true
      kind: action
```

### Configuration Schema
```yaml
backup:
  enabled: boolean          # Default: false
  kind: enum                # disk | postgres | neo4j | action
  volume: string            # Volume name to snapshot (required if component has multiple volumes)
  volumes: list[string]     # Alternative: multiple volumes to snapshot

  # For postgres/neo4j types (optional overrides)
  database_name: string     # Override default database detection
  credentials_secret: string # K8s secret containing DB credentials
```

## Implementation Scope

### New Objects/Resources

1. **Backup** - Represents a point-in-time backup of an instance
   - Linked to: Instance, Application
   - Contains: Timestamp, status, metadata, component backup references
   - States: Pending, InProgress, Completed, Failed

2. **Restore** - Represents a restore operation
   - Linked to: Backup, Target Instance
   - States: Pending, InProgress, Completed, Failed

### Component Model Extension

Add `backup` field to the component definition within drivers:
```python
class ComponentBackupConfig:
    enabled: bool = False
    kind: BackupType  # Enum: DISK, POSTGRES, NEO4J, ACTION
    volume: Optional[str] = None
    volumes: Optional[List[str]] = None
    actions: Optional[BackupActions] = None
```

### Kubernetes Manifest Injection

When generating K8s manifests for a component with backup enabled:

1. Read backup configuration from driver
2. Determine target volume(s)
3. Inject Velero annotations into pod spec:
```yaml
   metadata:
     annotations:
       backup.velero.io/backup-volumes: 
```
4. For database types, potentially inject init containers or sidecar for backup commands

### API Endpoints (High-Level)

The API should be exposed in GraphQL


## Key Design Decisions to Make

1. **Backup Storage**: Where are backup metadata and references stored? (Styrmin DB + Velero backend)

2. **Multi-component Backups**: Should instance backup be atomic across all components, or component-by-component?

The goal is to have an atomic backup across all components by default.

3. **Backup Naming/Retention**: How are backups named? What's the retention policy model?

Use a simple nameing with the name of the driver, the name of the environment, the name of the component and the time of the backup

4. **Restore Targeting**: Can you restore to a different instance? Different namespace?

Yes it should be possible to restore a backup in a different namespace

5. **Scheduling**: Will scheduled backups be part of this feature, or a follow-up?

Scheduled backup should be part of the initial implementation

6. **Progress Tracking**: How do we surface Velero backup/restore progress to users?

We need to expose some GraphQL queries to query the associated k8s resources.

## Out of Scope (Initial Implementation)

- Cross-cluster backup/restore
- Backup encryption (rely on Velero/storage backend)
- Backup verification/validation
- Point-in-time recovery for databases

## References

- Velero documentation: https://velero.io/docs/
- Velero pod volume backup annotation: `backup.velero.io/backup-volumes`
- Velero supports pre/post hooks for custom commands during backup/restore

## Questions for Clarification

1. Should the backup type be defined at the driver level (all instances use same backup strategy) or overridable per instance?

2. For database backups, should the dump file be stored alongside the volume snapshot, or is the volume snapshot sufficient?

3. How should we handle backup dependencies between components (e.g., backup database before app server)?

4. What's the expected UX for triggering backups - CLI, UI, API, or all three?
