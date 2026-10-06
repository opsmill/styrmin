# Alignment Check: spec.md against the PRD

**Feature**: [spec.md](spec.md) | **Date**: 2026-10-06

## Source

- PRD: "Steps and failure causes for tasks, backups and restores", [opsmill/styrmin#2 (comment)](https://github.com/opsmill/styrmin/issues/2#issuecomment-6012882649), fetched with `gh issue view 2 --repo opsmill/styrmin` on 2026-10-06.
- Seed issue body: [opsmill/styrmin#2](https://github.com/opsmill/styrmin/issues/2), used for context only. The PRD supersedes it.

## Verdict

⚠️ MINOR DRIFT (proceeding)

Every PRD goal, user story, functional requirement, success criterion, out-of-scope item and assumption is in the spec with the same meaning. The PRD's two open questions are answered in the spec and labelled as recommendations. The additions are clarifications that the PRD's own acceptance scenarios need once the current code is known; each is labelled with its basis. One missing sentence (the operator status output gate) was added during this check.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| Minor | added (necessary clarification) | Open questions: output size, retention | FR-003, FR-016 | The PRD left both open. The spec answers them (last 200 lines and 64 KiB; kept as long as the parent record) and labels both as recommendations, the second based on the PRD's own [CLAUDE RECOMMENDED] assumption. |
| Minor | added (necessary clarification) | P1 journey ("for any task type … create, update, upgrade, stop components, start components, run a job, and delete"); P1 acceptance ("they view the upgrade") | FR-019 | Every reconcile task is stored as `noop` today, so users cannot find "the upgrade". FR-019 makes the types the PRD lists visible. Labelled. |
| Minor | added (necessary consequence) | P1 acceptance (HelmRelease not Ready after an upgrade → `FAILED`); SC-003 | Dependencies (operator readiness); Context | The operator reports updates ready without waiting for FluxCD, so the acceptance scenario cannot pass without changing it. Consequence visible to users: after an update a deployment reaches `RUNNING` only when FluxCD reports the new release Ready, and a failed update ends `FAILED`. Labelled; this fixes the PRD's own problem statement ("a task can show `SUCCESS` while the HelmRelease fails"). |
| Minor | changed (implementation note) | Implementation decisions: "Backup and restore flows … write their steps through the step recorder directly, because they run as `INTERNAL` flows" | Assumptions (backup and restore flows) | The restore steps and per-component backup work run in the cluster flow, which has no database access. Those parts write with the action token, as FR-014 already requires of Prefect flows. Labelled. Requirements FR-013 and FR-014 are unchanged. |
| Minor | added (clarification) | Edge case "A later task interrupts the operator phases"; FR-006 | Edge case "Tasks started by the same hook interrupt each other" | Spells out how FR-006 applies when the tasks one hook started supersede each other. Consistent with the PRD's rule "`SUPERSEDED` if it did not start the later task". |
| Minor | added (clarification) | Assumption "The agent reports every 5 seconds, and the deployment page refreshes every 10 seconds" | Assumptions | States that the 15 seconds of FR-005 and SC-002 start when the change is recorded, and that the operator checks FluxCD every 60 seconds. SC-002's wording is unchanged. |
| Minor | added (from PRD sections) | Implementation decisions ("Service-layer errors", "Drivers and reconciliation"); P2 acceptance | FR-017, FR-018, SC-005 | Restate PRD implementation decisions and the P2 acceptance scenario as testable requirements. |
| Minor | missing → fixed | Governance gates: "The FluxCD reason change also changes the operator's status output." | Governance Gates Crossed | The sentence was missing and was added during this check. |

Plan-level notes (not spec drift, recorded for reviewers):

- `recordStep` additionally accepts only the built-in `styrmin-actions` user ([research.md](research.md) D14). FR-014's `READ_WRITE` requirement still holds.
- The status reporter sends the instance the operator handled (`status.instanceId`) in the existing `instanceId` field; the report's GraphQL input is unchanged, as the PRD recommends ([research.md](research.md) D4).

## Action

Proceed. No remediation pass was needed (0 of 2 used). The fixed governance sentence is committed with this report.
