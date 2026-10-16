# Spec/PRD Alignment Check: Per-Component Replica Counts

**Date**: 2026-10-15 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Tasks**: [tasks.md](tasks.md)

## Source

- PRD "Per-component replica counts", posted as a comment on issue #202: <https://github.com/opsmill/styrmin/issues/202#issuecomment-6187621046>. Fetched with `gh api repos/opsmill/styrmin/issues/comments/6187621046` on 2026-10-15.
- No inline PRD content in the request besides the URL.

## Verdict

⚠️ MINOR DRIFT (proceeding)

Every user story (1 to 15), journey, functional requirement (FR-001 to FR-014), edge case, success criterion (SC-001 to SC-006), assumption and out-of-scope item of the PRD is in the spec. The three PRD open questions are answered in the spec's Clarifications. The drift below is additions that follow from the PRD's own problem statement or decisions, and one extension of the FR-010 rule to values submitted in the same request. None removes or weakens a PRD requirement.

One internal inconsistency was fixed during this check: the plan had created a new E2E module, while the PRD's Testing Decisions and the spec's Clarifications say the E2E extends an existing test that deploys `simple-app`. Research D-012, the plan, the quickstart and tasks T030/T031 now extend `backend/tests/e2e/test_deployment_image_override.py` and reuse its deployment.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|----------|----------|---------------|----------------|-------------|
| Minor | added | FR-011: "mark the database component as singleton" | FR-011; Clarifications (singleton components, critique P2) | The spec also marks `task-manager-db` and `cache` of the `infrahub` drivers as singleton. Both run a standalone stateful service (bitnami PostgreSQL and Redis, `architecture: standalone`) that cannot run 2 replicas; the charts render 1 replica, so no pod count changes. Follows the PRD's problem statement ("nothing would stop a user from scaling such a component by mistake"). |
| Minor | changed | FR-010: "drop a stored parameter value that the target version no longer declares" | Edge cases (submitted retired parameter); research D-007 | The rule also applies to a retired parameter submitted in the same version-change request (for example an old `styrminctl deployments apply` manifest). A default value gives the same result as omitting it; a changed value is still rejected with the parameter and its value. |
| Minor | added | Implementation Decisions: new codes for three rules | Edge cases (override on an undeclared component); contracts/errors.md | A fourth error code, `UNKNOWN_COMPONENT_REPLICA_OVERRIDE`, applies the existing unknown-component rule of the other override kinds to the new slot. FR-009 (orphaned overrides kept) is unchanged. |
| Minor | added | Open question 2; user need 14 | FR-010a | The rejection error must state how to resolve it. Follows from answering open question 2 with "the upgrade dialog does not change". |
| Minor | added | Out of Scope ("no layering"); Governance Gates (same role) | FR-015, FR-016 | Restates two PRD statements as testable requirements. No new scope. |
| Minor | changed | Journey P1 acceptance: `task-worker` from 1 to 3 | US1 acceptance scenario 1: `server` from 1 to 2 | Different example component and count, same behaviour; matches the PRD's E2E scenario (`server` to 2 on `simple-app`). |
| Info | resolved | Open Questions 1 to 3 | Clarifications | 1: infrahub chart 4.33.2 and infrahub-enterprise chart 4.19.2 ship no autoscaler for `server` or `task-worker` (charts pulled and read). 2: the upgrade dialog stays as is; the UI path is two steps, the API/SDK/CLI path one request. 3: the E2E extends `test_deployment_image_override.py` in `shard_configuration` as a dual-entrypoint node (CI runs its UI variant); the infrahub upgrade is covered by functional tests, not on the infrahub shard. |
| Info | added | — | Out of Scope | Records the two decisions from open questions 2 and 3 as out of scope (upgrade dialog change, infrahub-shard E2E). |

## Action

Proceed. No remediation pass. The minor drift items are recorded here and in the spec's Clarifications so the reviewer can reverse any of them:

- To keep FR-011 exactly as the PRD wrote it, remove `singleton: true` from `task-manager-db` and `cache` in tasks T046 and T047 and the matching assertions in T039.
- To limit FR-010 to stored values only, drop the "resubmits `p: 5`" case in T038 and restrict `drop_retired_parameters` to keys of the stored map in T044.
