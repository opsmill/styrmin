# Feature Specification: Environment-Level Backup and Restore

**Feature Branch**: `001-env-backup-restore`  
**Created**: 2026-04-04  
**Status**: Draft  
**Input**: User description: "feat: Environment-level backup and restore operations — Add the ability to back up and restore an entire environment as a single coordinated operation."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create Environment Backup (Priority: P1)

A platform operator managing a multi-application environment (e.g., a full staging stack with 5+ deployments) wants to capture a point-in-time snapshot of all applications at once. They initiate a single environment-level backup operation, which automatically creates individual backups for every active application instance in that environment. The operator can monitor the overall progress and see which individual backups have completed, are in progress, or have failed.

**Why this priority**: This is the core capability — without the ability to create an environment backup, no other stories deliver value. It directly addresses the primary pain point of manually triggering individual backups one-by-one.

**Independent Test**: Can be fully tested by creating an environment backup for an environment with multiple deployments and verifying that individual backups are created for each active application instance. Delivers immediate value by reducing a multi-step manual process to a single operation.

**Acceptance Scenarios**:

1. **Given** an environment with 3 active deployments (each with an active application instance), **When** the operator creates an environment backup, **Then** a single EnvironmentBackup record is created with status PENDING, and 3 individual Backup records are created — one per active application instance — each linked to the EnvironmentBackup.

2. **Given** an environment backup has been created, **When** all constituent backups complete successfully, **Then** the EnvironmentBackup status transitions to COMPLETED and records a completion timestamp.

3. **Given** an environment backup is in progress, **When** one constituent backup fails, **Then** the EnvironmentBackup status transitions to PARTIALLY_FAILED, the error details are captured, and all other constituent backups continue to completion.

4. **Given** an environment backup is in progress, **When** all constituent backups fail, **Then** the EnvironmentBackup status transitions to FAILED.

5. **Given** an environment with no active deployments (or no active application instances), **When** the operator attempts to create an environment backup, **Then** the system returns an error indicating there are no active instances to back up.

6. **Given** an environment with an active deployment that already has an in-progress backup, **When** the operator creates an environment backup, **Then** the system skips that instance (does not create a duplicate backup) and proceeds with the remaining instances, noting the skipped instance in the EnvironmentBackup metadata.

---

### User Story 2 - Restore Environment from Backup (Priority: P2)

A platform operator needs to recover an entire environment to a known-good state after an incident. They select a previously completed environment backup and initiate a restore operation. The system triggers individual restore operations for each constituent backup, restoring all applications in the environment to their backed-up state.

**Why this priority**: Restore is the second half of the backup/restore lifecycle. Without restore, backups have limited value. However, creating backups is a prerequisite, so restore is P2.

**Independent Test**: Can be tested by restoring from a completed environment backup and verifying that individual restores are created for each constituent backup. Delivers value by enabling single-action environment recovery.

**Acceptance Scenarios**:

1. **Given** a completed EnvironmentBackup with 3 constituent backups, **When** the operator initiates an environment restore, **Then** an EnvironmentRestore record is created with status PENDING, and 3 individual Restore records are created — one per constituent backup — each targeting the original application instance's namespace.

2. **Given** an environment restore is in progress, **When** all constituent restores complete successfully, **Then** the EnvironmentRestore status transitions to COMPLETED.

3. **Given** an environment restore is in progress, **When** one or more constituent restores fail, **Then** the EnvironmentRestore status transitions to PARTIALLY_FAILED, capturing error details for each failed restore while allowing successful restores to remain.

4. **Given** an EnvironmentBackup with status FAILED (no constituent backups completed), **When** the operator attempts to restore from it, **Then** the system returns an error indicating the backup cannot be restored.

5. **Given** an EnvironmentBackup with status PARTIALLY_FAILED (some constituent backups completed), **When** the operator initiates a restore, **Then** the system restores only the successfully completed constituent backups and notes which applications could not be restored.

---

### User Story 3 - View Environment Backup Status and History (Priority: P3)

A platform operator wants to view the history of environment-level backups for a given environment and inspect the details of a specific environment backup, including the status of each constituent backup and any errors.

**Why this priority**: Visibility into backup state is important for operational confidence, but the core create/restore operations must exist first.

**Independent Test**: Can be tested by listing environment backups for an environment and viewing details of a specific backup. Delivers value by providing operators with a clear audit trail.

**Acceptance Scenarios**:

