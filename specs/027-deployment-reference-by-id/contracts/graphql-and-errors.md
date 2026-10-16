# Contract: GraphQL Surface and Errors

## Schema change: descriptions only

No type, field or argument is added, removed or renamed.

```graphql
"""
Reference to another deployment in the same environment. Styrmin stores the
id of the named deployment; a name given here is replaced with that id when
the config is written.
"""
input DeploymentReferenceInput {
  """Id of a deployment in the same environment."""
  deploymentId: String = null

  """
  Name of a deployment in the same environment. Styrmin stores the id of
  that deployment instead of the name when the config is written.
  """
  deploymentName: String = null

  components: [String!] = null
}
```

The mutations that take the input, or a JSON config that can hold the same structure, behave as follows:

| Operation | Reference given by name | Reference to a missing or tombstoned deployment |
| --- | --- | --- |
| `deploy(config:)` | stored as the id; a name of the new deployment gives its own id | refused, nothing saved |
| `updateDeployment(input:)` | stored as the id; resolved after the rename in the same request | refused, nothing saved |
| `updateDeploymentVersion(input:)` | stored as the id; resolved after the rename in the same request | refused, nothing saved |
| `createEnvironment(config:)` (JSON) | refused: the new environment has no deployment | refused |
| `updateEnvironment(input:)` | stored as the id | refused, config unchanged |
| `cloneEnvironment(configOverride:)` | resolved against the source environment, then pointed at the counterpart | refused |

`Deployment.config` and `Environment.config` (`JSON!`) return the stored form of [stored-config.md](stored-config.md).

## Error: unresolvable reference

```json
{
  "message": "Affinity term at deployment.config.scheduling.pod_affinity.required[0] names deployment 'postgres' (7f0c…), which was deleted",
  "extensions": {
    "code": "VALIDATION_ERROR",
    "path": "deployment.config.scheduling.pod_affinity.required[0]",
    "deployment_id": "7f0c2a3e-1b2c-4d5e-8f90-0a1b2c3d4e5f",
    "deployment_name": "postgres",
    "deleted": true
  }
}
```

`deleted` appears only for a tombstoned deployment. For a name that matches no deployment, `deployment_name` is the name as written and `deployment_id` is absent.

## Error: clone leaves out a named deployment

Returned by `cloneEnvironment` before any record or backup is created.

```json
{
  "message": "An affinity term names a deployment that the clone does not copy: postgres",
  "extensions": {
    "code": "VALIDATION_ERROR",
    "deployments": [
      {
        "deployment_id": "7f0c2a3e-1b2c-4d5e-8f90-0a1b2c3d4e5f",
        "deployment_name": "postgres",
        "paths": [
          "environment.config.scheduling.pod_anti_affinity.preferred[0].term",
          "deployment[api].config.scheduling.pod_affinity.required[0]"
        ]
      }
    ]
  }
}
```

## Clone record

- `deploymentResults[].reason` can be "an affinity term names deployment postgres, which was not cloned" on a `FAILED` entry.
- `cloneErrors[].step` can be `referenced_deployment_not_cloned` (fatal), when the new environment's config names a deployment whose capture or creation failed.
