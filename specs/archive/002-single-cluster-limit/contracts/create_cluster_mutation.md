# Contract: createCluster Mutation

**Feature**: `002-single-cluster-limit` | **Date**: 2026-03-28

## GraphQL Mutation

### Before (current)

```graphql
type Mutation {
  createCluster(name: String!, config: JSON): Cluster
}
```

### After (proposed)

```graphql
type Mutation {
  createCluster(name: String! = "default", config: JSON): Cluster
}
```

**Change**: `name` parameter gains a default value of `"default"`. It remains non-null (`String!`) — callers can still provide a custom name, but omitting it results in `"default"`.

## Behavior Changes

### Success (no cluster exists)

**Request**:
```graphql
mutation {
  createCluster(config: { ingress_class: "traefik" }) {
    id
    name
    config
  }
}
```

**Response**:
```json
{
  "data": {
    "createCluster": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "default",
      "config": { "ingress_class": "traefik", "runtime_class": "default", "dedicated_ingress": {} }
    }
  }
}
```

### Error (cluster already exists)

**Request**:
```graphql
mutation {
  createCluster(name: "second-cluster") {
    id
    name
  }
}
```

**Response**:
```json
{
  "errors": [
    {
      "message": "Only one cluster is allowed. Delete the existing cluster before creating a new one.",
      "extensions": {
        "code": "CLUSTER_LIMIT_REACHED"
      }
    }
  ],
  "data": {
    "createCluster": null
  }
}
```

## Backward Compatibility

- Callers providing `name` explicitly: **No change** in behavior.
- Callers omitting `name`: **Previously impossible** (was required with no default). Now uses `"default"`.
- Error response format: Follows existing `extensions.code` pattern used by all service errors.

## Required Regeneration Steps

After implementing the backend change:

1. `uv run styrmin export graphql-schema schema.graphql`
2. `uv run invoke generate`
