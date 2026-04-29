## ADR-011: Replace urql with TanStack Query for GraphQL Data Fetching

**Status**: Accepted
**Date**: 2026-04-26
**Source**: specs/archive/001-tanstack-query-migration/research.md (R1–R10)

## Context

The frontend previously used urql (`@urql/core` + `@urql/exchange-graphcache`) to execute 28 GraphQL operations (14 queries, 14 mutations) generated from `.graphql` files via `graphql-codegen`. Cache invalidation after mutations was performed by manually calling `reexecute({ requestPolicy: "network-only" })` on every consumer, and a custom `useAutoRefresh` hook polled queries on a setInterval. There was no built-in DevTools surface and the conditional-fetch primitive (`pause: true`) inverted the natural reading of "fetch when ready".

Adoption of TanStack Router (ADR-010) created momentum to standardize on the TanStack ecosystem, and TanStack Query was the natural data-layer counterpart: declarative cache invalidation, built-in `refetchInterval`, first-class DevTools, and a codegen plugin (`@graphql-codegen/typescript-react-query`) compatible with the team's existing `.graphql` file workflow.

## Decision

Replace urql with TanStack Query in a single big-bang migration:

1. Adopt `@graphql-codegen/typescript-react-query` to generate typed `useQuery` / `useMutation` hooks (with auto-generated query-key factories like `['GetCluster', { id }]`) directly from the existing `.graphql` files — no operation file changes.
2. Use a thin **native-`fetch`-based fetcher function** wired into the codegen `fetcher` config; do not introduce `graphql-request` as a dependency.
3. Configure a single `QueryClient` (in `src/lib/query-client.ts`) with project-wide defaults: `staleTime: 0`, `gcTime: 5 min`, queries `retry: 3`, mutations `retry: 0`, `refetchOnWindowFocus: true`. Provide it via `QueryClientProvider` at the app root.
4. Replace urql's `pause: !cond` with TanStack Query's `enabled: cond`.
5. Replace the custom `useAutoRefresh` hook with per-query `refetchInterval` (which automatically pauses on hidden tabs).
6. Cache invalidation lives in mutation `onSuccess` callbacks via `queryClient.invalidateQueries({ queryKey: [...] })` — never via direct `setQueryData` and never via re-running queries by hand.
7. Lazy-mount `@tanstack/react-query-devtools` behind `import.meta.env.DEV` so it ships only in dev builds.
8. Extend `frontend/src/test/utils.tsx` with a per-test `QueryClient` (retries off, gc off) wrapped in `QueryClientProvider`.
9. Defer route-level data loading (TanStack Router `loader` + `queryClient.ensureQueryData`) to a future enhancement; the initial migration keeps component-level fetching to limit blast radius.
10. Remove all urql packages.

## Consequences

**Easier:**

- Mutations declare their invalidation surface inline (`onSuccess` → `invalidateQueries`), so cache freshness is no longer the consumer's problem.
- Polling, retry, and stale handling are query options rather than separate mechanisms; the bespoke `useAutoRefresh` hook is gone.
- DevTools provide visibility into query state, cache contents, and inflight mutations — previously absent.
- Generated query keys make targeted vs broad invalidation symmetric (`['GetCluster']` invalidates all, `['GetCluster', { id }]` invalidates one).

**Harder:**

- Mutation success handlers must enumerate the query keys they affect; forgetting one leaves stale UI. (Mitigated by codegen producing predictable key shapes.)
- The `staleTime: 0` default preserves urql-equivalent freshness but means every mount triggers a refetch; tuning per-query is a future concern.
- Route-level data loading is *not* used yet — page components still fetch on render. Migrating to router loaders later is a follow-up architectural change, not a free upgrade.

## Alternatives Considered

- **graphql-request as the fetcher**: Adds a dependency for what is one `fetch()` call against `/graphql`. Rejected as unnecessary.
- **genql**: TypeScript-first GraphQL client that replaces `.graphql` files with TS code. Rejected — would invalidate the existing operation file workflow.
- **Manual hooks (no codegen plugin)**: Hand-written wrappers around `useQuery`/`useMutation`. Rejected — reintroduces the maintenance burden codegen exists to remove.
- **Optimistic updates / `setQueryData` after mutations**: Rejected as scope creep; the app does not need optimistic UI today, and direct cache writes duplicate server logic.
- **Route-level loaders from day one**: Powerful but a separate architectural shift on top of a library swap. Rejected to keep migration scope bounded; revisit once TanStack Query is settled.
- **Incremental dual-library migration**: Running urql and TanStack Query providers in parallel during a phased rollout. Rejected — at ~38 hook call sites the dual-provider state costs more in confusion than the big-bang risks.
