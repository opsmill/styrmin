# Quickstart: Cluster & Environment Capability Declarations

**Feature Branch**: `001-cluster-env-capabilities`

## What This Feature Does

Adds a `capabilities` field to Clusters and Environments that automatically derives and persists what each can support (storage types, backup, ingress). Capabilities are queryable via GraphQL and available in Application Driver Jinja2 templates.

## Key Files to Understand

| File | Purpose |
|------|---------|
| `backend/styrmin_backend/db/models.py` | Cluster/Environment DB models — new `capabilities` JSON column |
| `backend/styrmin_backend/context/models/capabilities.py` | NEW — Pydantic models for capability structure |
| `backend/styrmin_backend/services/capabilities.py` | NEW — Derivation logic (compute capabilities from config) |
| `backend/styrmin_backend/services/clusters.py` | Cluster service — triggers capability computation |
| `backend/styrmin_backend/services/environments.py` | Environment service — triggers capability computation |
| `backend/styrmin_backend/context/models/contexts.py` | ClusterContext/EnvironmentContext — new `capabilities` field |
| `backend/styrmin_backend/services/context.py` | Context generation — populates capabilities for templates |
| `backend/styrmin_backend/api/definitions/cluster/model.py` | GraphQL Cluster type — new resolver |
| `backend/styrmin_backend/api/definitions/environment/model.py` | GraphQL Environment type — new resolver |

## Implementation Order

1. **Capability models** (`capabilities.py`) — Define Pydantic models for the hierarchical structure
2. **DB schema** (`models.py`) — Add `capabilities` JSON column to Cluster and Environment
3. **Derivation service** (`services/capabilities.py`) — Logic to compute capabilities from config
4. **Service integration** (`clusters.py`, `environments.py`, `backup_storage_locations.py`) — Call derivation on create/update
5. **GraphQL exposure** (`cluster/model.py`, `environment/model.py`) — Add `capabilities` resolver field
6. **Context integration** (`contexts.py`, `context.py`) — Add capabilities to template rendering context
7. **Tests** — Unit tests for derivation, integration tests for GraphQL and context rendering

## How Capability Derivation Works

```text
Cluster config (JSON)           →  compute_cluster_capabilities()  →  capabilities (JSON)
  ├── standard_storage          →    storage.standard
  ├── ingress_class + fqdn_suffix  → ingress.external
  └── (future categories)       →    ...

Environment config + relations  →  compute_environment_capabilities()  →  capabilities (JSON)
  ├── config.standard_storage   →    storage.standard (env-scoped)
  ├── backup_storage_location   →    backup.velero
  ├── ingress_class + fqdn_suffix  → ingress.external (env-scoped)
  └── (future categories)       →    ...
```

## Template Usage Examples

```jinja2
{# Check if storage is available #}
{% if cluster.capabilities.storage %}
  storageClassName: "{{ cluster.capabilities.storage.standard.storage_class }}"
{% endif %}

{# Check if backup is available #}
{% if environment.capabilities.backup %}
  backupEnabled: true
{% endif %}

{# Check if ingress is available #}
{% if environment.capabilities.ingress %}
  ingress:
    className: "{{ environment.capabilities.ingress.external.ingress_class }}"
{% endif %}
```

## GraphQL Query Examples

```graphql
# Get cluster capabilities
query {
  cluster(clusterName: "default") {
    name
    capabilities
  }
}

# Get environment capabilities (with cluster context)
query {
  environment(environmentName: "production", clusterName: "default") {
    name
    capabilities
    cluster {
      capabilities
    }
  }
}
```
