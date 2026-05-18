# Extraction Record

**Extracted on**: 2026-05-17
**Extracted by**: speckit.extract

## ADRs Created

- [`dev/adr/adr-043-resourcespec-first-class-plus-extended-map.md`](../../dev/adr/adr-043-resourcespec-first-class-plus-extended-map.md) (from Decision 3)
- [`dev/adr/adr-044-scheduling-merge-semantics.md`](../../dev/adr/adr-044-scheduling-merge-semantics.md) (from Decisions 2 + 4 + 5)
- [`dev/adr/adr-045-affinity-by-deployment-reference-via-label.md`](../../dev/adr/adr-045-affinity-by-deployment-reference-via-label.md) (from Decision 6)
- [`dev/adr/adr-046-runtime-class-validation-syntactic-only.md`](../../dev/adr/adr-046-runtime-class-validation-syntactic-only.md) (from Decision 7, reverted after shipping)
- [`dev/adr/adr-047-post-render-injection-toggles-and-kind-list.md`](../../dev/adr/adr-047-post-render-injection-toggles-and-kind-list.md) (from Decisions 8 + 9)
- [`dev/adr/adr-048-scheduling-provenance-map.md`](../../dev/adr/adr-048-scheduling-provenance-map.md) (from Decision 10)

## Knowledge Updated

- [`dev/knowledge/backend/data-models.md`](../../dev/knowledge/backend/data-models.md) (Configuration Models → new `SchedulingConfig` sub-section with `ResourceSpec`, `PostRenderInjection`, merge precedence, affinity-by-deployment label)
- [`dev/knowledge/backend/api.md`](../../dev/knowledge/backend/api.md) (GraphQL Types → new `ResolvedComponentScheduling` type with provenance map example)

## Guidelines Updated

None.

## Archive

Spec directory moved to `specs/archive/001-pod-scheduling-config/` as a historical record.
