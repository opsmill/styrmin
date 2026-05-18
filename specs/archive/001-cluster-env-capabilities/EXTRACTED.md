# Extraction Record

**Extracted on**: 2026-05-17
**Extracted by**: speckit.extract

## ADRs Created

- [`dev/adr/adr-035-capabilities-as-extensible-json-column.md`](../../dev/adr/adr-035-capabilities-as-extensible-json-column.md) (from R1 + R3)
- [`dev/adr/adr-036-capabilities-recalculation-in-service-layer.md`](../../dev/adr/adr-036-capabilities-recalculation-in-service-layer.md) (from R2)
- [`dev/adr/adr-037-environment-capabilities-computed-independently.md`](../../dev/adr/adr-037-environment-capabilities-computed-independently.md) (from R5)

## Knowledge Updated

None — `Cluster.capabilities` / `Environment.capabilities` model fields, `ClusterContext.capabilities` / `EnvironmentContext.capabilities` context fields, the `capabilities: JSON` GraphQL fields, and the Capabilities Service entries (`compute_cluster_capabilities`, `compute_environment_capabilities`) are all already documented in `data-models.md`, `api.md`, and `services.md`.

## Guidelines Updated

None.

## Archive

Spec directory moved to `specs/archive/001-cluster-env-capabilities/` as a historical record.
