# Contract: Hook Migration Map

**Purpose**: Documents the 1:1 mapping between current urql hook patterns and their TanStack Query replacements.

## API Surface Changes

### Query Hook Usage

| urql Pattern | TanStack Query Pattern |
|-------------|----------------------|
| `const [{ data, fetching, error }, reexecute] = useXxxQuery({ variables })` | `const { data, isLoading, error, refetch } = useXxxQuery(variables)` |
| `fetching` | `isLoading` (first load) or `isFetching` (any fetch including background) |
| `error` (CombinedError) | `error` (Error) |
| `reexecute({ requestPolicy: "network-only" })` | `refetch()` or `queryClient.invalidateQueries()` |
| `pause: condition` | `enabled: !condition` (note: inverted boolean) |

### Mutation Hook Usage

| urql Pattern | TanStack Query Pattern |
|-------------|----------------------|
| `const [result, execute] = useXxxMutation()` | `const { mutateAsync, isPending, error, data } = useXxxMutation()` |
| `const result = await execute(variables)` | `const data = await mutateAsync(variables)` |
| `result.fetching` | `isPending` |
| `result.error` | `error` |
| `result.data` | `data` |

### Auto-Refresh Pattern

| Current Pattern | TanStack Query Pattern |
|----------------|----------------------|
| `useAutoRefresh({ onRefresh: () => reexecute(...), interval: 10000 })` | `useXxxQuery(variables, { refetchInterval: 10_000 })` |
| `autoRefresh.enabled` / `autoRefresh.setEnabled` | Managed via `enabled` + component state if toggle needed |
| `autoRefresh.refreshNow()` | `refetch()` |
| `autoRefresh.lastRefreshedAt` | `dataUpdatedAt` from query result |

### Conditional Query Pattern

| Current (DeploymentDetailPage.tsx) | TanStack Query |
|-----------------------------------|----------------|
| `useListBackupsQuery({ variables: { instanceId: instanceId! }, pause: !instanceId })` | `useListBackupsQuery({ instanceId: instanceId! }, { enabled: !!instanceId })` |
| `useListRestoresQuery({ variables: { backupId: backup.id }, pause: backup.status !== "completed" })` | `useListRestoresQuery({ backupId: backup.id }, { enabled: backup.status === "completed" })` |

## Provider Change

| Current | New |
|---------|-----|
| `import { Provider } from "urql"` | `import { QueryClientProvider } from "@tanstack/react-query"` |
| `<Provider value={client}>` | `<QueryClientProvider client={queryClient}>` |

## Test Utility Change

| Current | New |
|---------|-----|
| No GraphQL provider in test wrapper | `QueryClientProvider` with test-configured `QueryClient` (retries disabled) |
