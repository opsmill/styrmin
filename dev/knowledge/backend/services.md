# Backend Services Documentation

## Overview

The services layer contains the business logic of the application. It sits between the API layer and the data access layer, orchestrating operations across repositories and external systems.

```text
styrmin_backend/services/
├── clusters.py                    # Cluster management
├── cluster_config_fanout.py       # Cluster config fan-out (ADR-066)
├── environments.py                # Environment management
├── deployment.py                  # Deployment orchestration
├── deployment_status.py           # Server-side handler for reportDeploymentStatuses
├── deployment_timeline.py         # Deployment history with version correlation and context diffs
├── applications.py                # Driver loading (Git, local, object)
├── application_drivers.py         # Read-side accessors for application drivers
├── instances.py                   # Instance lifecycle
├── tasks.py                       # Task state management
├── pod_status.py                  # Server-side handler for reportPodStatuses
├── services_discovery.py          # In-cluster service discovery
├── capabilities.py                # Cluster/environment capability derivation
├── backup_storage_locations.py    # Backup storage location (BSL) management
├── context.py                     # Context generation (generate_context_from_deployment)
├── primitives.py                  # run_job, stop_components, start_components
├── user.py                        # User action workflow registration helpers
├── unit_of_work.py                # Repository coordination (UnitOfWork + SqlModelUnitOfWork)
├── exceptions.py                  # ServiceError hierarchy
├── utils.py                       # Utilities
│
├── driver/                        # Application driver parsing
│   ├── provider.py                # Git-based driver fetching
│   ├── loaders.py                 # Load from filesystem
│   ├── deserializers.py           # Parse YAML/JSON
│   ├── validators.py              # Validate driver structure
│   ├── parsers.py                 # Extract metadata
│   └── models/                    # Driver domain models
│
├── reconciliation/                # State reconciliation (see reconciliation.md)
│   ├── diffs/                     # Diff computation
│   │   ├── comparison.py
│   │   ├── diffs.py
│   │   └── serializer.py
│   └── remediation.py             # Remediation strategies
│
├── backup/                        # Backup/restore (see backup-restore.md)
│   ├── service.py                 # Backup/restore service functions and STRATEGY_MAP
│   ├── environment.py             # Environment backup and environment restore (ADR-055)
│   ├── clone.py                   # Environment clone records and their derived status (ADR-056)
│   ├── ttl.py                     # Backup retention TTL resolution
│   ├── scheduler.py               # Backup schedule management
│   └── strategies/                # disk / postgres / mariadb / mongodb / neo4j / action
│
├── helm/                          # Helm rendering helpers
│   ├── renderer.py                # render_helm_repository_spec / render_helm_chart_spec
│   └── _environment.py            # Jinja2 environment setup
│
├── workflow/                      # Prefect workflow execution wrapper
│   ├── __init__.py                # StyrminWorkflowExecutor (abstract)
│   ├── worker.py                  # WorkflowWorkerExecutor (concrete impl)
│   └── utils.py                   # Utilities
│
├── ingress_controller/            # Ingress controller lifecycle
│
├── scheduling/                    # Pod scheduling helpers
│   ├── references.py              # find, bind and remap deployment references in stored configs
│   └── validator.py               # reconcile-time resolution of deployment references
│
├── env_vars/                      # Free-form deployment env vars (post-render injection, ADR-057)
│   ├── validator.py               # name regex + size caps + risky-name warning
│   ├── resolver.py                # env→dep→comp deepest-wins merge
│   └── exceptions.py              # InvalidEnvVarNameError, ComponentContainerNotDeclaredError, etc.
│
├── image_overrides/               # Per-component image overrides (018)
│   ├── reference.py               # image-reference grammar + {{ app.version }} substitution
│   ├── resolver.py                # stored overrides → live entries and orphans
│   ├── validator.py               # write-time checks: unknown component, reference at the app version
│   └── exceptions.py              # InvalidImageReferenceError, UnknownComponentImageOverrideError
│
├── container_overrides/           # Per-component command/args overrides (014; applied by post-render since 022)
│   ├── validator.py               # non-empty list of strings, size caps, [] rejected
│   ├── resolver.py                # stored blocks → live entries and orphans, no layering
│   └── exceptions.py              # InvalidContainerCommandError, InvalidContainerArgsError, etc.
│
├── component_container/           # Post-render patches into each component container (018, 022)
│   ├── overrides.py               # override_applies, applicable_overrides: the overrides that apply in a context
│   ├── patch_builder.py           # merge patch (env, command, args) + JSON6902 guard (and image) per Deployment/StatefulSet
│   └── exceptions.py              # guard-failure parser, ComponentContainerNotFoundError
│
├── replicas/                      # Per-component replica counts (023, ADR-070)
│   ├── resolver.py                # ReplicaSource, ResolvedReplicas, resolve_replicas, replica_patch_count
│   ├── patch_builder.py           # build_component_replica_patches: one spec.replicas patch per kind per component
│   ├── validator.py               # write-time checks: unknown component, singleton above 1, maximum count
│   └── exceptions.py              # InvalidReplicaCountError, ReplicaCountAboveMaximumError, UnknownComponentReplicaOverrideError, SingletonReplicaOverrideError
│
├── service_ingress/               # Per-service ingress overrides (#598, ADR-090)
│   ├── validator.py               # write-time checks: unknown service, service that is not external, override that a version change would drop
│   └── exceptions.py              # DuplicateServiceNameError, UnknownServiceIngressOverrideError, ServiceIngressNotBuiltError, ServiceIngressOverrideWouldBeDroppedError
│
├── parameters/                    # Driver parameter values
│   ├── validator.py               # validate_parameter_values: defaults, kinds, unknown parameters
│   ├── retired.py                 # drop_retired_parameters: the rule on a driver version change (023)
│   └── exceptions.py              # RetiredParameterValueError
│
└── utilities/                     # Infrastructure utilities (ingress, etc.)
    └── utilities.py               # Utility management
```

<!-- Extracted from specs/001-env-backup-restore on 2026-10-13 (backup/environment.py, backup/clone.py, backup/ttl.py) and specs/021-cluster-config-update on 2026-10-13 (cluster_config_fanout.py) -->

## Unit of Work Pattern

The `UnitOfWork` pattern coordinates database operations across multiple repositories within a single async transaction. The abstract base lives in `services/unit_of_work.py`; the SQLModel implementation is `SqlModelUnitOfWork`, which is what the API layer wires up via dependency injection.

### Interface

```python
class UnitOfWork(ABC):
    session: AsyncSession

    backup_storage_locations: BackupStorageLocationRepository
    clusters: ClusterRepository
    environments: EnvironmentRepository
    helm_repositories: HelmRepositoryRepository
    helm_charts: HelmChartRepository
    component_configs: ComponentConfigRepository
    application_drivers: ApplicationDriverRepository
    application_driver_versions: ApplicationDriverVersionRepository
    application_instances: ApplicationInstanceRepository
    actions: ActionRepository
    utilities: UtilityRepository
    tasks: TaskRepository
    deployments: DeploymentRepository
    deployed_services: DeployedServiceRepository
    backups: BackupRepository
    restores: RestoreRepository
    environment_backups: EnvironmentBackupRepository
    environment_restores: EnvironmentRestoreRepository
    environment_clones: EnvironmentCloneRepository
    backup_schedules: BackupScheduleRepository
    pod_statuses: PodStatusRepository
    deployment_statuses: DeploymentStatusRepository

    async def __aenter__(self) -> "UnitOfWork": ...
    async def __aexit__(self, type_, value, traceback) -> bool | None: ...

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...
```

<!-- Extracted from specs/001-env-backup-restore on 2026-10-13 (environment_backups, environment_restores) and specs/010-environment-clone on 2026-10-13 (environment_clones) -->

`__aexit__` calls `rollback()` automatically when the `async with` block exits with an exception; otherwise services must call `await uow.commit()` explicitly.

