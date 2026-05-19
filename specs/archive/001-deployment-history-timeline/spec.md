# Feature Specification: Deployment History Timeline with Change Tracking

**Feature Branch**: `001-deployment-history-timeline`  
**Created**: 2026-04-03  
**Status**: Extracted  
**Input**: GitHub Issue [opsmill/styrmin#3](https://github.com/opsmill/styrmin/issues/3)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Deployment Operation Timeline (Priority: P1)

As a platform operator, I want to see a chronological timeline of all operations performed on a deployment so that I can understand its lifecycle and troubleshoot issues.

From the deployment detail page, I navigate to a history section and see a list of all tasks (create, update, upgrade, etc.) ordered by time. Each entry shows the task type, status (completed, failed, in-progress), and when it was created and completed.

**Why this priority**: This is the core value of the feature. Without a visible timeline, none of the other stories deliver value. It directly addresses the problem that users currently see only the current state with no historical context.

**Independent Test**: Can be fully tested by navigating to any deployment that has had at least one operation performed. The timeline should display task entries with type, status, and timestamps.

**Acceptance Scenarios**:

1. **Given** a deployment with 3 completed tasks (create, update, upgrade), **When** a user views the deployment detail page, **Then** all 3 tasks appear in newest-first order with type, status, and timestamps displayed.

2. **Given** a deployment with a currently running task, **When** a user views the timeline, **Then** the in-progress task appears at the top with a visual indicator of its active status and no completion timestamp.

3. **Given** a deployment with no tasks, **When** a user views the deployment detail page, **Then** the timeline section displays an empty state message indicating no operations have been recorded.

---

### User Story 2 - See Application Version at Each Operation (Priority: P2)

As a platform operator, I want to see the application version associated with each operation in the timeline so that I can track version progression and identify when upgrades occurred.

**Why this priority**: Version tracking is a natural extension of the timeline and provides the key context needed to understand upgrade operations. It builds on the P1 timeline and is the most common piece of information operators look for.

**Independent Test**: Can be tested by viewing a deployment that has gone through at least one upgrade. Each timeline entry should show the application version at the time of that operation.

**Acceptance Scenarios**:

1. **Given** a deployment that was created at version 1.0 and upgraded to version 2.0, **When** a user views the timeline, **Then** the create entry shows version 1.0 and the upgrade entry shows version 2.0.

2. **Given** a deployment that was updated (config change) without a version change, **When** a user views the timeline, **Then** the update entry shows the same version as the previous entry.

---

### User Story 3 - View Change Summary Between Operations (Priority: P3)

As a platform operator, I want to see a summary of what changed between operations so that I can understand the impact of each change without needing to inspect raw configuration.

When viewing a timeline entry, I can expand or click into it to see a diff of the deployment context between this operation and the previous one. The context object contains the full runtime state (version, parameters, configuration), so comparing contexts provides a comprehensive view of what changed.

**Why this priority**: Change tracking adds the most diagnostic value but is the most complex to implement. It depends on the timeline (P1) and version display (P2) being in place. It is valuable but not essential for initial operational visibility.

**Independent Test**: Can be tested by performing an update that changes configuration parameters on a deployment, then verifying the timeline entry shows a diff summary of the changed values.

**Acceptance Scenarios**:

1. **Given** a deployment that was upgraded from version 1.0 to 2.0, **When** a user expands the upgrade timeline entry, **Then** they see a diff of the context showing the version change and any other context differences.

2. **Given** a deployment that had a configuration parameter changed, **When** a user expands the update timeline entry, **Then** they see a diff of the context highlighting the changed values.

3. **Given** a deployment's first operation (create), **When** a user expands it, **Then** no diff is shown since there is no prior state to compare against.

---

### Edge Cases

- What happens when a task fails mid-operation? The timeline should still show the failed task with its error status and the timestamp of when it was last updated.

- What happens when a deployment has a large number of operations (100+)? The timeline should support pagination or lazy loading to avoid performance degradation.

- What happens when task data is incomplete (e.g., missing completion timestamp)? The UI should gracefully handle missing fields by showing "N/A" or omitting the field rather than displaying errors.

- What happens when two operations overlap in time? Each operation should appear as a separate entry ordered by creation timestamp.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST expose task timestamps (created and completed) through the data access layer so the frontend can display them.

- **FR-002**: System MUST provide a way to query tasks filtered by a specific deployment, returning them in newest-first order by default.

- **FR-003**: The deployment detail page MUST display a timeline section showing all operations associated with that deployment.

- **FR-004**: Each timeline entry MUST display: task type (create, update, upgrade, etc.), task status, creation timestamp, and completion timestamp (if available).

- **FR-005**: Each timeline entry MUST display the application version associated with that operation.

- **FR-006**: System MUST support expanding a timeline entry to view a diff of the deployment context between the current operation and the previous one.

- **FR-007**: The timeline MUST handle deployments with no operations by showing a meaningful empty state.

- **FR-008**: The timeline MUST handle large operation histories (100+ entries) without degrading the user experience.

- **FR-009**: Change diffs MUST compare the full context objects between consecutive operations, highlighting additions, removals, and modifications.

### Key Entities

- **Task**: Represents a single operation performed on a deployment. Key attributes: type (create/update/upgrade/etc.), status, creation time, completion time, associated deployment, associated application version.

- **Deployment**: The parent entity whose history is being displayed. Has an ordered collection of tasks representing its operational history.

- **ApplicationInstance**: Captures the runtime state (version, context/configuration) of a deployment at a point in time. Provides the version and configuration data needed for change summaries.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can view the complete operational history of any deployment from the deployment detail page within 2 seconds of page load.

- **SC-002**: Users can identify when a deployment was created, last modified, and what operations have occurred without leaving the deployment detail page.

- **SC-003**: Users can determine the application version at any point in a deployment's history by viewing the timeline.

- **SC-004**: For deployments that have undergone configuration changes, users can view a summary of what changed without accessing raw data or logs.

- **SC-005**: Time-to-diagnosis for deployment issues is reduced by providing change context directly on the deployment detail page.

## Clarifications

### Session 2026-04-03

- Q: What default sort order should the timeline use? → A: Newest-first (most recent operation at top).
- Q: How should change tracking work for P3? → A: Direct diff/comparison of the full context objects between consecutive operations, rather than parsed parameter-level summaries.

## Assumptions

- The existing Task model already captures sufficient data (type, status, timestamps, deployment link) to power the timeline without schema changes beyond exposing timestamps.

- Application version information is accessible from the ApplicationInstance associated with each task or deployment state.

- Change tracking will use direct comparison (diff) of the full context objects between consecutive operations rather than parsed parameter-level extraction. The context already contains the runtime state needed to understand what changed.

- The timeline is read-only; users cannot modify or delete historical entries.

- Timestamps are displayed in the user's local timezone.
