# Feature Specification: Rename Backups and Add a Description

**Feature Branch**: `034-backup-rename-description`

**Created**: 2026-11-27

**Status**: Draft

**Input**: GitHub issue [opsmill/styrmin#39](https://github.com/opsmill/styrmin/issues/39), "feat: Add ability to rename backups and add description", including the maintainer comment of 2026-10-16.

## Summary

Operators who keep several backups of one deployment cannot tell them apart. Most backups have the default name `styrmin-<backup id>`, a backup cannot be renamed after it is created, and a backup has no field for a note such as "taken before the 2.0 migration". When the operator restores, they can pick the wrong backup.

This feature lets an operator give a backup a name and a description when they create it, and change both later. The name and the description exist only in Styrmin. The Velero `Backup` object that holds the data keeps a name built from the backup's id, so a rename never changes which Velero object belongs to the backup ([ADR-073](../../dev/adr/0073-kubernetes-objects-named-and-found-by-record-id.md)).

Not decided by the issue and decided here: names are unique per application instance instead of across all backups, and the name template for scheduled backups is deferred because no code runs backup schedules today (see Out of scope).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Rename a backup and edit its description (Priority: P1)

An operator views the backup list of a deployment, finds a backup named `styrmin-9f2c…`, and changes its name to `before-2.0-migration` and its description to "Taken before the schema migration on 2026-11-20. Known good." The new name and description appear in the backup list, in the restore dialog, in the CLI and in the SDK.

**Why this priority**: This is the change the issue asks for. Every existing backup has a name the operator did not choose, and only a rename fixes those.

**Independent Test**: Create a backup with no name, rename it and set a description through the web UI, then view the backup through the API and the CLI. The new name and description are returned, and a restore from the backup still succeeds.

**Acceptance Scenarios**:

1. **Given** a backup named `styrmin-<id>`, **When** the operator renames it to `before-2.0-migration`, **Then** the backup list, the backup detail and every API, SDK and CLI read of the backup show `before-2.0-migration`.
2. **Given** a backup with no description, **When** the operator sets the description, **Then** the backup list shows the description next to the backup.
3. **Given** a backup with a description, **When** the operator sets an empty description, **Then** the backup has no description.
4. **Given** a completed backup that the operator renamed, **When** the operator restores it, **Then** the restore uses the same Velero backup data as before the rename and succeeds.
5. **Given** a backup that is in progress, **When** the operator renames it, **Then** the rename succeeds and the running backup finishes normally.
6. **Given** two backups of the same application instance, **When** the operator renames one to the name of the other, **Then** the rename is rejected with an error that names the conflict, and neither backup changes.
7. **Given** an operator with the read-only role, **When** they try to rename a backup, **Then** the request is rejected and the backup does not change.

---

### User Story 2 - Name and describe a backup when creating it (Priority: P2)

An operator creates an on-demand backup before a risky change and gives it the name `pre-upgrade-3.1` and the description "Before upgrade to driver 3.1". The backup is created with that name and description.

**Why this priority**: Creating with a name already works; adding the description at creation saves the operator a second step.

**Independent Test**: Create a backup with a name and a description from the web UI, from the CLI and from the SDK, and verify both values on the created backup.

**Acceptance Scenarios**:

1. **Given** a deployment, **When** the operator creates a backup with a name and a description, **Then** the backup has that name and that description.
2. **Given** a deployment, **When** the operator creates a backup with no name, **Then** the backup is named `styrmin-<backup id>` as today, and has no description.
3. **Given** an instance that already has a backup named `nightly`, **When** the operator creates another backup of that instance named `nightly`, **Then** creation is rejected with an error that names the conflict and no backup is created.
4. **Given** two different application instances, **When** the operator creates a backup named `nightly` on each, **Then** both backups are created.

---

### User Story 3 - Existing custom-named backups keep working (Priority: P1)

Before this feature, a backup created with a custom name has a Velero `Backup` object with that custom name. After the upgrade, the operator can still restore that backup, and can rename it without losing access to its data.

**Why this priority**: A restore that fails after an upgrade loses the operator's data. This must hold from the first release of the feature.

**Independent Test**: Create a backup with a custom name on the version before this feature (or simulate its record and Velero object), upgrade, then restore it and rename it.

**Acceptance Scenarios**:

1. **Given** a backup that an earlier version created with the custom name `pre-migration`, **When** the operator restores it after the upgrade, **Then** the restore reads the Velero backup named `pre-migration` and succeeds.
2. **Given** the same backup, **When** the operator renames it to `golden`, **Then** a later restore still reads the Velero backup named `pre-migration`.
3. **Given** a backup that an earlier version created with the default name `styrmin-<id>`, **When** the operator restores or renames it, **Then** the restore reads the Velero backup named `styrmin-<id>`.

---

### Edge Cases

- The operator sends a name that is empty or only whitespace: the request is rejected; the backup keeps its name.
- The operator sends a name longer than the maximum length (FR-005): the request is rejected.
- The operator renames a backup to its current name: the request succeeds and nothing changes.
- The operator sends only a description, or only a name: only that field changes.
- The operator renames a backup that does not exist or was deleted: the request returns a not-found error.
- The backup is a constituent of an environment backup: rename and description behave the same as for a standalone backup; the environment backup's own name does not change.
- Two backups of one instance were created before the upgrade with names that are unique across all backups: they are still unique per instance, so no existing data violates the new rule.
- Restores keep their own names; this feature does not change how a restore or its Velero `Restore` object is named.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Operators MUST be able to set an optional name and an optional description when they create an on-demand backup, through the web UI, the GraphQL API, the Python SDK and the CLI.
- **FR-002**: When the operator gives no name, the backup MUST be named `styrmin-<backup id>`, as today.
- **FR-003**: Operators MUST be able to change the name, the description, or both, of an existing backup, through the web UI, the GraphQL API (an `updateBackup` mutation that takes the backup id and an optional name and description and returns the backup), the Python SDK and the CLI. A field that the operator does not send MUST stay unchanged.
- **FR-004**: Sending an empty description MUST remove the description.
- **FR-005**: A backup name MUST be 1 to 255 characters after leading and trailing whitespace is removed. Styrmin MUST store the name without that whitespace. A description MUST be at most 2,000 characters.
- **FR-006**: A backup name MUST be unique among the backups of one application instance. Two backups of different instances MAY share a name. Creating or renaming a backup to a name that another backup of the same instance has MUST be rejected with a typed conflict error that names the existing backup.
- **FR-007**: Renaming a backup or changing its description MUST NOT change, create or delete any Kubernetes object.
- **FR-008**: Every new backup MUST have a Velero `Backup` object named after the backup's id (`styrmin-<backup id>`), whatever name the operator gives it.
- **FR-009**: Every flow that creates or reads a Velero `Backup` object for a backup (the backup flow, the restore flow, and the environment backup and restore flows that use them) MUST find the object by the backup's id, never by the backup's name. For backups that an earlier version created with a custom name, Styrmin MUST keep using the Velero object that already exists under that custom name.
- **FR-010**: Rename and description changes MUST be allowed in every backup status, including pending and in progress.
- **FR-011**: Renaming a backup and changing its description MUST require the same role as creating a backup (read-write). The read-only role MUST be able to view the name and the description.
- **FR-012**: The deployment's backup list in the web UI MUST show each backup's description and MUST offer an edit action that changes the name and the description.
- **FR-013**: The restore dialog and every other place that lists backups for selection MUST show the backup's current name.
- **FR-014**: The user documentation MUST describe how to name, describe and rename a backup, and MUST state that a rename does not change the Velero object.

### Key Entities

- **Backup**: one backup of one application instance. Gains an optional **description**. Its **name** becomes unique per instance instead of across all backups, and becomes a label that only Styrmin shows. Its Velero object name is derived from the backup's id, or, for a backup created with a custom name before this feature, is the name the Velero object already has.
- **Velero Backup object**: the Kubernetes object that holds the backup data. Its name never changes after it is created.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can rename a backup and set its description from the backup list in under 30 seconds, without leaving the deployment page.
- **SC-002**: 100% of restores of renamed backups read the same Velero backup data as before the rename (verified by an end-to-end test that renames a backup and then restores it).
- **SC-003**: 100% of backups created with a custom name before the upgrade can still be restored after the upgrade (verified by a test against a record created the old way).
- **SC-004**: No rename or description change creates, changes or deletes a Kubernetes object (verified by tests).

## Out of scope

- **Name template for scheduled backups.** The issue asks that scheduled backups get names such as `daily-<date>`. Styrmin stores backup schedules, but no code creates a backup from a schedule today (`Backup.schedule_id` is never set). A name template would have no effect until scheduled backups run. This is deferred to the issue that makes schedules create backups; a follow-up issue is recorded in the implementation report.
- Renaming restores, environment backups or environment restores.
- Searching or filtering the backup list by name or description.

## Assumptions

- The maximum name length of 255 characters and description length of 2,000 characters are defaults chosen here; the issue does not give limits.
- The default name stays `styrmin-<backup id>` so that existing scripts that recognise the default name keep working.
- An existing database has no two backups of one instance with the same name, because names are unique across all backups today, so moving to per-instance uniqueness needs no data repair.
- Environment backup constituents keep receiving the default name.
