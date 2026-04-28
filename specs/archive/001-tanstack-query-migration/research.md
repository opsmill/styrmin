# Research: Replace urql with TanStack Query

**Feature**: 001-tanstack-query-migration
**Date**: 2026-04-03

## R1: GraphQL Codegen Plugin for TanStack Query

**Decision**: Use `@graphql-codegen/typescript-react-query` plugin to generate TanStack Query hooks from existing `.graphql` files.

**Rationale**: This plugin is the official Guild-maintained codegen plugin for TanStack Query. It generates typed `useQuery` and `useMutation` hooks directly from GraphQL operations, matching the current pattern of generated urql hooks. It supports TanStack Query v5 and generates hooks with proper query key factories.

**Alternatives considered**:
- **Manual hook creation**: Writing custom hooks wrapping `useQuery`/`useMutation` with a generic `graphql-request` fetcher. More control but loses the automatic type generation that the team relies on. Rejected for higher maintenance burden.
- **genql**: Alternative type-safe GraphQL client. Rejected because it replaces the `.graphql` file approach entirely, requiring rewriting all operations as TypeScript.
- **graphql-request + custom fetcher**: Using `graphql-request` as the fetcher with hand-written TanStack Query hooks. Viable but unnecessary given the codegen plugin exists.

## R2: GraphQL Transport / Fetcher Function

**Decision**: Use a lightweight custom fetcher function using the native `fetch` API, configured in the codegen plugin.

**Rationale**: The codegen plugin supports a `fetcher` configuration that generates hooks using a custom fetch function. Since the current urql setup is minimal (just `cacheExchange` + `fetchExchange` hitting `/graphql`), a simple `fetch`-based function is sufficient. No need for `graphql-request` as an additional dependency.

**Alternatives considered**:
- **graphql-request**: Popular GraphQL client library. Adds an unnecessary dependency when native `fetch` suffices for the simple request pattern used here.
- **urql core as fetcher**: Keeping `@urql/core` solely as a transport layer. Rejected because it defeats the purpose of the migration and adds confusion.

## R3: Query Key Strategy

**Decision**: Use the codegen-generated query key factories. The `@graphql-codegen/typescript-react-query` plugin automatically generates unique query keys based on operation name and variables.

**Rationale**: Consistent, automatic query key generation ensures cache invalidation works correctly. The plugin generates keys like `['GetCluster', { id: '...' }]` which enables both broad invalidation (all `GetCluster` queries) and targeted invalidation (specific cluster by ID).

**Alternatives considered**:
- **Manual key constants**: Defining query keys in a separate file. More explicit but creates a maintenance burden that must stay in sync with operations.

## R4: Cache Invalidation Strategy After Mutations

**Decision**: Use `queryClient.invalidateQueries()` in mutation `onSuccess` callbacks to invalidate related queries. This replaces the current `reexecute({ requestPolicy: "network-only" })` pattern.

**Rationale**: TanStack Query's invalidation model is declarative — you specify which query keys to invalidate, and it automatically refetches active queries. This is more maintainable than the current manual `reexecute` calls and handles cases where multiple components use the same query.

**Alternatives considered**:
- **Optimistic updates**: Updating cache immediately before server confirms. More complex and unnecessary for this migration — the current app doesn't use optimistic updates.
- **Cache manipulation via `setQueryData`**: Directly updating cached data after mutation. Brittle and requires duplicating server logic client-side.

## R5: Conditional Query Execution (pause → enabled)

**Decision**: Replace urql's `pause` option with TanStack Query's `enabled` option. The mapping is direct: `pause: !condition` becomes `enabled: condition`.

**Rationale**: Both serve identical purposes — preventing query execution until a condition is met. The semantic inversion (`pause` = don't run vs `enabled` = do run) is the only difference. Only 2 instances exist in the codebase (both in `DeploymentDetailPage.tsx`), making this a low-risk change.

**Alternatives considered**: None — this is a direct 1:1 mapping with no alternative approaches.

## R6: Auto-Refresh Migration

**Decision**: Replace the custom `useAutoRefresh` hook with TanStack Query's built-in `refetchInterval` option on individual queries.

**Rationale**: TanStack Query natively supports polling via `refetchInterval` on a per-query basis. This eliminates the need for a custom hook that manually calls `reexecute()`. The built-in approach also automatically pauses refetching when the browser tab is not focused (via `refetchIntervalInBackground: false`), which is better default behavior.

**Alternatives considered**:
- **Keep `useAutoRefresh` adapted for TanStack Query**: Modifying the hook to call `queryClient.invalidateQueries()` instead of `reexecute()`. Viable but unnecessary complexity when the built-in option exists.
- **Route-level polling via TanStack Router loaders**: Possible but mixes concerns. Polling is a data-layer concern, not a routing concern.

## R7: TanStack Router Integration (Route-Level Data Loading)

**Decision**: Defer route-level data loading integration to a future enhancement. The initial migration will use TanStack Query hooks at the component level, matching the current urql pattern.

**Rationale**: Route-level data loading via TanStack Router's `loader` option is powerful but represents a significant architectural change beyond the scope of a library swap. The current component-level fetching pattern works well and is the lower-risk migration path. Route-level integration can be evaluated as a separate initiative once the TanStack Query foundation is in place.

**Alternatives considered**:
- **Implement route-level loading immediately**: Using `loader` functions with `queryClient.ensureQueryData()` in route definitions. More powerful (data fetches start before component renders) but significantly increases migration scope and changes the data loading architecture.

## R8: DevTools Configuration

**Decision**: Use `@tanstack/react-query-devtools` with lazy loading, rendered only in development mode.

**Rationale**: TanStack Query DevTools provide visual inspection of queries, cache state, and mutation status. The `ReactQueryDevtools` component supports lazy loading and is automatically excluded from production builds when wrapped in a `process.env.NODE_ENV` check (or Vite's `import.meta.env.DEV`).

**Alternatives considered**: None — DevTools are a standard part of TanStack Query adoption.

## R9: Test Utility Setup

**Decision**: Extend the existing test utility wrapper (`frontend/src/test/utils.tsx`) to include a `QueryClientProvider` with a test-specific `QueryClient` that has retries disabled and no garbage collection.

**Rationale**: The current test utils already provide a custom `render()` function with TanStack Router context. Adding `QueryClientProvider` follows the same pattern. Disabling retries in tests prevents flaky assertions. Each test gets a fresh `QueryClient` to avoid cache pollution between tests.

**Alternatives considered**:
- **MSW (Mock Service Worker) integration**: Mocking at the network level. Valuable for integration tests but orthogonal to the base utility setup — can be added separately.

## R10: Migration Strategy (Incremental vs Big Bang)

**Decision**: Big-bang migration — convert all operations in a single pass, then remove urql.

**Rationale**: The frontend has only ~11 page components with ~38 hook invocations. This is small enough to migrate in one pass without risking a prolonged dual-library state. An incremental approach would require both urql and TanStack Query providers simultaneously, adding complexity without meaningful risk reduction at this scale.

**Alternatives considered**:
- **Incremental per-page migration**: Converting one page at a time while keeping both libraries. Useful for large codebases but overkill for ~11 pages. Creates a confusing dual-provider state during transition.
