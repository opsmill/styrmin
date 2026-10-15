# Extraction Record

**Extracted on**: 2026-10-15
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. [ADR-069](../../../dev/adr/0069-container-command-args-by-post-render.md) was written during
implementation and records research D-001 to D-012.

## ADRs Updated

- dev/adr/0069-container-command-args-by-post-render.md (§4: retired filters rejected at driver
  load; §6: `removed_key` error for `spec.container_overrides`; source paths moved to the archive)

## Knowledge Updated

None. The knowledge pages and `CONTEXT.md` were updated during implementation (commits `02623b6f`,
`84974511`).

## Guidelines Updated

- dev/guidelines/backend/python.md (Logging: log whether an override is set, not its value)
- dev/guidelines/backend/python.md (Retiring a driver-facing template surface: load-time
  rejection, `before` validator for a removed key)
- dev/guidelines/backend/python.md (Per-component pod overrides go through post-render: `yaml.dump`
  for strategic-merge patches, whole-list replacement for fields without a merge key)

## Archive

Spec directory moved to `specs/archive/022-post-render-container-overrides/` as a historical record.
