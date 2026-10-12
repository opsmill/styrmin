# Data Model: Update a Cluster's Config in Place

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Research**: [research.md](research.md)

No table, column or Alembic revision changes. The cluster config stays in the existing `cluster.config` JSON column, and the capabilities in `cluster.capabilities`.

## 1. Cluster (existing row, replaced in place)

| Field | Change |
|---|---|
| `config` (JSON) | Replaced by the submitted config after defaults and validation (FR-005). |
| `capabilities` (JSON) | Recomputed with `compute_cluster_capabilities` in the same transaction (FR-007). |
| `updated_on` | Set by the existing base model on save. |

**Validation** (`validate_cluster_config` → `ClusterConfig`, `extra="forbid"`): unchanged from `createCluster`. A failure raises `InvalidContextError` (`VALIDATION_ERROR`) and nothing is saved (FR-008).

**Defaults** (shared helper with `create_cluster`): `ingress_class` → `traefik` and `runtime_class` → `default` when the submitted config leaves them out. Every other key left out is absent from the stored config.

## 2. Resolved config (existing, read only)

`ResolvedConfig` is the merge `cluster → environment → deployment`, deepest value wins, with the per-key merge of `env_vars` and the environment-plus-deployment merge of `scheduling` (`context/resolvers.py::_resolve_instance_config`). Each instance stores it in `context.instance.config`.

New public entry point:

```text
resolve_instance_config(cluster: ClusterConfig, environment: EnvironmentConfig, deployment: DeploymentConfig) -> ResolvedConfig
```

**At-config rule** (research D1): a deployment is at the cluster config when

```text
canonical(resolve_instance_config(new cluster, env.config, deployment.config))
  == canonical(deployment.active_instance.context.instance.config)
canonical(x) = ResolvedConfig.model_validate(x).model_dump(exclude_none=True, mode="json")
```

A deployment without an active instance, or whose stored resolved config fails validation, is not at config.

## 3. Effective dedicated ingress of an environment (existing rule)

`environment.config.dedicated_ingress` if set, otherwise `cluster.config.dedicated_ingress`. Any object, including `{}`, turns the controller on; an absent or `null` value turns it off (`_resolve_dedicated_ingress`). An environment cannot turn off a value set at the cluster.

## 4. Dedicated ingress controller (existing internal deployment)

A `Deployment` row with `internal = true`, at most one live per environment (`find_internal_by_environment`). Its active instance's `context.instance.config.dedicated_ingress` holds the values it was rendered with.

State use in this feature (`DeploymentState`), see [research.md](research.md) D4 and D5:

| Controller state | Meaning for the fan-out |
|---|---|
| `PENDING`, `DEPLOYING` | Not ready. Applications whose `dedicated_ingress` changes wait. The controller is not removed in this state. |
| `RUNNING` | Ready. Entering this state runs the environment's fan-out, which moves the waiting applications, then the removal check. |
| `FAILED` | Not ready. Redeployed when its values change, or again when applications wait to move onto it. Applications already on it whose `dedicated_ingress` does not change are redeployed anyway (Clarifications). Entering this state runs the removal check. |
| `DELETING` | Being removed. No second controller is created; applications that would move onto a controller wait. |

**Application rule**: an application whose resolved `dedicated_ingress` changes to a set value is redeployed only when the controller is `RUNNING` with that value. Every other application whose resolved config differs is redeployed at once.

**Removal rule**: the controller is removed when no live non-internal deployment is left (existing #252 rule), or when all of these hold:

- the environment's effective `dedicated_ingress` is off;
- every live non-internal deployment's active instance has no `dedicated_ingress`;
- no live non-internal deployment is `PENDING` or `DEPLOYING`;
- the controller is not `PENDING` or `DEPLOYING`.

The rules depend only on stored state, so they also apply after an environment update (research D5).

## 5. Deployment (existing)

A redeploy uses `redeploy_for_environment_update`: a new instance from the current driver version, `DEPLOYING`, an `UPDATE_INSTANCE` task. It returns `None` for a `RESTORING` deployment. Tombstoned deployments are not listed by `find_all_by_environment`. Internal deployments are excluded from the general rule and handled by section 4.

## 6. Fan-out counts (in memory, logged)

| Count | Meaning |
|---|---|
| `environments` | Environments of the cluster evaluated. |
| `environments_failed` | Environments whose fan-out failed. Their writes are rolled back and their other counts are left out. |
| `evaluated` | Live deployments seen, internal and `DELETING` ones included. A `DELETING` application is not redeployed. |
| `dispatched` | Application redeploys started. |
| `skipped_noop` | Applications already at the resolved config. |
| `skipped_restoring` | `RESTORING` applications. |
| `skipped_waiting_for_ingress` | Applications that wait for their controller to become ready, or whose controller is being removed. |
| `dispatch_failed` | Redeploys that could not be started. |
| `ingress_controllers_created`, `ingress_controllers_redeployed`, `ingress_controllers_removed` | Controller actions. |

FR-010's "skipped" is the sum of the three `skipped_*` counts; "failed" is `dispatch_failed`. The update logs these counts once as `cluster_config_fanout`; each status-reporter continuation logs them for one environment as `cluster_config_fanout_continued`.

## 7. Glossary

The CONTEXT.md entry **Config fan-out** is extended to the cluster case: after a cluster's config is updated, one redeploy for each live, non-internal deployment whose resolved config is not yet at the new cluster config, ordered around the dedicated ingress controller.
