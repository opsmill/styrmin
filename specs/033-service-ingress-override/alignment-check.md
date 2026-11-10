# Alignment Check: Service ingress override

**Date**: 2026-11-10
**Feature**: [spec.md](spec.md)

## Source

- The PRD in the comment [#issuecomment-6763699998](https://github.com/opsmill/styrmin/issues/598#issuecomment-6763699998) on issue [#598](https://github.com/opsmill/styrmin/issues/598), fetched with `gh api repos/opsmill/styrmin/issues/comments/6763699998` on 2026-11-10.
- The body of issue #598, fetched with `gh issue view 598 --json body`.
- No inline PRD in the invocation: the invocation was only the comment URL.

## Verdict

⚠️ **MINOR DRIFT (proceeding)**, with one deliberate change of a requirement that the PRD owner must confirm (finding 1).

Remediation passes used: 0. No finding is a missing, softened or contradicted requirement. The one changed requirement is a correction of an internal conflict of the PRD, not a scope change, but it changes the wording of a numbered requirement, so it is listed first.

## Findings

| # | Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|---|
| 1 | Significant if unconfirmed | changed | FR-002 | FR-002 | The PRD gives the application address to "the first external service that the driver declares". In the `infrahub` driver that is `task-manager`, while the chart's Ingress for the `infrahub` service already uses the application address as its host (`driver/examples/infrahub/values.j2.yml` line 10). Two Ingresses would claim one host, which breaks PRD FR-013, SC-002 and SC-005. The spec gives the address to the first service the driver declares, only when it is external. Evidence: [research.md](research.md) D-003, [critique](critiques/critique-20261110-1000.md) E1. The spec marks the change in the requirement itself. |
| 2 | Minor | added | none | Edge Cases (tcp and udp) | A service of `kind: tcp` or `udp` declared `external` gets no Ingress, because an Ingress cannot route it. The PRD is silent. Clarification, needed for FR-001 to be testable. |
| 3 | Minor | added | FR-014 ("after the upgrade") | Edge Cases, FR-014 | The spec states that existing deployments whose stored driver version declares `external` and renders its own Ingress get a second Ingress as soon as they run a Styrmin release with this feature, not only at a driver version change. The PRD does not say which upgrade it means. Inferred from the code paths in research D-001 and D-002, not reproduced. Left as a question for the PRD owner. |
| 4 | Minor | added | User stories 5, 6, 7 | FR-015, FR-016 | The PRD has no numbered requirement for the manifest, API and UI paths and for the overridden or inherited marks. The spec adds two requirements that carry those user stories. Expansion of detail. |
| 5 | Minor | changed | Open Questions 1 to 3 (three `NEEDS CLARIFICATION` markers) | Assumptions | The PRD's three open questions are written as "not known" or "decided in the plan" in Assumptions, with no marker. The spec does not answer any of them. The plan decides question 2 (the UI gets the services from `deployedServices` and from `ApplicationDriverVersion.services`, research D-010). Questions 1 and 3 stay not known. |
| 6 | Minor | changed | User stories 1 to 15, three journeys P1 to P3 | User Stories 1 to 4 | The spec groups the PRD's 15 user stories and 3 journeys into four stories and keeps every numbered FR and SC. Stories 11 (sandbox), 12 (driver author builds Ingress), 13 (hostnames), 14 (migration guide) and 15 (end-to-end tests) are covered by SC-005, FR-001, FR-011 (extended to name the hostname rule), FR-012 to FR-014 and the test line of each FR. Story 8 and 9 are User Story 4. No loss of content. |

Checked and found equal to the PRD: FR-001, FR-003 to FR-013 (wording kept), SC-001 to SC-006, Key Entities, Out of Scope (all eight items), Governance Gates, Assumptions, the three P1 to P3 acceptance scenarios.

Not compared: the PRD's "Implementation Decisions" and "Testing Decisions" sections are design, not requirements. They live in [plan.md](plan.md). The plan follows them, except that the Ingress builder extends the existing `IngressUtility` instead of adding a separate module (research D-001), and the application address rule (finding 1).

## Action

Proceed to Completion. No re-run of specify, plan or tasks. Before implementation, the PRD owner confirms finding 1 and answers finding 3 (also listed in the critique as P1).
