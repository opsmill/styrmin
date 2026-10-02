# GraphQL Deltas

All additive. No field, argument, or input is removed or renamed. Every addition ships a
propagation test (Constitution §V, `dev/guides/graphql-propagation-tests.md`).

## `ComponentConfig.container` (driver version read path)

```graphql
type ComponentConfig {
  id: UUID!
  name: String!
  config: JSON

  """
  The component container the driver declares for this component
  (`components.<name>.container` in the driver specification file): the container
  that receives per-component post-render overrides such as env vars. Null when the
  driver declares none — component-scope env vars are then rejected and broader
  scopes skip this component.
  """
  container: String
}
```

Source: `ComponentConfig.config["container"]`. Propagation test: load a driver whose component
declares `container: simple-app`; query `applicationDriverVersion { componentConfigs { name container } }`.

## `Component.container` (deployment read path)

```graphql
type Component {
  id: UUID!
  name: String!
  enabled: Boolean!

  """
  The component container declared by the deployment's pinned driver version, or null
  when it declares none. See `ComponentConfig.container`.
  """
  container: String
}
```

Source: the deployment's `Component.config["container"]` (copied from the driver version on
deploy and driver switch). Propagation test: deploy, query
`deployment { components { name container } }`; switch to a driver version without the
container and assert `null`.

## `ComponentEnvVars.isApplicable`

```graphql
type ComponentEnvVars {
  component: String!
  envVars: [EnvVar!]!
  isOrphaned: Boolean!

  """
  False when these env vars cannot reach any container: the component is orphaned
  (`isOrphaned`) or the driver declares no component container for it. Stored values
  are kept but not injected.
  """
  isApplicable: Boolean!
}
```

Propagation test: stored component-scope env vars on a component whose driver version (a) has a
container → `true`; (b) has none → `false`, values returned; (c) does not declare the component →
`isOrphaned: true`, `isApplicable: false`.

## Error codes

| Code | Raised by | `extensions` metadata |
|---|---|---|
| `COMPONENT_CONTAINER_NOT_DECLARED` | `updateDeployment`, `deploy` (any write carrying a new or changed component-scope env var block for a component without a container) | `componentName`, `componentsWithContainer` |

Mutation-error test: submit the write, assert the code and metadata, and assert no Prefect task
was submitted.

`RETIRED_TEMPLATE_FILTER` is a render-time error recorded on the instance, not a GraphQL
mutation error (see [errors.md](errors.md)).

## Description updates (no shape change)

- `ComponentConfigInput.name` / `.envVars`: mention `COMPONENT_CONTAINER_NOT_DECLARED`.
- `ComponentEnvVars` type description: injection happens by post-render into the component
  container.
- Replace "operator" with "user" in every description touched.

## Regeneration

`uv run styrmin export graphql-schema schema.graphql`, then `uv run invoke generate` (SDK types
and frontend TypeScript). SDK `.graphql` files that select these types gain the new fields:
`get_deployment_component_env_vars_full.graphql` (`isApplicable`), `load_version.graphql` and
`load_local_version.graphql` (`componentConfigs { container }`). Frontend
`get_deployment.graphql` adds `components { container }`.
