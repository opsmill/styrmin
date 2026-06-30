# Spec/Ask Alignment Check: Anonymous opt-out telemetry for `styrminctl`

**Feature**: `015-styrminctl-telemetry` | **Date**: 2026-06-21

## 1. Source

- **Source PRD**: GitHub issue comment
  <https://github.com/opsmill/styrmin/issues/275#issuecomment-4762258122> — a full, structured PRD
  (Problem Statement, Solution Overview, 10 User Stories, 3 prioritised Journeys, FR-001…FR-018, Key
  Entities, Edge Cases, SC-001…SC-005, Implementation/Testing/Constitution decisions, Out of Scope,
  Open Questions, Assumptions).
- Fetched via `gh api repos/opsmill/styrmin/issues/comments/4762258122` (full body retrieved).
- Compared against: `specs/015-styrminctl-telemetry/spec.md` (post-critique state).

## 2. Verdict

✅ **ALIGNED**

The spec is a faithful, complete restatement of the PRD. All 18 functional requirements, all 5 success
criteria, all edge cases, the key entities, the out-of-scope list, and the assumptions are preserved
with intact semantics. The PRD's single open question was resolved exactly as the PRD directed. The few
additions the spec makes are clarifications or strengthening of existing PRD requirements, not new
scope or altered meaning.

## 3. Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| ✅ none | missing | FR-001…FR-018 | spec §Functional Requirements | All 18 FRs present with identical semantics (verbatim wording, minor formatting only). |
| ✅ none | missing | PRD User Stories 1–10 | spec US1–US3 | The 10 stories are folded into the PRD's own 3 prioritised journeys (P1/P2/P3); every actor/value is represented. No story dropped. |
| ✅ none | missing | SC-001…SC-005 | spec §Success Criteria | All five carried verbatim. |
| ✅ none | missing | PRD Edge Cases / Out of Scope / Assumptions / Key Entities | spec §Edge Cases / §Out of Scope / §Assumptions / §Key Entities | All carried. |
| info | resolved | PRD Open Question (`payload_format`) | spec §Assumptions; FR-005 | Resolved to the string `"1.0"` — exactly the PRD's stated resolution (`RESOLVE AS: "1.0" string`). Not drift. |
| info | added (clarify) | PRD FR-012 + maintainer story 10 ("de-duplicate events") + "dropped repeat-counts are acceptable" | spec US1 measurement note | Spec makes explicit that the signal is per-install **reach**, not call frequency. Derived from the PRD; no new requirement. |
| info | added (clarify) | PRD US5 (silent) + US6/US9 (opt-out/trust) + "README documents what is collected" | spec §Assumptions disclosure-stance note | Records the deliberate silent-plus-documented disclosure rationale. No behaviour change. |
| info | added (strengthen) | PRD FR-008 (exclude option **values**) | spec FR-010 addition | "Deriving option names MUST NOT read/convert values or `@file`." Protects an existing PRD guarantee; does not change semantics. |
| info | added (impl detail) | PRD Testing Decisions (`api_only` E2E vs local sink) | spec §Assumptions E2E-harness note | Clarifies the E2E uses a real subprocess + real sink and needs no vCluster. Consistent with the PRD's `api_only` decision. |

No 🛑 significant drift: nothing required by the PRD is missing, no requirement's semantics changed, no
acceptance criterion softened, no off-scope scope added, and no PRD constraint contradicted.

## 4. Action

**Proceed.** No remediation required. `spec.md`, `plan.md`, and `tasks.md` are aligned with the source
PRD and ready for review / implementation. Remediation counter: 0 passes used.