`SqlModelUnitOfWork.__aexit__` differs for a block entered while a savepoint (`session.begin_nested()`) is open: when the block exits with an exception, it rolls back only that savepoint, and the outer transaction stays usable, so the code that opened the savepoint can catch the error and keep its other writes. When several nested blocks are open inside the same savepoint, the first one to exit rolls the savepoint back and the others leave the transaction as it is ([#508](https://github.com/opsmill/styrmin/issues/508)). A block entered outside a savepoint rolls back the whole transaction, and an explicit `uow.rollback()` always does. This matters because services open nested `async with uow` blocks of their own: context generation opens one, and `resolve_deployment_reference`, which it calls, opens another. The savepoints are the status reporter's two (phase history and the cluster config fan-out hook), the per-environment fan-out steps that `update_cluster` and `update_environment` share ([ADR-066](../../adr/0066-cluster-config-fanout.md) decision 6, [#452](https://github.com/opsmill/styrmin/issues/452)), and each redeploy of the config fan-out of `restore_environment_backup` (`services/backup/environment.py`, [#508](https://github.com/opsmill/styrmin/issues/508)). `SqlModelUnitOfWork.commit()` raises when a savepoint is open, because in SQLAlchemy 2.0 `session.commit()` there would commit the outer transaction and end the caller's failure isolation.

`async with uow:` marks a transaction block, not the session's lifetime: a single unit of work is entered many times (once per service call and per GraphQL field resolver in a request), so `__aexit__` never closes the session. The code that creates the session closes it:

- **API requests:** `get_session()` (`db/utils.py`) closes the request session when FastAPI tears down the `get_unit_of_work_dependency` dependency.
- **Prefect flows and other standalone code:** `get_unit_of_work()` (`services/unit_of_work.py`) is an async context manager that opens a fresh session and closes it on exit. Use it as `async with get_unit_of_work() as uow:` around each step, so the connection returns to the pool before the flow waits on Kubernetes or Velero.

`DeploymentRepository` exposes a `find_all_by_environment(environment_id, *, include_deleted=False)` accessor (added in 009-environment-update) that returns every non-tombstoned deployment in an environment, internal rows included; `include_deleted=True` adds the tombstoned rows. Callers wanting a narrower subset filter the result in-loop. The fanout in `update_environment` uses this accessor and applies the tombstoned/internal exclusion at iteration time so the per-deployment counters can distinguish "evaluated but excluded" from "evaluated and dispatched/skipped".

### Usage Pattern

```python
async def some_operation(uow: UnitOfWork) -> Result:
    async with uow:
        entity = await uow.repository.get(id)
        entity.update(...)
        await uow.repository.save(entity)
        await uow.commit()
        return entity
```

## Core Services

### Clusters Service (`clusters.py`)

Manages Kubernetes cluster definitions. Only one cluster may exist at a time.

| Function | Description |
|----------|-------------|
| `create_cluster(uow, name="default", config=None)` | Create a cluster (raises `ClusterLimitReachedError` if one already exists). Computes and persists capabilities. |
| `update_cluster(uow, cluster_id, config, acting_user_id, *, dry_run=False)` | Replace the cluster config in full (`ingress_class` and `runtime_class` defaults as on create), recompute capabilities and commit, log `cluster_config_updated` with the acting user and the changed keys, then run the cluster config fan-out. Returns `ClusterUpdateResult` (the cluster and the `FanOutResult`). With `dry_run`, validates and returns `plan_cluster_config_fan_out` without saving. Raises `ClusterNotFoundError`, `InvalidContextError`, or `EnvironmentOperationInProgressError` when an environment clone occupies any environment of the cluster: a clone whose capture of a source environment of the cluster has not ended, or a clone that has not ended and creates an environment of the cluster (`find_clone_occupying_environment`). See "Cluster config fan-out" below and [ADR-066](../../adr/0066-cluster-config-fanout.md). |
| `resolve_cluster(uow, cluster_id?, cluster_name?)` | Resolve cluster by ID or name (exactly one required) |
| `get_cluster(cluster_id, uow)` | Retrieve cluster by ID |
| `get_clusters(uow)` | List all clusters |
| `delete_cluster(cluster_id, uow)` | Delete a cluster (raises `ClusterInUseError` while it still has environments) |

#### Cluster config fan-out

`services/cluster_config_fanout.py` holds `fan_out_cluster_config(cluster, uow, acting_user_id)`, `plan_cluster_config_fan_out(cluster, cluster_config, uow)` (the dry run) and `continue_environment_fan_out(environment_id, uow, trigger_deployment_id)`. Each returns a `FanOutResult`: the counts that are logged, and the deployments redeployed (with their task), waiting for a controller, skipped for a restore and failed to start, the controller actions and the failed environments. For each environment of the cluster, it redeploys (`redeploy_for_environment_update`) each live, non-internal deployment whose resolved config, computed now with `resolve_instance_config`, differs from its active instance's `context.instance.config`. A `DELETING` deployment is counted in `evaluated`, like an internal deployment, and is not redeployed. When the environment's effective `dedicated_ingress` changes, it creates the controller (`create_ingress_controller`, attributed to the acting user) or redeploys it, and an application that would move onto the controller waits until the controller is `RUNNING` with the new values. Each environment ends with `tear_down_unused_ingress_controller`.

In the update call, each environment runs in its own transaction and is committed before the next one starts (in the status reporter, in a savepoint of the report), and each redeploy start, controller action and removal check runs in a savepoint nested in it, so a failure rolls back only that step's writes and is logged and counted. A failure outside these steps (for example, the environment's stored config no longer validates) rolls back the environment's transaction and is logged as `cluster_config_fanout_environment_error`; the environment counts in `environments` and `environments_failed` only. The other environments are still evaluated, and `update_cluster` returns the updated cluster with the environment in `failed_environments`. The counts, `environments_failed` included, are logged as `cluster_config_fanout` (update call) or `cluster_config_fanout_continued` (status reporter). The controller table, the per-application rule and the removal rule are in [ADR-066](../../adr/0066-cluster-config-fanout.md).

### Environments Service (`environments.py`)

Manages environments within clusters.

| Function | Description |
|----------|-------------|
| `resolve_environment(uow, environment_id?, environment_name?, cluster_id?, cluster_name?)` | Resolve environment by ID or name with cluster context |
| `create_environment(name, cluster_id, uow, config=None, upcoming_deployments=None)` | Create environment in cluster (name unique per cluster). Computes and persists capabilities. Binds the deployment references of `config` with no environment, so it refuses every reference except one to a deployment in `upcoming_deployments` (`{id: name}`), which only the environment clone flow passes, for its counterparts. |
| `get_environment(environment_id, uow)` | Retrieve environment by ID |
| `get_environments(uow)` | List all environments |
| `update_environment(environment_id, uow, config, *, acting_user_id)` | Validate, bind the deployment references against the environment (a refused reference saves nothing), persist the env-config row, then fan out a redeploy Task to every live, non-internal deployment in the environment whose active instance is not already at the new config, and create or redeploy the environment's dedicated ingress controller for `acting_user_id`. See "Environment-config fanout" below + [ADR-012](../../adr/0012-environment-config-fanout.md). Raises `EnvironmentOperationInProgressError` while an environment clone occupies the environment (`guard_no_clone_occupying_environment`). Only the clone part of the environment-level guard applies: an environment backup or restore in progress does not block the update. The check runs before the `config is None` no-op path, so a no-op update is also refused while a clone occupies the environment. |
| `delete_environment(environment_id, uow)` | Delete an environment and everything that depends on it, in four steps (see "Deleting an environment" below). |

<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

#### Deleting an environment

<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

`delete_environment` runs four steps, in this order:

1. It settles the environment clone records in which the environment appears, in one transaction:
   - as the created environment, with `detach_clones_from_created_environment`;
   - as the source environment, with `resolve_clones_of_deleted_source_environment`.

   The rules for which clone records are kept and which entries they get are in [backup-restore.md](backup-restore.md#environment-clone). Settling the clones first means that every clone still linked to a snapshot of the environment has finished, so the capture guard in step 2 cannot refuse.
2. It deletes the environment backups of the environment, with the same cascade as `delete_environment_backup` (`delete_environment_backups_for_environment`).
3. It asks the cluster to tear down every remaining deployment of the environment with `request_cluster_teardown`, then deletes the deployment rows with `uow.deployments.delete_all_for_environment`. The teardown request is best effort: the rows are deleted even when the cluster did not answer, and the failures are logged as `environment_delete_teardown_incomplete`.
4. It deletes the environment row. When a concurrent delete already removed it, the call returns without an error.

The `environment_deleted` log line records the number of environment backups and deployments deleted, the teardown requests that succeeded and failed, and the clone records discarded, kept, deleted and failed.

#### Environment-config fanout

<!-- Extracted from specs/009-environment-update on 2026-05-08 -->

`update_environment` is the load-bearing write path for environment configuration. The mutation is thin: validate the input through the Pydantic pipeline, commit the env-config row **before** any Task dispatch (FR-009a), then call `fan_out_environment_config` (`services/cluster_config_fanout.py`), which calls `redeploy_for_environment_update(deployment, uow)` for each live, non-internal deployment whose active instance is not already at the new config, then commits.

Per-deployment no-op detection is in `_deployment_already_at_config(deployment, new_config) -> bool` — it compares the canonical Pydantic round-trip of the deployment's active-instance environment-config slice against the canonical round-trip of the new config. This shape handles two cases with one code path: a true environment-wide no-op (every deployment skips, zero Tasks dispatched, zero spurious timeline entries) and partial-fanout recovery (a re-submission of the same input dispatches Tasks only for laggards that didn't reach the new config on a prior attempt). See [ADR-012](../../adr/0012-environment-config-fanout.md) §1 for the design rationale.

The fanout helper `redeploy_for_environment_update(deployment, uow) -> Task | None` lives in `services/deployment.py`. It mirrors the post-version-decision portion of `update_deployment_version` — does NOT change the deployment's `application_version`, `parameters`, or `service_name_overrides`; only regenerates the active instance against the deployment's currently-bound driver and dispatches the resulting Task.

For a `RESTORING` deployment it returns `None` and changes nothing, because a restore is about to delete and recreate that namespace and a concurrent `apply_state` would write to the same objects. `update_environment` counts that case as `skipped_restoring` in the `env_config_fanout_dispatched` log line. The cluster config fan-out also uses this helper, for applications and for the `REDEPLOY` action on a dedicated ingress controller.

<!-- Extracted from specs/010-environment-clone on 2026-10-13 and specs/021-cluster-config-update on 2026-10-13 -->

<!-- Updated for #424 on 2026-10-14 -->

`fan_out_environment_config` runs the per-environment steps of the cluster config fan-out with the environment comparison passed as `at_config`, so an environment update orders the dedicated ingress controller the same way ([ADR-066](../../adr/0066-cluster-config-fanout.md) decisions 2 and 3): it creates the controller (attributed to `acting_user_id`, the administrator who called `updateEnvironment`) when the effective `dedicated_ingress` is set and the environment has applications, or redeploys it when it was rendered with other values; when the effective value is set, an application whose rendered `dedicated_ingress` differs from its own resolved value (its own `dedicated_ingress`, else the effective value; #453) waits (`skipped_waiting_for_ingress`) until the status reporter sees the controller reach `RUNNING` and redeploys it. When an update turns the environment's own `dedicated_ingress` off and the cluster sets none, the applications are redeployed at once and the removal check (`tear_down_unused_ingress_controller`) removes the controller once they have moved. Like the cluster config fan-out, it skips `DELETING` deployments, and each redeploy, controller action and removal check runs in a savepoint, so a failure rolls back only that unit. The per-item error logs use the `env_config_fanout_` prefix (`env_config_fanout_dispatch_error`, `env_config_fanout_evaluation_error`, `env_config_fanout_ingress_controller_error`, `env_config_fanout_ingress_removal_error`).

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

Each redeploy runs in its own savepoint, so a redeploy that fails rolls back only its own writes and keeps the instances and Tasks of the redeploys before it ([#452](https://github.com/opsmill/styrmin/issues/452)). Per-deployment dispatch failures are caught, logged, and counted (`dispatch_failed`); they do NOT propagate or roll back the env-config row, and peer deployments still receive Tasks (FR-008). One structured log line per fanout dispatch (`env_config_fanout_dispatched ...`) records the counts (FR-023), including the dedicated ingress counts of the cluster config fan-out. The metric `env_config_fanout_deployments_total{environment, outcome}` (FR-023a) is emitted via `_emit_fanout_metric`, once per outcome with the number of deployments; the metric backend is not yet wired in v1, so the helper currently logs the would-be metric at `info` level — see the TODO at `services/environments.py::_emit_fanout_metric`.

### Capabilities Service (`capabilities.py`)

Derives hierarchical capabilities from cluster/environment configuration. Capabilities are persisted as JSON and recalculated on relevant config changes.

| Function | Description |
|----------|-------------|
| `compute_cluster_capabilities(cluster)` | Compute capabilities from cluster config (storage, ingress) |
| `compute_environment_capabilities(environment)` | Compute capabilities from environment config and BSL (backup, ingress) |

Called automatically by cluster/environment creation and BSL assign/unassign operations, and also by:

- `update_cluster` (`clusters.py`), before it commits the new cluster config;
- `update_environment` (`environments.py`), before it commits the new environment config;
- `restore_environment_backup` (`backup/environment.py`), when it writes the captured config back.

An environment clone creates its environment through `create_environment`, so the new environment's capabilities are computed from its own config, not copied from the source ([ADR-027](../../adr/0027-environment-capabilities-computed-independently.md)).

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

### Deployment Service (`deployment.py`)

Orchestrates application deployments.

| Function | Description |
|----------|-------------|
| `deploy_application(driver_name, version, environment_id, uow, created_by_user_id, deployment_config=None, deployment_parameters=None, deployment_name=None, service_name_overrides=None, driver_version_id=None, skip_initial_reconcile=False, release_reference=None, deployment_id=None, upcoming_deployments=None) -> Task \| UUID` | Deploy an application. `driver_version_id` pins a driver version instead of the latest one. With `skip_initial_reconcile`, the deployment starts in `RESTORING`, its services and active instance are still created, `apply_state` is not called, the call logs `deploy_application_reconcile_skipped` and returns the deployment's id. The clone flow keeps its counterpart deployment by this id, because a user can rename the deployment as soon as it is committed ([#493](https://github.com/opsmill/styrmin/issues/493)). `release_reference` fixes the Helm release name instead of `styrmin-<deployment id>`. `deployment_id` gives the new deployment the id the caller chose; otherwise it gets a new one. `upcoming_deployments` (`{id: name}`) lists the other deployments the caller is about to create, which an affinity term may name; the new deployment is added to it, so a term may also name the new deployment. Only the environment clone flow passes the last four, for its counterpart deployments ([ADR-056](../../adr/0056-environment-clone-record-and-cross-target-restore.md), [ADR-075](../../adr/0075-deployment-references-stored-by-id.md)). <!-- Extracted from specs/010-environment-clone on 2026-10-13 and specs/027-deployment-reference-by-id on 2026-10-17 --> |
| `get_deployment(deployment_id, uow)` | Get deployment by ID |
| `update_deployment(deployment_id, config, uow)` | Update deployment configuration. Returns `Task \| None` — a no-op update (resolved desired state equals the current instance) returns `None` with no new instance and no reconcile dispatched. |
| `update_deployment_version(deployment_id, version, uow)` | Change application version. Returns `Task \| None` — requesting the current version is a no-op (`None`, no instance, no reconcile). When the target application version differs from the active instance's and the target driver version declares an `upgrade`/`core` action, and one of its declared `upgrade` actions has no registered flow, it returns a task of type `upgrade_instance` that is already `failed`, with no flow run and a failed hook step, and leaves the deployment unchanged, so the same request starts a new task once the driver is loaded again ([Request check before an upgrade](hooks-and-actions.md#request-check-before-an-upgrade)). <!-- Extracted from specs/029-local-driver-actions on 2026-10-20 --> |
| `redeploy_for_environment_update(deployment, uow) -> Task \| None` | Per-deployment redeploy helper used by the env-config fanout (009) and the cluster config fan-out (021). Regenerates the active instance against the deployment's currently-bound driver and dispatches a Task; does NOT change `application_version`, `parameters`, or `service_name_overrides`. Returns `None` and changes nothing for a `RESTORING` deployment. |
| `delete_deployment(deployment_id, uow)` | Request platform-driven teardown — see lifecycle below |
| `request_cluster_teardown(deployment_id) -> bool` | Set `spec.deletionRequested` on the deployment's `StyrminDeployment` CR, the same signal `delete_deployment` sends. It writes nothing to the database and checks no state, so it also works on the `RESTORING` counterpart deployments of a clone. It returns `False` instead of raising when the CR cannot be patched. Only `delete_environment` calls it. <!-- Extracted from specs/010-environment-clone on 2026-10-13 --> |
| `create_ingress_controller(environment_id, uow, created_by_user_id) -> Deployment` | Create the environment's internal ingress controller deployment from the latest version of the internal driver and dispatch it. Callers check first that no live controller exists. `_ensure_ingress_controller` calls it on the first deploy, and the cluster config fan-out calls it for a `CREATE` action. <!-- Extracted from specs/021-cluster-config-update on 2026-10-13 --> |
| `effective_dedicated_ingress(environment_config, cluster_config)` | The environment's own `dedicated_ingress`, else the cluster's. Any object, including `{}`, turns the controller on; only an absent or null value turns it off. |
| `rendered_dedicated_ingress(deployment)` | The `dedicated_ingress` value that the deployment's active instance was rendered with, or `None` without an active instance. |
| `tear_down_unused_ingress_controller(environment_id, uow) -> int` | Request the deletion of the environment's controller once no application depends on it (lifecycle step 5 below). Runs in the caller's transaction, does not commit, and returns the number of controllers whose deletion it requested. |

Replica overrides and retired parameters (023, [ADR-070](../../adr/0070-replica-overrides-and-retired-parameters.md)):

- `_validate_replica_overrides` returns at once when the config sets no `replicas` (`has_replica_overrides`). Otherwise it builds the component declarations of a driver version with `parse_stored_replica_declaration` and calls `validate_replica_overrides` with the server setting `max_replica_count`. `_validate_config_write` calls it after `validate_deployment_config`, so `INVALID_REPLICA_COUNT` comes first, and before `_validate_component_container_targets`. `deploy_application` calls it with no stored config. `update_deployment_version` without a submitted config calls it on the stored config against the target driver version.
- `update_deployment_version` calls `drop_retired_parameters` on the merged parameter map only when the target driver version differs from the bound one, before `validate_parameter_values` runs against the target driver version and before any ingress dispatch or task.

<!-- Extracted from specs/027-deployment-reference-by-id on 2026-10-17 -->

Deployment references in affinity terms (027, [ADR-075](../../adr/0075-deployment-references-stored-by-id.md)):

- Every write binds the deployment references of the config it stores with `bind_deployment_references(uow, environment_id, config, *, path_prefix, upcoming_deployments=None)` (`services/scheduling/references.py`): each `deployment_ref` of a pod affinity or pod anti-affinity term becomes `{"deployment_id": "<lowercase uuid>"}`, plus `components` when given. A name matches a deployment in `upcoming_deployments` first, then a non-tombstoned deployment of the environment, unless that row is in `upcoming_deployments` under its old name. An id must be in `upcoming_deployments` or be a deployment of the environment that is not tombstoned. The first reference that fails raises `UnresolvableAffinityReferenceError` with the term's full path; its message also gives the environment's name and the reason, and for a tombstoned deployment how to fix the term. The function opens no `async with uow` of its own, so a refusal inside a caller's savepoint rolls back only that savepoint.
- `deploy_application` binds the deployment config (`deployment.config`) and each component config it copies from the driver version (`component[<name>].config`) with `{**upcoming_deployments, new id: resolved name}`, after the name is resolved and before the ingress controller is dispatched, so a refused term starts nothing.
- `update_deployment` binds the whole `deployment.config` on every call, after the rename and the new config are set and before phase 1 saves anything, with `{deployment.id: name after the request}`. A stored id of a tombstoned deployment is therefore refused in phase 1, also on a call that changes only the name. Phase 1 then calls `check_deployment_scheduling` (`services/context.py`), which resolves the environment's, the deployment's and each component's terms as phase 2 does, so a term of the environment's config or of a component that names a tombstoned deployment refuses the update before phase 1 commits.
- `update_deployment_version` binds the effective config after the name is validated, and the component configs that it copies again only when the target driver version differs from the bound one, before the no-op comparison.
- `create_environment` binds with no environment (`environment_id=None`), and `update_environment` binds against the environment before it saves the config.
- At reconcile, `_populate_component_scheduling` (`services/context.py`) and the `resolvedScheduling` resolver call `resolve_component_scheduling` for each component. It drops each pod affinity block that a deeper level discards with `replace: true`, expands each remaining level in its own level, with the prefixes `environment.config.scheduling`, `deployment.config.scheduling` and `component[<name>].config.scheduling`, and then merges the levels. `resolve_deployment_reference` (`services/scheduling/validator.py`) reads ids only, with `DeploymentRepository.find_reference_target`, which reads the id, name, environment and tombstone of a deployment without its components or active instance: a reference that gives a name, an id of another environment and a tombstoned deployment (`deleted=True`, last name) are refused, and an id in `upcoming_deployments` resolves without a lookup. `generate_instance_from_deployment` and `generate_context_from_deployment` take `upcoming_deployments` and pass it down.

**Deployment Flow:**

1. Validate configuration
2. Find matching application driver version
3. Create deployment with components
4. Generate instance from deployment
5. Apply state via reconciliation
6. Return task for tracking

**Deployment Lifecycle (incl. tombstoning):**

<!-- Extracted from specs/008-deployment-deletion on 2026-05-02 -->

The platform-driven delete flow is intentionally **state-driven, not orchestration-driven** — no Prefect flow, no long-running task. The mutation is thin and every state transition is observed off the existing reconciliation cadence:

1. **Resolver** — `deleteDeployment(id)` calls `services.deployment.delete_deployment(uow)`, which:
   - Guards against `RESTORING` (raises `DeploymentRestoringError` → `DEPLOYMENT_RESTORING`).
   - Returns the existing in-flight `DELETE_DEPLOYMENT` task if the row is already `DELETING` (idempotent).
   - Raises `DeploymentNotFoundError` if the row is unknown OR `deleted_at IS NOT NULL` (intentional conflation, see ADR-010).
   - Otherwise patches `spec.deletionRequested = true` on the cluster-side `StyrminDeployment` CR via `kr8s` and creates a born-complete `DELETE_DEPLOYMENT` task (`status=success`, no `prefect_flow_run_id`) in the same UnitOfWork.
   - When the patch finds no CR (`CustomResourceNotFound`), the operator has nothing to tear down, for example after a create that failed at its `hook:setup:pre` step, which runs before the flow writes the namespace and the CR. The service then sets the status to `DELETING` itself and creates the same task, so the reporter's synthetic `Deleted` report (step 4) tombstones the deployment and ends the teardown step. A namespace that the create wrote before its CR write failed stays in the cluster ([follow-up](../../../specs/archive/029-local-driver-actions/follow-ups.md#delete-the-empty-namespace-of-a-create-whose-styrmindeployment-write-failed)). For a `RUNNING` deployment, a missing CR means that something other than Styrmin deleted it, so its resources may remain; the service goes on and logs `deployment_delete_without_styrmin_deployment` at `WARNING` (at `INFO` for a `FAILED` deployment). While the deployment is `PENDING` or `DEPLOYING`, the flow of the change can still write the CR, so the service raises `DeploymentRolloutInProgressError` (`ALREADY_IN_PROGRESS`) instead and writes nothing; its message names the deployment and tells the user to delete it again when its status is `running` or `failed`. Any other patch error still fails the request (spec 029, T052).
2. **Operator** — a `@kopf.on.update(field="spec.deletionRequested", new=True)` handler observes the flip and runs `_teardown_owned_resources` in reverse order (service aliases in all namespaces → Services → HelmRelease → NetworkPolicies/Secrets), then issues a namespace delete. See [Deletion](../agent/operator.md#deletion) for the service-alias step ([#503](https://github.com/opsmill/styrmin/issues/503)).
3. **Reporter (active CR path)** — while teardown is in progress, the operator reports `displayState: Deleting`; the agent's status reporter (`agent/status/reporter.py`) maps it to `DeploymentState.DELETING`. The DB row's `deleted_at` is still NULL — `DELETING` rows remain visible in the default deployment list.
4. **Reporter (terminal transition)** — the `StyrminDeployment` CR is `scope: Namespaced` and lives in the deployment's own namespace, so deleting the namespace deletes the CR with it (see `dev/knowledge/agent/operator.md` § "Namespace co-location"). When the reporter sees DB `status == "deleting"` AND no CR present in the cluster, it synthesises a final `displayState: Deleted` report. Kubernetes deletes the CR before it removes the namespace, so the reporter waits while the namespace has a deletion timestamp, or while it cannot read the namespace (FR-003 of spec 008). A namespace without a deletion timestamp, such as the one of a create that failed before its CR write, does not hold the report back. The reporter is the **sole writer** of `Deployment.deleted_at`: it stamps `deleted_at = now()` atomically with the `DELETED` state flip in the same UnitOfWork commit, so readers cannot observe `status == DELETED` with `deleted_at IS NULL`. In that same commit it also deletes the deployment's `DeployedService` rows (`delete_services_for_deployment`): unlike the deployment row, these carry no audit value and are pure operational discovery/uniqueness state, so a tombstoned deployment must stop occupying its service names and stop leaking into other deployments' service-discovery context. See ADR-046.
   A `DELETING` row only accepts a `Deleted` report: deletion is one-way, so a report polled before the operator saw `deletionRequested` (still `Running` / `Deploying`) is ignored.
5. **Dedicated ingress teardown** — when a non-internal deployment reaches `DELETED`, the reporter calls `services.deployment.tear_down_unused_ingress_controller` in a savepoint of the same commit (the cluster config fan-out hook described below). When no other non-tombstoned, non-internal deployment is left in the environment, it patches `spec.deletionRequested` on the environment's internal ingress controller, records a born-complete `DELETE_DEPLOYMENT` task for it, and sets its status to `DELETING` directly, so new deployments stop reusing the controller before the agent reports the teardown. The controller then follows steps 2–4 like any deployment. A missing CR still moves it to `DELETING` (the synthetic `Deleted` report tombstones it); any other patch failure leaves it untouched and logs `ingress_controller_teardown_request_failed`. While the controller is `DELETING`, `_ensure_ingress_controller` rejects new deployments with `IngressControllerNotHealthyError`, since a second controller would collide with a pinned node port or load balancer IP; once it is tombstoned, `find_internal_by_environment` ignores it and the next deployment provisions a fresh controller.
   The same function also removes the controller while applications are left, once the environment's effective `dedicated_ingress` is off, every application's active instance was rendered without it, no application is `PENDING`, `DEPLOYING`, `FAILED` or `RESTORING`, and the controller is not `PENDING` or `DEPLOYING` ([ADR-066](../../adr/0066-cluster-config-fanout.md) §3). On a state change, the reporter runs it in a savepoint when an internal deployment reaches `FAILED` or an application reaches `RUNNING`, `FAILED` or `DELETED`; when an internal deployment reaches `RUNNING`, it runs `continue_environment_fan_out` instead, which ends with the same check and skips `DELETING` applications as the update call does. A failure in the savepoint is logged as `cluster_config_fanout_hook_error` and the report still commits.
6. **Janitor** — a separate `@kopf.timer` in `operator/janitor.py` reaps CRs that reached `phase: Deleted` more than `DELETED_CR_TTL_HOURS` (default 6h) ago. CRs stuck in `Deleting` are NEVER auto-reaped — they remain visible until human action resolves them.

A row with `deleted_at IS NOT NULL` is **tombstoned**: the cluster-side workload is gone, but the row, its timeline (Tasks), and any associated backups remain queryable. `Environment.deployments(includeDeleted: false)` excludes tombstoned rows by default (and `includeInternal: false` excludes internal deployments, such as the ingress controller); `deployment(id)` is unfiltered so direct-id lookups always succeed (forensic interface).

Deployment-name uniqueness is per `(environment_id, name)` and ignores tombstoned rows via a partial unique index — see ADR-011 / `dev/knowledge/backend/data-models.md`. **Service**-name uniqueness (per `(environment_id, resolved_name)`) is handled differently: rather than a tombstone-aware index/filter, the terminal-transition cleanup above removes a tombstoned deployment's `DeployedService` rows outright, so the names are simply free again. See ADR-046 for why service names diverge from the ADR-011 convention.

### Application Drivers Service (`application_drivers.py`)

Read-side accessors for application drivers stored in the database.

| Function | Description |
|----------|-------------|
| `get_application_drivers(uow)` | List all application drivers |
| `get_application_driver(driver_id, uow)` | Fetch a driver by ID |

### Applications Service (`applications.py`)

Driver loading. The "loaders" pull a driver spec from a source (Git, local directory, or in-memory object), validate it, register its actions with Prefect, and persist the resulting `ApplicationDriver` / `ApplicationDriverVersion` rows.

Loading is **identity-aware** (spec 013): each load computes a provenance fingerprint — `content_hash` (SHA-256 over the canonical three-file input) for local source, `source_commit_sha` (resolved at HEAD) for git source — and looks up via `get_by_identity`. Same identity tuple → the existing row is returned, and no row is created. New fingerprint at the same `(driver, source, version)` → a new row is created alongside the existing ones; no row is ever deleted by the load path. The Prefect action registration is keyed on the fingerprint short prefix and on `action_directory_of` (the driver directory of a git row, the path of a local row), so historical deployments keep resolving actions to the bytes they were deployed from.

`ensure_action_registrations(driver_object, prefect_manager)` registers the actions of driver versions loaded from git and from a local directory (spec 029). It looks up each declared hook and mode with the lookup that hooks use, and registers the actions of each pair that has no registered flow; a load with nothing to register makes no Prefect write. It runs for a new driver version after the service and component validations and before the insert, and for a matching identity before the load returns the stored row, so a repeated load registers the actions that hooks cannot resolve, for example after their Prefect deployments were deleted (FR-006). It refuses with `DriverLoadingError` a local path that contains `{` or `}` when the driver declares actions. See [hooks-and-actions.md](hooks-and-actions.md#registration-pipeline) and [ADR-081](../../adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md).

When the identity matches, the load also compares the `icon`, `description` and `links` of the file with the stored columns. When any of them differs, it writes all three, commits, and returns the row read again. The identity tuple pins the file content, so this only fills in driver versions stored before spec 020 added the columns. No other column changes and no row is created ([ADR-053](../../adr/0053-driver-version-provenance-fingerprint.md)). When two loads of the same driver race and the insert of one fails on the unique identity index, that load returns the row of the other load unchanged.

| Function | Description |
|----------|-------------|
| `load_application_driver_from_object(driver_spec, uow, ...)` | Load a driver from an in-memory `DriverSpec` |
| `load_application_driver_from_git_repository(repository_url, branch, uow, driver_directory=None) -> LoadedDriverVersion` | Clone a driver from Git and load it from the driver directory, or from the repository root when `driver_directory` is `None` (spec 028). The stored driver directory goes into `source_path`, which is part of the identity |
| `load_application_driver_from_local_directory(path, uow) -> LoadedDriverVersion` | Load a driver from a local filesystem path |

The Git and local loaders return `LoadedDriverVersion(version, warnings)`: the stored driver version and the warnings of its `spec.info` block (see "Driver information in `spec.info`" below). `_store_loaded_driver` logs each warning before it stores the driver version. `_driver_info_columns` maps `spec.info` to the three columns:

- `icon`: `str(info.icon)`, the URL as `HttpUrl` normalizes it;
- `description`: the text, or `None` when it is empty;
- `links`: a list of `{"link", "url"}` dictionaries in file order, or `None` when there is none.

<!-- Extracted from specs/020-driver-info-display on 2026-10-13 -->

### Tasks Service (`tasks.py`)

Tracks async operation status.

| Function | Description |
|----------|-------------|
| `get_task(task_id, uow)` | Get task by ID |
| `get_tasks(uow)` | List all tasks |
| `update_task_state(task_id, state_name, state_message, uow)` | Update task status |

### Step Services (`steps/`)

<!-- Extracted from specs/019-task-steps on 2026-10-08 -->

Steps record the units of work of a task, a backup or a restore, so users can view what ran and why
it failed. The data model is in [data-models.md](data-models.md#step), the GraphQL surface in
[api.md](api.md#step), and the decisions in
[ADR-060](../../adr/0060-steps-and-derived-task-result.md).

| Module | What it does |
|--------|--------------|
| `recorder.py` | The only code that creates or changes steps. Its functions run in the caller's transaction and do not commit, except `record_event`, the entry point of the `recordStep` mutation. It enforces the state rules: a forbidden transition is logged and returns the step unchanged, because a late write is not an error. It also creates a task's operator-phase steps (`ensure_operator_steps`) and supersedes the open operator-phase steps of older tasks (`supersede_operator_steps`). |
| `internal_flows.py` | Step writes from INTERNAL flows. Each write runs in its own transaction and logs a warning instead of failing the flow. `open_task_step` retries for up to 10 seconds while the task row is not committed yet. `fail_open_steps` fails the open steps of a USER flow that failed or crashed. |
| `operator_history.py` | `apply_operator_report` turns one status report into changes to the operator-phase steps of the task that the report belongs to. See [Steps of a rollout](../agent/operator.md#steps-of-a-rollout). |
| `results.py` | Calculates the task result on every read. `compute_task_result` and `family_results` are pure functions, so a read model can apply them to rows it loaded in bulk; `get_task_result` serves single reads. See [Task result](data-models.md#task-result). |
| `reads.py` | Step reads for the API, the check of `startedByStepId` (`check_starting_step`), and the "no report from the agent" rule (`no_report_since`, 60 seconds). |
| `exceptions.py` | `StepNotFoundError` (`NOT_FOUND`), `InvalidStepRecordError` and `InvalidStartingStepError` (`VALIDATION_ERROR`). |

The step definitions (key, name and kind of each step that a flow records) are constants in
`domain/steps.py`, for example `COMMAND` and `RESTORE_NAMESPACE`.

**Timeline read model.** `deployment_timeline.py::load_timeline_read_model` loads, for all the
tasks of a timeline, their steps, the tasks those steps started and the last agent reports, in a
fixed number of queries. It then calculates every task result and "no report" time in memory and
returns a `TimelineReadModel`. The GraphQL `Task` and `Step` objects read their part from it, so
the timeline does not query once per task or per step.
`tests/unit/services/test_deployment_timeline_steps.py` fails when a timeline of 20 tasks needs more
queries than a timeline of one task, or more than five.

### Primitives Service (`primitives.py`)

Low-level operations on deployments.

| Function | Description |
|----------|-------------|
| `run_job(deployment_id, commands, env, image, uow)` | Run job in deployment context |
| `stop_components(deployment_id, components, uow)` | Stop specific components |
| `start_components(deployment_id, components, uow)` | Start specific components |

### Context Service (`context.py`)

Generates deployment contexts.

| Function | Description |
|----------|-------------|
| `generate_context_from_deployment_id(deployment_id, uow)` | Generate GlobalContext for deployment |

#### FQDN utility (`context/fqdn.py`)

<!-- Extracted from specs/001-service-fqdn-context on 2026-05-17 -->

Single source of truth for service-FQDN construction, used by both context generation and the GraphQL resolver path. Backs the `primary_fqdn` / `human_readable_fqdn` fields on `ServiceReference` and the matching `DeployedService` GraphQL fields. See [ADR-022](../adr/0022-compute-service-fqdns-at-runtime.md).

| Function | Signature | Description |
|----------|-----------|-------------|
| `to_fqdn_label` | `(value: str) -> str` | RFC 1035 DNS-label sanitizer: lowercase → replace non-alphanumeric with `-` → collapse consecutive `-` → strip leading/trailing `-` → truncate to 63. Also registered as the `to_fqdn_label` Jinja2 filter for non-FQDN sanitization use cases. |
| `compute_primary_fqdn` | `(app_name, deployment_id, fqdn_suffix) -> str \| None` | `{sanitized-app}-{deployment-id}.{suffix}`. Returns `None` when `fqdn_suffix` is empty. |
| `compute_human_readable_fqdn` | `(service_host, environment_name, fqdn_suffix) -> str \| None` | `{sanitized-host}-{sanitized-env}.{suffix}`. Returns `None` when `fqdn_suffix` is empty. |

**Call sites**:

- **Context generation** (`services/context.py`) — populates `ServiceReference` fields while building the deployment context for driver templates.
- **GraphQL resolution** (`Deployment.deployed_services()` resolver in `api/definitions/service/model.py`) — resolves environment + cluster + `ResolvedConfig.fqdn_suffix` once per deployment, computes FQDNs for all services in one pass, and injects them into `DeployedService` Strawberry instances. Avoids N+1 on the environment/cluster lookups.

Driver templates that previously concatenated `{{ app.name }}-{{ instance.deployment_id }}.{{ instance.config.fqdn_suffix }}` inline have been migrated to reference these pre-computed fields. The Jinja2 `to_fqdn_label` filter remains registered for templates that still need sanitization for other purposes (labels, annotations).

## Driver Services (`services/driver/`)

Handles loading and parsing of application driver specifications from Git repositories.

### Provider (`provider.py`)

```python
class DriverProvider(ABC):
    @contextmanager
    def provide(self) -> Generator[Path, None, None]:
        """Yield the folder that holds the driver files."""

    def get_source(self) -> DriverSource:
        """Return the source of the driver (GitSource or LocalSource)."""
```

**GitDriverProvider**: Clones Git repositories using Dulwich, optionally with GitHub credentials.

<!-- Extracted from specs/028-git-driver-directory on 2026-10-18 -->

`GitDriverProvider(repository, branch, token, driver_directory=None)` loads a driver from the repository root or from a driver directory of the repository. The helpers it uses are in `services/driver/driver_directory.py`.

1. **Before the clone**, the constructor calls `normalise_driver_directory`, which returns the stored form or `None` for the repository root:
   - It removes surrounding whitespace, empty segments and `.` segments.
   - It refuses an absolute path, a `..` segment, a backslash, `{` or `}`, a control character, and a stored value longer than 255 characters (`MAX_DRIVER_DIRECTORY_LENGTH`).
   - The stored value goes on `GitSource.driver_directory`. That field carries the driver directory to storage (`source_path`) and to `ActionsWorkflowBuilder`, which adds the `set_working_directory` pull step ([hooks-and-actions.md](hooks-and-actions.md#pull-steps)).
2. **The clone** is the whole repository at the branch. The provider records the HEAD commit SHA as the fingerprint ([ADR-053](../../adr/0053-driver-version-provenance-fingerprint.md)).
3. **After the clone**, before any driver file is read, `_check_driver_directory` runs, for loads from the repository root too:
   - The resolved driver directory must be inside the resolved clone root (`resolve_inside`). The error names the first part of the path that is a symlink leading outside the repository (`_first_link_outside`).
   - `driver.styrmin.yml`, `values.j2.yml` and `actions.py` must resolve inside the driver directory. Prefect puts the folder of the resolved `actions.py` on `sys.path`, so a link to another folder of the repository is refused too.
   - Each path must be readable. `Path.resolve()` does not raise on a symlink loop in Python 3.14, so `_follow_error` calls `stat()` and reports the error.
   - The driver directory must be a folder that holds `driver.styrmin.yml`.
4. The provider logs the repository, branch, commit and driver directory at info level, and yields the resolved driver directory.

Every refusal and failure raises `DriverLoadingError`, or `MissingDriverSpecificationError` when `driver.styrmin.yml` is missing. Both have the code `VALIDATION_ERROR`. The messages after the clone name the driver directory (or "the repository root"), the repository, the branch and the full commit SHA. They never contain the temporary clone path or the target of a symlink. `redact_user_info` removes the user info of every `scheme://` URL from the repository URL and from the text of clone errors. `quoted` escapes control characters in the values the messages show. See [ADR-079](../../adr/0079-driver-actions-import-only-from-their-driver-directory.md).

`LocalDriverProvider` is not changed: the path the admin gives is the driver directory, and no real-path check runs, because a Kubernetes ConfigMap or Secret volume exposes every file as a symlink.

### Loaders (`loaders.py`)

Load driver definitions from the filesystem after cloning.

### Deserializers (`deserializers.py`)

Parse driver manifest files (YAML/JSON) into domain models.

When the driver specification file does not validate, `format_validation_error` writes one line per invalid field, in the form `- <path>: <message> (found <value>)`:

- The path uses `[n]` for list indexes, for example `spec.info.links[0]`.
- The value is shown only when it is a string, an integer or a float, and never for a missing field.

The loader wraps these lines in `DriverLoadingError("Error while deserializing the driver resource: The driver specification is invalid:\n…")` (`loaders.py`).

<!-- Extracted from specs/020-driver-info-display on 2026-10-13 -->

### Validators (`validators.py`)

Validate driver structure and content against schema requirements.

### Driver Models (`models/`)

Domain models representing driver resources:

- `Driver` - Root driver definition
- `Action` - Custom actions with hooks (pre/core/post)
- `Code` - Code resource references
- `Component` - Component definitions

#### Driver information in `spec.info`

<!-- Extracted from specs/020-driver-info-display on 2026-10-13 -->

`Specification.info: Info` is required in the driver specification file, and every key in it is optional (`models/resources/driver.py`). `Info` accepts `icon`, `description`, `links`, `authors` and `license`. Styrmin stores the first three on the driver version and does not store `authors` or `license`.

An invalid `icon` or `links` value does not fail the load. The wrap validator `Info._drop_invalid_icon_and_links` removes it before validation and records one warning for each value it removes. The `warnings` property returns these warnings. The rules are:

- `icon` must be an absolute `https` URL.
- Each `links[].url` must be an absolute `http` or `https` URL.
- Neither may contain a username or password. The warning for such a URL does not repeat the value.
- A `links` entry must be a mapping with exactly the keys `link` and `url`, and `link` must be text. Each invalid entry is removed on its own.
- A `links` value that is not a list is removed as a whole.

Each warning names the field and ends with what was left out, for example `spec.info.links[1].url must be an absolute http or https URL, such as https://example.com/docs (found '…'). The link was not stored.` Any other invalid field of the file still fails the load. The decision is recorded in [ADR-068](../../adr/0068-invalid-driver-info-dropped-with-load-warning.md).

<!-- Extracted from specs/015-infrahub-mcp-driver on 2026-08-04 -->

#### Parameter declarations: requiredness and kinds

Two conventions in `models/resources/parameters.py` surprise driver authors,
because `driver/DRIVERS.md` documents the `parameters` block without stating
either:

**A parameter is required iff it has no `default`.** There is no `required` field
on `DriverParameterDefinition`. `validate_parameter_values`
(`services/parameters/validator.py`) treats any parameter without a default as
mandatory and raises `Missing required parameter: '<name>'` when it is omitted at
deploy time. Because the model is `extra="forbid"`, writing `required: true` does
not add a constraint — it fails driver-load validation as an unknown key.

```yaml
parameters:
  - name: infrahub_address        # required — no default
    kind: string
  - name: mcp_read_only           # optional — has a default
    kind: boolean
    default: false
```

**`DriverParameterKind` is `string | integer | boolean | enum` — there is no
`secret` kind.** Credentials must not be modelled as parameters. Drivers that need
a token either use a passthrough auth mode hardcoded in `values.j2.yml`, or
consume a Kubernetes Secret the chart already references. An `enum` parameter
requires a non-empty `values` list and its `default`, if present, must be a
member; the deploy-time validator rejects out-of-set values before any render.

Values that must not vary per deployment belong as literals in `values.j2.yml`,
not as parameters with a default — a default is an invitation to change it.

A replica count is not a parameter. Since 023, a component declares a driver default with
`replicas` and a fixed count of 1 with `singleton: true` (see [Replica counts](#replica-counts-servicesreplicas)).

## Replica counts (`services/replicas/`)

<!-- Extracted from specs/023-per-component-replicas on 2026-10-15 -->

Design rationale: [ADR-070](../../adr/0070-replica-overrides-and-retired-parameters.md).

| Module | Contents |
|--------|----------|
| `resolver.py` | `ReplicaSource` (`OVERRIDE`, `DRIVER_DEFAULT`, `CHART`), the frozen `ResolvedReplicas(count, source, override_applies)`, `resolve_replicas(declared_replicas, singleton, override, is_orphaned)` and `replica_patch_count(resolved, enabled)`. Pure functions; the patch builder and `Deployment.componentReplicas` call them. |
| `patch_builder.py` | `build_component_replica_patches(context)`: for each component of `context.components` and each kind in `REPLICA_PATCH_KINDS` (`Deployment`, `StatefulSet`), at most one `SpecPatch(specs={"replicas": N})` targeted by the component's label selector. `N` is 0 for a stopped component; no patch when the source is `CHART`. Logs the component, count, source and enabled flag at debug level. `ApplicationHelmReleaseBuilder.build()` places the patches after the component label patches and before the backup, scheduling and component container patches. |
| `validator.py` | `validate_replica_overrides(config, components, stored_config, checked_against, max_replica_count)` on the raw config dict: `UnknownComponentReplicaOverrideError` for an added or changed override on an undeclared component (the stored value sent again passes), `SingletonReplicaOverrideError` for an override above 1 on a singleton component, changed or not, and `ReplicaCountAboveMaximumError` for an added or changed override above `max_replica_count` (the stored value sent again passes). The caller passes the server setting `STYRMIN_MAX_REPLICA_COUNT`; driver defaults are not checked against it. |
| `exceptions.py` | `InvalidReplicaCountError` (`INVALID_REPLICA_COUNT`), `UnknownComponentReplicaOverrideError` (`UNKNOWN_COMPONENT_REPLICA_OVERRIDE`), `SingletonReplicaOverrideError` (`SINGLETON_REPLICA_OVERRIDE`), `ReplicaCountAboveMaximumError` (`REPLICA_COUNT_ABOVE_MAXIMUM`). |

The count itself is checked by `ComponentConfigBlock` (`context/models/config.py`), which raises
`InvalidReplicaCountError` before type conversion. The driver-side keys are typed by
`ReplicaDeclaration` (`context/models/components.py`), the base of both `ArbitrarySectionModel`
classes; see [data-models.md](data-models.md#componentconfig).

## Service ingress overrides (`services/service_ingress/`)

<!-- Extracted from specs/033-service-ingress-override on 2026-11-10 -->

Design rationale: [ADR-090](../../adr/0090-styrmin-builds-the-ingress-of-an-external-service.md).

A deployment stores the ingress class and the FQDN suffix of one external service in `DeploymentConfig.services`, a dict keyed by the driver service name whose values are `ServiceConfigBlock` (`context/models/config.py`, `extra="forbid"`). There is no database column and no Alembic revision. A block with both fields empty is dropped, and a config without the key dumps without it, so the stored config of a deployment without an override is unchanged. `ingress_class` must be a Kubernetes object name (`validate_service_ingress_class`) and `fqdn_suffix` must be a DNS name (`validate_service_fqdn_suffix`). The cluster, environment and deployment levels do not check these two settings.

| Module | Contents |
|--------|----------|
| `validator.py` | `validate_service_ingress_overrides(config, services=, stored_config=, checked_against=, current_version=, target_version=)` on the raw config dict, and `has_service_ingress_overrides(config)`. `services` maps each driver service name of the target version to its `ServiceScope`. |
| `exceptions.py` | The errors in the table below. All are `ServiceError` subclasses. |

| Error | Code | Raised when |
|-------|------|-------------|
| `UnknownServiceIngressOverrideError` | `UNKNOWN_SERVICE_INGRESS_OVERRIDE` | An override that is added or changed names a service that the driver version bound after the write does not declare. Metadata: `service_name`, `known_services`, `checked_against`. |
| `ServiceIngressNotBuiltError` | `SERVICE_INGRESS_NOT_BUILT` | An override that is added or changed names a service that is not `scope: external`, or is external with kind `tcp` or `udp`. Metadata: `service_name`, `scope`, `kind`, `checked_against`. |
| `ServiceIngressOverrideWouldBeDroppedError` | `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED` | The driver version changes, and a stored override that the request sends again, or that the request leaves in place, names a service that the target version removes, declares internal, or declares with kind `tcp` or `udp`. Metadata: `service_name`, `current_version`, `target_version`, `reason` (`removed`, `internal` or `not_http_or_https`), and `target_kind` for the last reason. |
| `DuplicateServiceNameError` | `DUPLICATE_SERVICE_NAME` | The `services` list of the input has the same name twice. Raised when the input is flattened (`_flatten_services` in `api/definitions/deployment/inputs.py`), before the validator runs. Metadata: `name`. |

The service layer calls the validator through `_validate_service_ingress_overrides` in `services/deployment.py`, from `_validate_config_write`, which `deploy_application`, `update_deployment` and `update_deployment_version` use, before any task, flow run or ingress dispatch. `update_deployment_version` passes the driver version that the deployment is bound to now, so a version change is detected. When that call carries no config, the stored config is checked against the target version. A request that clears the override, by leaving it out, is accepted even when the target version no longer declares the service. This differs from the replica validator, which keeps an override on a removed component as an orphan ([ADR-070](../../adr/0070-replica-overrides-and-retired-parameters.md)).

`services/context.py` fills the template data. `services.<driver service name>` gains `ingress_class` and `overridden`, and `human_readable_fqdn` uses the override suffix. Each entry of `deployed_services` gains `driver_service_name`, `scope`, `ingress_class` and `fqdn_suffix`. A service uses the override of the deployment that owns it (`_service_overrides_by_deployment`), and the services of the deployment come last and in the order of the driver version (`_order_deployed_services`), because the Ingress builder gives the application address to the first declared service. `compute_service_address` in `context/fqdn.py` computes the class, suffix and hosts for the template data and for the `DeployedService` resolver, as [ADR-022](../../adr/0022-compute-service-fqdns-at-runtime.md) requires.

The Ingress itself is built by `IngressUtility` (`agent/service/kubernetes/resources/utilities/ingress.py`), described in [Ingresses that Styrmin builds](../agent/operator.md#ingresses-that-styrmin-builds) and [the agent overview](../agent/overview.md#utilities).

## Retired parameters (`services/parameters/retired.py`)

<!-- Extracted from specs/023-per-component-replicas on 2026-10-15 -->

`drop_retired_parameters(values, current_definitions, target_definitions, checked_against)`
returns the parameter map without the parameters that the current driver version declares and the
target does not, when each holds the current default with the same type
(`type(value) is type(default) and value == default`). It logs each drop at info level. Any other
value raises `RetiredParameterValueError` (`RETIRED_PARAMETER_VALUE`, in
`services/parameters/exceptions.py`) for the first such parameter by name. Keys that neither
version declares are kept for `validate_parameter_values`, which rejects them as unknown. The input
map is not modified.

## Reconciliation Engine (`services/reconciliation/`)

Implements declarative state management by comparing desired state (deployment) with current state (instance). See [reconciliation.md](reconciliation.md) for full details.

### Diffs (`diffs/`)

Compares current and new `Instance` objects using DeepDiff:

- `InstanceCreation` - New instance, no current (first deployment)
- `InstanceDeletion` - Current instance, no new (not implemented)
- `InstanceUpdate` - Both exist, contains typed diff entries:
  - `ApplicationVersionChange` - Version string changed
  - `ApplicationDriverVersionChange` - Driver version ID changed
  - `ContextChange` - Resolved configuration changed

### Remediation (`remediation.py`)

Maps diff types to remediation strategies:

```python
class Remediator:
    strategies = {
        InstanceCreation: InstanceCreationStrategy,   # Implemented (with setup hooks)
        InstanceDeletion: InstanceDeletionStrategy,   # Not implemented
        InstanceUpdate: InstanceUpdateStrategy,       # Implemented (with upgrade hook support)
    }
```

When `InstanceUpdate` contains an `ApplicationVersionChange`, the strategy first attempts the upgrade path (looking up driver upgrade hooks from Prefect). If no upgrade hook is defined, it falls back to a regular update. See [hooks-and-actions.md](hooks-and-actions.md) for details.

### State Application

```python
async def apply_state(
    deployment: Deployment,
    current_instance: Instance | None,
    uow: UnitOfWork,
) -> Task:
    """Compare instances, generate remediation, submit to Prefect."""
```

## Helm Services (`services/helm/`)

### Renderer (`renderer.py`)

Renders Helm chart and repository specifications using Jinja2 templates loaded by `_environment.py`.

```python
def render_helm_repository_spec(
    repository_id: UUID,
    repository_url: str,
    repository_type: str = "oci",
) -> dict:
    """Render a Helm Repository specification."""

def render_helm_chart_spec(
    helm_chart_id: UUID,
    name: str,
    version: str,
    repository_id: UUID,
) -> dict:
    """Render a Helm Chart specification."""
```

These produce dicts ready to be embedded in a `HelmRelease` CRD spec. Driver values templates are rendered separately during context resolution.

## Workflow Services (`services/workflow/`)

This package wraps Prefect for the rest of the backend.

- `services/workflow/__init__.py` defines the abstract `StyrminWorkflowExecutor`.
- `services/workflow/worker.py` defines `WorkflowWorkerExecutor(StyrminWorkflowExecutor)`, the concrete implementation that submits flow runs via `arun_deployment` and waits for results.

## Utilities Service (`services/utilities/`)

Manages infrastructure utilities (e.g., Ingress controllers).

```python
def initialize_utilities():
    """Initialize built-in utilities on startup"""
```

## Telemetry Services (`services/telemetry/`)

<!-- Extracted from specs/020-backend-telemetry on 2026-10-10 -->

This package builds and sends the anonymous daily report about the install
([ADR-061](../../adr/0061-server-anonymous-daily-telemetry.md)). The INTERNAL flow
`send_telemetry_report` (`workflows/templates/telemetry.py`) runs it in the task worker; see
[orchestration-flows.md](orchestration-flows.md) for the schedule and the late-run check.

| Module | What it does |
|---|---|
| `install.py` | `ensure_install_id()` runs on every server start, whether telemetry is on or off. It calls `InstallationRepository.get_or_create_install_id()` and commits. On any exception it logs one warning and returns `None`, so the server keeps starting. |
| `payload.py` | `build_report_data(uow)` builds the `data` object of the report. The daily flow and `styrmin telemetry show` both call it, so the command prints exactly what the flow sends. It may create the install ID, so the caller commits. |
| `sender.py` | `build_envelope(data)` wraps the data in the `styrminctl` envelope with `kind: "styrmin"` and `payload_format: "1.0"`. `send_report(data, endpoint, logger)` posts it once and returns whether the endpoint answered 2xx. It never raises. |
| `state.py` | `startup_message(settings)` returns the line the server logs on every start. `show_status_message(settings)` returns the line `styrmin telemetry show` prints to standard error. |

How `payload.py` fills the report:

- **Counts** come from repository methods: `count()` on the cluster and environment repositories,
  `DeploymentRepository.count_live()` (deployments with `deleted_at IS NULL`), and
  `ApplicationDriverVersionRepository.list_usage()`, which returns one `DriverVersionUsage` per
  driver version with its name, version, source type and number of live deployments. The query
  never selects the driver source repository, branch, path or fingerprint.
- **Driver entries** with the same name, version and source type are merged with their counts
  added, and sorted by name, version and source type. Driver versions that differ only in the
  fields the report leaves out would otherwise look like duplicates, and the same database state
  gives the same data and checksum.
- **`styrmin_version()`** reads `project.version` from the workspace root `pyproject.toml`
  (`/source/pyproject.toml` in the image) and accepts it only when `project.name` is
  `styrmin-mvp`. Otherwise it returns `"unknown"`. The release workflow bumps only that file;
  `styrmin-backend` stays at `0.1.0`, so `importlib.metadata` cannot give the release version.

How `sender.py` sends:

- `checksum(data)` is the SHA-256 hex digest of `json.dumps(data)`, the same rule as
  `styrminctl`. The server has its own copy instead of importing the CLI package, and
  `tests/unit/services/telemetry/test_sender.py::test_checksum_matches_styrminctl` asserts both
  give the same digest.
- The post runs inside `asyncio.timeout(10)`, which limits DNS, connect, write and read together.
  An `httpx` timeout alone applies to each phase separately.
- Every exception, timeout or answer outside 2xx counts as a failed send and is logged in one INFO
  line with the error type or HTTP status.

`styrmin telemetry show` (`cli/telemetry.py`) prints the report data as JSON on standard output and
the state line on standard error. It sends nothing. It creates the install ID when the database has
none, which is its only write.

## Exception Hierarchy

All service-layer exceptions inherit from `ServiceError`, which carries an `error_code` (string) and a `default_message` and is mapped to GraphQL extensions by the `StructuredErrorExtension` middleware. Defined in `services/exceptions.py`:

```text
ServiceError (base)
├── NoInstanceError
├── ServiceUnexpectedError
├── InvalidContextError
├── ApplicationDriverNotFoundError
├── ApplicationDriverVersionNotFoundError
├── ClusterLimitReachedError
├── ClusterAlreadyExistsError
├── ClusterNotFoundError
├── EnvironmentAlreadyExistsError
├── EnvironmentNotFoundError
├── InvalidChartValuesError
├── ChartValuesTemplateRenderingError
├── InstanceNotFoundError
├── InconsistentStateError
├── InvalidVersionError
├── InvalidVersionSyntaxError
├── UnupgradableApplicationInstanceError
├── TaskNotFoundError
├── UnknownTaskStateError
├── DeploymentNotFoundError
├── DeploymentNameValidationError
├── DeploymentNameConflictError
├── IngressControllerNotHealthyError
├── InternalDeploymentError
├── ServiceNameConflictError
├── InvalidServiceOverrideError
├── BackupNotFoundError
├── BackupAlreadyInProgressError
├── BackupDuringUpgradeError
├── BackupDeletionError
├── RestoreNotFoundError
├── RestoreAlreadyInProgressError
├── BackupScheduleNotFoundError
├── BackupScheduleAlreadyExistsError
├── EnvironmentBackupNotFoundError          # NOT_FOUND
├── EnvironmentRestoreNotFoundError         # NOT_FOUND
├── EnvironmentOperationInProgressError     # ALREADY_IN_PROGRESS; operation_kind environment_backup / environment_restore / environment_clone
├── EnvironmentBackupNotRestorableError     # OPERATION_DENIED
├── EnvironmentCloneNotFoundError           # NOT_FOUND
├── EnvironmentBackupInUseByCloneError      # IN_USE
├── UnknownEnvironmentConfigFieldError      # VALIDATION_ERROR
├── InvalidCloneDeploymentSelectionError    # NOT_FOUND
├── AmbiguousIdentifierError
├── BackupStorageLocationNotFoundError
├── BackupStorageLocationAlreadyExistsError
├── BackupStorageLocationInUseError
├── InvalidSchedulingConfigError
├── UnknownComponentInConfigError
├── UnresolvableAffinityReferenceError      # VALIDATION_ERROR; deleted=True for a tombstoned deployment
├── UnclonedDeploymentReferenceError        # VALIDATION_ERROR; metadata deployments[]
├── SchedulingPatchRenderingError
├── InvalidEnvVarNameError                  # services/env_vars/exceptions.py
├── DuplicateEnvVarNameError
├── EnvVarSizeLimitExceededError
├── UnknownComponentEnvVarError
├── ComponentContainerNotDeclaredError      # services/env_vars/exceptions.py; override env_vars, image, command or args
├── InvalidContainerCommandError            # services/container_overrides/exceptions.py
├── InvalidContainerArgsError
├── UnknownComponentContainerOverrideError
├── ContainerOverrideSizeLimitExceededError
├── InvalidReplicaCountError                # services/replicas/exceptions.py; INVALID_REPLICA_COUNT
├── ReplicaCountAboveMaximumError          # services/replicas/exceptions.py; REPLICA_COUNT_ABOVE_MAXIMUM
├── UnknownComponentReplicaOverrideError    # UNKNOWN_COMPONENT_REPLICA_OVERRIDE
├── SingletonReplicaOverrideError           # SINGLETON_REPLICA_OVERRIDE
├── DuplicateServiceNameError               # services/service_ingress/exceptions.py; DUPLICATE_SERVICE_NAME
├── UnknownServiceIngressOverrideError      # UNKNOWN_SERVICE_INGRESS_OVERRIDE
├── ServiceIngressNotBuiltError             # SERVICE_INGRESS_NOT_BUILT
├── ServiceIngressOverrideWouldBeDroppedError  # SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED
├── RetiredParameterValueError              # services/parameters/exceptions.py; RETIRED_PARAMETER_VALUE
└── RetiredTemplateFilterError              # services/exceptions.py; component_env_vars, component_command, component_args
```

`RetiredTemplateFilterError` (`RETIRED_TEMPLATE_FILTER`) builds its message and its `migration_guide`
metadata from the filter name: `component_env_vars` links the env var migration guide, and
`component_command` and `component_args` link `CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL`. At driver
load, `JinjaTemplateValidator` walks the parsed template's `Filter` nodes and raises the same error
with `retired_filter_load_message()`, which names the line of the call, so a driver version that
calls a retired filter is not loaded; the render-time filters stay registered for driver versions
loaded earlier. A `driver.styrmin.yml` with `spec.container_overrides` fails in a `before` model
validator on `Specification` with a `removed_key` error that links the same guide. Spec 022
removed `DriverContainerOverrideDocComponentMismatchError`
(`DRIVER_CONTAINER_OVERRIDE_DOC_COMPONENT_MISMATCH`) together with `spec.container_overrides`
([ADR-069](../../adr/0069-container-command-args-by-post-render.md)).

<!-- Extracted from specs/001-env-backup-restore on 2026-10-13 (the first four Environment* errors) and specs/010-environment-clone on 2026-10-13 (the clone errors) -->

<!-- Extracted from specs/011-admin-user-group-mgmt on 2026-05-13 -->

## Authorization helpers

Feature 011 adds two small helper modules under `backend/styrmin_backend/api/auth/` that admin mutations compose to enforce the auth invariants without scattering the rules across resolvers.

### `auth/admin_guards.py` — pure functions over a snapshot

The last-admin invariant lives in two **pure** functions that take their state as parameters:

```python
@dataclass(frozen=True, slots=True)
class AdminSnapshot:
    direct_admin_user_ids: frozenset[UUID]
    group_admin_user_ids: frozenset[UUID]   # admin via group only
    active_by_user_id: Mapping[UUID, bool]

def would_leave_zero_admins(
    action: AdminAction,             # DEACTIVATE | DELETE | DEMOTE | REMOVE_FROM_ADMIN_GROUP
    target_user_id: UUID,
    snapshot: AdminSnapshot,
) -> bool: ...

def can_hard_delete_user(user_id: UUID, fk_refs_present: bool) -> bool: ...
```

Both functions are table-driven testable without a database. The **service-layer caller** is responsible for the concurrency story:

1. Open the UnitOfWork transaction.
2. Lock the admin-conferring rows: `SELECT ... FROM "user" WHERE active = TRUE AND role = 'ADMIN' FOR UPDATE`, plus the matching `"group"` and `user_group` rows for active admin-conferring memberships. A concurrent demotion is forced to wait.
3. Build `AdminSnapshot` from the locked rows.
4. Call `would_leave_zero_admins(...)` and either continue or raise `LastAdminError`.
5. Commit. The locks release.

PostgreSQL's default `READ COMMITTED` is sufficient given the explicit `FOR UPDATE` — no escalation to `REPEATABLE READ`. The lock surface is tiny (admin users + admin groups) so contention is negligible at any realistic admin headcount.

### `auth/membership.py` — diff-and-mutate set replacement

Membership writes go through two functions that implement set-semantics replacement:

```python
async def replace_user_groups(
    uow: UnitOfWork, *, user_id: UUID, group_ids: list[UUID]
) -> tuple[int, int]:
    """Return (added, removed). No-change → (0, 0) with no INSERT/DELETE statements."""

async def replace_group_members(
    uow: UnitOfWork, *, group_id: UUID, member_ids: list[UUID]
) -> tuple[int, int]:
    """Symmetric."""
```

Both load the existing membership, compute `to_add = new - existing` and `to_remove = existing - new`, and issue **only** those `INSERT`/`DELETE` rows. When both sets are empty, zero SQL statements are emitted (the unit test asserts this with `sqlalchemy.event.listens_for(engine, "before_execute")`). A full `DELETE all → INSERT all` is **not** acceptable — it produces spurious churn on no-change paths.

The resolver hands the user-supplied list straight in; normalisation (dedup, ordering) belongs inside the helper, not in every call site.

## Key Files

| File | Purpose |
|------|---------|
| [services/unit_of_work.py](backend/styrmin_backend/services/unit_of_work.py) | Repository coordination |
| [services/deployment.py](backend/styrmin_backend/services/deployment.py) | Deployment orchestration |
| [services/scheduling/references.py](backend/styrmin_backend/services/scheduling/references.py) | Find, bind and remap the deployment references of a stored config |
| [services/scheduling/validator.py](backend/styrmin_backend/services/scheduling/validator.py) | Reconcile-time resolution of deployment references to label selectors |
| [services/applications.py](backend/styrmin_backend/services/applications.py) | Driver management |
| [services/reconciliation/remediation.py](backend/styrmin_backend/services/reconciliation/remediation.py) | State reconciliation |
| [services/driver/provider.py](backend/styrmin_backend/services/driver/provider.py) | Git-based driver loading |
| [services/replicas/resolver.py](backend/styrmin_backend/services/replicas/resolver.py) | Order of precedence of a component's replica count |
| [services/replicas/patch_builder.py](backend/styrmin_backend/services/replicas/patch_builder.py) | `spec.replicas` post-render patches, stopped state included |
| [services/service_ingress/validator.py](backend/styrmin_backend/services/service_ingress/validator.py) | Write-time checks of the per-service ingress overrides |
| [agent/service/kubernetes/resources/utilities/ingress.py](backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py) | The chart post-render patch and the Ingress that Styrmin builds for an external service |
| [services/parameters/retired.py](backend/styrmin_backend/services/parameters/retired.py) | Rule for parameters a target driver version no longer declares |
| [services/telemetry/payload.py](backend/styrmin_backend/services/telemetry/payload.py) | Data of the daily telemetry report |
| [api/auth/admin_guards.py](backend/styrmin_backend/api/auth/admin_guards.py) | Pure last-admin guard functions over `AdminSnapshot` |
| [api/auth/membership.py](backend/styrmin_backend/api/auth/membership.py) | Set-semantics membership replacement (diff-and-mutate) |
