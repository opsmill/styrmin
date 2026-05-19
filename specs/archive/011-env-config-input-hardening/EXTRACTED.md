# Extraction Record

**Extracted on**: 2026-05-10
**Extracted by**: speckit.extract

## ADRs Created

- [`dev/adr/adr-014-schema-walking-input-propagation-tests.md`](../../dev/adr/adr-014-schema-walking-input-propagation-tests.md) (from research §1)
- [`dev/adr/adr-015-frontend-value-transform-boundary.md`](../../dev/adr/adr-015-frontend-value-transform-boundary.md) (from research §5)

## Knowledge Updated

- [`dev/knowledge/backend/api.md`](../../dev/knowledge/backend/api.md) — added "Notable typed error codes" subsection documenting `INVALID_ENV_VAR_VALUE` (US3 / FR-008..FR-011).
- [`dev/knowledge/backend/e2e-testing.md`](../../dev/knowledge/backend/e2e-testing.md) — added "`api_only` audit discipline" subsection codifying the dual-entrypoint heuristic from research §3.

## Guidelines Updated

- [`dev/guidelines/backend/python.md`](../../dev/guidelines/backend/python.md) — added "Validator entry-point type guards" subsection (research §4).
- [`dev/guidelines/backend/python.md`](../../dev/guidelines/backend/python.md) — added "Schema-walking propagation tests" subsection (research §1, paired with ADR-014).
- [`dev/guidelines/frontend/forms.md`](../../dev/guidelines/frontend/forms.md) — added "Value-transform boundary for full-replacement inputs" subsection (research §5, paired with ADR-015).

## Archive

Spec directory moved to `specs/archive/011-env-config-input-hardening/` as a historical record.
