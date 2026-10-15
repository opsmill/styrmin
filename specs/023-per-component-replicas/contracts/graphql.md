# Contract: GraphQL Surface

**Feature**: [../spec.md](../spec.md) | Research: [D-009](../research.md#d-009-graphql-surface)

Every new or changed field, input field and enum gets a propagation test (Constitution §V, [`dev/guides/graphql-propagation-tests.md`](../../../dev/guides/graphql-propagation-tests.md)). After the change, regenerate `schema.graphql` and the SDK types.

## Input: `ComponentConfigInput.replicas` (new)

File: [`api/definitions/deployment/inputs.py`](../../../backend/styrmin_backend/api/definitions/deployment/inputs.py).

```graphql
input ComponentConfigInput {
  name: String!
  envVars: [EnvVarInput!] = null
  command: [String!] = null
  args: [String!] = null
  image: String = null

  """
  Replica count for this component, scoped to this deployment: an integer of 1 or more, applied to
  `spec.replicas` of every Deployment and StatefulSet that matches the component's label selector.
  Needs no component container. Under full-replacement semantics `null`/omitting it CLEARS the
  override, and the component returns to the driver default or to the chart's count. A value below 1
  raises `INVALID_REPLICA_COUNT` (stop the component instead); a value above 1 on a singleton
  component raises `SINGLETON_REPLICA_OVERRIDE`; adding or changing it on a component the driver
  version does not declare raises `UNKNOWN_COMPONENT_REPLICA_OVERRIDE`.
  """
  replicas: Int = null
}
```

Reaches every write path that takes `ComponentConfigInput`: `deploy(config:)`, `updateDeployment(input:)`, `updateDeploymentVersion(input:)`. `_flatten_components` passes it through unchanged.

## Read: `Deployment.componentReplicas` (new)

File: [`api/definitions/deployment/model.py`](../../../backend/styrmin_backend/api/definitions/deployment/model.py).

```graphql
enum ReplicaSource {
  "The user's replica override on this deployment."
  OVERRIDE
  "components.<name>.replicas in the driver version, or 1 for a singleton component."
  DRIVER_DEFAULT
  "No replica patch: the chart's own count applies. Styrmin does not read it."
  CHART
}

type ComponentReplicas {
  component: String!
  "The count Styrmin applies while the component runs. Null when the source is CHART or the row is orphaned. A stopped component runs 0 pods whatever this is; see Deployment.components[].enabled."
  count: Int
  source: ReplicaSource!
  "The stored replica override, applied or not. Null when none is stored."
  override: Int
  "The bound driver version marks the component singleton: true."
  singleton: Boolean!
  "The bound driver version no longer declares the component."
  isOrphaned: Boolean!
  "False only when a stored override is not applied (orphaned component)."
  isApplicable: Boolean!
}

type Deployment {
  # ...existing fields...
  "One row per component the bound driver version declares, plus one per orphaned replica override, sorted by component name."
  componentReplicas: [ComponentReplicas!]!
}
```

The resolver calls `resolve_replicas` ([research D-003](../research.md#d-003-one-replica-resolver-for-the-patch-the-write-checks-and-the-read-field)) with the bound driver version's component declarations (from the deployment's `Component` rows) and the stored `DeploymentConfig.components`.

## Read: `ComponentConfig.replicas` and `ComponentConfig.singleton` (new)

File: [`api/definitions/application_driver/model.py`](../../../backend/styrmin_backend/api/definitions/application_driver/model.py).

```graphql
type ComponentConfig {
  id: UUID!
  name: String!
  config: JSON!
  container: String
  "Default replica count the driver version declares (components.<name>.replicas). Null when not declared."
  replicas: Int
  "The driver version marks the component as a singleton component: its replica count is fixed at 1."
  singleton: Boolean!
}
```

Resolved from `config["replicas"]` and `config["singleton"]`, defaulting to `null` and `false` for driver versions loaded before the change.

## Mutations and arguments (unchanged signatures)

- `updateDeploymentVersion(deploymentId, version, parameters, driverVersionId, startedByStepId, input)`: no signature change. New behaviour: the rule for retired parameters (research D-007) and the replica checks against the target driver version (D-006). Both can raise the new error codes in [errors.md](errors.md).
- `stopComponents` and `startComponents`: no change. A stopped component's override stays stored.

## Propagation tests (functional)

| Surface | Test |
|---------|------|
| `ComponentConfigInput.replicas` on `updateDeployment` | value stored at `config.components.<name>.replicas`; `null` clears it |
| `ComponentConfigInput.replicas` on `deploy` | value stored on create |
| `ComponentConfigInput.replicas` on `updateDeploymentVersion(input:)` | value stored with the version change; checked against the target |
| `Deployment.componentReplicas` | projects every source, an orphaned override, a singleton row and `isApplicable` from stored state |
| `ComponentConfig.replicas`, `ComponentConfig.singleton` | values from a loaded driver version; defaults for a row without the keys |
| `ReplicaSource` | covered by the `componentReplicas` test |
