# Contract: `updateCluster` GraphQL mutation

**Feature**: [../spec.md](../spec.md) | **Decision**: [../research.md](../research.md) D2

## Schema additions

```graphql
input StandardStorageInput {
  storageClass: String!
}

input FastStorageInput {
  storageClass: String!
}

"""
Full-replacement input for cluster configuration updates. Submit the complete
desired configuration; any field omitted (null) is removed from the stored
config, except ingressClass and runtimeClass, which default to "traefik" and
"default" as on createCluster.
"""
input UpdateClusterInput {
  ingressClass: String = null
  runtimeClass: String = null
  nodeSelector: String = null
  fqdnSuffix: String = null
  externalUrlScheme: ExternalUrlScheme = null
  externalUrlPort: Int = null
  externalDnsEndpointsType: ExternalDnsEndpointsType = null
  dedicatedIngress: DedicatedIngressInput = null
  standardStorage: StandardStorageInput = null
  fastStorage: FastStorageInput = null
  scheduling: SchedulingInput = null
  dbSize: String = null
  backupTtl: String = null
}

type Mutation {
  """
  Replace a cluster's config and redeploy every deployment whose resolved
  config changes. Requires the ADMIN role. Identify the cluster by id or name.
  """
  updateCluster(
    input: UpdateClusterInput!
    clusterId: UUID = null
    clusterName: String = null
    dryRun: Boolean! = false
  ): UpdateClusterResult!
}

type UpdateClusterResult {
  cluster: Cluster!
  dryRun: Boolean!
  redeployed: [UpdateClusterDeployment!]!
  waitingForIngress: [UpdateClusterDeployment!]!
  skippedRestoring: [UpdateClusterDeployment!]!
  failedToStart: [UpdateClusterDeployment!]!
  unchangedCount: Int!
  ingressControllers: [UpdateClusterIngressController!]!
  failedEnvironments: [UpdateClusterEnvironment!]!
}

type UpdateClusterDeployment {
  deploymentId: UUID!
  deploymentName: String!
  environmentId: UUID!
  environmentName: String!
  taskId: UUID          # null in a dry run and when the redeploy did not start
}

type UpdateClusterIngressController {
  environmentId: UUID!
  environmentName: String!
  action: IngressControllerAction!   # CREATE | REDEPLOY | REMOVE
  failed: Boolean!
}

type UpdateClusterEnvironment {
  environmentId: UUID!
  environmentName: String!
}
```

The result type was added after the review of 2026-10-12: the first version returned only the
`Cluster`, so the caller could not learn which deployments were redeployed or failed to start.

`DedicatedIngressInput`, `SchedulingInput`, `ExternalUrlScheme` and `ExternalDnsEndpointsType` already exist and are reused unchanged.

## Behaviour

| Case | Result |
|---|---|
| Valid input, `ADMIN` | Returns the `Cluster` with the new `config` and `capabilities`, and the fan-out lists. Redeploys are started before the response, one environment transaction at a time (research D7). |
| Valid input, `dryRun: true` | Returns the stored `Cluster` and the lists that saving would produce (`taskId` null). Nothing is saved and no task is created. |
| Both or neither of `clusterId` and `clusterName` | `AmbiguousIdentifierError` (existing). |
| Unknown cluster | `ClusterNotFoundError` (`NOT_FOUND`, existing). |
| Config fails `ClusterConfig` validation | `InvalidContextError` (`VALIDATION_ERROR`); nothing saved. |
| An environment of the cluster has a clone in progress | `EnvironmentOperationInProgressError` (`ALREADY_IN_PROGRESS`, `operation_kind: environment_clone`), whose message names the environment and says that nothing was saved; nothing saved. |
| Caller without `ADMIN` | Refused by the existing permission extension; nothing saved. |
| Unknown input field | Refused by GraphQL validation before the resolver runs. |

## Conversion

`update_cluster_input_to_dict(input)` uses the existing `_convert_value` from `api/definitions/config/inputs.py`: top-level `None` fields are omitted, nested inputs become snake_case dicts, enums become their values. The result goes to `services.clusters.update_cluster(uow, cluster_id, config, acting_user_id, dry_run=...)`.

## Propagation test

`backend/tests/functional/graphql/test_cluster_update_propagation.py`, per [graphql-propagation-tests.md](../../../dev/guides/graphql-propagation-tests.md):

- every `UpdateClusterInput` field reaches `cluster.config` in the database, with snake_case keys;
- an omitted field is absent from the stored config, and the two defaults apply;
- `capabilities` returned by the mutation and read back by `cluster(...)` include the recomputed ingress and storage capabilities;
- a non-admin caller is refused and the row is unchanged;
- `dryRun` returns the planned redeploy and leaves the row and the tasks unchanged;
- a redeploy that fails to start is listed in `failedToStart`, and the others in `redeployed` with their task.

## SDK operation

`python_sdk/src/styrmin_sdk/graphql/update_cluster.graphql`:

The operation selects `cluster { id name config capabilities createdOn updatedOn }`, `dryRun`,
every list with all its fields, and `unchangedCount`, and passes `$dryRun: Boolean! = false`.

The frontend gets its own copy in `frontend/src/graphql/update_cluster.graphql` for the P2 form.
