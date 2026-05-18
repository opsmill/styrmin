# Extraction Record

**Extracted on**: 2026-05-17
**Extracted by**: speckit.extract

## ADRs Created

- [`dev/adr/adr-050-scenario-driver-protocol-and-parametrized-fixture.md`](../../dev/adr/adr-050-scenario-driver-protocol-and-parametrized-fixture.md) (from R1 + R4 + R7 supporting context)

## Knowledge Updated

None — `e2e-testing.md` already documents `ScenarioDriver`, `api_only` / `ui_only` markers, `[api-chromium]` / `[ui-chromium]` variants, ref dataclasses, and the session-scoped resources fixture in current form.

## Guidelines Updated

None. Selector priority (R4) may justify a future `dev/guidelines/frontend/e2e-pages.md` if page-object drift becomes a concern.

## Reversal note

R6's UI-only auto-retry via `pytest-rerunfailures` was added then removed in commit `bce37c1` (incompatible with `--pdb`). Documented in `AGENTS.md` § Debugging E2E Tests and `dev/knowledge/backend/e2e-testing.md` line 115; no ADR needed.

## Archive

Spec directory moved to `specs/archive/001-dual-e2e-entrypoints/` as a historical record.
