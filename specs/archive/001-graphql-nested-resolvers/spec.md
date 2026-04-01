# Feature Specification: Add Nested Object Resolvers to GraphQL Schema

**Feature Branch**: `001-graphql-nested-resolvers`
**Created**: 2026-03-25
**Status**: Extracted
**Input**: [GitHub Issue #25](https://github.com/opsmill/styrmin/issues/25)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fetch Deployment with Related Entities in a Single Query (Priority: P1)

As a client developer, I want to query a deployment and retrieve its associated environment and application driver version in the same query, so that I can display complete deployment information without making multiple round-trip requests.

**Why this priority**: Deployments are the central concept in the platform. Resolving their relationships (environment, application driver version) is the highest-value improvement because deployment views are the most frequently accessed and currently require the most follow-up queries.

**Independent Test**: Can be fully tested by querying a deployment with nested `environment` and `applicationDriverVersion` fields and verifying the related objects are returned inline.

**Acceptance Scenarios**:

1. **Given** a deployment exists with a valid environment, **When** a client queries the deployment and requests the nested `environment` field, **Then** the full environment object is returned within the deployment response.
2. **Given** a deployment exists with a valid application driver version, **When** a client queries the deployment and requests the nested `applicationDriverVersion` field, **Then** the full application driver version object is returned within the deployment response.
3. **Given** a deployment exists, **When** a client queries using only the existing `environmentId` field (without the new nested field), **Then** the query continues to work as before with no breaking changes.

---

### User Story 2 - Traverse the Application Driver Version Chain (Priority: P2)

As a client developer, I want to navigate from an application driver version to its parent application driver, and from an application instance to its application driver version, so that I can display the full lineage of a deployed application without extra queries.

**Why this priority**: Understanding the driver hierarchy (instance → version → driver) is essential for operational dashboards and debugging. This enables clients to show which driver and version are behind any running instance.

**Independent Test**: Can be fully tested by querying an application driver version with the nested `applicationDriver` field and an application instance with the nested `applicationDriverVersion` field, verifying both return the correct related objects.

**Acceptance Scenarios**:

1. **Given** an application driver version exists with a valid parent driver, **When** a client queries the version and requests the nested `applicationDriver` field, **Then** the parent application driver object is returned inline.
2. **Given** an application instance exists with a valid driver version, **When** a client queries the instance and requests the nested `applicationDriverVersion` field, **Then** the associated application driver version object is returned inline.

---

### User Story 3 - Navigate from Tasks, Backups, and Restores to Their Parent Entities (Priority: P3)

As a client developer, I want to traverse from operational entities (tasks, backup schedules, backups, restores) to their parent entities in a single query, so that I can build complete operational views without additional lookups.

**Why this priority**: These are supporting relationships used in operations and audit views. They are less frequently queried than deployment/driver relationships but still important for building complete UIs for backup management and task monitoring.

**Independent Test**: Can be fully tested by querying each entity type (task, backup schedule, backup, restore) with its new nested parent field and verifying the correct parent object is returned.

**Acceptance Scenarios**:

1. **Given** a task exists with a valid deployment, **When** a client queries the task and requests the nested `deployment` field, **Then** the associated deployment object is returned inline.
2. **Given** a backup schedule exists with a valid deployment, **When** a client queries the backup schedule and requests the nested `deployment` field, **Then** the associated deployment object is returned inline.
3. **Given** a backup exists with a valid application instance, **When** a client queries the backup and requests the nested `instance` field, **Then** the associated application instance object is returned inline.
4. **Given** a restore exists with a valid backup, **When** a client queries the restore and requests the nested `backup` field, **Then** the associated backup object is returned inline.
5. **Given** a task exists where the associated deployment has been deleted, **When** a client queries the task and requests the nested `deployment` field, **Then** a null value is returned (since the relationship is nullable).

---

### Edge Cases

- What happens when a nested resolver references an entity that has been deleted? If the foreign key is nullable (e.g., `Task.deploymentId`), the nested field returns null. If non-nullable, the relationship is guaranteed by the data model to always resolve. In the unlikely event of a data integrity violation on a non-nullable relationship, the resolver returns a GraphQL field error to surface the issue rather than silently masking it.
- What happens when a client requests deeply nested chains (e.g., `restore → backup → instance → applicationDriverVersion → applicationDriver`)? The system resolves each level independently; no depth limit is enforced in this iteration. Performance may degrade with deep nesting, but correctness is maintained. Depth limiting is deferred to a future optimization pass.
- What happens when multiple nested fields are requested on the same entity in a single query? All requested nested fields resolve independently within the same response.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST expose a nested `environment` field on the `Deployment` type that returns the associated environment object.
- **FR-002**: System MUST expose a nested `applicationDriverVersion` field on the `Deployment` type that returns the associated application driver version object.
- **FR-003**: System MUST expose a nested `applicationDriver` field on the `ApplicationDriverVersion` type that returns the parent application driver object.
- **FR-004**: System MUST expose a nested `applicationDriverVersion` field on the `ApplicationInstance` type that returns the associated application driver version object.
- **FR-005**: System MUST expose a nested `deployment` field on the `Task` type that returns the associated deployment object (nullable, since the relationship may not exist).
- **FR-006**: System MUST expose a nested `deployment` field on the `BackupSchedule` type that returns the associated deployment object.
- **FR-007**: System MUST expose a nested `instance` field on the `Backup` type that returns the associated application instance object (nullable, since the relationship may not exist).
- **FR-008**: System MUST expose a nested `backup` field on the `Restore` type that returns the associated backup object.
- **FR-009**: System MUST preserve all existing `*Id` fields alongside the new nested object fields to maintain backward compatibility.
- **FR-010**: System MUST return null for nullable nested fields when the referenced entity does not exist or the foreign key is null.
- **FR-011**: System MUST update the published schema definition and generated client types to reflect the new fields.
- **FR-012**: Nested resolver fields MUST inherit authorization from the parent entity and MUST NOT perform additional authorization checks on the resolved child entity.
- **FR-013**: Non-nullable nested resolvers MUST raise a GraphQL field error if the referenced entity cannot be found due to a data integrity violation, rather than returning null or silently failing.

### Key Entities

- **Deployment**: Represents a deployed application in an environment. Has relationships to Environment and ApplicationDriverVersion.
- **ApplicationDriverVersion**: A specific version of an application driver. Belongs to an ApplicationDriver.
- **ApplicationInstance**: A running instance of a deployed application. Linked to an ApplicationDriverVersion.
- **Task**: An operational task associated with a deployment (nullable relationship).
- **BackupSchedule**: A scheduled backup configuration tied to a deployment.
- **Backup**: A completed backup of an application instance (nullable relationship to instance).
- **Restore**: A restore operation that references a specific backup.
- **Environment**: A deployment target environment within a cluster.
- **ApplicationDriver**: A top-level driver definition that has multiple versions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Clients can retrieve a deployment along with its environment and application driver version details in a single query, eliminating the need for follow-up requests.
- **SC-002**: All 8 specified nested relationships are queryable and return correct data for all existing records in the system.
- **SC-003**: Existing queries that use only `*Id` fields continue to function identically with no changes required from clients.
- **SC-004**: Nullable nested fields correctly return null when the referenced entity does not exist, rather than producing errors.
- **SC-005**: No existing query patterns break or produce errors after the schema changes are deployed.

## Clarifications

### Session 2026-03-25

- Q: Do nested resolver fields enforce authorization checks, or inherit access from the parent entity? → A: Nested fields inherit the parent's authorization (no additional checks on nested fields).
- Q: Should the system enforce a maximum query depth limit for deeply nested chains? → A: No depth limit for this iteration; defer to future optimization.
- Q: What should happen if a non-nullable nested relationship fails to resolve due to a data integrity violation? → A: Return a GraphQL field error (standard resolver exception behavior).

## Assumptions

- The underlying database relationships already exist for all 8 entity pairs; no database schema changes are required.
- The current lazy-loading approach used by existing nested resolvers is acceptable for this iteration; query optimization (e.g., batching or eager loading) is deferred to a future enhancement.
- The nullability of each nested field matches the nullability of the corresponding foreign key field as defined in the issue (e.g., `Task.deployment` is nullable, `Deployment.environment` is non-nullable).
