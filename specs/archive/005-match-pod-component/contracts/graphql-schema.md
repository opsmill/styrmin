# GraphQL Schema Contract

This is the diff that `uv run styrmin export graphql-schema schema.graphql` must produce after the implementation lands. It's reproduced here so the implementation has an exact target and the regeneration step has something to compare against.

## `type PodStatus`

```diff
 type PodStatus {
   id: UUID!
   deploymentId: UUID!
   podName: String!
   namespace: String!
   phase: PodPhase!
   ready: Boolean!
   restartCount: Int!
   containerStatuses: JSON!
   nodeName: String
   startedAt: DateTime
   lastPolledAt: DateTime
+  componentName: String
   createdOn: DateTime
   updatedOn: DateTime
 }
```

- `componentName` is nullable (`String`, no `!`) because the field on the DB column is nullable. Field placement (anywhere in the type) is cosmetic; Strawberry orders by attribute order on the Python class.

## `input PodStatusInput`

```diff
 input PodStatusInput {
   podName: String!
   namespace: String!
   phase: PodPhase!
   ready: Boolean!
   restartCount: Int!
   containerStatuses: JSON = null
   nodeName: String = null
   startedAt: DateTime = null
+  componentName: String = null
 }
```

- Default `null` so existing callers (which won't set the field) still validate.

## SDK queries that must be updated

- `python_sdk/src/styrmin_sdk/graphql/get_pod_statuses.graphql` — add `componentName` to the selection set.
- `python_sdk/src/styrmin_sdk/graphql/get_deployment_pod_statuses.graphql` — add `componentName` to the selection set inside `podStatuses`.

## SDK queries that do NOT change

- `python_sdk/src/styrmin_sdk/graphql/report_pod_statuses.graphql` — the mutation's response shape is `success / message / podsUpdated / podsRemoved`; pod input fields are not selected. The new `componentName` input gets picked up automatically by `uv run invoke generate` via the schema.

## Regeneration commands

After model changes:

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
```

CI fails if either is stale.
