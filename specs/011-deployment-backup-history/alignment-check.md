# Spec/Ask Alignment Check: Keep a Deployment's Backup History When It Gets a New Instance

**Date**: 2026-10-08
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Tasks**: [tasks.md](tasks.md)

## 1. Source

- PRD: [opsmill/styrmin issue #304, comment 6070292805](https://github.com/opsmill/styrmin/issues/304#issuecomment-6070292805), fetched with `gh api` on 2026-10-08. It was confirmed in a review session on 2026-10-08 and references commit `a2a627d3` on `develop`.
- Context: the issue body of [#304](https://github.com/opsmill/styrmin/issues/304), which describes the upgrade case only. The PRD widens it to four operations.

## 2. Verdict

⚠️ MINOR DRIFT (proceeding)

Every PRD requirement, user story, journey, edge case, success criterion, implementation decision, testing decision, out-of-scope item and open question is present in the spec, the plan or the tasks. The findings below are decisions the PRD does not state, taken to make the spec testable, plus one wording error that was fixed in this phase. None removes, softens or contradicts a PRD requirement.

## 3. Findings

| Severity | Category | PRD reference | Spec reference | Description |
|----------|----------|---------------|----------------|-------------|
| Low (fixed) | changed | Problem: "an upgrade: `update_deployment_version`" | Problem, first bullet | The spec said "an upgrade to a new driver version". `update_deployment_version` changes the application version and rebinds the driver version. Changed to "an upgrade to a new application version" in this phase. |
| Low | added | FR-004: "`--instance-id` MUST keep listing the backups of one instance" | FR-004 | The spec adds that `restore --last --target-instance-id` keeps choosing from that instance's backups, because no deployment is named (critique P4). The PRD does not cover this case. It follows the PRD's own rule for `--instance-id`. |
| Low | added | FR-003 (no rule for an unknown `deploymentId`) | contracts/graphql.md, research R4 | `backups(deploymentId:)` with an id that matches no deployment returns `[]`, as `backups(instanceId:)` and `backupSchedules(deploymentId:)` do today. The PRD does not specify it. |
| Low | added | Testing decisions, E2E scenario | research R9, tasks T028 | The E2E extension also re-reads the active instance id before the backup, which fixes the stale-instance problem the PRD describes in "The existing E2E test hides this bug today". The existing restore and delete steps then run against a backup of an earlier instance. The PRD asks only that the backup is still listed with its application version. |
| Low | added | FR-002: "MUST show ... the application version" | contracts/ui.md | The Backups tab column is labelled "Application version", so it is not read as the driver version shown in the page header (critique P3). |
| Info | added | Constitution alignment, VII (documentation list) | research R11, task T040 | `dev/knowledge/backend/backup-restore.md` is added to the documentation list, because it documents the `backups(instanceId: UUID!)` signature. Required by Constitution §VII. |
| Info | added | Testing decisions: "A backend integration test" | research R8, task T016 | The integration test lives in `backend/tests/functional/graphql/`, not `backend/tests/integration/`, because the latter holds Kubernetes-backed agent tests. `refresh_deployment` has no caller on this branch, so the test calls it at the service layer (research R2). |

No PRD requirement is missing, no requirement's meaning changed, no acceptance criterion was dropped or softened, and no PRD constraint is contradicted.

### Coverage map

| PRD item | Where it is covered |
|----------|---------------------|
| User stories 1, 2, 3, 4, 5 | spec US1 scenarios 1 to 4, FR-001, FR-002 |
| User story 6, journey P2 | spec US2, FR-004 |
| User stories 7, 8 | spec US3, FR-003, SC-004 |
| User story 9 | spec US4, FR-006 |
| FR-001 to FR-005 | spec FR-001 to FR-005 |
| Edge cases (6) | spec Edge Cases, FR-007, FR-008 |
| SC-001 to SC-004 | spec SC-001 to SC-004 |
| Implementation decisions | plan "Design", research R1 to R7 |
| Testing decisions | research R8, R9; tasks T004, T007, T011, T016 to T018, T028, T029, T030, T033 |
| Constitution alignment and documentation | plan "Constitution Check"; tasks T037 to T042 |
| Governance gates | plan "Constitution Check" |
| Assumptions | spec Assumptions |
| Out of scope (6 items) | spec Out of Scope |
| Open questions (2) | spec "Open Questions Carried From the PRD" |

## 4. Action

Proceed. The one wording error was fixed in `spec.md` in this phase. The remaining findings are clarifications recorded in research and the contracts, so the reviewer can confirm them. No remediation pass was needed (0 of 2 used).
