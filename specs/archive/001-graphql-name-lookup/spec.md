# Feature Specification: Name-Based Resource Lookup in GraphQL APIs

**Feature Branch**: `001-graphql-name-lookup`
**Created**: 2026-03-29
**Status**: Extracted
**Input**: User description: "Allow cluster and environment lookup by name in GraphQL APIs" ([GitHub Issue #9](https://github.com/opsmill/styrmin/issues/9))

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Look Up a Cluster by Name (Priority: P1)

As an API consumer, I want to query or delete a cluster using its human-readable name instead of its UUID, so I can interact with the platform without first looking up opaque identifiers.

**Why this priority**: This is the simplest and highest-impact change. Clusters are the top-level resource, and name-based access removes the most common friction point for both interactive exploration and scripted workflows.

**Independent Test**: Can be fully tested by querying a cluster by name and verifying the correct cluster is returned. Delivers immediate value for any user who knows their cluster name.

**Acceptance Scenarios**:

1. **Given** a cluster named "us-east-1" exists, **When** I query for a cluster by name "us-east-1", **Then** the system returns the cluster details for "us-east-1".
2. **Given** a cluster named "us-east-1" exists, **When** I request deletion of the cluster by name "us-east-1", **Then** the cluster is deleted successfully.
3. **Given** no cluster named "nonexistent" exists, **When** I query for a cluster by name "nonexistent", **Then** the system returns a clear "not found" error.

---

### User Story 2 - Look Up an Environment by Name Within a Cluster (Priority: P2)

As an API consumer, I want to query or delete an environment using its name combined with a cluster identifier, so I can reference environments in a human-readable way without needing UUIDs.

**Why this priority**: Environment lookups are the second most common operation. Because environment names are only unique within a cluster, a cluster identifier must accompany the environment name, making this slightly more complex than cluster lookup.

**Independent Test**: Can be tested by creating an environment in a known cluster and then querying it by environment name + cluster name. Delivers value for any user managing environments.

**Acceptance Scenarios**:

1. **Given** an environment "staging" exists in cluster "us-east-1", **When** I query for environment "staging" in cluster "us-east-1", **Then** the system returns the correct environment details.
2. **Given** an environment "staging" exists in cluster "us-east-1", **When** I request deletion of environment "staging" in cluster "us-east-1", **Then** the environment is deleted successfully.
3. **Given** environments named "staging" exist in both cluster "us-east-1" and cluster "eu-west-1", **When** I query for environment "staging" in cluster "us-east-1", **Then** only the "us-east-1" environment is returned.

---

### User Story 3 - Create and Deploy Using Names (Priority: P3)

As an API consumer, I want to create environments and trigger deployments using cluster and environment names instead of UUIDs, so my entire workflow uses human-readable identifiers end-to-end.

**Why this priority**: Creating environments and deploying are less frequent than lookups but complete the name-based workflow. Without this, users would need to mix names (for queries) with UUIDs (for mutations), which is inconsistent.

**Independent Test**: Can be tested by creating an environment using a cluster name and then deploying to that environment by name. Delivers value for scripted deployment pipelines.

**Acceptance Scenarios**:

1. **Given** a cluster "us-east-1" exists, **When** I create an environment named "staging" referencing cluster "us-east-1" by name, **Then** the environment is created and associated with the correct cluster.
2. **Given** environment "staging" exists in cluster "us-east-1", **When** I trigger a deployment targeting environment "staging" in cluster "us-east-1" by name, **Then** the deployment executes against the correct environment.

---

### User Story 4 - Same Environment Name Across Clusters (Priority: P2)

As a platform operator, I want to use the same environment name (e.g., "staging", "production") in multiple clusters, so that naming conventions remain consistent across my infrastructure without artificial conflicts.

**Why this priority**: This is foundational for realistic multi-cluster usage. Without per-cluster uniqueness, operators are forced into awkward naming patterns like "staging-us-east" to avoid global collisions. This also enables accurate name-based environment lookup.

**Independent Test**: Can be tested by creating two environments with the same name in different clusters and verifying both coexist without error.

**Acceptance Scenarios**:

1. **Given** a cluster "us-east-1" with environment "staging", **When** I create an environment also named "staging" in cluster "eu-west-1", **Then** the creation succeeds and both environments coexist.
2. **Given** two environments named "staging" in different clusters, **When** I query each by name with its respective cluster context, **Then** the correct environment is returned for each.
3. **Given** a cluster "us-east-1" with environment "staging", **When** I try to create another environment named "staging" in the same cluster "us-east-1", **Then** the system rejects the request with a uniqueness error.

---

### User Story 5 - Manage Clusters by Name in CLI (Priority: P1)

As a CLI user, I want to use cluster names as the default identifier in `styrminctl` commands (e.g., `styrminctl clusters get us-east-1`) so I can work with memorable names instead of copying UUIDs.

**Why this priority**: The CLI is the primary interface for operators. Name-based access in the CLI delivers the most immediate ergonomic improvement, matching the API change.

**Independent Test**: Can be tested by running `styrminctl clusters get <name>` and verifying it returns the correct cluster. Falls back to `--id <uuid>` for UUID-based access.

**Acceptance Scenarios**:

1. **Given** a cluster named "us-east-1" exists, **When** I run `styrminctl clusters get us-east-1`, **Then** the CLI displays the cluster details.
2. **Given** a cluster named "us-east-1" exists, **When** I run `styrminctl clusters delete us-east-1`, **Then** the cluster is deleted.
3. **Given** a cluster with UUID "abc-123", **When** I run `styrminctl clusters get --id abc-123`, **Then** the CLI displays the cluster details (backward-compatible UUID access).

---

### User Story 6 - Manage Environments by Name in CLI (Priority: P2)

As a CLI user, I want to reference environments by name in `styrminctl` commands, providing cluster context where needed, so my entire CLI workflow uses human-readable identifiers.

**Why this priority**: Environments are referenced in multiple CLI commands (get, delete, create, deploy, backup-locations). Name-based access with cluster context completes the CLI ergonomic improvement.

**Independent Test**: Can be tested by running `styrminctl environments get staging --cluster us-east-1` and verifying the correct environment is returned.

**Acceptance Scenarios**:

1. **Given** environment "staging" exists in cluster "us-east-1", **When** I run `styrminctl environments get staging --cluster us-east-1`, **Then** the CLI displays the correct environment.
2. **Given** environment "staging" exists in the "default" cluster, **When** I run `styrminctl environments get staging` (omitting `--cluster`), **Then** the CLI looks up "staging" in the "default" cluster and displays it.
3. **Given** a cluster "us-east-1" exists, **When** I run `styrminctl environments create staging --cluster us-east-1`, **Then** the environment is created in the specified cluster.
4. **Given** environment "staging" in cluster "us-east-1", **When** I run `styrminctl deployments create my-driver 1.0 staging --cluster us-east-1`, **Then** the deployment targets the correct environment.
5. **Given** environment "staging" in cluster with UUID "abc-123", **When** I run `styrminctl environments get staging --cluster-id abc-123`, **Then** the CLI displays the correct environment (UUID-based cluster context).

---

### Edge Cases

- What happens when a caller provides both an ID and a name for the same resource? The system must reject the request with a clear validation error.
- What happens when a caller provides neither an ID nor a name? The system must reject the request with a clear validation error explaining that one identifier is required.
- What happens when an environment name lookup is attempted without a cluster context? The system must reject the request, since environment names are only unique within a cluster.
- What happens when the provided name exists but the provided cluster context does not? The system must return a "not found" error for the cluster, not silently fail.
- What happens to existing API calls that use UUIDs? They must continue to work exactly as before with no changes required.
- What happens when a CLI user provides both a positional name and an `--id` flag? The CLI must reject the request with a clear error.
- What happens when a CLI user omits the `--cluster` flag for an environment name lookup? The CLI defaults to looking up the environment in the "default" cluster.
- What happens when a CLI user provides both `--cluster` and `--cluster-id`? The CLI must reject the request with a clear validation error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow looking up a cluster by its unique name as an alternative to its UUID.
- **FR-002**: System MUST allow looking up an environment by its name combined with a cluster identifier (name or UUID) as an alternative to the environment UUID.
- **FR-003**: System MUST allow deleting a cluster by name as an alternative to UUID.
- **FR-004**: System MUST allow deleting an environment by name (with cluster context) as an alternative to UUID.
- **FR-005**: System MUST allow creating an environment using a cluster name as an alternative to cluster UUID.
- **FR-006**: System MUST allow triggering a deployment using environment name (with cluster context) as an alternative to environment UUID.
- **FR-007**: System MUST reject any request that provides both an ID and a name for the same resource, returning a clear validation error.
- **FR-008**: System MUST reject any request that provides neither an ID nor a name for a required resource, returning a clear validation error.
- **FR-009**: System MUST require a cluster identifier (name or UUID) when looking up an environment by name.
- **FR-010**: System MUST enforce environment name uniqueness per cluster rather than globally, allowing the same environment name to exist in different clusters.
- **FR-011**: System MUST continue to support all existing UUID-based operations without any changes to their behavior.
- **FR-012**: System MUST change the environment uniqueness constraint from global to per-cluster in the model definition. No migration script is needed (project is pre-production; schema is managed via `metadata.create_all()`).
- **FR-013**: CLI MUST accept resource names as the default positional argument for all commands that currently accept cluster or environment UUIDs.
- **FR-014**: CLI MUST provide an `--id` flag as an alternative for UUID-based access on all commands that accept a resource identifier.
- **FR-015**: CLI MUST provide a `--cluster` flag (name-only) and a `--cluster-id` flag (UUID) for cluster context when referencing an environment by name. The `--cluster` flag MUST default to "default".
- **FR-016**: CLI commands that reference an environment (deployments create, backup-locations assign/unassign) MUST also support environment name with cluster context.
- **FR-017**: SDK MUST accept name-based parameters and pass them through to the GraphQL API for resolution. The CLI MUST NOT resolve names to UUIDs locally.
- **FR-018**: SDK MUST support both name-based and UUID-based parameters for all cluster and environment operations, matching the GraphQL API's dual-identifier support.

### Key Entities

- **Cluster**: A Kubernetes cluster managed by the platform. Has a globally unique name. Serves as the parent scope for environments.
- **Environment**: A deployment target within a cluster (e.g., "staging", "production"). Has a name that is unique within its parent cluster but not globally. Belongs to exactly one cluster.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: API consumers can query, create, delete, and deploy to resources using human-readable names without ever needing to look up UUIDs first.
- **SC-002**: All existing UUID-based API operations continue to function identically with zero breaking changes.
- **SC-003**: Platform operators can use identical environment names (e.g., "production") across multiple clusters without naming conflicts.
- **SC-004**: 100% of validation error cases (both ID and name provided, neither provided, missing cluster context) return clear, actionable error messages.
- **SC-005**: Every operation that accepts a resource identifier supports both UUID and name-based lookup with identical result behavior.
- **SC-006**: CLI users can perform all cluster and environment operations using names as the default identifier without needing to look up UUIDs.
- **SC-007**: Existing CLI scripts using UUIDs via the `--id` flag continue to work without modification.

## Clarifications

### Session 2026-03-29

- Q: How should the CLI accept name-based identifiers? → A: Names become the default positional argument; UUIDs available via `--id` flag.
- Q: How should CLI environment commands accept cluster context? → A: Separate `--cluster` (name-only) and `--cluster-id` (UUID) flags. `--cluster` defaults to "default" (the default cluster name).
- Q: Should the SDK expose name-based parameters or should the CLI resolve names itself? → A: SDK passes names through to the GraphQL API; the API handles resolution. CLI stays thin.

### Session 2026-03-30

- Q: Is a database migration script needed for the uniqueness constraint change? → A: No. Project is not in production; model change alone is sufficient (`metadata.create_all()` handles fresh databases).

## Assumptions

- Cluster names are already globally unique in the system, making them a reliable alternative identifier.
- The platform manages a small number of clusters and environments, so name-based lookup performance is not a concern.
- No existing data has duplicate environment names across clusters (since the current global uniqueness constraint prevents this). No migration script is needed as the project is pre-production.
- Environment name-based lookup always requires a cluster context -- there is no use case for globally ambiguous environment name resolution.