1. **Given** an environment with 5 past environment backups, **When** the operator queries the environment backup list, **Then** all 5 EnvironmentBackup records are returned with their status, creation time, and constituent backup count.

2. **Given** a specific EnvironmentBackup, **When** the operator queries its details, **Then** the response includes the EnvironmentBackup metadata plus a list of all constituent backups with their individual statuses.

3. **Given** an environment with no environment backups, **When** the operator queries the list, **Then** an empty list is returned.

---

### User Story 4 - Delete Environment Backup (Priority: P4)

A platform operator wants to delete an environment backup that is no longer needed. Deleting the environment backup removes the parent record and all associated constituent backups and their restores.

**Why this priority**: Cleanup is a supporting operation. It's needed for hygiene but doesn't deliver primary value.

**Independent Test**: Can be tested by deleting an environment backup and verifying that all constituent backups and restores are also removed.

**Acceptance Scenarios**:

1. **Given** a completed EnvironmentBackup with 3 constituent backups (one of which has 2 restores), **When** the operator deletes the EnvironmentBackup, **Then** the EnvironmentBackup record, all 3 constituent Backup records, and all associated Restore records are deleted.

2. **Given** an EnvironmentBackup with an in-progress constituent backup, **When** the operator attempts to delete it, **Then** the system returns an error indicating the backup cannot be deleted while operations are in progress.

---

### User Story 5 - End-to-End Backup and Restore Verification (Priority: P5)

The development team needs end-to-end tests that verify the complete environment backup and restore lifecycle, ensuring that the feature works correctly across the full stack (API, service layer, orchestration).

**Why this priority**: E2E tests validate the integration of all components and catch issues that unit tests cannot. They are critical for confidence in the feature but depend on all other stories being implemented first.

**Independent Test**: Can be tested by running the E2E test suite which exercises create backup, monitor status, restore from backup, and cleanup operations through the styrmin SDK (matching existing E2E test patterns in `backend/tests/e2e/`).

**Acceptance Scenarios**:

1. **Given** a test environment with multiple deployments, **When** the E2E test suite runs, **Then** it successfully creates an environment backup, verifies all constituent backups are created, and confirms the environment backup reaches COMPLETED status.

2. **Given** a completed environment backup in the test environment, **When** the E2E test suite initiates a restore, **Then** it verifies all constituent restores are created and the environment restore reaches COMPLETED status.

3. **Given** the E2E test suite, **When** it simulates a partial failure scenario (e.g., one instance backup fails), **Then** it verifies the environment backup correctly transitions to PARTIALLY_FAILED and the error details are captured accurately.

---

### Edge Cases

- What happens when a new deployment is added to the environment while an environment backup is in progress? The backup only includes instances that existed at the time the backup was initiated.

- How does the system handle an environment where some deployments do not have backup-capable components (no backup config in their driver version)? Those deployments are skipped and noted in the EnvironmentBackup metadata.

- What happens if the environment's backup storage location is not configured? The system returns an error before creating any backup records, since all constituent backups share the same BSL.

- What happens if an environment restore is attempted while another environment restore from the same backup is already in progress? The system rejects the request to prevent conflicting restore operations.

- What happens when the operator deletes a constituent backup directly (not via the environment backup)? The individual backup is deleted; the EnvironmentBackup record retains a reference but marks that constituent as missing/deleted.

- What happens if an environment backup exceeds the overall timeout? The EnvironmentBackup transitions to FAILED, any still-running constituent backups are cancelled, and the timeout is recorded in the error details.

## Clarifications

### Session 2026-04-04

- Q: What interfaces should this feature expose? → A: GraphQL API + CLI + Frontend UI
- Q: Should EnvironmentBackup status be computed or stored? → A: Stored as a column, updated when each constituent backup completes/fails
- Q: Should there be a maximum number of concurrent constituent backups? → A: Configurable limit with sensible default (e.g., max 5 concurrent)
- Q: How should the system handle constituent backup timeouts? → A: Overall environment backup timeout (entire operation fails if exceeded)
- Q: Should environment backups support user-provided metadata? → A: Optional name field only (short label, max 128 chars)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow creating an environment-level backup that automatically initiates individual backups for all active application instances in the specified environment.

- **FR-002**: System MUST create a parent EnvironmentBackup record that links to all constituent Backup records created during the operation.

