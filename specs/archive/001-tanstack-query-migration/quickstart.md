# Quickstart: Replace urql with TanStack Query

**Feature**: 001-tanstack-query-migration
**Date**: 2026-04-03

## Prerequisites

- Node 22+, pnpm installed
- Repository cloned and on `001-tanstack-query-migration` branch
- Backend running (or accessible at `localhost:8000` for dev proxy)

## Setup

```bash
# Install dependencies (after package.json changes)
cd frontend && pnpm install

# Regenerate hooks from .graphql files
pnpm codegen
# or from repo root:
# cd frontend && npx graphql-codegen
```

## Key Files to Understand

| File | Purpose |
|------|---------|
| `frontend/codegen.ts` | Codegen config — controls which plugin generates hooks |
| `frontend/src/lib/query-client.ts` | QueryClient configuration (new) |
| `frontend/src/lib/graphql-fetcher.ts` | GraphQL fetch function (new) |
| `frontend/src/App.tsx` | Provider setup — wraps app with QueryClientProvider |
| `frontend/src/generated/graphql.ts` | Auto-generated hooks (do not edit manually) |
| `frontend/src/test/utils.tsx` | Test wrapper with QueryClient |

## Development Workflow

```bash
# Start dev server
cd frontend && pnpm dev

# Run tests
cd frontend && pnpm test

# Regenerate hooks after modifying .graphql files
cd frontend && pnpm codegen

# Lint and format
cd frontend && pnpm lint && pnpm format
```

## Migration Pattern Reference

### Before (urql)

```typescript
const [{ data, fetching, error }, reexecute] = useListClustersQuery();

// Refresh
reexecute({ requestPolicy: "network-only" });
```

### After (TanStack Query)

```typescript
const { data, isLoading, error, refetch } = useListClustersQuery();

// Refresh
refetch();
```

### Mutations Before

```typescript
const [result, createCluster] = useCreateClusterMutation();
const res = await createCluster({ name: "my-cluster" });
if (res.error) { /* handle error */ }
```

### Mutations After

```typescript
const createCluster = useCreateClusterMutation({
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ListClusters'] }),
});
const data = await createCluster.mutateAsync({ name: "my-cluster" });
```

## Verification

1. **All pages load**: Navigate to every route and verify data appears
2. **Mutations work**: Create/update/delete operations complete and refresh related data
3. **Auto-refresh**: Pages with polling update data automatically
4. **DevTools visible**: In dev mode, TanStack Query DevTools panel appears
5. **Tests pass**: `cd frontend && pnpm test` — all green
6. **No urql references**: `grep -r "urql" frontend/src/` returns nothing
