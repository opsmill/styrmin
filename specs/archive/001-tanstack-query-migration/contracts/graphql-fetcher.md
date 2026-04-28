# Contract: GraphQL Fetcher Function

**Purpose**: Defines the fetch function used as the transport layer for all generated TanStack Query hooks.

## Interface

```typescript
function graphqlFetcher<TData, TVariables>(
  query: string,
  variables?: TVariables,
  options?: RequestInit
): () => Promise<TData>
```

## Behavior

1. Sends a `POST` request to `/graphql` (relative URL, same as current urql config)
2. Sets `Content-Type: application/json` header
3. Serializes `{ query, variables }` as the request body
4. Parses the JSON response
5. If response contains `errors`, throws an `Error` with the first error message
6. Returns `response.data` as `TData`

## Error Handling

- **Network errors**: Thrown as-is (native `fetch` errors)
- **GraphQL errors**: Extracted from `response.errors` array, thrown as `Error`
- **HTTP errors**: Non-2xx status codes result in thrown errors

## Configuration

- **Endpoint**: `/graphql` (matches current urql config in `frontend/src/lib/urql.ts`)
- **No authentication headers**: The current setup uses no auth headers (session/cookie based or dev mode)
- **No custom headers**: Matching current minimal setup