- **FR-003**: System MUST derive the overall EnvironmentBackup status using the following rules:
  - **PENDING**: Set at creation time, before the orchestration workflow starts.
  - **IN_PROGRESS**: Set when the orchestration workflow begins dispatching constituent backups. Remains IN_PROGRESS while any constituent is PENDING or IN_PROGRESS, regardless of how many have already completed or failed.
  - **COMPLETED**: All constituent backups reached COMPLETED.
  - **PARTIALLY_FAILED**: All constituents have a terminal status (COMPLETED or FAILED) and at least one of each.
  - **FAILED**: All constituent backups FAILED, or the overall timeout was exceeded.

- **FR-004**: System MUST allow restoring an entire environment from a completed or partially-completed EnvironmentBackup by creating individual restore operations for each successfully completed constituent backup.

- **FR-005**: System MUST create a parent EnvironmentRestore record that links to all constituent Restore records created during the operation.

- **FR-006**: System MUST derive the overall EnvironmentRestore status from the aggregate status of its constituent restores, using the same aggregation logic as EnvironmentBackup.

- **FR-007**: System MUST allow querying environment backups by environment, including filtering by status.

- **FR-008**: System MUST allow querying the details of a specific environment backup, including all constituent backup statuses.

- **FR-009**: System MUST allow deleting an environment backup, which cascades to delete all constituent backups and their associated restores.

- **FR-010**: System MUST prevent deletion of an environment backup while any constituent operation (backup or restore) is in progress.

- **FR-011**: System MUST skip application instances that already have an in-progress backup when creating an environment backup, recording the skipped instances in the EnvironmentBackup metadata.

- **FR-012**: System MUST reject environment backup creation if the environment has no backup storage location configured.

- **FR-013**: System MUST reject environment backup creation if the environment has no active application instances to back up.

- **FR-014**: System MUST reuse existing individual backup and restore logic without duplicating backup strategy implementations.

- **FR-015**: System MUST provide end-to-end tests that verify the complete environment backup and restore lifecycle through the styrmin SDK (which exercises the full stack including the GraphQL API). E2E tests MUST NOT use raw GraphQL calls.

- **FR-016**: Feature MUST be exposed via three interfaces: GraphQL API (mutations and queries), CLI commands (`styrmin env backup` / `styrmin env restore`), and Frontend UI (environment detail page with backup/restore actions).

- **FR-017**: System MUST enforce a configurable maximum concurrency limit for constituent backup operations within a single environment backup (default: 5). Excess backups MUST be queued and started as running ones complete.

- **FR-018**: System MUST enforce a configurable overall timeout for environment backup operations. If the timeout is exceeded, the entire EnvironmentBackup transitions to FAILED and any still-running constituent backups are cancelled.

### Key Entities

- **EnvironmentBackup**: A parent record representing a coordinated backup of all active application instances in an environment at a point in time. Links to the source Environment and contains references to all constituent Backup records. Tracks overall status (stored as a persistent column, updated via callback when each constituent backup completes or fails), timestamps, an optional user-provided name (max 128 chars), and metadata (e.g., skipped instances, initiator).

- **EnvironmentRestore**: A parent record representing a coordinated restore operation from an EnvironmentBackup. Links to the source EnvironmentBackup and contains references to all constituent Restore records. Tracks overall status and timestamps.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Platform operators can back up an entire environment with a single operation instead of initiating individual backups for each application (reduction from N operations to 1, where N is the number of active deployments).

- **SC-002**: Platform operators can restore an entire environment to a known-good state with a single operation instead of manually restoring each application individually.

- **SC-003**: Environment backup status accurately reflects the aggregate state of all constituent backups at all times — operators never need to manually check individual backups to understand overall progress.

- **SC-004**: No existing individual backup or restore behavior is modified — all current single-application backup and restore operations continue to work identically.

- **SC-005**: End-to-end tests cover the full lifecycle: environment backup creation, status tracking, environment restore, partial failure handling, and cleanup (deletion).

## Assumptions

- The existing Velero-based backup infrastructure and Prefect workflow orchestration remain unchanged. Environment-level operations compose on top of existing per-instance backup/restore flows.

- Environment backups use the environment's already-configured BackupStorageLocation. No new storage configuration is needed.

- The "active application instance" for each deployment is the instance targeted for backup. Deployments without an active instance are skipped.

- Constituent backups are initiated concurrently (not sequentially) for performance, with a configurable concurrency limit (default: 5 concurrent constituent backups). The system does not guarantee ordering between individual backup operations.

- Environment restore targets the original namespaces of each constituent backup (same-environment restore). Cross-environment restore is out of scope for this feature.
