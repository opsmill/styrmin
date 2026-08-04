# Extraction Record

**Extracted on**: 2026-08-04
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. Every decision in this spec is a reuse-or-convention call on an existing UI
surface with no architectural commitment: the tabs primitive, client-side sorting, a
hand-rolled relative-time helper, the propagation-test pattern, and the deliberate
absence of a feature flag all follow established practice. The `createdOn` GraphQL
addition is purely additive and has no home in `dev/knowledge/backend/api.md`, which
documents no driver types.

## Knowledge Updated

None.

## Guidelines Updated

- `dev/guidelines/frontend/routing.md` (Route Definitions — **new subsection** "In-page
  state stays out of the URL": detail-page tab and sub-selection state is
  component-local, and URL persistence is a uniform cross-page change, not a per-page
  one)
- `dev/guidelines/frontend/data-fetching.md` (**new section** "Reconcile local selection
  against every refresh" — keep the selection if still present, fall back silently if
  removed, plus the known auto-refresh error behaviour)
- `dev/guidelines/frontend/data-fetching.md` (**new section** "Rendering `JSON` scalar
  fields" — runtime shape guards, degrade to empty state, do not mirror the payload in a
  hand-written type)

## Not extracted

- §1 (tabs primitive reuse), §3 (client-side newest-first sort), §4/§12 (`createdOn`
  field and its SDK additivity), §5 (propagation test pattern), §7 (hand-rolled
  relative-time), §8/§9 (E2E and unit-test layout), §13 (no feature flag) — all conform
  to documented conventions.

## Follow-up left open

§11 records a **known limitation, deliberately preserved**: any query error, including a
transient failure during the 10s auto-refresh poll, replaces the page with
`<ErrorState>`. Changing it (retain last-good snapshot, non-blocking banner) is a
project-wide UX change. Noted in the data-fetching guideline so reviewers do not flag it
as a regression.

## Archive

Spec directory moved to `specs/archive/012-driver-detail-tabs/` as a historical record.
