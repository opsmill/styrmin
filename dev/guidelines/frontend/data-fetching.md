<!-- Extracted from specs/001-tanstack-query-migration on 2026-04-26 -->

## Frontend Data Fetching Guidelines

Conventions for using TanStack Query in the frontend. See [knowledge/frontend/data-fetching.md](../../knowledge/frontend/data-fetching.md) for the architectural overview.

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

<!-- Extracted from specs/012-driver-detail-tabs on 2026-08-04 -->

### Reconcile local selection against every refresh

When a polled query feeds a list the user selects from (a version rail, a row
table), the selected id is local state and the list is not — a refresh can remove
the selected entry out from under the component. Reconcile in a `useEffect` keyed on
the fetched collection:

- Selected entry still present → **keep the selection unchanged.** Do not re-derive
  it from the list on every poll; that resets the user's choice every interval.
- Selected entry gone → **fall back silently** to the natural default (newest
  first, or the first row).

Silently, because the trigger was a background poll the user did not initiate — a
toast for something they did not do erodes trust in the page. Enumerate the
fallback as a named test case; it is the branch that rots.

```ts
useEffect(() => {
  if (!versions?.length) return;
  setSelectedId((current) =>
    current && versions.some((v) => v.id === current) ? current : versions[0].id,
  );
}, [versions]);
```

Note the current behaviour on a **failed** poll: any `error` from the query
replaces the page with `<ErrorState>`, including a transient failure mid-refresh.
That is consistent across detail pages and is a known limitation, not a
per-feature bug — retaining the last-good snapshot behind a non-blocking banner is
a project-wide change, not something to fix in one page.

### Rendering `JSON` scalar fields

A GraphQL `JSON` scalar arrives as `unknown`. It carries a shape the backend does
not validate on the way out (driver-declared `components` is the canonical case), so
**treat it as untrusted input and guard before iterating**:

```ts
function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

if (!isPlainObject(components)) return <EmptyState />;
```

- Check the container, then each value you descend into. Skip an
  unexpectedly-shaped entry rather than failing the whole render.
- Degrade to the section's empty state; never throw and never render `[object
  Object]`.
- **Do not mirror the payload in a hand-written TypeScript interface or a strict
  Zod schema** for read-only display. Runtime guards plus optional chaining absorb
  new fields the producer adds without a frontend change — which is the point, since
  driver authors extend these blobs freely.
- Render known keys explicitly and unknown scalar keys generically, so a driver that
  declares something new shows up instead of disappearing.
