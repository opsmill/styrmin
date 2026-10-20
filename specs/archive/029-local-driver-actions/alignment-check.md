# Alignment Check: Spec 029 Against the PRD of #372

**Date**: 2026-10-19

## Source

- PRD: [opsmill/styrmin#372, comment 6262219647](https://github.com/opsmill/styrmin/issues/372#issuecomment-6262219647), "PRD: Run the actions of drivers loaded from a local directory", posted 2026-10-19. Fetched with `gh api`.
- Seed issue: [#372](https://github.com/opsmill/styrmin/issues/372), for context.
- Compared against: [spec.md](spec.md) after the critique fixes, with [plan.md](plan.md) and [research.md](research.md) for the implementation decisions.

## Verdict

⚠️ MINOR DRIFT (proceeding)

The spec carries every PRD element:
- the nine user stories and the three journeys with their acceptance criteria;
- FR-001 to FR-006 with their verifications;
- the five edge cases, SC-001 to SC-004 and the four assumptions;
- the out-of-scope list, the seven decisions with their rejected alternatives, and the documentation list.

The PRD's open question is answered in the spec's Clarifications. No PRD requirement is missing, dropped or contradicted. The findings below are additions or clarifications that the code on `develop` required. Each one keeps the PRD's intent.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|----------|----------|---------------|----------------|-------------|
| Minor | added | FR-001 | FR-001, second bullet; Edge Cases | A local load is refused when its path contains `{` or `}` and the driver declares actions. The PRD does not have this. Research R-005 found that Prefect replaces `{{ ... }}` in pull-step inputs with blocks, variables and environment variables, the action token included. The refusal follows the rule ADR-079 set for git driver directories. |
| Minor | added | Journey P3, second acceptance; SC-003 | FR-007; Clarifications | The PRD expects the operator to "run the upgrade again" after loading the driver again. On `develop`, a second request for the same upgrade after a failed one is a no-op (`_update_is_noop`). FR-007 states the outcome the PRD assumes. The plan meets it by checking the hooks before the request writes anything (research R-009), so the deployment is unchanged and the task still fails with a failed hook step, as FR-005 requires. |
| Minor | changed | FR-005: "when the target version declares an upgrade action" | FR-005: "an `upgrade`/`core` action"; Edge Cases; Out of Scope | The spec reads "upgrade action" as the `upgrade`/`core` action, which is the one every bundled driver declares under the name `upgrade`. A target that declares only `upgrade`/`pre` or `upgrade`/`post` keeps today's plain update. No driver in the repository declares that combination, and a follow-up records it. |
| Minor | changed | Journey P1, second acceptance: "upgrades it to a newer version loaded from a local directory" | User story 1, scenario 2 | The spec names a newer application version whose driver version was loaded locally, and states that a change of driver version alone is an update. The flow takes the upgrade path only on an application version change (critique P2). |
| Minor | changed | SC-004 | SC-004; Clarifications | SC-004 is kept word for word. The spec adds that it is checked outside this repository and is not a condition for merging, because spec 029 demo 1 is not in this repository (the PRD's open question). Inside the repository, SC-001 for `infrahub` and the E2E test of user story 1 stand in for it. |
| Minor | added | Implementation decisions: the check in the action's Job | Plan; research R-002 | `run_deployment_or_fail` adds the first error log of a crashed flow run to its error. Without this, the hook step would show only "Process exited with status code: 1", and FR-003 and FR-004 could not name the path, the image and the fingerprints. It also changes the text of other crashed runs, for example an `actions.py` that fails to import. |
| Minor | changed | Implementation decisions: hook resolution "replaces the seven direct lookups" | Plan; research R-007 | Five lookups move to hook resolution. `instantiate_application`, which holds the other two, is deleted instead of migrated: only four unit tests call it, and it cannot run against the real unit of work. |
| Minor | changed | Testing decisions: prefer extending an existing E2E | Plan; research R-011 | The plan adds a new E2E module, `test_local_driver_actions.py`. No existing E2E test deploys a driver loaded from a local directory, and the three journeys change deployments. The module shares one deployment between user stories 1 and 3, and the user story 2 failures stop before Helm runs. |
| Minor | added | — | Edge Cases; Out of Scope | When the check fails during an upgrade, the upgrade cannot be requested again. This is true of every failed upgrade today. The spec records the limitation and a follow-up, and does not change it (critique P5). |

## Action

Proceed. No remediation pass was run; the remediation counter is 0.

The findings above are recorded so that a reviewer of the PRD can confirm them. FR-007 and the brace refusal are the two additions with the most visible effect on users.
