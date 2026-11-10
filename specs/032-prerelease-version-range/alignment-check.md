# Alignment Check: spec.md against the source PRD

**Date**: 2026-11-10
**Spec**: [spec.md](spec.md)

## Source

- The PRD in [issue #591, comment 6762618486](https://github.com/opsmill/styrmin/issues/591#issuecomment-6762618486), "PRD: Accept prerelease application versions when they fit a driver version's range". Read in full with `gh api repos/opsmill/styrmin/issues/comments/6762618486`.
- The [issue description](https://github.com/opsmill/styrmin/issues/591), read with `gh issue view 591`.
- The [comment of 2026-11-04](https://github.com/opsmill/styrmin/issues/591#issuecomment-6625117869), which the PRD supersedes. Read to confirm what was replaced. Its decision (keep the old rule, explain it in the message) is intentionally not in the spec.
- Not reachable: the [Slack direct message of 2026-11-09](https://opsmillworkspace.slack.com/archives/D0C1JLMPB2S/p1794227533527739), which the PRD says is visible to two participants only. The spec relies on the PRD's own account of it.

## Verdict

⚠️ MINOR DRIFT (proceeding)

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| Minor | changed | FR-004 and SC-003: "A refusal MUST name the version and list every supported range of the driver" and "Every refused request lists all supported ranges" | FR-004, SC-003 | The spec limits both to a refused request to create, upgrade or pin a deployment, and states that the error a driver author sees at driver load keeps its own text. The PRD's own wording speaks of "request" in SC-003 and of "refusal" in FR-004, so the spec resolves an ambiguity and does not remove a requirement. Added by the critique (finding P2). |
| Minor | missing | User story 6: "As a driver author, I want my driver's default version to be a prerelease that fits my range, so that the driver loads" | FR-001 (driver load), Edge Cases (default version) | The spec has no user story or acceptance scenario for this case. The requirement is in FR-001 and the edge case, and the tasks cover it (T009, T010, T012). |
| Minor | added | "Related pull request to rework: PR #594" (Further Notes) | Out of Scope, last item | The spec lists the rework of #594 as out of scope "beyond what this feature needs". The PRD places it in Further Notes and in Testing Decisions (prior art). This is a scoping sentence taken from the PRD, not a new requirement. |
| Minor | added | none | Assumptions: the Deploy form pins the selected driver version; the control experiment of the issue as evidence | Two assumptions come from reading the repository and the issue, and are labelled with their sources. They do not add a requirement. Added by the critique (findings P4 and E8). |

No requirement, goal or non-goal of the PRD is missing, no semantic change was found, and no acceptance criterion was dropped or softened. The three user journeys (P1 to P3), the six functional requirements, the four success criteria and the five out-of-scope items of the PRD are all in the spec. The spec adds FR-007 (stable versions behave as before, which is the PRD's SC-004 as a requirement) and FR-008 (documentation, glossary and changelog, which are in the PRD's "Documentation" decision). The PRD's three open questions are recorded as assumptions that the plan resolves.

## Action

Proceed to completion. No re-run of the earlier phases is needed. Remediation passes used: 0 of 2.
