# Extraction Record

**Extracted on**: 2026-05-17
**Extracted by**: speckit.extract

## ADRs Created

None — all R-section decisions are either implementation detail (chart key paths, Jinja conditional, E2E test shape) or already covered by existing ADRs ([ADR-039](../../dev/adr/adr-039-config-additions-via-baseconfigsection-no-migration.md) for the "no GraphQL/SDK change" pattern; established Pydantic validator conventions in the same file).

## Knowledge Updated

- [`dev/knowledge/backend/data-models.md`](../../dev/knowledge/backend/data-models.md) (Configuration Models → new `IngressServiceConfig` sub-section listing `type`, `annotations`, `load_balancer_ip`, `external_traffic_policy`, `ip_families`, `ip_family_policy`, `node_port`, and the two cross-field validators)

## Guidelines Updated

None.

## Archive

Spec directory moved to `specs/archive/001-ingress-ipfamily-nodeport/` as a historical record.
