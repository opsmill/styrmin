# Spec/Ask Alignment Check: Update a Cluster's Config in Place

**Date**: 2026-10-12

## Source

- PRD "Update a cluster's config in place", fetched with `gh api` from [opsmill/styrmin#423 (comment)](https://github.com/opsmill/styrmin/issues/423#issuecomment-6123640046). No inline PRD content besides the link.
- Compared against [spec.md](spec.md) after the critique fixes (commit `504c2d2b`).

## Verdict

⚠️ MINOR DRIFT (proceeding)

Every PRD requirement (FR-001 to FR-010), user story (1 to 14), acceptance scenario, success criterion (SC-001 to SC-004), assumption and out-of-scope item is present in the spec with the same meaning. The differences are corrections, answers to the PRD's open questions, and one side effect on the environment update that the user should know about (finding 3).

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| Minor | changed | FR-008, Error handling ("`INVALID_CONTEXT`") | FR-008, US1 scenario 8, Clarifications | The PRD names the invalid-config error code `INVALID_CONTEXT`. In the code, `InvalidContextError` has the code `VALIDATION_ERROR`; `INVALID_CONTEXT` appears only in comments. The spec keeps the PRD's meaning (the same error as `createCluster`) and uses the real code. |
| Minor | changed | FR-004, user stories 7 and 8 ("created … first, then the applications are redeployed") | FR-004, SC-005, Clarifications | The PRD's "first … then" could mean dispatch order or readiness order. The spec reads it as readiness order (the controller is `RUNNING` before the applications move; it is removed after their redeploys finish), because the PRD gives "so that the applications stay reachable" as the reason. This is stricter than dispatch order and adds SC-005. |
| Minor | added | Out of scope ("`updateEnvironment` neither creates, redeploys nor removes the controller … needs a separate issue") | Edge cases, Out of Scope | The controller removal rule depends only on stored state, so it also acts after an environment update: when an environment turns its own `dedicated_ingress` off, its controller is now removed after its applications move to the shared class (today it stays until the last application is deleted). Creation and redeploy after an environment update stay out of scope. The spec, plan, ADR-0066 task and changelog task state this change. **Review recommended**: if this side effect is not wanted, the removal rule needs a persisted marker of cluster-triggered changes, which the plan rejected (research D4, D5). |
| Minor | added | Open question ("failed or being removed controller") | Clarifications, US2, edge cases | The PRD left this open. The spec answers it: applications already on a failed controller are redeployed; applications that would move onto a controller wait until it is ready; a failed new controller is retried on resubmission; no second controller while one is being removed. |
| Minor | added | — | US3 scenario 2 | A user without `ADMIN` views the cluster config and cannot edit it on the detail page. Follows from PRD FR-009 and user story 13. |
| Minor | added | — | Edge cases, Out of Scope | A cluster `scheduling` change starts no redeploy, because the current resolution does not read the cluster's `scheduling`. Fact from the code, not a new behaviour. |
| Minor | changed | Actor "operator" | Context | The spec calls the human actor "administrator" (a user with the `ADMIN` role), because CONTEXT.md reserves "operator" for the kopf operator. Same people and the same permission. |

No PRD requirement, goal, non-goal, acceptance criterion or constraint is missing, softened or contradicted.

## Action

Proceed to Completion. No remediation pass was run (counter: 0 of 2). Finding 3 is listed in the Completion summary for the user's review before implementation.
