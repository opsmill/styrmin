# SDK API Changes for Name-Based Resource Lookup

**Feature**: 001-graphql-name-lookup
**Date**: 2026-03-29

## ClusterResource

### `get(cluster_id=None, cluster_name=None) -> Cluster`

**Before**: `get(cluster_id: str | UUID) -> Cluster`
**After**: Both params optional, exactly one required.

```python
# By UUID (existing)
cluster = await sdk.clusters.get(cluster_id="abc-123")

# By name (new)
cluster = await sdk.clusters.get(cluster_name="us-east-1")
```

### `delete(cluster_id=None, cluster_name=None) -> None`

**Before**: `delete(cluster_id: str | UUID) -> None`
**After**: Both params optional, exactly one required.

## EnvironmentResource

### `get(environment_id=None, environment_name=None, cluster_id=None, cluster_name=None) -> Environment`

**Before**: `get(environment_id: str | UUID) -> Environment`
**After**: ID-based or name-based (with cluster context).

```python
# By UUID (existing)
env = await sdk.environments.get(environment_id="def-456")

# By name + cluster name (new)
env = await sdk.environments.get(environment_name="staging", cluster_name="us-east-1")

# By name + cluster ID (new)
env = await sdk.environments.get(environment_name="staging", cluster_id="abc-123")
```

### `create(name, cluster_id=None, cluster_name=None, config=None) -> Environment`

**Before**: `create(name: str, cluster_id: str | UUID, config=None) -> Environment`
**After**: `cluster_id` becomes optional, `cluster_name` added as alternative.

### `delete(environment_id=None, environment_name=None, cluster_id=None, cluster_name=None) -> None`

**Before**: `delete(environment_id: str | UUID) -> None`
**After**: ID-based or name-based (with cluster context).

## DeploymentResource

### `create(driver, version, environment_id=None, environment_name=None, cluster_id=None, cluster_name=None, ...) -> Task`

**Before**: `create(driver, version, environment_id: str | UUID, ...) -> Task`
**After**: `environment_id` becomes optional, name-based alternative added.

## GraphQL Query File Changes

Each `.graphql` file in `python_sdk/src/styrmin_sdk/graphql/` is updated to include optional name variables. Example for `get_cluster.graphql`:

```graphql
# Before
query GetCluster($clusterId: UUID!) {
    cluster(clusterId: $clusterId) { id name config }
}

# After
query GetCluster($clusterId: UUID, $clusterName: String) {
    cluster(clusterId: $clusterId, clusterName: $clusterName) { id name config }
}
```
