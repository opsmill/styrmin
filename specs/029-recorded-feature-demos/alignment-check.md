# Alignment Check: Spec Against the PRD

**Date**: 2026-10-17

## Source

- PRD: "Recorded demos of four Styrmin features for the beta presentation", [opsmill/styrmin#518 (comment)](https://github.com/opsmill/styrmin/issues/518#issuecomment-6240009049), fetched with `gh api repos/opsmill/styrmin/issues/comments/6240009049` on 2026-10-17.
- Seed issue: [#518](https://github.com/opsmill/styrmin/issues/518), for its three undecided questions.

## Verdict

⚠️ MINOR DRIFT (proceeding)

Every user story, journey, functional requirement (FR-001 to FR-013), success criterion, edge case, testing decision, out-of-scope item and governance gate of the PRD is in the spec with the same meaning. The differences below come from planning research that found two PRD assumptions do not hold; the spec records each one with its evidence and flags it for the maintainer. None removes or softens a PRD requirement.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
| --- | --- | --- | --- | --- |
| Minor | changed | Solution ("All four demos use Infrahub and Semaphore"); Key entities ("The `infrahub` driver backs up its Neo4j database") | Clarifications (planning session); FR-019; User Stories 3 and 4; Key Entities | Demos 3 and 4 deploy Infrahub with the `infrahub-enterprise` driver instead of `infrahub`. The `infrahub` driver's Neo4j backup needs Neo4j Enterprise, and its backup E2E test is skipped as "not supported with community" (research R-007). The demos still use Infrahub and Semaphore; the edition shown changes. Flagged for the maintainer (critique P2). |
| Minor | added | Implementation decisions ("API or interface surface: none"); E2E check added | Clarifications (planning session); Edge Cases; FR-016 unchanged | Research found that a clone probably keeps the source's alias Services (R-013), so the FR-016 check is expected to fail and demo 4 to show two devices in the clone. The spec adds no product change: it records that the defect is reported as a separate issue and that demo 4 and the FR-016 check land after a fix. This adds a delivery dependency the PRD did not foresee. |
| Minor | changed | Demo 1 ("for example 1.10.0"); Implementation decisions ("Playwright … 1.61 or later") | Clarifications (planning session) | The versions file starts at 1.10.11, a later patch of the same minor version than the PRD's example, and Playwright is 1.64, within "1.61 or later" (R-001, R-015). |
| Minor | added | Constitution alignment §VII (guide section; no `docs/`, towncrier or `CONTEXT.md`) | Plan, Constitution Check VII; tasks T045 | The plan adds one paragraph to `dev/knowledge/backend/e2e-testing.md` about the page objects' new typing setting. The PRD's exclusions do not cover `dev/knowledge/`, and Constitution §VII asks for it. |
| None | resolved | Open questions (playbook location; device schema) | Clarifications (second session) | Both answered: the playbook and inventory live in the Semaphore image as a local repository, as the PRD proposed; a small `InfraDevice` schema kept with the demos defines the devices. |
| None | expanded | P1 acceptance ("none of the environments that the demos created remain") | SC-005 | Turned into a success criterion; same meaning. |
| None | expanded | Implementation decisions (page objects for Infrahub and Semaphore; Semaphore image; documentation) | FR-014, FR-015, FR-017, FR-018 | PRD implementation and documentation decisions written as requirements; same meaning. |

## Action

Proceed. No remediation pass was needed (0 of 2 used). The two research findings are flagged in the spec's Clarifications for the maintainer, and task T048 repeats them in the pull request notes.
