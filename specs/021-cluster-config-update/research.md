# Research: Update a Cluster's Config in Place

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-12

Each decision lists what was chosen, why, and the alternatives that were rejected. Code references are to the tree at the start of this feature (`18087336`).

## D1. The cluster config fan-out compares the resolved config, not the cluster slice

**Decision**: A deployment is redeployed when the resolved config that Styrmin computes now, from the new cluster config, the current environment config and the deployment config, differs from `active_instance.context.instance.config`. Both sides are normalized with `ResolvedConfig.model_validate(...).model_dump(exclude_none=True, mode="json")` before the comparison. A stored resolved config that fails validation counts as "differs" and the deployment is redeployed, the same rule as ADR-012 for a missing environment slice.

A new public function `resolve_instance_config(cluster, environment, deployment)` in `context/resolvers.py` wraps the private `_resolve_instance_config` so that the fan-out computes the resolved config without building a whole `GlobalContext` (no driver, chart or deployed-service lookups per deployment).

**Rationale**:

- The spec requires that deployments in an environment that overrides the changed value are not redeployed (FR-002, User Story 1 scenario 1). A comparison of the cluster slice (`context.cluster.config`), which is the direct transposition of ADR-012, would mark every deployment as changed after any cluster change, including the deployments of environment B in the acceptance scenario.
- The resolved config is what driver templates read (`instance.config.*` in every example driver) and what the ingress post-render patch reads (`context.instance.config.dedicated_ingress`, `context.instance.config.ingress_class`). So "the resolved config changed" is the closest observable proxy for "the rendered manifests may change".
- The comparison also redeploys deployments that an earlier environment fan-out missed, which is the ADR-012 laggard recovery, extended to any cause.

**Alternatives considered**:

