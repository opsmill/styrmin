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
  ): Cluster
}
```

`DedicatedIngressInput`, `SchedulingInput`, `ExternalUrlScheme` and `ExternalDnsEndpointsType` already exist and are reused unchanged.

## Behaviour

| Case | Result |
|---|---|
| Valid input, `ADMIN` | Returns the `Cluster` with the new `config` and `capabilities`. Redeploys are started before the response (research D7). |
| Both or neither of `clusterId` and `clusterName` | `AmbiguousIdentifierError` (existing). |
| Unknown cluster | `ClusterNotFoundError` (`NOT_FOUND`, existing). |
| Config fails `ClusterConfig` validation | `InvalidContextError` (`VALIDATION_ERROR`); nothing saved. |
| An environment of the cluster has a clone in progress | `EnvironmentOperationInProgressError` (`ALREADY_IN_PROGRESS`, `operation_kind: environment_clone`); nothing saved. |
| Caller without `ADMIN` | Refused by the existing permission extension; nothing saved. |
| Unknown input field | Refused by GraphQL validation before the resolver runs. |

## Conversion

`update_cluster_input_to_dict(input)` uses the existing `_convert_value` from `api/definitions/config/inputs.py`: top-level `None` fields are omitted, nested inputs become snake_case dicts, enums become their values. The result goes to `services.clusters.update_cluster(uow, cluster_id, config, acting_user_id)`.

## Propagation test

`backend/tests/functional/graphql/test_cluster_update_propagation.py`, per [graphql-propagation-tests.md](../../../dev/guides/graphql-propagation-tests.md):

- every `UpdateClusterInput` field reaches `cluster.config` in the database, with snake_case keys;
- an omitted field is absent from the stored config, and the two defaults apply;
- `capabilities` returned by the mutation and read back by `cluster(...)` include the recomputed ingress and storage capabilities;
- a non-admin caller is refused and the row is unchanged.

## SDK operation

`python_sdk/src/styrmin_sdk/graphql/update_cluster.graphql`:

```graphql
mutation UpdateCluster($input: UpdateClusterInput!, $clusterId: UUID, $clusterName: String) {
  updateCluster(input: $input, clusterId: $clusterId, clusterName: $clusterName) {
    id
    name
    config
    capabilities
    createdOn
    updatedOn
  }
}
```

The frontend gets its own copy in `frontend/src/graphql/update_cluster.graphql` for the P2 form.
