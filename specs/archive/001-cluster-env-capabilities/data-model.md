# Data Model: Cluster & Environment Capability Declarations

**Feature Branch**: `001-cluster-env-capabilities`
**Date**: 2026-04-01

## Entity Changes

### Cluster (modified)

**File**: `backend/styrmin_backend/db/models.py`

| Field | Type | Storage | Notes |
|-------|------|---------|-------|
| `capabilities` | `dict \| None` | `sa_column=Column(JSON)` | New. Persisted hierarchical capability structure. Nullable, defaults to `None`. |

All existing fields unchanged.

### Environment (modified)

**File**: `backend/styrmin_backend/db/models.py`

| Field | Type | Storage | Notes |
|-------|------|---------|-------|
| `capabilities` | `dict \| None` | `sa_column=Column(JSON)` | New. Persisted hierarchical capability structure. Nullable, defaults to `None`. |

All existing fields unchanged.

## New Pydantic Models

**File**: `backend/styrmin_backend/context/models/capabilities.py` (new)

### CapabilityDetails

Base model for sub-capability details. Each capability category defines its own detail structure.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| (varies by category) | `dict[str, Any]` | No | Extensible key-value details |

### StorageCapabilityDetail

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `storage_class` | `str` | Yes | Kubernetes storage class name |

### IngressCapabilityDetail

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `ingress_class` | `str` | Yes | Ingress controller class (e.g., `traefik`) |
| `fqdn_suffix` | `str` | Yes | DNS zone suffix for FQDN generation |

### BackupCapabilityDetail

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `storage_location` | `str` | Yes | BackupStorageLocation name |

### Capabilities

Root model representing the full capability set for a Cluster or Environment.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `storage` | `dict[str, StorageCapabilityDetail] \| None` | No | Keyed by storage type name (e.g., `standard`, `ssd`) |
| `backup` | `dict[str, BackupCapabilityDetail] \| None` | No | Keyed by backup provider name (e.g., `velero`) |
| `ingress` | `dict[str, IngressCapabilityDetail] \| None` | No | Keyed by ingress type (e.g., `external`) |

**Extensibility**: New categories are added as optional fields on the `Capabilities` model. The JSON column stores whatever the model serializes — no schema migration needed.

**Serialization**: `model_dump(exclude_none=True)` — absent categories are omitted from the JSON, not stored as `null`.

## Context Model Changes

**File**: `backend/styrmin_backend/context/models/contexts.py`

### ClusterContext (modified)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `config` | `ClusterConfig` | Yes | Existing |
| `capabilities` | `dict[str, Any]` | No | New. Populated from persisted capabilities during context generation. Defaults to empty dict. |

### EnvironmentContext (modified)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | `str` | Yes | Existing |
| `config` | `EnvironmentConfig` | Yes | Existing |
| `capabilities` | `dict[str, Any]` | No | New. Populated from persisted capabilities during context generation. Defaults to empty dict. |

## Capability Derivation Rules

### Storage (Cluster)

**Source**: `cluster.config.standard_storage`
**Logic**: If `standard_storage` is configured, emit `storage.standard` with the storage class name.

### Storage (Environment)

**Source**: `environment.config` (environment-scoped — only what the environment itself configures)
**Logic**: Same as cluster but scoped to environment's own config.

### Backup (Environment only)

**Source**: `environment.backup_storage_location`
**Logic**: If `backup_storage_location` is assigned (non-null), emit `backup.velero` with the BSL name.

### Ingress (Cluster or Environment)

**Source**: `config.ingress_class` (or `dedicated_ingress`) AND `config.fqdn_suffix`
**Logic**: If both an ingress class and fqdn_suffix are present, emit `ingress.external` with the ingress class and fqdn_suffix.

## Recalculation Triggers

| Trigger | Entities Affected | Service Function |
|---------|-------------------|------------------|
| Cluster create/update | Cluster | `create_cluster()` |
| Environment create/update | Environment | `create_environment()` |
| BSL assign to environment | Environment | `assign_backup_storage_location()` |
| BSL unassign from environment | Environment | `unassign_backup_storage_location()` |

## JSON Storage Examples

### Cluster with storage and ingress

```json
{
  "storage": {
    "standard": {"storage_class": "standard"}
  },
  "ingress": {
    "external": {"ingress_class": "traefik", "fqdn_suffix": "apps.example.com"}
  }
}
```

### Environment with backup (no ingress)

```json
{
  "backup": {
    "velero": {"storage_location": "main-backup"}
  },
  "storage": {
    "standard": {"storage_class": "standard"}
  }
}
```

### Empty capabilities (no config)

```json
null
```
