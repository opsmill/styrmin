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

<!-- Extracted from specs/011-admin-user-group-mgmt on 2026-05-13 -->

### Auth-aware fetching

See [`knowledge/frontend/data-fetching.md`](../../knowledge/frontend/data-fetching.md) → "Authenticated requests and error mapping" for the architectural shape.

- All GraphQL calls MUST go through `graphqlFetcher` (the codegen-wired fetcher). Do not add ad-hoc `fetch('/graphql', ...)` calls — they will not carry the `credentials: 'include'` flag, the unauthenticated handler, or the typed-error mapping.
- Error handlers MUST consume the typed error classes (`UnauthenticatedError`, `ForbiddenError`, `GraphQLOperationError`) via `instanceof`. Never string-match `error.message` to detect auth state — messages are localised, refactored, or wrapped without warning.
- Code MUST NOT attempt to read the session cookie from JavaScript. The cookie is `HttpOnly`; the browser handles transport when `credentials: 'include'` is set. There is no in-memory token mirror, no `document.cookie` read, no `localStorage` shadow.

### Tests

- Use the `customRender` from `src/test/utils.tsx`, which already wraps children in a `QueryClientProvider` with retries off and gc off. Do not construct a `QueryClient` per test by hand.
- Do not assume cache state survives across tests — each test builds a fresh `QueryClient`.

<!-- Extracted from specs/012-deployment-pods-tab on 2026-05-15 -->

### Tab-scoped polling

When a query lives inside an in-app tab or panel that the user may not currently be looking at, gate **both** the query's `enabled` and its `refetchInterval` on the same active-tab boolean:

```ts
useGetDeploymentPodsQuery(
  { deploymentId },
  {
    enabled: isActive,
    refetchInterval: isActive && autoRefreshEnabled ? 10_000 : false,
  },
);
```

- `refetchIntervalInBackground: false` (the default) only suppresses polling on hidden **browser** tabs. It does not help with an in-app tab the user has navigated away from — the gating must be explicit.
- Pair with the existing `AutoRefreshIndicator` if the operator should be able to pause and resume manually; `autoRefreshEnabled` is local component state, `isActive` is the prop from the parent tab container.
- Gating with `enabled: isActive` alone is also acceptable when the previous data should disappear when the tab is inactive. Keep `refetchInterval: false` in the inactive branch either way; otherwise an interval timer keeps firing against a stale `enabled: false` state and refreshes the data the moment the tab reactivates.

The Pods tab on the deployment detail page is the canonical example.
