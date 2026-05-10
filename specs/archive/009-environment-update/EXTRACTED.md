# Extraction Record

**Extracted on**: 2026-05-10
**Extracted by**: speckit.extract

## ADRs Created

- (none — already captured in [`dev/adr/adr-020-environment-config-fanout.md`](../../dev/adr/adr-020-environment-config-fanout.md) during implementation)

## Knowledge Updated

- [`dev/knowledge/backend/deployment-env-vars.md`](../../dev/knowledge/backend/deployment-env-vars.md) — "Setting values via the API" section now reflects the typed `UpdateEnvironmentInput` for environment-scope writes (deployment / per-component scopes still use `config: JSON`).

## Guidelines Updated

- [`dev/guidelines/backend/python.md`](../../dev/guidelines/backend/python.md) — added "Per-target failure isolation in fanout writes" subsection capturing the per-deployment try/except pattern from research §4.

## Archive

Spec directory moved to `specs/archive/009-environment-update/` as a historical record.
