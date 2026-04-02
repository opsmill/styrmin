# Research: Cluster & Environment Capability Declarations

**Feature Branch**: `001-cluster-env-capabilities`
**Date**: 2026-04-01

## R1: Capability Data Storage Strategy

**Decision**: Store capabilities as a JSON column on Cluster and Environment models, following the existing pattern used for `config` fields.

**Rationale**: The project already stores structured data (ClusterConfig, EnvironmentConfig) as `dict | None` with `sa_column=Column(JSON)`. Capabilities follow the same pattern — a Pydantic model serialized to a JSON column. This avoids new tables, keeps the model simple, and aligns with `metadata.create_all()` (no Alembic).

**Alternatives considered**:
- Separate `Capability` table with foreign keys: Rejected — adds join complexity for a read-heavy, computed field. Extensibility is better served by JSON (new categories = new keys, no schema changes).
- Computed on every query (no persistence): Rejected — user explicitly requested persistence. Even though computation is cheap, caching avoids redundant work.

## R2: Capability Recalculation Trigger

**Decision**: Recalculate capabilities in the service layer during create/update operations on Cluster and Environment (and when BackupStorageLocation assignments change).

**Rationale**: Capabilities are derived from `config`, `standard_storage`, `dedicated_ingress`, `fqdn_suffix`, and `backup_storage_location_id`. These only change through mutations (create_cluster, create_environment, assign_backup_storage_location, etc.). Computing capabilities inline in the service functions is straightforward and guaranteed to be consistent.

**Alternatives considered**:
- Database triggers: Rejected — project uses SQLModel/SQLAlchemy async, not raw SQL triggers. Would break the layered architecture (Constitution III).
- Background task (Prefect): Rejected — overkill for a cheap, synchronous computation. Adds latency between config change and capability update.
- Event-driven recalculation: Rejected — no event bus exists in the project. Would require new infrastructure for a simple operation.

## R3: Hierarchical Capability Model Structure

**Decision**: Use a nested dict structure: `{category: {sub_capability: details}}`.

**Rationale**: The spec requires hierarchical organization by category (e.g., `storage` → `standard`, `ssd`). A nested dict naturally maps to JSON storage and Jinja2 template access (`{{ cluster.capabilities.storage.standard }}`). Pydantic models validate the structure.

**Example structure**:
```json
{
  "storage": {
    "standard": {"storage_class": "standard"},
    "ssd": {"storage_class": "fast-ssd"}
  },
  "ingress": {
    "external": {"ingress_class": "traefik", "dns_zone": "example.com"}
  },
  "backup": {
    "velero": {"storage_location": "my-bsl"}
  }
}
```

**Alternatives considered**:
- Flat list of capability objects: Rejected — doesn't support the hierarchical category/sub-capability requirement. Harder to query by category in templates.
- Separate model per category: Rejected — not extensible. Adding a new category would require new Pydantic models and code changes.

## R4: Context Integration Approach

**Decision**: Add a `capabilities` field to both `ClusterContext` and `EnvironmentContext` Pydantic models. Populate them in `generate_context_from_deployment()` by reading the persisted capabilities from the database models.

**Rationale**: The context pipeline converts `GlobalContext` to a dict via `model_dump(exclude_none=True)` and passes it to Jinja2. Adding `capabilities` to `ClusterContext` and `EnvironmentContext` makes them automatically available as `{{ cluster.capabilities.* }}` and `{{ environment.capabilities.* }}`. SilentUndefined already handles missing categories gracefully.

**Alternatives considered**:
- Add capabilities only to `InstanceContext.config` (resolved): Rejected — capabilities are entity-specific (cluster vs environment), not merged like config. The environment-scoped view means environment capabilities differ from cluster capabilities.
- Inject capabilities as a top-level GlobalContext field: Rejected — breaks the logical grouping. Capabilities belong to their respective entities.

## R5: Environment-Scoped Capability Computation

**Decision**: Environment capabilities are computed independently based on the environment's own configuration and relationships, not by copying and filtering cluster capabilities.

**Rationale**: The environment has its own `config` dict, its own `backup_storage_location` relationship, and its own ingress settings. Computing environment capabilities from these sources directly is simpler and more correct than filtering cluster capabilities. For categories like storage, the environment's config determines what storage classes it uses — it doesn't inherit all cluster storage classes.

**Alternatives considered**:
- Copy cluster capabilities and filter: Rejected — creates coupling between cluster and environment capability computation. Changes to cluster capability logic would affect environment logic unexpectedly.

## R6: GraphQL Exposure

**Decision**: Add a `capabilities` resolver field on both Cluster and Environment Strawberry types, returning the persisted JSON as a `JSON` scalar (consistent with how `config` is exposed).

**Rationale**: The existing pattern exposes `config` as a `JSON` scalar. Capabilities follow the same pattern for consistency. This allows the frontend to access the full hierarchical structure without needing to define GraphQL types for every capability category (which would break extensibility).

**Alternatives considered**:
- Define strongly-typed GraphQL types per capability: Rejected — defeats extensibility requirement (FR-008). Adding a new capability category would require GraphQL schema changes.
- Expose as a list of key-value pairs: Rejected — loses hierarchical structure and is harder to query for specific categories.

## R7: Ingress Capability Derivation

**Decision**: Derive ingress capability from the presence of both `ingress_class` (or `dedicated_ingress`) in config AND `fqdn_suffix` in config (as proxy for DNS zone availability).

**Rationale**: `ingress_class` indicates an ingress controller is available. `fqdn_suffix` indicates a DNS zone is configured for FQDN generation. Both are required per the spec. These fields already exist in the config hierarchy.

**Alternatives considered**:
- Check only `ingress_class`: Rejected — spec requires both ingress controller AND DNS zone.
- Introduce a separate `dns_zone` field: Rejected — `fqdn_suffix` already serves this purpose in the existing config model. No need for a new field.
