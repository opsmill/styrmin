# Feature Specification: Cluster & Environment Capability Declarations

**Feature Branch**: `001-cluster-env-capabilities`  
**Created**: 2026-04-01  
**Status**: Draft  
**Input**: GitHub Issue #42 — Expose capability declarations on clusters and environments

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Query Cluster Capabilities (Priority: P1)

As an operator, I want to query a single field on a cluster to see all its capabilities, so I can quickly understand what that cluster supports without inspecting multiple config fields and relationships.

**Why this priority**: This is the foundational interaction — without the ability to query capabilities, no other capability-related features can work. Clusters are the primary infrastructure unit.

**Independent Test**: Can be fully tested by querying a cluster's capabilities field and verifying it returns a structured list of supported capabilities derived from the cluster's current configuration.

**Acceptance Scenarios**:

1. **Given** a cluster with `standard_storage` configured, **When** an operator queries the cluster's capabilities, **Then** the response includes a `storage` category with a sub-capability for the available storage type.
2. **Given** a cluster with no storage configuration, **When** an operator queries the cluster's capabilities, **Then** the `storage` category is absent.
3. **Given** a cluster with multiple storage classes configured, **When** an operator queries the cluster's capabilities, **Then** the `storage` category contains sub-capabilities for each available storage type.
4. **Given** a cluster with an ingress controller configured and a DNS zone available, **When** an operator queries the cluster's capabilities, **Then** the response includes an `ingress` category indicating external endpoint exposure is available.
5. **Given** a cluster with an ingress controller but no DNS zone, **When** an operator queries the cluster's capabilities, **Then** the `ingress` category is absent.

---

### User Story 2 - Query Environment Capabilities (Priority: P1)

As an operator, I want to query a single field on an environment to see all its capabilities — including both environment-specific capabilities (like backup support) and inherited cluster-level capabilities (like storage types) — so I get a complete picture in one query.

**Why this priority**: Environments are where deployments happen. Operators need a unified view of what's available at the environment level, combining both environment-specific and cluster-inherited capabilities.

**Independent Test**: Can be fully tested by querying an environment's capabilities field and verifying it returns capabilities derived from both the environment's own configuration and its parent cluster's configuration.

**Acceptance Scenarios**:

1. **Given** an environment with a `BackupStorageLocation` assigned, **When** an operator queries the environment's capabilities, **Then** the response includes a backup capability indicating backup is supported.
2. **Given** an environment without a `BackupStorageLocation`, **When** an operator queries the environment's capabilities, **Then** the backup capability is absent.
3. **Given** an environment on a cluster that has `standard_storage` and `ssd` configured, but the environment is only configured for `standard_storage`, **When** an operator queries the environment's capabilities, **Then** the response includes only the `standard` storage sub-capability (environment-scoped view, not full cluster inheritance).
4. **Given** an environment on a cluster with ingress capabilities, but the environment has no ingress configuration, **When** an operator queries the environment's capabilities, **Then** the `ingress` category is absent from the environment's capabilities.

---

### User Story 3 - Access Capabilities in Template Rendering Context (Priority: P1)

As an Application Driver author, I want cluster and environment capabilities to be available in the Jinja2 template rendering context (GlobalContext), so I can use them in Helm values templates to conditionally configure deployments based on what the target infrastructure supports.

**Why this priority**: Application Drivers are the primary consumers of capabilities. Without context access, drivers cannot conditionally enable features like ingress, backup, or storage class selection based on infrastructure capabilities. This is as fundamental as the query API.

**Independent Test**: Can be fully tested by rendering a driver template that references capabilities (e.g., `{{ cluster.capabilities.storage }}` or `{{ environment.capabilities.ingress }}`) and verifying the rendered output matches the expected capabilities.

**Acceptance Scenarios**:

