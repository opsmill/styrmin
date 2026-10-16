# ADR-066: Cluster Config Fan-Out — Resolved-Config Comparison and Dedicated Ingress Ordering

**Status**: Accepted
**Date**: 2026-10-12
**Source**: [issue #423](https://github.com/opsmill/styrmin/issues/423) and
specs/archive/021-cluster-config-update/ (spec, plan, research D1 to D12).
**Related**: [ADR-012](0012-environment-config-fanout.md) (environment config fan-out; this ADR
narrows its "convention to replicate"), [ADR-026](0026-capabilities-recalculation-in-service-layer.md)
(capabilities recomputed in the service layer), [ADR-008](0008-deployment-soft-delete-tombstoning.md)
(the status reporter tombstones deployments),
[ADR-064](0064-styrmindeployment-write-order-by-instance-sequence.md) (the instance with the
highest sequence wins on the StyrminDeployment).

## Context

Before #423, an administrator set a cluster's config only when they created the cluster. To
change one value, such as the shared ingress class or a storage class, they deleted every
deployment and every environment of the cluster, deleted the cluster and created it again.

Each environment and each deployment takes the cluster's value for every key it does not set
itself. The resolved config of a deployment is the merge of the cluster config, then the
environment config, then the deployment config, where the deepest value wins (`env_vars` is
merged per key, and `scheduling` is merged from the environment and the deployment only). Each
instance stores the resolved config it was rendered with in `context.instance.config`.

ADR-012 introduced the environment config fan-out. After `updateEnvironment`, Styrmin redeploys
each live, non-internal deployment of the environment whose active instance stores an
environment config (`context.environment.config`) that differs from the new environment config.
ADR-012 recommends this comparison of the changed level's config for future fan-outs.

A cluster update differs from an environment update in two ways:

- One cluster value reaches the deployments of several environments, and an environment can set
  the same key itself, which hides the cluster's value from its deployments.
- `dedicated_ingress` decides whether the applications of an environment are served by the
  environment's dedicated ingress controller, an internal deployment, or by the cluster's shared
  ingress class. An application that is redeployed onto a controller that does not answer yet is
  not reachable.

## Decision

### 1. Compare the resolved config, not the stored cluster config

`update_cluster` (`services/clusters.py`) saves the config, then `fan_out_cluster_config`
(`services/cluster_config_fanout.py`) evaluates every live, non-internal deployment of every
environment of the cluster. A deployment is redeployed when the resolved config computed now,
from the new cluster config, the current environment config and the deployment config, differs
from `active_instance.context.instance.config`. Both sides are normalised with
`ResolvedConfig.model_validate(...).model_dump(exclude_none=True, mode="json")`. A deployment
without an active instance, or whose stored resolved config fails validation, is redeployed.

`resolve_instance_config(cluster, environment, deployment)` in `context/resolvers.py` is the
public entry point to the resolution that `generate_context_from_deployment` uses, so the
comparison needs no driver, chart or deployed-service lookup per deployment.

ADR-012's comparison does not apply, because the cluster config that each instance stores
(`context.cluster.config`) differs on every deployment after any cluster change. It would redeploy the deployments of an
environment that sets the changed value itself, and it would redeploy every deployment after a
change to a value that no resolution reads (today the cluster's `scheduling` value). The resolved
config is what driver templates (`instance.config.*`) and the ingress post-render patch read.

A driver template can also read `cluster.config.*`, which `driver/DRIVERS.md` documents. A
deployment that the fan-out skips keeps the `context.cluster.config` of its last render, so such a
template sees the previous cluster value until the deployment is redeployed for another reason.
This is a limitation of this decision. Styrmin's own code reads the resolved config:
`run_job` (`services/primitives.py`) takes the runtime class from `instance.config`.

The redeploy is `redeploy_for_environment_update`, the same primitive as the environment
fan-out: a new instance at the deployment's current application version and bound driver
version, and an `update_instance` task. Tombstoned deployments are skipped. A `DELETING`
deployment is left to its teardown: it is counted in `evaluated`, like an internal deployment, and
in no skipped count. A `RESTORING` deployment is skipped and counted. A redeploy that cannot be
started is caught, logged and counted, and the other redeploys still start. A resubmission of the
same config therefore redeploys only the deployments that are not at their resolved config,
whatever the cause.

The environment fan-out in `services/environments.py` keeps its comparison of the stored
environment config.

> Amended 2026-10-14 ([#424](https://github.com/opsmill/styrmin/issues/424)): the first version of
> this paragraph said that the environment fan-out is not changed. `update_environment` now runs
> the per-environment steps of decisions 2, 3 and 6 through `fan_out_environment_config`, with its
> own comparison passed as `at_config` and its own log prefix (`env_config_fanout_*`). See the
> amendment of decision 3.

### 2. Order the dedicated ingress changes through the status reporter

The effective `dedicated_ingress` of an environment is the environment's own value, or else the
cluster's. Any object, including `{}`, turns the controller on.

In the update call, for each environment, Styrmin acts on the environment's live controller
(`find_internal_by_environment`):

| New effective value | Controller | Action |
|---|---|---|
| Set, and the environment has applications | None | Create it, attributed to the administrator who submitted the config. |
| Set | Exists, not `DELETING`, rendered with other `dedicated_ingress` values | Redeploy it with the new values. |
| Set | `FAILED`, same values, and at least one application waits to move onto it | Redeploy it again. |
| Set | `DELETING` | None. No second controller while the first one is being removed. |
| Not set | Exists | None in this step. Removal follows decision 3. |

Each application whose resolved config differs is then handled as follows (`_plan_environment`):

- The environment's effective `dedicated_ingress` is set, and the application's resolved
  `dedicated_ingress` (its own value, else the effective value) differs from the value its active
  instance was rendered with: the application is redeployed only when the controller is
  `RUNNING`, was rendered with the effective value, and this run starts no action on it.
  Otherwise it waits on its current config and is counted as `skipped_waiting_for_ingress`.
- In every other case, including an effective value that is not set: it is redeployed at once,
  whatever the controller state.

> Amended 2026-10-13: the first version of this list said that an application waits when "its
> resolved `dedicated_ingress` changes to a set value". The code compares the environment's
> effective value with the value the application was rendered with, as written above. A known
> limitation follows from this: the check does not use the application's own resolved value, so
> a deployment that sets its own `dedicated_ingress`, different from the environment's effective
> value, can wait for the controller for no reason. The implement report lists this as a deferred
> finding (specs/archive/021-cluster-config-update/opsmill-implement-report.md, §5 "Deferred").
>
> Amended 2026-10-16 ([#453](https://github.com/opsmill/styrmin/issues/453)): the check now
> compares the application's resolved value with the value it was rendered with, as the first
> version intended. A deployment that sets its own `dedicated_ingress` keeps it, so it no longer
> waits, and a `FAILED` controller is not redeployed for it.

Each environment is planned first (`_plan_environment`): the applications to redeploy, the ones
that wait and the controller action. The plan is then carried out. A dry run (decision 4) returns
the plan of every environment and carries out none.

The status reporter (`report_deployment_statuses` in `services/deployment_status.py`) continues
the work, only when a deployment's state changes:

- An internal deployment that moves to `RUNNING` runs `continue_environment_fan_out` for its
  environment: the same per-environment evaluation, without controller creation, because no
  administrator acts. The applications that waited are redeployed.
- An internal deployment that moves to `FAILED`, and an application that moves to `RUNNING`,
  `FAILED` or `DELETED`, run the removal check of decision 3. The check after `DELETED` is the
  #252 removal. Before this decision it ran outside a savepoint, so its failure rolled back the
  whole status report.

Both hooks run in a savepoint (`uow.session.begin_nested()`), like `_record_operator_steps`. A
failure is logged (`cluster_config_fanout_hook_error`) and the status report still commits.

No list of waiting applications is stored. The comparison of decision 1 recomputes it from the
database each time, which also makes the continuation idempotent.

### 3. Remove the controller once no application depends on it

`tear_down_unused_ingress_controller` (`services/deployment.py`) requests the deletion of the
environment's controller when no live application is left in the environment (the #252 rule,
unchanged), or when all of the following hold:

- The environment's effective `dedicated_ingress` is not set.
- Every live application's active instance was rendered without `dedicated_ingress`.
- No live application is `PENDING`, `DEPLOYING`, `FAILED` or `RESTORING`. FluxCD rolls a failed
  upgrade back to the previous release, whose Ingress can still use the controller, and a restore
  brings back the backed-up release. The check runs again when the application reaches `RUNNING`,
  `FAILED` or `DELETED`.
- The controller is not `PENDING` or `DEPLOYING`. The flow that creates or redeploys a controller
  does not check for `DELETING`, so a deletion requested before that flow writes the
  StyrminDeployment would leave a controller running without a live row. The check runs again
  when the controller reaches `RUNNING` or `FAILED`.

The deletion path is the one #252 built: the row moves to `DELETING`, a born-complete
`delete_deployment` task with its steps is recorded, and the operator tears the controller down.

The check runs at the end of each environment's fan-out and from the status reporter. Because it
reads only stored state, it also acts after an environment update. When `updateEnvironment`
turns the environment's own `dedicated_ingress` off and the cluster sets none, the controller is
now removed once the applications have been redeployed without it. Before this decision, it
stayed until the last application of the environment was deleted.

> Amended 2026-10-14 ([#424](https://github.com/opsmill/styrmin/issues/424)): the first version of
> this decision ended with "The environment update still neither creates nor redeploys the
> controller." An environment update now acts on the controller as decision 2 describes, for the
> environment it updates: it creates the controller, attributed to the administrator who submitted
> the environment config, or redeploys it when its values differ, and the applications that move
> onto it wait until it is `RUNNING` with the new values. The status reporter's continuation then
> redeploys them, with the resolved-config comparison of decision 1. `update_environment` runs
> the removal check at the end of the update, like the cluster fan-out. No dry run is added to
> `updateEnvironment`, and its result type is unchanged.

### 4. A typed `UpdateClusterInput`, while `createCluster` keeps its JSON argument

`updateCluster(input: UpdateClusterInput!, clusterId: UUID, clusterName: String, dryRun: Boolean! = false): UpdateClusterResult!`
requires the `ADMIN` role. `UpdateClusterResult` holds the cluster and what the fan-out did: the
deployments redeployed (with their task), waiting for a controller, skipped for a restore and
failed to start, the number already at their resolved config, the controller actions per
environment, and the environments whose evaluation failed. With `dryRun`, the config is validated
and the same lists say what saving would do; nothing is saved and no task is created. The CLI
prints the lists and the edit dialog shows them, before saving (dry run) and after.

`UpdateClusterInput` mirrors `ClusterConfig` field by field and reuses
the existing inputs `DedicatedIngressInput`, `SchedulingInput`, `StandardStorageInput` and
`FastStorageInput` and the enums `ExternalUrlScheme` and `ExternalDnsEndpointsType`, following
ADR-012's convention of one Strawberry input per Pydantic class.
`update_cluster_input_to_dict` drops the top-level fields that are `null`.

The update replaces the whole config. A key left out is removed, except `ingress_class` and
`runtime_class`, which get the `createCluster` defaults (`traefik` and `default`) through the
shared `_apply_cluster_defaults`. The config is validated with `validate_cluster_config`
(`InvalidContextError`, `VALIDATION_ERROR`), and the capabilities are recomputed in the same
transaction (ADR-026). The update is refused with `EnvironmentOperationInProgressError` while an
environment clone occupies any environment of the cluster (`find_clone_occupying_environment`):
while the clone's capture of a source environment of the cluster has not ended, and while the
clone that creates an environment of the cluster has not ended. Environment backups and restores
do not block the update. No column changes, so no migration ships.

`createCluster` keeps `config: JSON`. Changing it was out of scope. The two cluster mutations
therefore take the config in different shapes: GraphQL validation refuses an unknown field of
`UpdateClusterInput`, and `ClusterConfig`'s `extra="forbid"` refuses an unknown key of the
`createCluster` JSON.

### 5. The SDK refuses unknown keys in the config

The SDK input models that ariadne-codegen generates ignore unknown keys. Under full replacement,
a misspelled key (`fqdn_sufix`) would be dropped, the real key would be removed, and every
deployment that takes it would be redeployed without it. The SDK's `clusters.update()` therefore
takes the config as a dict, like `clusters.create()`, and `cluster_update_input`
(`python_sdk/src/styrmin_sdk/resources/clusters.py`) runs `validate_input_strict` before any
request. It refuses every key, at any depth, that is neither a field name nor an alias, and names
its path (`dedicated_ingress.servce`). `styrminctl clusters update` calls the same check before
it connects.

The check also accepts the stored enum values that `clusters get` returns (`http`,
`NodeExternalIP`, `NoSchedule`) and converts them to the GraphQL enum names with
`to_graphql_enum_names`, so a config read from the API can be changed and sent back.
`styrminctl clusters get --json` prints only the config, as JSON; the table output cuts long
values and cannot be copied.

`clusters.update()` waits up to 600 seconds (`UPDATE_CLUSTER_TIMEOUT_SECONDS`), because the server
starts every redeploy before it answers. On a timeout, the CLI says that the server can still be
saving the config.

The guard applies to `clusters.update()` only. A direct GraphQL caller is already protected by
GraphQL validation. Other commands with the same exposure (`deployments update`,
`env-clones create --config-override`) are not changed.

### 6. Transaction boundaries

1. In one transaction: load the cluster, run the clone guard on each environment, apply the
   defaults, validate, set `config` and `capabilities`, commit. The row is committed before any
   redeploy starts, as in ADR-012 decision 4. Log `cluster_config_updated cluster_id=… user_id=…
   changes=…`, with the previous and new value of each top-level key that changed. Styrmin keeps no
   history of cluster configs; this line is the record of who changed what
   ([#447](https://github.com/opsmill/styrmin/issues/447)).
2. For each environment, in its own transaction: plan it, start the controller action, each
   redeploy and the removal check, each in a savepoint, then commit. An installation has one
   cluster, so one transaction for the whole fan-out would hold row locks across one Prefect call
   per deployment of the installation, and each flow, which waits 10 seconds for its task row
   (`TASK_ROW_WAIT_SECONDS`), could start long before that commit.
3. Log one line: `cluster_config_fanout cluster_id=… environments=… environments_failed=…
   evaluated=… dispatched=… skipped_noop=… skipped_restoring=… skipped_waiting_for_ingress=…
   evaluation_failed=… dispatch_failed=… ingress_controllers_created=…
   ingress_controllers_redeployed=… ingress_controllers_removed=… ingress_controller_failed=…
   ingress_controller_removal_failed=…`. `evaluation_failed` counts the applications whose
   comparison raised, `dispatch_failed` the application redeploys that could not start, and the two
   `ingress_controller_*failed` counts the controller actions and removal checks that failed.

Each status reporter continuation logs the same counts for one environment as
`cluster_config_fanout_continued`.

A failing redeploy start, controller action or removal check rolls back only its own savepoint
and is logged and counted, as decisions 1 to 3 describe. When the evaluation of an environment
fails outside these steps (for example, the environment's stored config no longer validates), the
environment's transaction is rolled back (in the status reporter, its savepoint), the failure is
logged as `cluster_config_fanout_environment_error`, and the environment counts in `environments`
and `environments_failed` only: its other counts are left out of the log line. The other
environments are still evaluated, and `updateCluster` returns the updated cluster with the
environment in `failedEnvironments`.

`SqlModelUnitOfWork.commit()` raises when a savepoint is open. In SQLAlchemy 2.0,
`session.commit()` inside a savepoint commits the outer transaction, so a helper that committed
there would end the failure isolation without any error.

The redeploy path opens nested `async with uow` blocks of its own (context generation and
`resolve_deployment_reference`). `SqlModelUnitOfWork.__aexit__` therefore rolls back only the
innermost open savepoint when such a block exits with an exception while a savepoint is open, and
the whole transaction otherwise, as before. Without this rule, a failure in a nested block rolled
back the whole transaction, including the savepoint of the caller and the redeploys already
written, and the caller kept using a session whose transaction was gone. An explicit
`uow.rollback()` still rolls back the whole transaction.

Since [#508](https://github.com/opsmill/styrmin/issues/508), the rule depends on the savepoint
that was open when the block was entered, not when it exits: a block entered inside a savepoint
rolls back that savepoint if it is still active, and a block entered outside any savepoint rolls
back the whole transaction. Under the first rule, when two nested blocks were open inside the
savepoint (context generation calls `resolve_deployment_reference`), the inner block rolled back
the savepoint, and the outer block found no savepoint open and rolled back the whole transaction
(amended 2026-10-17).

## Consequences

- Administrators change any cluster value without deleting a deployment, an environment or the
  cluster, through `styrminctl clusters update`, the SDK's `clusters.update()`, GraphQL or the
  Edit button on the cluster detail page.
- A resubmission of the stored config redeploys only the deployments and dedicated ingress
  controllers that are not at their resolved config, whatever the cause: for example a deployment
  whose redeploy could not be started earlier, or a `RUNNING` controller whose `dedicated_ingress`
  values an environment update changed. When every deployment is at its resolved config and every
  controller runs with its environment's values, it starts no redeploy.
- When a Styrmin release changes how the resolved config is computed (for example a new default),
  the next cluster update redeploys every deployment whose stored resolved config differs in that
  field, even when the administrator changed nothing that the deployment reads. Each of these
  redeploys adds a new instance and an `update_instance` task to the deployment.
- Any transition of a controller to `RUNNING`, including after its first deploy or after a repair,
  runs its environment's fan-out. With converged deployments it starts no redeploy. Deployments
  that are not at their resolved config are redeployed.
- If the controller moves to `RUNNING` while an update call evaluates the same environment, both
  can start a redeploy of one application. Both instances carry the same resolved config, and the
  one with the highest instance sequence wins on the StyrminDeployment (ADR-064). The cost is one
  extra task.
- If a status reporter continuation fails, the waiting applications move only at the controller's
  next transition to `RUNNING` or at a resubmission of the cluster config.
- `apply_state` dispatches the Prefect flow before the transaction commits. If an environment's
  commit, or the status report's savepoint or commit, fails after a dispatch, the flow refers to a
  task row that does not exist. Each environment commits on its own, so the window is one
  environment's redeploys, as in `update_environment`, which also commits once per environment.
- `updateCluster` answers after every environment has been committed. In a large installation the
  call can take longer than the SDK's default 30-second timeout, so `clusters.update()` waits up to
  600 seconds.
- Two updates do not merge: the update saved last wins, and a file saved before another update
  reverts it. There is no concurrency check.
- Kubernetes refuses any change to the volume claim templates of an existing StatefulSet, and
  driver templates can write the storage class there. A storage class change then fails that
  deployment's redeploy. The new instance is already active, so a resubmission does not retry it.
  The administrator recovers by submitting the previous storage class again or by recreating the
  deployment. There is no workaround in Styrmin, and existing volumes are not moved.
- A pre-existing operator race in the #252 deletion path can leave a deleted controller in
  `DELETING`: when kopf's delete handler and the StyrminDeployment timer run at the same moment,
  kopf keeps its finalizer and the namespace stays `Terminating` (seen once in the E2E run of
  2026-10-12, recorded in specs/archive/021-cluster-config-update/e2e-evidence.md). While the controller
  stays `DELETING`, the applications that would move onto a controller keep waiting, and the
  recovery "resubmit after the removal has finished" is not available. A change to the
  StyrminDeployment custom resource, such as a new annotation, made kopf run the handler again and
  remove the finalizer. This decision does not change the operator. The race was fixed later for
  agents of releases after v0.1.48 ([#446](https://github.com/opsmill/styrmin/issues/446),
  [PR #474](https://github.com/opsmill/styrmin/pull/474)); see the Deletion section of
  [`dev/knowledge/agent/operator.md`](../knowledge/agent/operator.md#deletion).
- A nested `async with uow` block that fails inside any savepoint now undoes only that savepoint's
  writes. The only savepoints are the status reporter's two and the cluster config fan-out's, all
  opened to isolate a failure, so no other caller changes behaviour. `uow.commit()` inside a
  savepoint raises. When this decision was taken, `update_environment` opened no savepoint, so a
  nested block that failed during one of its redeploys rolled back the whole open transaction,
  including the redeploys written before it in the same fan-out. Since
  [#452](https://github.com/opsmill/styrmin/issues/452), `update_environment` runs each redeploy
  in its own savepoint, as decision 6 does. Since #424, it also runs each controller action and
  removal check in a savepoint (amended 2026-10-14).
- The environment and cluster fan-outs now use different comparisons. Since #424 they share the
  per-environment steps and differ only in the comparison (amended 2026-10-14). Replacing the
  environment comparison with the resolved-config comparison is left for a later change.
- New fan-outs whose change reaches deployments through more than one config level should compare
  the resolved config, as decision 1 does, not the stored config of one level.

## Alternatives Considered

- Compare the cluster config that each instance stores (`context.cluster.config`), as ADR-012
  does for the environment config: rejected, see decision 1.
- Render the full Helm values and compare them: rejected. It needs the driver version, the chart
  and the deployed services of every deployment, and it misses the post-render patches (ingress
  annotations, env vars, scheduling).
- Compare only the cluster keys that changed: rejected. It does not recover deployments that
  missed an earlier update, and it needs the previous config, which is not reliable after a
  partial failure.
- Start every redeploy at once, the controller first: rejected. The applications would move to a
  controller that does not answer yet.
- A Prefect flow that waits for the controller, then redeploys the applications: rejected. It adds
  a long-running flow and a new flow type per environment (which ADR-012 rejected for the
  environment fan-out), and it holds a worker slot while it polls.
- A stored table of pending redeploys: rejected. The comparison already derives the pending set
  from the database, and a table would hold state that can drift from it.
- The operator waits in the application's prerequisites until the environment's controller is
  ready: rejected. The operator would need to know which controller serves which environment, and
  the wait would not show in Styrmin's tasks.
- Remove the controller in the update call, after starting the application redeploys: rejected.
  The redeploys run asynchronously, so the controller would be removed before the applications
  have moved.
- `config: JSON` on `updateCluster`, like `createCluster`: rejected. It reverses ADR-012's typed
  input convention for a new mutation, and the one benefit it has over the typed input (unknown
  keys refused by every surface) is restored in the SDK, and so in the CLI, by decision 5
  (wording corrected 2026-10-13).
- A typed input with a JSON escape hatch: rejected. Two write paths to validate and test, which
  ADR-012 decision 3 already rejected.
- Commit the whole fan-out once, at the end: rejected. See decision 6.
- Answer `updateCluster` before the fan-out and run it in the background: rejected. The caller
  could not learn which deployments were redeployed or failed to start.
- A separate preview query instead of `dryRun`: rejected. It would duplicate the arguments and the
  validation of the mutation.
- An ariadne-codegen plugin that sets `extra="forbid"` on every generated SDK input: rejected for
  this change, because it changes every SDK input type for every SDK user. It remains a candidate
  for a separate change.
