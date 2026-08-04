# Contract — `updateDeployment` GraphQL mutation (existing, referenced)

**Status**: Existing contract. This feature uses it **unchanged**. Documented here for completeness so implementers and reviewers can verify behaviour without leaving the spec directory.

## Surface

```graphql
mutation UpdateDeployment($id: UUID!, $input: UpdateDeploymentInput!) {
  updateDeployment(id: $id, input: $input) {
    id
    name
    config
    parameters { name value }
    # ... usual deployment fields
  }
}
```

## Input shape (excerpt from `schema.graphql`)

`UpdateDeploymentInput` uses **full-replacement semantics** at the top level: an omitted (`null`) field means "do not touch the corresponding persisted state"; an empty list/dict means "explicitly clear". The single exception is `parameters`, which uses **merge semantics** for backwards compatibility — entries in the input merge on top of the persisted parameters dict, so existing keys not named in the input survive.

Editable fields in this feature (all already in the input):

- `name: String`
- `parameters: [ParameterValueInput!]` (merge)
- `serviceNameOverrides: [ServiceNameOverride!]`
- `components: [ComponentConfigInput!]`
- `envVars: [EnvVarInput!]`
- `ipWhitelist: [String!]`
- `dedicatedIngress: DedicatedIngressInput`
- `scheduling: SchedulingInput`
- `fqdnSuffix: String`
- `externalUrlScheme: ExternalUrlScheme`
- `externalUrlPort: Int`
- `externalDnsEndpointsType: ExternalDnsEndpointsType`
- `ingressClass: String`
- `dbSize: String`
- `runtimeClass: String`
- `nodeSelector: String`
- `standardStorage: StandardStorageInput`

## Error contract (existing)

The backend raises `ServiceError` subclasses surfaced as GraphQL errors with `extensions.code`. Frontend handlers must surface the error text on the dialog without retrying. Known codes that may fire from this feature:

- `DUPLICATE_PARAMETER_NAME` — duplicate `name` in the `parameters` list.
- `DUPLICATE_COMPONENT_NAME` — duplicate `name` in the `components` list.
- `DUPLICATE_ENV_VAR_NAME` — duplicate `name` in the `envVars` list with `scope=deployment`.
- `INVALID_INPUT` — generic validation failure (e.g., `externalUrlPort` out of range).
- `CONFLICT` (or whatever the existing concurrent-update code is — verify in slice 3) — deployment was modified between fetch and apply.

## Frontend integration points

- `frontend/src/lib/deployment-input.ts::deploymentConfigToInput()` projects the persisted config dict to the typed input. Reused unchanged.
- `frontend/src/graphql/update_deployment.graphql` — the canonical operation file. Reused unchanged.

## What changes about this contract

**Nothing**. This file exists to make that explicit. If a slice requires extending the input or adding a new field, that triggers the Governance Gate review per Constitution §III/Governance, regenerates `schema.graphql` and SDK types per CLAUDE.md, and adds a propagation test per Constitution §V.

If during implementation we decide to add `Deployment.lastUpdateEvent` to power the hero summary (see research R-009), that change is **additive and out of this contract's scope** — it modifies the query, not the mutation.
