# Contract: GraphQL Codegen Configuration

**Purpose**: Defines the expected codegen configuration that generates TanStack Query hooks from `.graphql` files.

## Input

- **Schema source**: `../schema.graphql` (backend-generated, no changes)
- **Documents**: `src/graphql/**/*.graphql` (28 operation files, no changes)

## Output

- **Target file**: `src/generated/graphql.ts`

## Plugin Chain

1. `typescript` — generates base TypeScript types from schema
2. `typescript-operations` — generates operation-specific types (query/mutation variables and results)
3. `typescript-react-query` — generates TanStack Query hooks

## Plugin Configuration

```yaml
config:
  reactQueryVersion: 5
  fetcher: "../lib/graphql-fetcher#graphqlFetcher"
  exposeFetcher: false
  exposeQueryKeys: true
  addSuspenseQuery: false
  scalars:
    UUID: string
    JSON: "Record<string, unknown>"
```

## Generated Hook Contract

### Query Hooks

For each query operation (e.g., `GetCluster`):

```typescript
// Query key factory
export const useGetClusterQueryKey = (variables: GetClusterQueryVariables) => ['GetCluster', variables];

// Hook
export const useGetClusterQuery = (
  variables: GetClusterQueryVariables,
  options?: Omit<UseQueryOptions<GetClusterQuery, Error>, 'queryKey' | 'queryFn'>
) => useQuery<GetClusterQuery, Error>({ ... });
```

**Return type**: `UseQueryResult<TData, Error>` with properties:
- `data: TData | undefined`
- `isLoading: boolean` (replaces urql's `fetching`)
- `error: Error | null` (replaces urql's `error`)
- `refetch: () => Promise<...>` (replaces urql's `reexecute`)

### Mutation Hooks

For each mutation operation (e.g., `CreateCluster`):

```typescript
export const useCreateClusterMutation = (
  options?: UseMutationOptions<CreateClusterMutation, Error, CreateClusterMutationVariables>
) => useMutation<CreateClusterMutation, Error, CreateClusterMutationVariables>({ ... });
```

**Return type**: `UseMutationResult` with properties:
- `mutateAsync: (variables) => Promise<TData>` (replaces urql's `execute`)
- `isPending: boolean` (replaces urql's `fetching`)
- `error: Error | null`
- `data: TData | undefined`