1. **Given** a deployment to a cluster with storage capabilities, **When** the driver template references `{{ cluster.capabilities.storage }}`, **Then** the template renders with the cluster's storage sub-capabilities available.
2. **Given** a deployment to an environment with backup capabilities, **When** the driver template references `{{ environment.capabilities.backup }}`, **Then** the template renders with the environment's backup capability available.
3. **Given** a deployment to an environment without ingress capabilities, **When** the driver template references `{{ environment.capabilities.ingress }}`, **Then** the template renders gracefully (empty/undefined, no error) thanks to SilentUndefined handling.
4. **Given** a deployment where capabilities have been recalculated since the last deployment, **When** the context is generated, **Then** it uses the latest persisted capabilities.

---

### User Story 4 - Programmatic Capability Checks in Automation (Priority: P2)

As an Application Driver (or any automation), I want to programmatically check whether a target environment has the required capabilities before attempting an operation (e.g., backup, storage provisioning), so I can fail gracefully with a clear message rather than encountering runtime errors.

**Why this priority**: This is the primary automation use case and the key motivator for having structured capabilities. However, it depends on User Stories 1, 2, and 3 being in place first.

**Independent Test**: Can be fully tested by writing an automation script that queries capabilities before performing an operation, and verifying it correctly identifies when prerequisites are missing.

**Acceptance Scenarios**:

1. **Given** an Application Driver that requires backup support, **When** it queries the target environment's capabilities and backup is available, **Then** it proceeds with the backup operation.
2. **Given** an Application Driver that requires backup support, **When** it queries the target environment's capabilities and backup is not available, **Then** it reports a clear prerequisite failure without attempting the operation.
3. **Given** an Application Driver that requires a specific storage type, **When** it queries the target cluster's capabilities, **Then** it can determine whether the required storage type is available.

---

### Edge Cases

- What happens when the underlying configuration changes (e.g., a `BackupStorageLocation` is removed)? Capabilities are recalculated and the persisted values updated; subsequent queries reflect the new state.
- What happens when a cluster has no configuration at all? The capabilities field should return an empty list, not an error.
- What happens when an environment's parent cluster is not accessible? The environment should still return its own capabilities; cluster-inherited capabilities should be omitted or flagged.
- What happens if capability recalculation fails? The previously stored capabilities remain until the next successful recalculation.
- What happens when a driver template references a capability category that doesn't exist on the target? Rendering proceeds without error (SilentUndefined), allowing templates to be portable across clusters/environments with different capability sets.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST expose a dedicated capabilities field on the Cluster entity that returns a structured list of computed capabilities.
- **FR-002**: System MUST expose a dedicated capabilities field on the Environment entity that returns a structured list of computed capabilities. Environment capabilities show cluster capabilities filtered by the environment's own configuration (environment-scoped view), not the full set of cluster capabilities.
- **FR-003**: System MUST derive the **storage type** capability from the cluster's and environment's existing storage configuration (e.g., `standard_storage`, `ssd`, `network-attached`).
- **FR-004**: System MUST derive the **backup support** capability from whether a `BackupStorageLocation` is assigned to the environment and any other relevant prerequisites are met.
- **FR-005**: Capabilities MUST be organized hierarchically by category (e.g., `storage`) with sub-capabilities inside each category (e.g., `standard`, `ssd`, `network-attached` under storage).
- **FR-006**: Capabilities MUST be calculated and persisted in the database so they are not recomputed on every query. Recalculation occurs when relevant configuration changes.
- **FR-007**: Capabilities MUST be read-only from the user's perspective — they are derived from existing state, not manually set by users.
- **FR-008**: The capability model MUST be extensible — adding new capability types in the future should not require data model changes or migrations.
- **FR-009**: Each capability MUST include at minimum a category identifier, a sub-capability name, and relevant details.
- **FR-010**: Capabilities MUST reflect the current state of the system — when underlying configuration changes, capabilities are recalculated and the stored values updated.
- **FR-011**: Capability presence is boolean — a capability either exists in the list or it does not. No status enum (e.g., degraded/unavailable) is required at this stage; the extensible model supports adding status in a future iteration.
- **FR-012**: System MUST derive an **ingress** capability indicating whether a cluster or environment can configure ingress or expose an API/endpoint externally. This is derived from the combination of an ingress controller being configured (e.g., presence of an ingress class) and a DNS zone being available.
- **FR-013**: Cluster capabilities MUST be accessible in the template rendering context (GlobalContext) under the cluster section, so Application Driver templates can reference them (e.g., `{{ cluster.capabilities.storage }}`).
- **FR-014**: Environment capabilities MUST be accessible in the template rendering context (GlobalContext) under the environment section, so Application Driver templates can reference them (e.g., `{{ environment.capabilities.backup }}`).
- **FR-015**: When capabilities are absent or a referenced capability category does not exist, template rendering MUST handle this gracefully (no errors), consistent with existing SilentUndefined behavior in the Jinja2 rendering pipeline.

