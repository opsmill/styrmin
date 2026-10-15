# Spec/Ask Alignment Check: Ingress Class Set Only After the Chart Renders

**Date**: 2026-10-15
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Tasks**: [tasks.md](tasks.md)

## Source

- PRD "Ingress class set only after the chart renders": [opsmill/styrmin#471 (comment)](https://github.com/opsmill/styrmin/issues/471#issuecomment-6187650614), fetched with `gh issue view 471` on 2026-10-15.
- Issue body of [#471](https://github.com/opsmill/styrmin/issues/471), for the description of the current behavior.

## Verdict

✅ ALIGNED

Every PRD requirement, user story, journey, success criterion, edge case, documentation item, testing decision, assumption and out-of-scope item is in the spec, and the plan and tasks carry them. The spec's additions are restatements of other PRD sections as requirements, or details that the PRD left to planning. None adds scope or changes a requirement's meaning.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|----------|----------|---------------|----------------|-------------|
| Info | added | "Implementation decisions" (ingress utility, "with no class resolved: leave the chart's class unchanged"); "Edge cases", first item | FR-006 | The PRD states the no-class behavior as an edge case and an implementation decision, not as an FR. The spec makes it a testable requirement with the same meaning. |
| Info | added | "Implementation decisions" (example drivers drop the class line and keep `spec.version`) | FR-007 | Same decision, written as a requirement. |
| Info | added | "Documentation changes in the same pull request" | FR-008 | The three documentation pages from the PRD, written as a requirement; the full documentation list is in the spec's Documentation Changes section. |
| Info | added | "Implementation decisions" (interfaces, errors, data) | FR-009 | The PRD's "no change to GraphQL, the SDK, `styrminctl` or the frontend", "no new error type" and "no database change", written as one constraint. |
| Info | added | "Assumptions"; PRD acceptance "`kubernetes.io/ingress.class: traefik`" | A-004 | The spec states that Traefik is the only dedicated controller implementation, which the PRD's acceptance values already assume. |
| Info | changed (format only) | "Open question" (`[NEEDS CLARIFICATION]`, "does not block the change") | Open Question, A-001 | The spec keeps the question open and non-blocking, as the PRD does, without a `[NEEDS CLARIFICATION]` marker, so the spec quality checklist passes. The meaning is unchanged. |
| Info | added | "User journeys", P2; FR-001 test | User Story 2, scenario 3 | A shared-mode scenario (chart renders `nginx`, resolved class `traefik`) taken from the PRD's FR-001 test. |
| Info | added | "Testing decisions" (integration test) | Testing Approach; tasks T016, T018 | The integration test also simulates a subchart Ingress (PRD A-002) and compares an old-style template with the migrated one (PRD FR-005). Both extend the PRD's test; neither adds a requirement. |
| Info | added | "Testing decisions" (E2E) | Testing Approach; task T019 | The E2E fixture drivers `late-container` and `failing-actions` keep their class line on purpose, as CI coverage of FR-005 in dedicated mode (critique E2). No new test. |

No finding is missing, dropped or contradicted.

## Coverage of the PRD

- User stories 1 to 6: spec User Stories 1 to 3 and FR-003 (story 4).
- Journeys P1 and P2: spec User Story 1 scenarios 1 and 2, User Story 2 scenarios 1 and 2.
- FR-001 to FR-005: spec FR-001 to FR-005, same tests.
- SC-001 to SC-004: spec SC-001 to SC-004; SC-003 adds how it is verified, matching the PRD's accepted gap.
- Edge cases: all four in the spec's Edge Cases.
- Implementation decisions: plan and research D-001 to D-005; the patch type left to planning is decided in D-001 (strategic merge patch with `ingressClassName: null`).
- Documentation: spec Documentation Changes; tasks T006, T012, T013, T020 to T024.
- Testing: unit tests (T003, T005, T007), new integration test (T011, T016 to T018), two existing E2E tests run locally with evidence (T014, T015, T027), no new E2E test.
- Out of scope: all five items in the spec's Out of Scope.

## Action

Proceed. No remediation pass was needed (0 of 2 used).