- Compare `context.cluster.config` (ADR-012's slice approach): rejected, see above.
- Render the full Helm values and compare them: rejected. It needs the driver version, the chart and the deployed services for every deployment, and a values comparison misses the post-render patches (ingress annotations, env vars, scheduling).
- Compare only the cluster keys that changed: rejected. It does not recover deployments that missed an earlier update (FR-002 resubmission rule), and it needs the old config, which is not reliable after a partial failure.

**Known consequence**: when a Styrmin upgrade changes how the resolved config is computed (for example a new default), the next cluster update redeploys every deployment whose stored resolved config differs in that field. This is the declarative behaviour (constitution I) and is recorded in the ADR.

## D2. Typed `UpdateClusterInput`, not a JSON argument

**Decision**: `updateCluster(input: UpdateClusterInput!, clusterId: UUID, clusterName: String): Cluster`. `UpdateClusterInput` mirrors `ClusterConfig` field by field and reuses the existing leaf inputs in `api/definitions/config/inputs.py` (`DedicatedIngressInput`, `SchedulingInput`, `ExternalUrlScheme`, `ExternalDnsEndpointsType`). Two new leaf inputs are added: `StandardStorageInput` and `FastStorageInput`, one per Pydantic class (ADR-012 convention). A converter `update_cluster_input_to_dict` drops `None` fields, like `update_environment_input_to_dict`.

**Rationale**:

- ADR-012 records the convention: "Any future config-shaped input should follow this 1:1 mapping rather than reverting to JSON-blob shortcuts." `updateEnvironment`, `updateDeployment` and the environment clone override all follow it.
- The input is discoverable by introspection, and the frontend form (User Story 3) gets generated TypeScript types.
- Only two leaf inputs are new. Every other nested type already exists.

**Alternatives considered**:

- `config: JSON`, like `createCluster`: the same JSON file would go through unchanged, and `ClusterConfig`'s `extra="forbid"` would refuse unknown keys on every surface. Rejected because it reverses the ADR-012 convention for a new mutation, and the one benefit that the typed input lacks (unknown keys refused) is restored in the CLI by D3.
- Typed input plus a JSON escape hatch: rejected. Two write paths to validate and test, which ADR-012 decision 3 already rejected for `updateEnvironment`.

**Consequence**: `createCluster` keeps its JSON argument. Changing it is out of scope. The asymmetry is recorded in the ADR.

## D3. The CLI refuses unknown keys in the config file

**Decision**: `styrminctl clusters update` parses `--config` (inline JSON or `@file`, snake_case or camelCase keys) with a new CLI helper `validate_input_strict(model, data)` that walks the generated Pydantic input model and raises a `ValueError` naming every key that is neither a field name nor an alias, at any depth. Only then does it call `UpdateClusterInput.model_validate`.

**Rationale**: The update replaces the whole config (FR-005). The generated SDK models keep Pydantic's default `extra="ignore"`, so a misspelled key (`fqdn_sufix`) would be dropped silently, the real key would be cleared, and every deployment that takes it would be redeployed without an FQDN suffix. User story 9 of the PRD asks that "a typo cannot change the cluster". A direct GraphQL caller is already protected, because GraphQL validation refuses unknown input fields.

**Research directive (third-party dependency gap)**: The gap is in `ariadne-codegen`, which generates the SDK input models with `extra="ignore"`.

- Extension mechanism: `ariadne-codegen` has a plugin system with hooks such as `generate_input_class`, so a plugin could add `model_config = ConfigDict(extra="forbid")` to every generated input class. Rejected for this feature: it changes the behaviour of every SDK input type (`UpdateEnvironmentInput`, `UpdateDeploymentInput`, …) for every SDK user, which is a separate decision with its own blast radius. It is recorded as a follow-up candidate.
- Upstream contribution: an `ariadne-codegen` option for input-model `extra` would serve the same purpose. Rejected for this feature for the same reason, and because the plugin hook already provides the capability without an upstream change.
- Chosen: a CLI-local helper of about 20 lines, applied to `clusters update` only. Existing commands with the same exposure (`deployments update`, `env-clones create --config-override`) are not changed by this feature.

## D4. The dedicated ingress ordering is driven by the status reporter

**Decision**: The ordering of FR-004 is enforced in two places.

1. **In the update call** (`fan_out_cluster_config`, per environment). Styrmin resolves the environment's new effective `dedicated_ingress` (environment value, else cluster value) and finds its live controller (`find_internal_by_environment`).

   **Controller action** (critique E1):

   | New effective value | Controller | Action |
   |---|---|---|
   | Set, environment has applications | None | Create it (new `_create_ingress_controller`, attributed to the administrator). |
   | Set | Exists, not `DELETING`, its instance has a different `dedicated_ingress` | Redeploy it with the new values (`redeploy_for_environment_update`). |
   | Set | `FAILED`, same values, and at least one application waits to move onto it | Redeploy it again (retry). |
   | Set | `DELETING` | None. No second controller while the first is being removed. |
   | Not set | Exists | None here. Removal follows D5. |
   | Any other case | | None. |

   **Application action**, for each live non-internal deployment whose resolved config differs (D1), decided from the deployment's own change, not only from the controller state:

   - Its `dedicated_ingress` changes and the new value is set (it moves onto the controller, or the controller's values change): redeployed now only if the controller is `RUNNING` and its instance has the new values. Otherwise it waits, and stays on its current config, where it is still reachable.
   - Any other change (its `dedicated_ingress` stays the same, or is removed): redeployed now, whatever the controller state. This keeps the Clarifications rule for applications already on a failed controller, and moves applications off a controller that is being turned off.

   "Waits" means the deployment is not redeployed in this call and is counted under `skipped_waiting_for_ingress`.

2. **In the status reporter** (`report_deployment_statuses`, on a state transition):
   - When an internal deployment moves to `RUNNING`, Styrmin runs the fan-out for that one environment (`continue_environment_fan_out`), which ends with the D5 removal check. The per-deployment comparison of D1 makes this idempotent: deployments already at the resolved config are skipped, and the ones that waited are redeployed.
   - When an internal deployment moves to `FAILED`, or a non-internal deployment moves to `RUNNING` or `FAILED`, Styrmin runs the D5 removal check.

**Rationale**:

- The spec reads "before" as "after the controller is ready" (Clarifications, SC-005). The status reporter is the only component that observes `RUNNING`. It already sets `RUNNING` only after the rollout task has finished (`_unfinished_rollout_task`), which is the definition of ready used everywhere else.
- The status reporter already hosts the same kind of side effect: `tear_down_unused_ingress_controller` runs there when the last application reaches `DELETED`.
- No new state is stored. The "waiting" list is not persisted, because the D1 comparison recomputes it from the database each time. A lost status transition is recovered by a resubmission of the cluster config, the same recovery that ADR-012 gives for a failed redeploy start.

**Alternatives considered**:

- Start all redeploys at once, controller first (dispatch order only): rejected. The applications would point to a controller that does not answer yet, and the PRD gives "so that the applications stay reachable" as the reason for the order.
- A Prefect flow that waits for the controller and then redeploys the applications: rejected. It adds a long-running flow per environment, a new flow type that ADR-012 rejected for the environment fan-out ("A dedicated `EnvConfigFanoutTask` type"), and it would hold a worker slot while it polls. Memory note: worker death mid-flow orphans flow runs (#312).
- A persisted "pending fan-out" table: rejected. The D1 comparison already derives the pending set from the database, so a table would duplicate state that can drift.
- The operator waits in the application's prerequisites until the environment's controller is ready: rejected. The operator would need to know which controller serves which environment, and the wait would be invisible in Styrmin's task model.

**Side effect, accepted**: any transition of a controller to `RUNNING` (for example after the first deploy creates it, or after a repair) also runs the environment's fan-out. With converged deployments this starts zero redeploys. With deployments that missed an earlier update it redeploys them, which is the intended laggard recovery.

**Race, accepted**: if the controller moves to `RUNNING` while an update call evaluates the same environment, both can start a redeploy for one deployment. Each redeploy creates a new instance, the instance with the highest instance sequence wins on the StyrminDeployment ([ADR-064](../../dev/adr/0064-styrmindeployment-write-order-by-instance-sequence.md)), and both instances carry the same resolved config. The cost is one extra timeline entry.

## D5. The controller is removed when no application depends on it any more

**Decision**: `tear_down_unused_ingress_controller` (`services/deployment.py`) is extended. Today it requests the deletion of the environment's controller when no live non-internal deployment is left. It now also requests it when all of the following hold:

- The environment's effective `dedicated_ingress` (environment value, else cluster value) is not set.
- Every live non-internal deployment of the environment has an active instance whose resolved config has no `dedicated_ingress`.
- No live non-internal deployment is in `PENDING` or `DEPLOYING`.
- The controller itself is not `PENDING` or `DEPLOYING` (critique E3). The `apply_state` flow that creates or redeploys a controller does not check for `DELETING`, so a deletion requested before that flow has written the StyrminDeployment would leave a controller running on the cluster after its row is tombstoned. The check runs again when the controller reaches `RUNNING` or `FAILED`.

The check runs at the end of each environment's fan-out (so an environment whose applications are already on the shared class loses its controller at once), and from the status reporter on the transitions listed in D4 step 2.

**Rationale**: This removes the controller only after every application's redeploy has finished (FR-004, SC-005), and it reuses the deletion path that #252 built (born-complete delete task, `DELETING` state, operator teardown, tombstone by the status reporter). An application whose redeploy could not be started keeps an active instance with `dedicated_ingress`, so the controller stays until a resubmission moves it. An application that is `RESTORING` keeps its old instance, so the controller stays until the restore has finished and a later update moves it.

**Effect on the environment update** (critique E2): both rules depend only on the stored state, so they also act after `updateEnvironment`. When an environment update turns the environment's own `dedicated_ingress` off and no cluster value applies, the environment fan-out redeploys the applications as today, and the controller is now removed once they have moved. Today it stays until the last application is deleted. When a controller of any environment becomes `RUNNING`, its environment's deployments that are not at their resolved config are redeployed. The environment update's other gaps (it neither creates nor redeploys the controller) stay out of scope. The spec, ADR-0065 and `docs/` state this change.

**Alternatives considered**: remove the controller in the update call after starting the application redeploys. Rejected: the redeploys run asynchronously, so the controller would disappear before the applications have moved to the shared ingress class.

## D6. The cluster update guard covers every environment of the cluster

**Decision**: `update_cluster` calls `guard_no_clone_occupying_environment` for each environment of the cluster before it saves anything. It does not call the backup or restore guards.

**Rationale**: FR-006. This is the same guard as `update_environment` (010 research D8): a redeploy would race the restore flow that builds the clone for the same namespaces. Environment backups and restores have never blocked a config update.

## D7. Transaction boundaries

**Decision**: `update_cluster` runs three steps.

1. In one transaction: load the cluster, run the clone guard on each environment, apply the `createCluster` defaults (`ingress_class: traefik`, `runtime_class: default`) through a shared helper, validate with `validate_cluster_config`, set `cluster.config` and `cluster.capabilities`, commit (FR-001, FR-007).
2. For each environment, in the same unit of work: evaluate and start the redeploys, then commit. A failure to start one redeploy is caught and counted, as in `update_environment` (`dispatch_failed`).
3. Log one line: `cluster_config_fanout cluster_id=… environments=… evaluated=… dispatched=… skipped_noop=… skipped_restoring=… skipped_waiting_for_ingress=… dispatch_failed=… ingress_controllers_created=… ingress_controllers_redeployed=… ingress_controllers_removed=…` (FR-010).

The status reporter continuation runs inside the status report's transaction, inside a savepoint (`uow.session.begin_nested()`), like `_record_operator_steps`. A failure is logged and does not fail the status report. It logs `cluster_config_fanout_continued environment_id=… trigger_deployment_id=…` with the same counts (critique E8).

Each redeploy start keeps its own `try/except`, as in `update_environment`, so a Prefect dispatch failure is counted and never reaches the savepoint (critique E4). A window remains: `apply_state` dispatches the flow before the commit, so if the savepoint or the status report's commit fails after a dispatch, the flow refers to a task row that does not exist. `update_environment` and `deploy_application` have the same window today; this feature does not widen it.

**Rationale**: Same commit order as ADR-012 decision 4. The savepoint keeps the status reporter's main job (state and snapshots) independent of the fan-out.

**Alternative considered**: one commit per environment, separate transactions. Rejected as unnecessary: the per-deployment try/except already isolates failures, and `update_environment` commits once for the whole loop.

## D8. Where the code lives

**Decision**: A new module `backend/styrmin_backend/services/cluster_config_fanout.py` holds `fan_out_cluster_config`, `continue_environment_fan_out`, the per-environment evaluation, the resolved-config comparison and the counts. `services/clusters.py` gets `update_cluster` and a shared `_apply_cluster_defaults`. `services/deployment.py` gets `_create_ingress_controller` (extracted from `_ensure_ingress_controller`, which keeps its current behaviour) and the extended `tear_down_unused_ingress_controller`. `services/deployment_status.py` calls the two hooks.

**Rationale**: `services/deployment.py` is already 1,783 lines. A separate module keeps the fan-out testable on its own (PRD: "each with its own suite"). The import direction stays acyclic: `cluster_config_fanout` imports `deployment`; `clusters` and `deployment_status` import `cluster_config_fanout`; `deployment` imports neither.

The environment fan-out in `services/environments.py` is not changed. The PRD notes that the cluster fan-out could later replace it; that is out of scope.

## D9. A new ADR is needed

**Decision**: Write `dev/adr/0065-cluster-config-fanout.md`.

**Rationale**: Two durable decisions differ from ADR-012 and are not obvious from the code: the resolved-config comparison (D1) and the readiness ordering of the dedicated ingress controller through the status reporter (D4, D5). ADR-012's "Convention to replicate" says new fan-outs adopt the slice comparison, so a reader of ADR-012 alone would expect the wrong rule. The ADR also records the `createCluster`/`updateCluster` input asymmetry (D2).

## D10. E2E design and shard

**Decision**: One new module `backend/tests/e2e/test_cluster_update.py`, marked `shard_compute`, `e2e`, `ci`.

- `test_cluster_update_redeploys_and_moves_dedicated_ingress` (`api_only`): covers User Story 1 scenarios 1 and 2 and User Story 2 scenarios 1 and 2 in four phases on two new environments (A takes every cluster value, B sets `ingress_class: traefik`), each with one `simple-app` deployment created through the SDK.
  1. Turn `dedicated_ingress` off: the applications in A and B are redeployed to the shared class; A's controller is removed only after A's application redeploy finished (task timestamps).
  2. Set `ingress_class: nginx`: A's application gets a redeploy task and its Ingress has `spec.ingressClassName: nginx`; B's application gets no task.
  3. Submit the original session config (dedicated ingress on, `traefik`): A's controller is created, A's application redeploy starts only after the controller task finished, and the application answers through A's controller (port-forward and HTTP, as in `test_traffic_routes_through_dedicated_ingress`).
  4. Submit the original config again: no new task on A's or B's application.
  The test restores the original session config in `finally`, then waits until no deployment of the cluster is `PENDING` or `DEPLOYING`, and deletes A and B.
- `test_edit_cluster_config_from_detail_page` (`ui_only`, User Story 3): changes only the FQDN suffix in the edit form, checks the stored config (new suffix, other values unchanged), and restores the original config through the SDK in `finally` with the same wait.

The helpers `_ingress_controller_ids`, `_wait_for_deployment_status`, `_wait_for_traefik_pod` and `_wait_for_namespace_gone` move from `test_ingress_controller.py` to `backend/tests/e2e/helpers/ingress.py` so both modules import them.

**Rationale**:

- The test changes the cluster config that every test in its shard shares (PRD Tests section). `test_cluster_update.py` sorts before `test_ingress_controller.py` and `test_pod_scheduling.py`, so it runs first in `shard_compute`, when the fewest deployments exist, and it restores the config and waits for convergence before the next module.
- `shard_compute` already runs the dedicated ingress tests, so its runtime already includes Traefik controller start-up.
- The E2E vCluster has no shared ingress controller (no Traefik or NGINX besides the dedicated ones), so "answers through the shared ingress class" (SC-004, second half) is checked through the Ingress resource (`ingressClassName`, no dedicated annotation) and the controller removal, not through HTTP. This limit is recorded in the test docstring.
- A new shard would change the CI matrix, which is a CI/CD change (Ask First). Not needed.
- The tests create deployments through the SDK, not through dual-entrypoint `scenario_driver` methods, so the `api_only` marker is valid (AGENTS.md).

**Alternatives considered**: extend `test_toggle_dedicated_ingress_on_off`. Rejected: it is not marked `ci` and it creates a second cluster, which the single-cluster limit refuses.

## D11. Frontend edit form (P2)

**Decision**: The fields of `CreateClusterDialog.tsx` are extracted into a shared `ClusterConfigFields` component and a shared Zod schema. A new `EditClusterDialog` on `ClusterDetailPage` is prefilled from `cluster.config`, submits `updateCluster` with the whole config, and carries every value the form does not show (`scheduling`, `node_selector`, `db_size`, `backup_ttl`, and `dedicated_ingress.service` fields outside the form) from the stored config into the input. The edit button is shown only to users with the `ADMIN` role.

**Rationale**: ADR-012 recorded that the environment form dropped nested fields and had to block saving. Carrying the unseen values avoids that gap from the start (User Story 3 scenario 1).

## D12. Kubernetes StatefulSet volume claim templates (dependency limit, no workaround)

**Decision**: No workaround. A storage class change fails the redeploy of a StatefulSet-based deployment, as the spec's edge case states.

**Research directive**: Kubernetes refuses any change to `spec.volumeClaimTemplates` of an existing StatefulSet. There is no extension point that allows it, and Styrmin cannot depend on a future Kubernetes release that changes this rule. A workaround (delete the StatefulSet with `--cascade=orphan` and recreate it) would leave the existing volumes on the old class anyway, and moving volumes is out of scope. The documentation of the update states the limit and the recovery.
