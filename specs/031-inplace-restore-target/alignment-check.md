# Alignment Check: Spec 031 Against the PRD of #532

**Date**: 2026-10-19

**Spec**: [spec.md](spec.md) at the commit that adds this report

## Source

- PRD "An in-place restore always restores into the deployment its backup was taken of", a comment on #532: [opsmill/styrmin#532 (comment)](https://github.com/opsmill/styrmin/issues/532#issuecomment-6267704797), last updated 2026-10-19T12:55:05Z. Fetched with `gh api repos/opsmill/styrmin/issues/comments/6267704797`, and fetched again before this check: the text had not changed.
- The issue body of [#532](https://github.com/opsmill/styrmin/issues/532), read for context. The PRD supersedes its "Not decided" line.

## Verdict

⚠️ MINOR DRIFT (proceeding)

Every PRD requirement, user story, acceptance criterion, edge case, success criterion, out-of-scope item and decision is in the spec, with the same meaning. FR-001 to FR-009 keep the PRD's numbering and wording. The spec adds three details that the PRD does not state. Each one expands an existing PRD item and none changes what the PRD decided, so no re-run is needed.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|----------|----------|---------------|----------------|-------------|
| Low | added | FR-007 ("The error MUST say that these options work only with `--last`") | FR-007 | The spec also requires the error to say that a backup is restored into the deployment it was taken of and that the command works without the option. Added by the critique (P4) so that a user whose script breaks after the upgrade knows what to run. |
| Low | added | "Constitution principles", VII (changelog fragments `removed` and `fixed`); Edge cases ("The changelog states this") | FR-011; Edge Cases (client older than the server) | The spec requires the `removed` fragment to also name the refused form `restore <backup id> --target-deployment X` and to say that clients and server must be upgraded together. The PRD states the first as an edge case and says a client that passes the removed arguments fails; the spec adds that a newer client also fails against an older server. Added by the critique (X1). |
| Low | added | "Constitution principles", VII (documentation list) | SC-003 | The spec turns the PRD's documentation list into a measurable criterion: no page or CLI help describes restoring into another deployment's namespace or naming a namespace. |
| Info | added | — | Context; Clarifications (critique) | The spec states, from the code, that `createRestore` accepted any namespace, including one that no deployment owns, and that the agent chart's ClusterRole allows deleting namespaces. It adds no requirement, and asks the maintainer whether a `security` changelog fragment is wanted. The PRD's fragment types are kept. |
| Info | added | — | Clarifications (autonomous) | Three answers not in the PRD, flagged for the maintainer: #531 on `develop` does not change the fix; `--environment` keeps its meaning and is not refused with a backup id; a deployment with no active instance records no target instance. None widens or narrows the PRD's scope. |

Checked with no finding:

- Solution bullets: namespace and instance from the backup's deployment (FR-001, FR-004); `createRestore`, the SDK and the CLI lose the arguments and the option (FR-002, FR-003, FR-006); the CLI refusal and `--last` (FR-007, FR-008); readable fields (FR-005); namespaces differ exactly when deployment ids differ (Clarifications, data model); clients that pass the arguments fail, as for #472 (Assumptions).
- User stories 1 to 6: spec User Stories 1 (PRD stories 1, 4 and 5), 2 (story 2), 3 (story 3) and 4 (story 6).
- P1 journey acceptance criteria: User Story 1 scenario 1, User Story 2 scenario 1, User Story 3 scenario 1.
- FR-009 and the environment clone: User Story 4; the clone keeps its namespace, now from the same function.
- Entities, the five edge cases, SC-001 and SC-002, the assumptions, the four out-of-scope items, and "Open questions: none".
- Tests: unit tests for the restore target resolution and the CLI; the functional GraphQL test as the propagation test; the lifecycle E2E extended with no new E2E node. The plan also runs the other E2E nodes whose calls change, which Constitution §V requires and the PRD does not contradict.
- Governance gates: one GraphQL schema change (approved in the PRD); no database, dependency, CI or authorization change.

## Action

Proceed. No remediation pass was needed (0 of 2 used). The low-severity additions are listed in `pr-notes.md` (task T041) for the maintainer to confirm.
