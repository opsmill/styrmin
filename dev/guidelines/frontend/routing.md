<!-- Extracted from specs/001-tanstack-router-migration on 2026-04-26 -->

## Frontend Routing Guidelines

Conventions for adding and modifying routes with TanStack Router. See [knowledge/frontend/routing.md](../../knowledge/frontend/routing.md) for the architectural overview.

### Route Definitions

- **Use code-based routing.** Do not introduce file-based routing or the TanStack Router Vite plugin — the route tree is small and an explicit assembly is easier to review.
- One route per file in `src/routes/`. Compose them in `src/routeTree.ts` via `rootRoute.addChildren([...])`.
- Use the `$paramId` syntax (e.g. `/environments/$environmentId`). `:paramId` is React Router and must not appear in new code.
- Always go through `lazyRouteComponent(() => import("..."))` for page components. Do not introduce ad-hoc `React.lazy` + `<Suspense>` for page code-splitting; the router owns pending state.

<!-- Extracted from specs/012-driver-detail-tabs on 2026-08-04 -->

### In-page state stays out of the URL

Detail-page tab selection and sub-selections (which driver version, which row is
expanded) are **component-local `useState`**, not URL search params. Every detail
page does it this way — `DeploymentDetailPage`, `DriverDetailPage` — and a new page
must match.

- **Do not add `validateSearch` + `useSearch` for tab state on one page.** URL
  persistence is genuinely better (shareable and bookmarkable links, state that
  survives a reload), but it is a **uniform** change across every detail page in one
  spec, not something adopted page by page. One page behaving differently from its
  siblings is worse than all of them lacking the feature.
- Keep the state in the page component that owns both the tab strip and the panels,
  so switching versions preserves the active tab and vice versa.

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

<!-- Extracted from specs/011-admin-user-group-mgmt on 2026-05-13 -->

### Role-gated routes

See [`knowledge/frontend/routing.md`](../../knowledge/frontend/routing.md) → "Auth and role-gated routes" for the architectural shape and the list of gated paths.

- Admin-only routes MUST gate in `beforeLoad` against `context.auth.currentUser.effectiveRole`, throwing `redirect({ to: "/" })` when the effective role is insufficient. The check MUST be synchronous — no `useEffect`, no loading flicker, no rendering of the page body before redirecting. The URL bar must never flash an admin path that the user cannot access.
- UI affordances for admin actions (nav links, action buttons, menu items) MUST be hidden via `<IfRole minimum="ADMIN">` (or `useEffectiveRole()` for conditional logic). They MUST NOT merely be disabled — a disabled control still reveals the feature's existence and tempts the user to look for a workaround.
- Role checks MUST read `effectiveRole`, which aggregates the user's direct role with every group-conferred role. Never read the raw `role` field for gating — it skips the group-conferred admin pathway and produces incorrect denials for users who are admin only via group membership.

### Tests

- Every test that renders a routed component goes through the `customRender` in `src/test/utils.tsx`, which builds a fresh `Router` per test from `createMemoryHistory`. Do not import `MemoryRouter` from `react-router` (it has been removed) and do not share router instances across tests.
- For tests that need a typed `useParams`, register the relevant route in the test router rather than mocking the hook.

<!-- Added for issue #332 on 2026-09-17 -->

### Browser tab titles

Every page component calls `useDocumentTitle()` from `@/hooks/use-document-title`
exactly once, producing a tab title in the `<page> · Styrmin` shape. `index.html`
carries the bare `Styrmin` as the pre-mount default.

- **Call it before any early return.** Detail pages return early for loading and
  error state; a hook placed after those returns breaks the rules of hooks.
- **Pass a static label on list and form pages**, matching the sidebar or the
  `PageLayout` title so the tab and the page agree: `useDocumentTitle("Drivers")`.
- **Pass the loaded object's name on detail pages, with a static fallback** for
  the window where the query is still in flight:

  ```tsx
  useDocumentTitle(deployment?.name ?? "Deployment");
  ```

  The fallback names the page rather than showing a placeholder, so the tab is
  never blank and never briefly wrong.

The title is deliberately **not** declared on the route. TanStack Router's `head`
option only sees route params and loader data, and these pages fetch through
TanStack Query inside the component, so a route-level title could not name the
object. One mechanism that covers both cases beats two that each cover half.
