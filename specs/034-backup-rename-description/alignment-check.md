# Alignment Check: Rename Backups and Add a Description

## Source

- [opsmill/styrmin#39](https://github.com/opsmill/styrmin/issues/39): the issue body with its eight acceptance criteria, and the [maintainer comment of 2026-10-16](https://github.com/opsmill/styrmin/issues/39#issuecomment-6225664591). Fetched with `gh issue view 39` on 2026-11-27.
- Compared against: [spec.md](spec.md), commit `ef528f94`, and the later plan, critique and tasks commits.

## Verdict

⚠️ MINOR DRIFT (proceeding)

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|----------|----------|---------------|----------------|-------------|
| Minor | dropped (deferred, with reason) | Acceptance criterion: "Scheduled backups should support a name template/prefix so auto-created backups get meaningful names (e.g., `daily-<date>`)" | Out of scope; research R10; tasks T041 | The spec defers the template. Styrmin stores `BackupSchedule` records, but no code creates a backup from a schedule: `Backup.schedule_id` and `BackupSchedule.prefect_deployment_id` are never written. The issue's condition, "auto-created backups", does not occur in the product today, so a template field would have no effect and could not be tested end to end. Meeting this criterion would mean building schedule execution, which the issue does not ask for. The user should confirm the deferral; a follow-up is recorded for the implementation report. |
| None | added (necessary) | Acceptance criterion "Velero CRD name … must remain unchanged"; maintainer comment on ADR-073 | FR-009, User Story 3, research R1 | The spec adds a migration that keeps the existing Velero name for backups created with a custom name before this feature. Without it, those backups could not be restored after the upgrade. This follows from the issue's constraint and from the maintainer comment. |
| None | added (necessary) | Maintainer comment (ADR-073) | research R2 | New Velero `Backup` objects get the label `styrmin.io/backup-id`, which ADR-073 requires for every object Styrmin creates. |
| None | added (expansion of detail) | Acceptance criteria 1 and 2 (name and description at creation) | FR-001, research R7 and R8 | The web UI gets a create dialog, the CLI gets `--description` and `update`, and the SDK gets `update_backup`. The issue names only GraphQL and the backup list. AGENTS.md requires that changes reach every surface, so this is not drift. |
| None | clarified | Acceptance criterion: "Backup names remain unique per instance" | FR-006, research R3 | Uniqueness changes from all backups to each application instance, as the issue states. The maintainer comment warned that this would let two backups share a Velero name. The spec removes that risk by naming Velero objects after the backup's id (FR-008). |
| None | clarified | Issue context: `service.py:99-100` placeholder naming | Summary, FR-002 | The maintainer comment says the issue describes older code. The spec uses the current behaviour: the name given, or `styrmin-<id>`. |

The other acceptance criteria are covered without drift:

- custom name at creation: FR-001;
- description at creation: FR-001;
- the `updateBackup(backupId, name, description): Backup` mutation: FR-003 and contracts/graphql.md;
- the name is shown only in Styrmin and the Velero name is unchanged: FR-007, FR-008 and FR-009;
- the backup list has an edit action and shows the description: FR-012;
- names are unique per instance: FR-006;
- `description` is added to the Backup model: data-model.md.

## Action

Proceed to implementation. No remediation pass was run (counter: 0).

The deferral of the scheduled-backup name template is the only open difference from the issue. It is reported in the completion summary so that the user can reverse it before merging.
