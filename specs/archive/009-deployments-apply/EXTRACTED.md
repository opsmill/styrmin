# Extraction Record

**Extracted on**: 2026-08-04
**Extracted by**: speckit.opsmill.extract

## ADRs Created

- `dev/adr/0048-declarative-apply-client-side-orchestration.md` (from D1, D8, and the D2 race follow-up)
- `dev/adr/0049-styrmin-v1-manifest-contract.md` (from D3, D4, D6, D9, D10, D13)
- `dev/adr/0050-composite-natural-key-deployment-lookup.md` (from D2)

## Knowledge Updated

- `dev/knowledge/backend/api.md` (Queries — corrected the `deployment` row and added a
  "`deployment` — two argument shapes" subsection)

## Guidelines Updated

None — every implementation pattern here conforms to existing conventions.

## Also updated

- `CONTEXT.md` — repointed the manifest-schema reference into the archive and linked ADR-049
- `python_sdk/AGENTS.md` — repointed the `sdk-apply.md` link and linked ADR-048

## Not extracted

- D5 (driver-mismatch error), D7 (fire-and-forget default), D11 (output format),
  D12 (PyYAML dependency placement) — captured in code and `CHANGELOG.md`; the
  conventions they follow are already established platform-wide.

## Archive

Spec directory moved to `specs/archive/009-deployments-apply/` as a historical record.
