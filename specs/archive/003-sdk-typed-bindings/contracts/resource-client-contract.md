# Contract: Resource Classes ↔ Generated Response Types

**Feature**: 003-sdk-typed-bindings | **Date**: 2026-04-01

## Overview

This contract defines how SDK resource classes use ariadne-codegen generated response types for validation, replacing hand-written Pydantic models. The execution layer (Transport + load_query) is unchanged.

## Flow (BEFORE → AFTER)

### Before

```
Resource                        Transport                    Server
   |                               |                           |
   |--- load_query("op_name") --->|                            |
   |--- execute(query, vars) ---->|--- POST /graphql --------->|
   |<-- dict (full response) -----|<-- JSON response ----------|
   |--- _check_graphql_errors --->|                            |
   |--- HandWrittenModel.model_validate(result["data"]["key"])
   |--- return HandWrittenModel   |                            |
```

### After

```
Resource                        Transport                    Server
   |                               |                           |
   |--- load_query("op_name") --->|                            |
   |--- execute(query, vars) ---->|--- POST /graphql --------->|
   |<-- dict (full response) -----|<-- JSON response ----------|
   |--- _check_graphql_errors --->|                            |
   |--- OuterType.model_validate(result["data"])
   |--- return data.inner_field   |                            |
```

**What changed**: Only the last two lines. Instead of `HandWrittenModel.model_validate(result["data"]["key"])`, we use `OuterType.model_validate(result["data"]).inner_field`.

## Interface: BaseResource (UNCHANGED)

```python
@dataclass
class BaseResource:
    _transport: Transport = field(repr=False)

    @staticmethod
    def _check_graphql_errors(result: dict[str, Any]) -> None:
        """Inspect result['errors'] and raise SDK exceptions. UNCHANGED."""
        ...
```

## Interface: StyrminClient (UNCHANGED)

```python
class StyrminClient:
    def __init__(self, server_address, timeout, headers):
        self._transport = Transport(server_address, timeout, headers)
        self.clusters = ClusterResource(self._transport)
        # ... all resources get _transport (same as today)
```

## Resource Method Pattern

### Before (example: ClusterResource.create)

```python
async def create(self, name: str, config: JsonValue | None = None) -> Cluster:
    variables: dict[str, Any] = {"name": name}
    if config is not None:
        variables["config"] = config
    result = await self._transport.execute(load_query("create_cluster"), variables)
    self._check_graphql_errors(result)
    return Cluster.model_validate(result["data"]["createCluster"])
```

### After

```python
from styrmin_sdk.graphql._generated.create_cluster import CreateCluster

async def create(self, name: str, config: JsonValue | None = None) -> CreateClusterCreateCluster:
    variables: dict[str, Any] = {"name": name}
    if config is not None:
        variables["config"] = config
    result = await self._transport.execute(load_query("create_cluster"), variables)
    self._check_graphql_errors(result)
    data = CreateCluster.model_validate(result["data"])
    return data.create_cluster
```

### List operations (after)

```python
from styrmin_sdk.graphql._generated.list_clusters import ListClusters

async def list(self) -> list[ListClustersClusters]:
    result = await self._transport.execute(load_query("list_clusters"))
    self._check_graphql_errors(result)
    data = ListClusters.model_validate(result["data"])
    return data.clusters or []
```

### Delete operations (UNCHANGED)

```python
async def delete(self, cluster_id=None, cluster_name=None) -> None:
    variables = ...
    result = await self._transport.execute(load_query("delete_cluster"), variables)
    self._check_graphql_errors(result)
    # No model validation — error check is sufficient
```

## Response Extraction Contract

Each generated outer type has a single field containing the actual data. Resource methods extract this inner field:

| Pattern | Outer Type | Inner Attribute | Return Type |
|---------|-----------|-----------------|-------------|
| Create/Mutate | `CreateCluster` | `create_cluster` | Inner model |
| Get | `GetCluster` | `cluster` | Inner model |
| List | `ListClusters` | `clusters` | `list[InnerModel]` |
| Delete | N/A | N/A | `None` or `bool` |
| Assign/Unassign | N/A | N/A | `None` |

## Error Handling Contract (UNCHANGED)

Error handling operates on the raw `result` dict **before** model validation:

```python
result = await self._transport.execute(load_query("op"), variables)
self._check_graphql_errors(result)  # raises SDK exceptions if errors present
# Only reaches here if no errors
data = OuterType.model_validate(result["data"])
```

| Error Code | SDK Exception |
|------------|--------------|
| `NOT_FOUND` | `ResourceNotFoundError` |
| `ALREADY_EXISTS` | `ResourceAlreadyExistsError` |
| Other | `OperationFailedError` |

## Backward Compatibility Contract

| Aspect | Guarantee |
|--------|-----------|
| `StyrminClient` constructor signature | Unchanged |
| Resource method signatures | Unchanged |
| Exception types and hierarchy | Unchanged |
| `from styrmin_sdk import Cluster` | Works (re-exported alias) |
| `from styrmin_sdk import Transport` | Works (kept) |
| `from styrmin_sdk import load_query` | Works if currently exported |
| `Task.type` → `Task.type_` | **BREAKING** — documented |

## Test Contract

Tests continue to mock `Transport.execute()` with raw dicts. The dict structure is unchanged:

```python
# Same as today — Transport mock returns raw GraphQL response dict
mock_transport.execute.return_value = {
    "data": {"createCluster": {"id": "...", "name": "test", "config": None}}
}
```

Assertions change to use generated type attribute names:
```python
result = await client.clusters.create(name="test")
assert result.name == "test"       # same as before
assert result.type_ == "deploy"   # Task only: type → type_
```
