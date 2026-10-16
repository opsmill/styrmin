# Contract: Driver Specification File

**Feature**: [../spec.md](../spec.md) | Research: [D-002](../research.md#d-002-where-the-driver-default-and-the-singleton-flag-are-declared-and-parsed), [D-013](../research.md#d-013-example-drivers)

## New component keys

```yaml
spec:
  components:
    server:
      container: infrahub-server
      replicas: 1            # optional, integer of 1 or more: the driver default
      identifier:
        label:
          service: infrahub-server
    database:
      container: neo4j
      singleton: true        # optional, boolean, default false: count fixed at 1
      identifier:
        label:
          infrahub/service: database
```

| Key | Type | Default | Effect |
|-----|------|---------|--------|
| `replicas` | integer from 1 to 2147483647 | not set | Styrmin patches this count onto the component's `Deployment` and `StatefulSet` workloads when the deployment has no replica override. Not set: the chart's count applies. |
| `singleton` | boolean | `false` | The component's count is fixed at 1. Without `replicas`, Styrmin patches 1. A replica override above 1 is rejected. Does not limit how many pods run during a rolling update. |

## Load errors

The driver version fails to load, and no row is stored, when:

- `singleton: true` and `replicas` is greater than 1;
- `replicas` is below 1 or above 2147483647, a string, a float or a boolean;
- `singleton` is not a boolean.

`singleton: true` with `replicas: 1` loads.

## Example drivers after the change

| Driver | Version | Change |
|--------|---------|--------|
| `infrahub` | `4` → `5` | Remove parameters `replicas_server` and `replicas_task_worker` and their `values.j2.yml` lines; `server.replicas: 1`, `task-worker.replicas: 2`; `singleton: true` on `database`, `task-manager-db` and `cache` |
| `infrahub-enterprise` | `3` → `4` | Same as `infrahub` |
| `simple-app` | `3` → `4` | `database.singleton: true` |
| `db-test`, `infrahub-mcp`, `semaphore`, `slurpit` | unchanged | — |

## Retired parameters on a version change

Not a driver file key, but it governs how a driver retires a parameter. On `updateDeploymentVersion`, a stored or submitted value for a parameter that the current version declares and the target version does not:

- equal (same type and value) to the current version's default: dropped;
- otherwise: `RETIRED_PARAMETER_VALUE` ([errors.md](errors.md)).
