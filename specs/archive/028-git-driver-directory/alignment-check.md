# Alignment Check: Spec 028 against the PRD

**Date**: 2026-10-17

## Source

- PRD: "Load an application driver from a driver directory of a git repository", [opsmill/styrmin#517 (comment)](https://github.com/opsmill/styrmin/issues/517#issuecomment-6236268970), fetched with `gh issue view 517 --json comments`.
- Issue body of [#517](https://github.com/opsmill/styrmin/issues/517), for the code references.

## Verdict

⚠️ MINOR DRIFT (proceeding)

Every PRD user story, functional requirement, success criterion, edge case and out-of-scope item is in the spec, with the same meaning. The differences are a renamed UI surface that does not exist under the PRD's name, details added to two requirements, and two requirements added by research and critique. None changes what an admin can do or removes a PRD constraint.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
| --- | --- | --- | --- | --- |
| Minor | changed | User story 5, FR-005: "the Source tab MUST show it" | Clarifications (fourth item), FR-005, US2-3 | The driver detail page has no Source tab; the source rows are on the Overview tab. The spec shows the driver directory in a "Driver directory" row of the Overview tab. Same outcome on the surface that exists. |
| Minor | added | FR-005 (Source tab only); "Frontend surface: one new field in the drawer, and one display change on the Source tab" | FR-005, US2-6 | The drivers list's Source cell also shows the driver directory (critique P2), so an admin can tell apart two versions from one repository and commit, which PRD user story 5 asks for. A second display change. |
| Minor | added | — | FR-010, US1-6, Clarifications (fifth item) | Two driver versions from different driver directories at one commit keep separate actions. Research R-003 found that the current Prefect deployment naming would let the second load replace the first's actions, which would break PRD user stories 4 and 5. A necessary requirement, not a scope change. |
| Minor | added | FR-006: removes a leading `./` and a trailing `/`, treats `""` and `.` as the root | FR-006 | Also removes surrounding whitespace, empty segments and `.` segments, so the PRD's "one form" holds for `drivers//infrahub` and `drivers/./infrahub`. Expansion of detail. |
| Minor | added | FR-007: absolute path, `..` segment, backslash | FR-007 | Also refuses a NUL character, which the operating system cannot open. Expansion of detail. |
| Minor | added | "Testing Decisions: One assertion on the stored driver directory is added to an existing test" | Plan Design §8, tasks T027, T035 | The plan adds the `sourcePath` check and a pull-step check to `test_driver_version_reselection`, and an Overview-row check to `test_driver_detail_inspects_versions_via_tabs`. More coverage on the same reused fixtures; no new test node, as the PRD asks. |
| Minor | changed | Assumptions: "The existing `set_directory` pull step can set the working directory for driver actions." | Assumptions; research R-002 | Prefect's `set_working_directory` step can, but Styrmin's `set_directory_pull_step` helper writes `/opt/prefect/…`, which does not exist in the default action image (`WORKDIR /source`). The plan changes the helper to a relative path. The assumption's intent holds. |
| Info | resolved | Open question: ADR for FR-004 and FR-008 | Clarifications (third item), Documentation | Resolved as the PRD recommends: one short new ADR. |
| Info | resolved | "Its name is not decided yet"; "Whether a new error code is needed is not decided yet" | Clarifications (first and second items) | `driverDirectory` (glossary term); no new error code. |

No PRD requirement, goal, non-goal or acceptance criterion is missing, dropped, softened or contradicted.

## Action

Proceed. No remediation pass was run (0 of 2 used).
