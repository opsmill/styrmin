# Feature Specification: Replace urql with TanStack Query

**Feature Branch**: `001-tanstack-query-migration`
**Created**: 2026-04-03
**Status**: Extracted
**Input**: GitHub Issue #55 — Replace urql with TanStack Query for frontend data fetching

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Core Data Fetching Works with TanStack Query (Priority: P1)

As a user of the Styrmin frontend, I can continue to browse all pages (clusters, environments, services, deployments, drivers) with data loading correctly, because the underlying data fetching layer has been swapped from urql to TanStack Query without any visible change in behavior.

**Why this priority**: This is the foundational migration — every page depends on GraphQL queries working correctly. Without this, no other stories are viable.

**Independent Test**: Navigate to every major page in the application and verify that data loads correctly, loading states appear, and error states are handled. Compare behavior against the current urql-based implementation.

**Acceptance Scenarios**:

1. **Given** a user navigates to any page that fetches data via GraphQL, **When** the page loads, **Then** the correct data is displayed with appropriate loading indicators, identical to current behavior.
2. **Given** a GraphQL query fails (e.g., network error, server error), **When** the user is on an affected page, **Then** an appropriate error state is shown to the user.
3. **Given** a page uses conditional fetching (previously urql's `pause` pattern), **When** the condition is not met, **Then** the query does not execute until the condition becomes true.

---

### User Story 2 - Mutations Continue to Work Correctly (Priority: P1)

As a user performing create, update, or delete operations (e.g., creating a cluster, deploying a service, editing an environment), I can complete these operations successfully because all GraphQL mutations have been migrated to TanStack Query mutation hooks.

**Why this priority**: Mutations are equally critical to queries — users cannot manage deployments without working mutations. This is co-priority with Story 1.

**Independent Test**: Execute every mutation operation in the application (create, update, delete for each entity type) and verify the operation completes, the UI reflects the change, and related data is refreshed.

**Acceptance Scenarios**:

1. **Given** a user submits a form that triggers a GraphQL mutation, **When** the mutation succeeds, **Then** the UI updates to reflect the change and related query data is refreshed.
2. **Given** a user submits a form that triggers a GraphQL mutation, **When** the mutation fails, **Then** the user sees an appropriate error message and can retry.
3. **Given** a mutation completes that affects data shown on the current page, **When** the mutation succeeds, **Then** stale data is automatically invalidated and re-fetched.

---

### User Story 3 - Automatic Data Refresh (Priority: P2)

As a user monitoring deployment status, I see data automatically refresh at regular intervals so I can track progress without manually reloading the page, because the existing auto-refresh behavior has been preserved using TanStack Query's built-in refresh interval capability.

**Why this priority**: Auto-refresh is important for the deployment monitoring use case but is not blocking for basic functionality.

**Independent Test**: Navigate to a page with auto-refresh enabled, wait for the configured interval, and verify that data updates without user interaction.

**Acceptance Scenarios**:

1. **Given** a user is on a page with auto-refresh enabled, **When** the configured refresh interval elapses, **Then** the data is automatically re-fetched and the UI updates.
2. **Given** a user navigates away from an auto-refreshing page, **When** they leave the page, **Then** the automatic refresh stops (no unnecessary network requests).

---

### User Story 4 - Developer Experience Improvements (Priority: P2)

As a developer working on the Styrmin frontend, I can use TanStack Query DevTools in development mode to inspect query states, cache contents, and debug data fetching issues, providing better observability into the data layer.

**Why this priority**: Developer experience improvements accelerate future development but are not user-facing.

**Independent Test**: Start the development server, open the browser, and verify that TanStack Query DevTools panel is accessible and shows active queries, their states, and cached data.

**Acceptance Scenarios**:

1. **Given** a developer runs the frontend in development mode, **When** they open the application in a browser, **Then** TanStack Query DevTools are accessible and show all active queries and their states.
2. **Given** the application is built for production, **When** deployed, **Then** DevTools are not included in the production bundle.

---

### User Story 5 - Test Infrastructure Support (Priority: P2)

As a developer writing tests for frontend components, I have access to a test utility wrapper that provides TanStack Query context, so I can write component tests that involve data fetching without additional setup.

**Why this priority**: Test infrastructure enables reliable testing of all migrated components but is a developer-facing concern.

**Independent Test**: Write a simple component test that uses a TanStack Query hook and verify it runs successfully using the provided test utilities.

**Acceptance Scenarios**:

1. **Given** a developer writes a component test for a component that uses TanStack Query, **When** they use the test utility wrapper, **Then** the component renders correctly with mocked or provided query data.
2. **Given** existing tests that were passing before the migration, **When** the test suite is run after migration, **Then** all previously passing tests continue to pass.

---

### Edge Cases

- What happens when the network connection is lost mid-query? Retry behavior should handle transient failures gracefully with configurable retry counts and backoff.
- What happens when a user rapidly navigates between pages? Query deduplication and cancellation should prevent race conditions and unnecessary requests.
- What happens when cached data becomes stale while the user is on a page? The stale-while-revalidate strategy should show cached data immediately while fetching fresh data in the background.
- What happens when multiple components on the same page request the same data? Query deduplication should ensure only one network request is made.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST fetch and display data from all 14 existing GraphQL queries through TanStack Query hooks with identical behavior to current implementation.
- **FR-002**: System MUST execute all 14 existing GraphQL mutations through TanStack Query mutation hooks with identical behavior to current implementation.
- **FR-003**: System MUST support conditional query execution (equivalent to current `pause` pattern) using an `enabled` option.
- **FR-004**: System MUST automatically invalidate and re-fetch related queries when a mutation succeeds.
- **FR-005**: System MUST support automatic periodic data refresh to replace the existing `useAutoRefresh` hook pattern.
- **FR-006**: System MUST generate typed hooks from `.graphql` operation files via GraphQL codegen, preserving full type safety.
- **FR-007**: System MUST provide a centralized query client configuration with sensible defaults for caching, retries, and stale time.
- **FR-008**: System MUST include query debugging tools in development builds only.
- **FR-009**: System MUST provide a test utility wrapper that supplies query context for component testing.
- **FR-010**: System MUST remove all urql dependencies from the project after migration is complete.
- **FR-011**: System MUST preserve all existing user-facing behavior — no functional regressions.

### Key Entities

- **Query Client**: Central configuration object that manages query defaults (stale time, retry behavior, cache time) and provides methods for cache invalidation.
- **Query**: A cached, auto-managed data fetch tied to a unique key. Maps 1:1 to existing GraphQL query operations.
- **Mutation**: A triggered data modification operation that can invalidate related queries on success. Maps 1:1 to existing GraphQL mutation operations.
- **Query Key**: A structured identifier used to uniquely identify and manage cached query data, enabling targeted invalidation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 28 GraphQL operations (14 queries, 14 mutations) function correctly — zero functional regressions visible to users.
- **SC-002**: All existing frontend tests pass after migration with no test modifications beyond updating the test wrapper.
- **SC-003**: Page load and data display behavior is indistinguishable from the current implementation from a user's perspective.
- **SC-004**: Zero references to the previous data fetching library remain in the codebase after migration.
- **SC-005**: Developers can inspect all active queries, cache state, and mutation status through debugging tools in development mode.
- **SC-006**: Data automatically refreshes on pages that previously had auto-refresh, with the same or better refresh behavior.
- **SC-007**: Generated hook types provide full type safety matching or exceeding the current codegen output.

## Assumptions

- The existing 28 `.graphql` operation files will be reused as-is — no changes to the GraphQL operations themselves are needed.
- The codegen plugin for TanStack Query supports all patterns currently in use (queries, mutations, conditional execution).
- The migration can be done incrementally per-component if needed, but the end state removes urql entirely.
- Route-level data loading integration with TanStack Router will be evaluated during planning and documented as a decision, but is not a hard requirement for the initial migration.
- The backend GraphQL API requires no changes — this is a frontend-only migration.
