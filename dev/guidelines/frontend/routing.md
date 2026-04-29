<!-- Extracted from specs/001-tanstack-router-migration on 2026-04-26 -->

## Frontend Routing Guidelines

Conventions for adding and modifying routes with TanStack Router. See [knowledge/frontend/routing.md](../../knowledge/frontend/routing.md) for the architectural overview and [ADR-010](../../adr/adr-010-migrate-frontend-router-to-tanstack.md) for context.

### Route Definitions

- **Use code-based routing.** Do not introduce file-based routing or the TanStack Router Vite plugin — the route tree is small and an explicit assembly is easier to review.
- One route per file in `src/routes/`. Compose them in `src/routeTree.ts` via `rootRoute.addChildren([...])`.
- Use the `$paramId` syntax (e.g. `/environments/$environmentId`). `:paramId` is React Router and must not appear in new code.
- Always go through `lazyRouteComponent(() => import("..."))` for page components. Do not introduce ad-hoc `React.lazy` + `<Suspense>` for page code-splitting; the router owns pending state.

### Type Registration

- The `declare module "@tanstack/react-router"` block in `src/router.ts` is **not optional**. Without it, `Link to=` and `useNavigate({ to })` accept arbitrary strings and lose type safety silently. If you split the router into multiple files, keep the augmentation in the file that exports the live `router` instance.

### Reading Route Params

- Prefer the route-specific `Route.useParams()` over a global `useParams()` import. Route-specific access yields the tightest type (only the params for that route) and surfaces typos at compile time.

  ```tsx
  // good
  const { environmentId } = environmentDetailRoute.useParams();
  // avoid
  const { environmentId } = useParams();
  ```

### Navigation

- Programmatic navigation **must** use the object form: `navigate({ to, params, search })`. Do not interpolate into strings.

  ```tsx
  // good
  navigate({ to: "/drivers/$driverId", params: { driverId: id } });
  // bad
  navigate(`/drivers/${id}`);
  ```

- Same for `<Link>`: pass `to` as a route path with `$param` placeholders and supply values via `params`.

### Active Link Styling

- Use `<Link activeProps={{ className: "..." }} activeOptions={{ exact }}>`. Do not reintroduce `useLocation().pathname` + a manual `isActive` helper — the router has the information natively and the manual approach drifts from the route tree.

### Not Found

- Add `notFoundComponent` on the root route, not a `*` catch-all child. TanStack Router handles unmatched routes structurally.

### Tests

- Every test that renders a routed component goes through the `customRender` in `src/test/utils.tsx`, which builds a fresh `Router` per test from `createMemoryHistory`. Do not import `MemoryRouter` from `react-router` (it has been removed) and do not share router instances across tests.
- For tests that need a typed `useParams`, register the relevant route in the test router rather than mocking the hook.
