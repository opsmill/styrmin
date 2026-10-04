# Contract: GraphQL deltas

Additive only. Regenerate `schema.graphql`, the SDK types (`uv run invoke generate`) and the
frontend types. Governance gate pre-approved in the idea brief ("GraphQL schema: input field, read
type, typed error codes").

## Input

```graphql
input ComponentConfigInput {
  name: String!
  envVars: [EnvVarInput!] = null
  command: [String!] = null
  args: [String!] = null
  """
  Image reference for this component's component container, scoped to this
  deployment. A full reference with an explicit tag or digest; every
  `{{ app.version }}` token is replaced with the deployment's application
  version at render time, and a literal tag pins the image. Under
  full-replacement semantics `null`/omitting it CLEARS the override (the chart
  image applies). Raises UNKNOWN_COMPONENT_IMAGE_OVERRIDE,
  INVALID_IMAGE_REFERENCE, or COMPONENT_CONTAINER_NOT_DECLARED (adding or
  changing it on a component without a component container; removing it is
  always accepted).
  """
  image: String = null
}
```

Shared by `deploy(config: DeploymentConfigInput)` and `updateDeployment(input: UpdateDeploymentInput)`,
and therefore by `styrminctl apply` manifests:

```yaml
spec:
  config:
    components:
      - name: server
        image: "registry.example/acme/simple-app-patched:{{ app.version }}"
```

## Read

```graphql
type ComponentImageOverride {
  component: String!
  reference: String!
  resolvedReference: String!
  isOrphaned: Boolean!
  isApplicable: Boolean!
}

type Deployment {
  # ... existing fields ...
  componentImageOverrides: [ComponentImageOverride!]!
}
```

- One entry per component with a stored override. Live components come first, sorted by name,
  then orphans sorted by name.
- `resolvedReference`: `reference` with every token replaced by `Deployment.applicationVersion`.
- `isApplicable`: `not isOrphaned and component.container != null` (the deployment's components,
  which mirror its pinned driver version).

## Operations to add or extend

| File | Change |
|---|---|
| `python_sdk/src/styrmin_sdk/graphql/get_deployment.graphql` | + `componentImageOverrides { component reference resolvedReference isOrphaned isApplicable }` |
| `python_sdk/src/styrmin_sdk/graphql/get_deployment_component_image_overrides_full.graphql` | new `GetDeploymentComponentImageOverridesFull` (E2E and propagation tests) |
| `frontend/src/graphql/get_deployment.graphql` (frontend operation) | + `componentImageOverrides { … }` |
| `frontend` update-deployment / deploy operations | regenerated for `image` on `ComponentConfigInput` |

## Propagation tests (Constitution §V)

| Field | Test |
|---|---|
| `ComponentConfigInput.image` (update) | value reaches `Deployment.config.components.<name>.image`; omitting it clears it |
| `ComponentConfigInput.image` (deploy) | value reaches the new deployment's config |
| `Deployment.componentImageOverrides` | stored → read projection, including `resolvedReference` substitution, `isOrphaned`, `isApplicable` false for a containerless component |
| Error codes | `UNKNOWN_COMPONENT_IMAGE_OVERRIDE`, `INVALID_IMAGE_REFERENCE` (each reason), `COMPONENT_CONTAINER_NOT_DECLARED` with `override: "image"` reach `extensions.code` and no task is created |
| `updateDeploymentVersion` | `INVALID_IMAGE_REFERENCE` (reason `after_substitution`) when the target version breaks a stored reference; no task created |
