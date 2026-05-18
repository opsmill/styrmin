# ADR-049: SDK leverages ariadne-codegen via outer-wrapper validation and `models/__init__.py` facade re-exports

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/003-sdk-typed-bindings/research.md (Decisions 1, 2, 5, 6)

## Context

The Python SDK historically validated GraphQL responses by hand: each resource method called `Transport.execute(load_query("..."), variables)`, manually pulled the inner field out of `result["data"]["<operation>"]`, and ran `model_validate` against a **hand-written** Pydantic model that mirrored the response shape. Hand-written models silently drift from `schema.graphql` — fields added or renamed on the server have to be remembered, with no compile-time signal.

[`ariadne-codegen`](https://github.com/mirumee/ariadne-codegen) generates Pydantic types directly from `schema.graphql` and the `.graphql` query files in `python_sdk/src/styrmin_sdk/graphql/`. For each operation `FooBar.graphql`, it produces:

- An **outer wrapper type** `FooBar` whose attributes mirror the response's top-level fields (i.e. `FooBar.foo_bar` for a query named `fooBar`).
- An **inner type** per traversed field, named `<Operation><Path>` (e.g. `GetClusterCluster`, `CreateClusterCreateCluster`, `ListClustersClusters`).
- A `Client` class that embeds the query strings and ships its own HTTP layer.

The design space:

1. **Use ariadne's generated `Client` class wholesale**, or keep the existing `Transport.execute()` + `load_query()` pipeline?
2. **Validate against the inner type directly** (still requires manual `result["data"]["<op>"]` indexing), or against the **outer wrapper** (one validation call, then typed attribute access)?
3. **Public API**: operation-specific names like `GetClusterCluster` everywhere, or **facade re-exports** so `from styrmin_sdk import Cluster` still works?

## Decision

### Execution layer — keep Transport + load_query

Keep `Transport.execute(load_query("<op>"), variables)` unchanged. Do **not** switch to the generated `Client` class. The `.graphql` files in `python_sdk/src/styrmin_sdk/graphql/` remain the operation source of truth (they already feed codegen) and the SDK's `_check_graphql_errors()` error-mapping layer stays in one place. Only the **models** change.

### Response validation — outer wrapper

Replace hand-written validation with the generated outer wrapper:

```python
# Before
result = await self._transport.execute(load_query("create_cluster"), variables)
self._check_graphql_errors(result)
return Cluster.model_validate(result["data"]["createCluster"])

# After
result = await self._transport.execute(load_query("create_cluster"), variables)
self._check_graphql_errors(result)
data = CreateCluster.model_validate(result["data"])
return data.create_cluster
```

The outer wrapper validates the full `result["data"]` dict; the inner field is then a typed attribute. Manual dictionary key access disappears.

List operations follow the same shape:

```python
data = ListClusters.model_validate(result["data"])
return data.clusters or []
```

### Delete / assign / unassign — error check only

Operations whose return value is discarded skip model validation entirely. `_check_graphql_errors(result)` on the raw dict is sufficient; no outer-wrapper instantiation is needed.

### Public API — `models/__init__.py` as a facade

Each operation generates its own variant of a type (`GetClusterCluster`, `CreateClusterCreateCluster`, `ListClustersClusters`, …) because GraphQL fragments can differ per query. Field access is identical across variants. `models/__init__.py` re-exports the **"get" operation's** inner type under the original public name:

```python
# models/__init__.py
from styrmin_sdk.graphql._generated.get_cluster import GetClusterCluster as Cluster
from styrmin_sdk.graphql._generated.get_deployment import GetDeploymentDeployment as Deployment
# …
```

Public imports `from styrmin_sdk import Cluster` continue to work; SDK consumers see no rename.

### Hand-written models that survive

- `ApplicationDriver` and `ApplicationDriverVersionSummary` — no list/get driver queries exist in the SDK, so ariadne-codegen produces no types for them.
- `Context` — uses a REST endpoint (`/deployments/{id}/context`), not GraphQL.

These remain hand-written; the facade does not re-export over them.

### Known break

`Task.type` becomes `Task.type_` everywhere because `type` is a Python builtin and `populate_by_name=True` on the generated base lets the JSON shape `"type"` deserialise into the `type_` field. Attribute access has to use `type_`. Documented as a breaking change for SDK consumers.

## Consequences

- Server-side schema changes propagate through `uv run invoke generate` to the SDK with no hand-edits — adding a field to `schema.graphql` and re-running codegen surfaces the new attribute on the generated type. Drift between server schema and SDK models becomes structurally impossible.
- The SDK still owns its transport, error mapping, and operation loading. Bugs in those layers stay localised; ariadne-codegen is a typing source, not a runtime dependency for HTTP / error handling.
- `isinstance(obj, Cluster)` against an object returned from `create()` (which is a `CreateClusterCreateCluster` instance, not `GetClusterCluster`) **does not match**. SDK consumers use field access, not isinstance checks — accepted cost. If isinstance behaviour is later needed, the canonical types could be derived from a common base, but no such use case exists in the codebase.
- The "get" variant is chosen as the canonical re-export because it typically has the most complete field set; this is convention, not enforced. If a future query selects a richer set of fields than the "get" operation does, the re-export source may need to switch.
- `Task.type_` is a permanent ergonomic wart for SDK consumers. Worth accepting — fighting it (manual remapping in every `from_instance`) would mean reintroducing exactly the hand-written-shim layer this ADR removes.

## Alternatives Considered

- **Use the generated `Client` class directly**: rejected. Duplicates transport configuration (server address, timeout, auth headers), requires re-implementing the existing `_check_graphql_errors()` error mapping on top of `AsyncBaseClient`, and the `.graphql` query files would become unused at runtime (still consumed by codegen). The pure-models swap captures the type-safety benefit without the transport churn.
- **Validate the inner type directly** (`CreateClusterCreateCluster.model_validate(result["data"]["createCluster"])`): rejected. Still requires manual `result["data"]["<op>"]` indexing, which is the very error-prone pattern this ADR aims to eliminate.
- **Operation-specific type names in the public API**: rejected. Forces every consumer that previously imported `Cluster` to import multiple `GetClusterCluster` / `CreateClusterCreateCluster` variants and pick the right one per call site. The facade preserves a sane single name.
- **Generate a unified `Cluster` type instead of one per operation**: rejected. ariadne-codegen's per-operation shape is correct — different GraphQL queries can select different subsets of fields, and a unified type would either over-promise (claim all fields exist) or under-promise (only include the intersection). Per-operation types with field-access compatibility is the right tradeoff; the facade hides the proliferation from the public API.