### Key Entities

- **Capability**: A structured declaration of what a cluster or environment supports. Organized hierarchically: a **category** (e.g., `storage`, `backup`, `ingress`) contains one or more **sub-capabilities** with type-specific details. Capabilities are derived from existing configuration and persisted in the database for efficient querying.
- **Cluster**: Existing entity, extended with a capabilities field that aggregates all capabilities derived from its configuration.
- **Environment**: Existing entity, extended with a capabilities field that shows an environment-scoped view — cluster capabilities filtered by the environment's own configuration, plus environment-specific capabilities.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operators can determine all supported capabilities of a cluster or environment by querying a single field, eliminating the need to inspect multiple configuration fields.
- **SC-002**: Automation (Application Drivers) can programmatically verify prerequisites before attempting operations, reducing failed deployment attempts due to missing infrastructure capabilities.
- **SC-005**: Application Driver templates can conditionally configure deployments based on capabilities available in the rendering context, without needing to inspect raw configuration fields.
- **SC-003**: Adding a new capability type requires only defining its derivation logic — no data model changes, migrations, or schema modifications.
- **SC-004**: Capability queries return results reflecting current system state — changes to underlying configuration trigger recalculation, and subsequent queries return updated capabilities.

## Assumptions

- Capabilities are **derived** from existing configuration and state, not declaratively set by operators. They are persisted in the database for efficient querying and recalculated when relevant configuration changes (a cheap, non-resource-intensive operation).
- The initial implementation covers three capability categories: **storage type**, **backup support**, and **ingress**. The extensible model supports future additions (e.g., GPU availability, network isolation).
- Environment capabilities show an **environment-scoped view**: cluster capabilities are filtered by the environment's own configuration, so only capabilities actually usable in that environment are displayed.
- The capability model lives as a persisted field on existing entities (Cluster, Environment) rather than as a separate concern, keeping the query surface simple.
- Capability presence is boolean (exists or doesn't). A status enum may be added in a future iteration if operational monitoring requires it.

## Clarifications

### Session 2026-04-01

- Q: Should capabilities be flat or hierarchical? → A: Hierarchical — organized by category (e.g., `storage`) with sub-capabilities inside.
- Q: Should capabilities be computed on every query or persisted? → A: Persisted in the database; recalculated on config changes (cheap operation).
- Q: What are the initial capability types? → A: Storage, backup, and ingress (external endpoint exposure).
- Q: Should capabilities have a status enum or boolean presence? → A: Boolean presence (C) — exists or doesn't. Extensible model supports adding status later.
- Q: What determines the ingress capability? → A: Combination of ingress controller configured + DNS zone available. Both must be present.
- Q: How does capability inheritance work for environments? → A: Environment-scoped view — cluster capabilities filtered by environment's own configuration (only what's actually usable).
- Q: Should capabilities be accessible in the template rendering context? → A: Yes — both cluster and environment capabilities must be available in GlobalContext for Application Driver Jinja2 templates.
