# Feature Specification: Leverage Generated Typed Bindings in SDK

**Feature Branch**: `003-sdk-typed-bindings`
**Created**: 2026-04-01
**Status**: Draft
**Input**: User description: "Related to issue #11 — we are generating the bindings for the SDK already but we aren't using them properly. The goal is to leverage the bindings in the SDK."

## Clarifications

### Session 2026-04-01

- Q: Should the generated Client class be used for execution, or only the generated response types? → A: Keep Transport execution as-is, only replace hand-written models with generated response types.
- Q: How to handle `Task.type` → `Task.type_` rename from generated types? → A: Accept the breaking change and document it.
- Q: What about models with no generated equivalent (ApplicationDriver, ApplicationDriverVersionSummary, Context)? → A: Keep as hand-written models.
- Q: How should resources validate responses — swap model in `model_validate()` or use outer wrapper type? → A: Use the generated outer wrapper type to validate the full `result["data"]` dict, avoiding manual key access.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Type-Safe SDK Operations (Priority: P1)

As an SDK consumer, when I call SDK resource methods (e.g., `client.clusters.create()`), the SDK validates and returns response data using the generated Pydantic response types instead of hand-written model classes, so that response data is validated against the exact GraphQL schema at runtime and I get accurate type hints in my IDE.

**Why this priority**: This is the core value proposition — replacing hand-written models with generated types eliminates an entire class of bugs where the SDK's models drift from the actual GraphQL schema.

**Independent Test**: Can be verified by calling any SDK resource method and confirming the response object is an instance of a generated type (not a hand-written model).

**Acceptance Scenarios**:

1. **Given** a running Styrmin backend, **When** an SDK consumer calls a create/get/list/delete method on any resource, **Then** the SDK validates the response using generated types and returns a correctly typed response.
2. **Given** the GraphQL schema has changed and bindings have been regenerated, **When** the SDK resource methods are called, **Then** any mismatch between response data and expected types is caught by the generated models' validation (not silently ignored).
3. **Given** an SDK consumer is using an IDE with type checking, **When** they access fields on SDK response objects, **Then** their IDE provides accurate autocomplete and type information.

---

### User Story 2 - Consistent Error Handling (Priority: P2)

As an SDK consumer, when a GraphQL operation returns an error, the SDK's existing structured error handling (ResourceNotFoundError, ResourceAlreadyExistsError, OperationFailedError) continues to work identically after the model replacement.

**Why this priority**: Existing SDK consumers depend on the current error handling contract. Switching models must not break this.

**Independent Test**: Can be tested by triggering known error conditions (e.g., creating a duplicate cluster) and verifying the same exception types are raised with the same information.

**Acceptance Scenarios**:

1. **Given** a resource does not exist, **When** the SDK consumer calls a get method for that resource, **Then** a `ResourceNotFoundError` is raised (same as current behavior).
2. **Given** a resource already exists, **When** the SDK consumer attempts to create a duplicate, **Then** a `ResourceAlreadyExistsError` is raised (same as current behavior).

---

### User Story 3 - Reduced Model Maintenance Burden (Priority: P3)

As a project maintainer, the hand-written domain models that duplicate the generated response types are replaced by (or mapped from) the generated types, reducing maintenance burden and eliminating model drift risk.

**Why this priority**: This is a maintenance and correctness improvement that follows naturally from adopting the generated types, but can be deferred if the generated types need adaptation for the public API surface.

**Independent Test**: Can be verified by confirming that the SDK's public response types are derived from or identical to the generated types, and that the hand-written models are removed or reduced to thin wrappers.

**Acceptance Scenarios**:

1. **Given** the generated bindings produce response types for all SDK operations, **When** a maintainer inspects the SDK codebase, **Then** there are no hand-written model classes that duplicate fields already present in generated types.
2. **Given** a new GraphQL query is added and bindings are regenerated, **When** the SDK is updated to expose the new operation, **Then** no new hand-written model class is needed — the generated type is used directly or via a minimal wrapper.

---

### Edge Cases

- What happens when the generated response type has a different field shape than the current hand-written model (e.g., additional fields, renamed fields)? The SDK should use the generated type as the source of truth.
- How does the SDK handle GraphQL operations that return union types or nullable fields? The generated types already model these; the SDK should pass them through.
- Error handling is unchanged — the existing `_check_graphql_errors()` dict-based pattern continues to work since Transport still returns raw dicts.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: SDK resource methods MUST use the generated response types for response validation instead of hand-written model classes. The existing Transport execution and `load_query()` pattern remains unchanged.
- **FR-002**: SDK MUST preserve its existing public API surface — method signatures, return types, and exception types MUST remain backward-compatible for consumers. **Exception**: `Task.type` is renamed to `Task.type_` (generated codegen avoids Python builtin); this is an accepted breaking change that must be documented.
- **FR-003**: SDK MUST use the generated response types as the basis for response data. Resource methods MUST validate the full `result["data"]` dict using the generated outer wrapper type (e.g., `CreateCluster.model_validate(result["data"])`), then extract the inner field — eliminating manual dictionary key access into the operation-level response and manual model validation against hand-written models.
- **FR-004**: SDK MUST maintain its existing structured error handling, mapping GraphQL errors to ResourceNotFoundError, ResourceAlreadyExistsError, and OperationFailedError as before.
- **FR-005**: SDK MUST continue to support all current operations (clusters, backups, deployments, environments, drivers, schedules, tasks, backup storage locations).
- **FR-006**: The manual query loader (`load_query()`) and Transport execution pattern are retained — no changes to the execution path.
- **FR-007**: The hand-written domain models MUST be either replaced by the generated types or reduced to re-exports/aliases of the generated types, eliminating duplication. **Exception**: `ApplicationDriver`, `ApplicationDriverVersionSummary`, and `Context` remain hand-written (no matching generated types exist).

### Key Entities

- **Generated Response Types**: Pydantic models auto-generated by ariadne-codegen from GraphQL queries that exactly mirror the response structure, providing type safety at development time and runtime validation.
- **Resource Classes**: The SDK's public-facing API layer (ClusterResource, BackupResource, etc.) that wraps operations with domain-specific methods and error handling.
- **Transport**: The HTTP/GraphQL execution layer — used directly by resources. Remains unchanged in this feature.
- **Query Loader**: The `load_query()` utility that loads `.graphql` files as strings for Transport. Remains unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All SDK resource methods validate responses using generated outer wrapper types (e.g., `CreateCluster.model_validate(result["data"])`) with zero manual dictionary key access into operation-level response data.
- **SC-002**: The SDK's public API remains backward-compatible — existing consumer code works without modification, except for the documented `Task.type` → `Task.type_` rename.
- **SC-003**: The number of hand-written model classes in the SDK is reduced to only those without generated equivalents (`ApplicationDriver`, `ApplicationDriverVersionSummary`, `Context`); all others are re-exports of generated types.
- **SC-004**: All existing SDK tests pass without modification to test assertions (only internal implementation changes).
- **SC-005**: Adding a new GraphQL operation to the SDK requires only regenerating bindings and adding a resource method — no new hand-written model class is needed.

## Assumptions

- The generated response types produced by ariadne-codegen cover all operations currently exposed by the SDK.
- The generated response types contain all fields that the current hand-written domain models expose, so no information is lost in the switch.
- The existing Transport and `load_query()` execution pattern remains unchanged and working.
- The project's existing regeneration workflow will continue to be used to regenerate bindings when the schema or queries change.
