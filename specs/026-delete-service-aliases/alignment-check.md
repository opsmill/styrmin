# Alignment Check: Deleting a Deployment Deletes Its Service Aliases

## Source

- PRD: "Design brief for the fix", [opsmill/styrmin#503 (comment)](https://github.com/opsmill/styrmin/issues/503#issuecomment-6226003710), fetched with `gh api repos/opsmill/styrmin/issues/comments/6226003710` on 2026-10-16.
- Context: the body of [#503](https://github.com/opsmill/styrmin/issues/503).

## Verdict

⚠️ MINOR DRIFT (proceeding)

Every decision, expected result, requirement, test, documentation item and exclusion of the brief is in [spec.md](spec.md). The spec states two of the brief's rules more precisely, because research and critique showed that the brief's wording cannot be met as written or would break restores. It also answers the brief's one open question. None of these changes the brief's intended outcome; two are flagged for the maintainer.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
| --- | --- | --- | --- | --- |
| Minor | changed | Decision 4; "Expected result when another deployment's flow runs during the deletion" | FR-007, FR-008; Clarifications (planning, critique) | The brief says the flow "writes no alias of A's services, writes nothing into `styrmin-<A id>`". A read and a write cannot be atomic, so the spec says the flow writes nothing for a deployment whose deletion it can read, deletes what it wrote just before it could read the request, and never creates another deployment's namespace. The outcome the brief expects holds: no alias of A remains, and A's namespace is not created again. The brief leaves the mechanism to the plan. |
| Minor | added | Decision 7; "Other cases", `kubectl delete styrmindeployment` | FR-017; edge case "A restore deletes and restores a deployment's namespace"; research R-011 | Not in the brief. A restore's namespace deletion runs the delete handler's teardown; without the guard, the new step would delete a running deployment's aliases, which Velero does not restore. The `kubectl delete` case of the brief still deletes the aliases while the namespace is not being deleted. Flagged for the maintainer (tasks T037). |
| Minor | added | "Not decided" | Clarifications (brief session, last item); FR-014 last item; tasks T005 | The brief asks whether to add a unit test for an alias that a deployment's own Service replaces. The spec answers yes, as a unit test of `apply_service`. Flagged for the maintainer. |
| Minor | added | — | User Story 2 scenario 6; `changelog/503.fixed.md` text (T033) | A consequence of the flow guard: another deployment's change no longer fails while the deleted deployment's namespace is being deleted. Stated so users learn of it; it adds no work beyond the brief's decision 4. |
| Minor | added | Decision 2 | Clarifications (planning); research R-001 | The teardown also checks that the CR's namespace is `styrmin-<spec.deploymentId>`, a second guard next to decision 7 for the copy of a source's CR that a cross-target restore deletes. A design detail; no change of scope. |

No requirement, goal, exclusion or acceptance criterion of the brief is missing, dropped, softened or contradicted.

## Action

Proceed. No remediation pass was needed (0 of 2 used). The two items flagged for the maintainer are listed in tasks T037 for the pull request notes.
