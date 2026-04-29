# Quickstart: TanStack Router Migration

## Prerequisites

- Node 22, pnpm installed
- Frontend dev environment working (`pnpm dev` starts successfully)

## Step-by-Step

### 1. Swap dependencies

```bash
cd frontend
pnpm remove react-router
pnpm add @tanstack/react-router
```

### 2. Create route definitions

Create `src/routes/` with route definitions using `createRootRoute` and `createRoute`:

```tsx
// src/routes/__root.tsx
import { createRootRoute, Outlet } from '@tanstack/react-router'
import { AppShell } from '@/components/AppShell'

export const rootRoute = createRootRoute({
  component: AppShell,  // AppShell renders <Outlet /> for child content
  notFoundComponent: () => <div>Page not found</div>,
})
```

```tsx
// src/routes/environmentDetail.tsx
import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { rootRoute } from './__root'

export const environmentDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/environments/$environmentId',
  component: lazyRouteComponent(
    () => import('@/pages/environments/EnvironmentDetailPage'),
  ),
})
```

### 3. Assemble route tree

```tsx
// src/routeTree.ts
import { rootRoute } from './routes/__root'
import { indexRoute } from './routes/index'
import { environmentDetailRoute } from './routes/environmentDetail'
// ... all other routes

export const routeTree = rootRoute.addChildren([
  indexRoute,
  environmentDetailRoute,
  // ... all 11 routes
])
```

### 4. Create router instance with type registration

```tsx
// src/router.ts
import { createRouter } from '@tanstack/react-router'
import { routeTree } from './routeTree'

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
```

### 5. Update App.tsx

```tsx
// src/App.tsx
import { RouterProvider } from '@tanstack/react-router'
import { Provider } from 'urql'
import { client } from '@/lib/urql'
import { router } from '@/router'

export default function App() {
  return (
    <Provider value={client}>
      <RouterProvider router={router} />
    </Provider>
  )
}
```

### 6. Update page components

Replace React Router hooks with TanStack Router equivalents in all page components:

```tsx
// Before (React Router)
import { useParams, useNavigate, Link } from 'react-router'
const { environmentId } = useParams()
navigate(`/environments/${environmentId}`)

// After (TanStack Router)
import { useParams, useNavigate, Link } from '@tanstack/react-router'
const { environmentId } = useParams({ from: '/environments/$environmentId' })
const navigate = useNavigate()
navigate({ to: '/environments/$environmentId', params: { environmentId } })
```

### 7. Update AppShell

```tsx
// Before
import { Outlet, Link, useLocation } from 'react-router'
const { pathname } = useLocation()

// After
import { Outlet, Link, useRouterState } from '@tanstack/react-router'
const pathname = useRouterState({ select: (s) => s.location.pathname })
// Or use Link's activeProps for active styling
```

### 8. Update test utilities

```tsx
// src/test/utils.tsx
import { createRouter, createRootRoute, createMemoryHistory, RouterProvider, Outlet } from '@tanstack/react-router'

const testRootRoute = createRootRoute({ component: () => <Outlet /> })

function customRender(ui: ReactElement, options?: CustomRenderOptions) {
  const router = createRouter({
    routeTree: testRootRoute.addChildren([]),
    history: createMemoryHistory({ initialEntries: [options?.initialLocation ?? '/'] }),
  })
  return render(ui, { wrapper: ({ children }) => <RouterProvider router={router}>{children}</RouterProvider>, ...options })
}
```

### 9. Verify

```bash
pnpm build          # Zero TypeScript errors
pnpm test           # All tests pass
pnpm dev            # Navigate all 11 routes manually
grep -r "from ['\"]react-router" src/  # Zero results
```

## Key Differences to Remember

| Concept | React Router | TanStack Router |
|---------|-------------|----------------|
| Param syntax | `:paramName` | `$paramName` |
| Param types | `string \| undefined` | `string` (non-optional) |
| Navigation | `navigate('/path')` | `navigate({ to: '/path', params: {...} })` |
| Active links | Manual `useLocation` check | `Link` `activeProps` |
| Layout outlet | `<Outlet />` from `react-router` | `<Outlet />` from `@tanstack/react-router` |
| Test router | `<MemoryRouter>` | `createRouter({ history: createMemoryHistory() })` |
