# ADR-025: Capabilities as JSON column with extensible nested-dict schema

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-cluster-env-capabilities/research.md (R1, R3)

## Context

A cluster or environment has *capabilities* — derived facts like "ssd storage is available via class `fast-ssd`" or "Velero backup is configured with location `main`". These were previously implicit: a driver template would read `cluster.config.standard_storage` and decide for itself whether to claim storage capability. The platform now needs to:

- **Persist** capabilities so the UI can show "what can this cluster do?" without re-running derivation logic.
- **Expose** them to driver templates without forcing each driver to re-implement the same checks.
- **Extend** with new categories (storage tiers, ingress kinds, future capability types) without invalidating existing data or requiring a migration each time.

Two orthogonal questions had to be settled together:

1. *Storage shape* — separate table per category? One blob per entity?
2. *Schema shape* — flat list? Strongly-typed object? Nested dict?

## Decision

Store capabilities as a single `JSON` column on both `Cluster` and `Environment` (`capabilities: dict | None = Field(sa_column=Column(JSON))`), following the existing precedent set by `config`. The contents follow a **nested-dict shape**:

```python
{
    "<category>": {
        "<sub_capability>": { ...detail fields... },
    },
}
```

Concrete categories live in `backend/styrmin_backend/context/models/capabilities.py` as typed Pydantic models (`Capabilities`, `StorageCapabilityDetail`, `IngressCapabilityDetail`, `BackupCapabilityDetail`), serialized with `model_dump(exclude_none=True)` so absent categories don't pollute the blob with `null`s. Driver templates and the GraphQL surface read the structure as `cluster.capabilities.<category>.<sub>` / `environment.capabilities.<category>.<sub>`.

The `capabilities` field is exposed on both `Cluster` and `Environment` GraphQL types as a `JSON` scalar (same pattern as `config`).

## Consequences

- Adding a new capability category is a Pydantic-model change — no DB migration, no `metadata.create_all()` adjustment, no GraphQL schema regeneration. Aligns with the project's no-Alembic posture.
- The nested shape maps 1:1 to Jinja2 template access (`{{ cluster.capabilities.storage.ssd.storage_class }}`) and to JS object access in the frontend — no special transport layer or unflattening step.
- The JSON-scalar GraphQL exposure preserves extensibility: a new category does not require a schema change, and the frontend can introspect categories at runtime.
- Pydantic validates the structure server-side at write time, so a malformed `capabilities` blob can't slip into the database from a service-layer bug. The wire surface is still loose-typed JSON, but the entry point through the service layer is strict.
- The tradeoff: queries can't directly filter on `WHERE capabilities.storage.ssd IS NOT NULL` without database-vendor-specific JSON operators. Acceptable because capability queries are pull-by-entity, never aggregate-across-clusters.

## Alternatives Considered

- **Separate `Capability` table joined to Cluster/Environment**: rejected. Adds join complexity for a read-heavy, computed field. Extensibility is worse, not better — new categories require new join logic. The JSON shape buys extensibility for free.
- **Compute on every read, do not persist**: rejected. The user explicitly requested persistence so the UI can render capabilities without round-tripping the derivation logic. Even if computation is cheap, caching it avoids duplicating the rules across read paths.
- **Flat list of `{category, sub, details}` objects**: rejected. Loses the hierarchical access pattern that drivers actually use, and forces clients to filter-and-group on every read.
- **Strongly-typed GraphQL types per category**: rejected. Defeats the extensibility goal — every new category would require a GraphQL schema change and SDK regeneration. JSON scalar with Pydantic-side validation is the right tradeoff for a frequently-extended shape.
