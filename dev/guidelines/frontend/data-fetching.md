<!-- Extracted from specs/001-tanstack-query-migration on 2026-04-26 -->

## Frontend Data Fetching Guidelines

Conventions for using TanStack Query in the frontend. See [knowledge/frontend/data-fetching.md](../../knowledge/frontend/data-fetching.md) for the architectural overview and [ADR-011](../../adr/adr-011-replace-urql-with-tanstack-query.md) for context.

### Operation Authoring

- All GraphQL operations live in `frontend/src/graphql/*.graphql`, one operation per file. Inline GraphQL strings in TypeScript are not allowed.
- Always consume operations through the **codegen-generated hooks** in `src/generated/`. Do not hand-write `useQuery`/`useMutation` wrappers — the generated hooks include typed query-key factories that the rest of these guidelines depend on.
- Run `pnpm codegen` after editing any `.graphql` file. CI fails if `src/generated/` is out of date.

### Query Keys and Invalidation

- Use the generated `getKey()` factories. Do not hand-write key tuples.
- Invalidation is the **mutation's** responsibility, not the consumer's. In every mutation `onSuccess`, list the query keys whose freshness the mutation breaks.

  ```ts
  const createCluster = useCreateClusterMutation({
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: useListClustersQuery.getKey() });
    },
  });
  ```

- Prefer broad invalidation (`getKey()` with no variables) over targeted invalidation when in doubt. Stale data is a worse failure than an extra refetch.
- Do not use `queryClient.setQueryData` to write into the cache directly. Server response shapes evolve, and direct cache writes duplicate server logic.
- Do not call `refetch()` manually as a substitute for invalidation; if a mutation should refresh data, declare that in `onSuccess`.

### Conditional Fetching

- Use `enabled: cond` for any query that should not fire until a condition is met.

  ```ts
  useGetDeploymentQuery({ id }, { enabled: !!id });
  ```

- The urql-era `pause` option is gone — never reintroduce a `pause: !cond` pattern.

### Polling / Auto-Refresh

- Use the per-query `refetchInterval` option for polling. Do not add a custom `useAutoRefresh`-style hook; the previous one was removed deliberately.

  ```ts
  useGetDeploymentQuery({ id }, { refetchInterval: 3000 });
  ```

- TanStack Query pauses polling on hidden tabs by default — do not override `refetchIntervalInBackground` without a documented reason.

### Fetcher / Transport

- The fetcher is a small `fetch`-based function wired into the codegen `fetcher` config. Do not add `graphql-request` (or any other GraphQL client library) — there is no supported pattern for using one alongside the codegen plugin in this codebase.

### Route-Level Data Loading

- Component-level fetching (a hook in the page component) is the current standard. Do not introduce TanStack Router `loader` functions on a per-page basis — adopting route loaders is a project-wide architectural shift, not an individual-feature decision.

### DevTools

- `@tanstack/react-query-devtools` is mounted lazily and gated by `import.meta.env.DEV`. Do not unconditionally import or render it; it must not ship to production.

### Tests

- Use the `customRender` from `src/test/utils.tsx`, which already wraps children in a `QueryClientProvider` with retries off and gc off. Do not construct a `QueryClient` per test by hand.
- Do not assume cache state survives across tests — each test builds a fresh `QueryClient`.
