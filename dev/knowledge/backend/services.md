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
├── applications.py                # Driver loading (Git, local, object) and application instantiation
├── application_drivers.py         # Read-side accessors for application drivers
├── instances.py                   # Instance lifecycle
├── tasks.py                       # Task state management
├── pod_status.py                  # Server-side handler for reportPodStatuses
├── parameters.py                  # Driver parameter resolution
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
│   └── strategies/                # disk / postgres / mariadb / mongodb / neo4j / neo4j-community / action
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

`SqlModelUnitOfWork.__aexit__` differs when a savepoint (`session.begin_nested()`) is open: a block that exits with an exception rolls back only the innermost open savepoint, and the outer transaction stays usable, so the code that opened the savepoint can catch the error and keep its other writes. Outside a savepoint it rolls back the whole transaction, and an explicit `uow.rollback()` always does. This matters because services open nested `async with uow` blocks of their own (context generation, `resolve_deployment_reference`). The savepoints are the status reporter's two (phase history and the cluster config fan-out hook) and the per-environment fan-out steps that `update_cluster` and `update_environment` share ([ADR-066](../../adr/0066-cluster-config-fanout.md) decision 6, [#452](https://github.com/opsmill/styrmin/issues/452)). `SqlModelUnitOfWork.commit()` raises when a savepoint is open, because in SQLAlchemy 2.0 `session.commit()` there would commit the outer transaction and end the caller's failure isolation.

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
| `delete_cluster(cluster_id, uow)` | Delete a cluster |

#### Cluster config fan-out

`services/cluster_config_fanout.py` holds `fan_out_cluster_config(cluster, uow, acting_user_id)`, `plan_cluster_config_fan_out(cluster, cluster_config, uow)` (the dry run) and `continue_environment_fan_out(environment_id, uow, trigger_deployment_id)`. Each returns a `FanOutResult`: the counts that are logged, and the deployments redeployed (with their task), waiting for a controller, skipped for a restore and failed to start, the controller actions and the failed environments. For each environment of the cluster, it redeploys (`redeploy_for_environment_update`) each live, non-internal deployment whose resolved config, computed now with `resolve_instance_config`, differs from its active instance's `context.instance.config`. A `DELETING` deployment is counted in `evaluated`, like an internal deployment, and is not redeployed. When the environment's effective `dedicated_ingress` changes, it creates the controller (`create_ingress_controller`, attributed to the acting user) or redeploys it, and an application that would move onto the controller waits until the controller is `RUNNING` with the new values. Each environment ends with `tear_down_unused_ingress_controller`.

In the update call, each environment runs in its own transaction and is committed before the next one starts (in the status reporter, in a savepoint of the report), and each redeploy start, controller action and removal check runs in a savepoint nested in it, so a failure rolls back only that step's writes and is logged and counted. A failure outside these steps (for example, the environment's stored config no longer validates) rolls back the environment's transaction and is logged as `cluster_config_fanout_environment_error`; the environment counts in `environments` and `environments_failed` only. The other environments are still evaluated, and `update_cluster` returns the updated cluster with the environment in `failed_environments`. The counts, `environments_failed` included, are logged as `cluster_config_fanout` (update call) or `cluster_config_fanout_continued` (status reporter). The controller table, the per-application rule and the removal rule are in [ADR-066](../../adr/0066-cluster-config-fanout.md).

### Environments Service (`environments.py`)

Manages environments within clusters.

| Function | Description |
|----------|-------------|
| `resolve_environment(uow, environment_id?, environment_name?, cluster_id?, cluster_name?)` | Resolve environment by ID or name with cluster context |
| `create_environment(name, cluster_id, uow, config=None)` | Create environment in cluster (name unique per cluster). Computes and persists capabilities. |
| `get_environment(environment_id, uow)` | Retrieve environment by ID |
| `get_environments(uow)` | List all environments |
| `update_environment(environment_id, uow, config, *, acting_user_id)` | Validate + persist env-config row, then fan out a redeploy Task to every live, non-internal deployment in the environment whose active instance is not already at the new config, and create or redeploy the environment's dedicated ingress controller for `acting_user_id`. See "Environment-config fanout" below + [ADR-012](../../adr/0012-environment-config-fanout.md). Raises `EnvironmentOperationInProgressError` while an environment clone occupies the environment (`guard_no_clone_occupying_environment`). Only the clone part of the environment-level guard applies: an environment backup or restore in progress does not block the update. The check runs before the `config is None` no-op path, so a no-op update is also refused while a clone occupies the environment. |
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

`fan_out_environment_config` runs the per-environment steps of the cluster config fan-out with the environment comparison passed as `at_config`, so an environment update orders the dedicated ingress controller the same way ([ADR-066](../../adr/0066-cluster-config-fanout.md) decisions 2 and 3): it creates the controller (attributed to `acting_user_id`, the administrator who called `updateEnvironment`) when the effective `dedicated_ingress` is set and the environment has applications, or redeploys it when it was rendered with other values; an application whose rendered `dedicated_ingress` differs from the effective value waits (`skipped_waiting_for_ingress`) until the status reporter sees the controller reach `RUNNING` and redeploys it. When an update turns the environment's own `dedicated_ingress` off and the cluster sets none, the applications are redeployed at once and the removal check (`tear_down_unused_ingress_controller`) removes the controller once they have moved. Like the cluster config fan-out, it skips `DELETING` deployments, and each redeploy, controller action and removal check runs in a savepoint, so a failure rolls back only that unit. The per-item error logs use the `env_config_fanout_` prefix (`env_config_fanout_dispatch_error`, `env_config_fanout_evaluation_error`, `env_config_fanout_ingress_controller_error`, `env_config_fanout_ingress_removal_error`).

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
| `deploy_application(driver_name, version, environment_id, uow, created_by_user_id, deployment_config=None, deployment_parameters=None, deployment_name=None, service_name_overrides=None, driver_version_id=None, skip_initial_reconcile=False, release_reference=None) -> Task \| None` | Deploy an application. `driver_version_id` pins a driver version instead of the latest one. With `skip_initial_reconcile`, the deployment starts in `RESTORING`, its services and active instance are still created, `apply_state` is not called, the call logs `deploy_application_reconcile_skipped` and returns `None`. `release_reference` fixes the Helm release name instead of `styrmin-<deployment id>`. Only the environment clone flow passes the last two, for its counterpart deployments ([ADR-056](../../adr/0056-environment-clone-record-and-cross-target-restore.md)). <!-- Extracted from specs/010-environment-clone on 2026-10-13 --> |
| `get_deployment(deployment_id, uow)` | Get deployment by ID |
| `update_deployment(deployment_id, config, uow)` | Update deployment configuration. Returns `Task \| None` — a no-op update (resolved desired state equals the current instance) returns `None` with no new instance and no reconcile dispatched. |
| `update_deployment_version(deployment_id, version, uow)` | Change application version. Returns `Task \| None` — requesting the current version is a no-op (`None`, no instance, no reconcile). |
| `redeploy_for_environment_update(deployment, uow) -> Task \| None` | Per-deployment redeploy helper used by the env-config fanout (009) and the cluster config fan-out (021). Regenerates the active instance against the deployment's currently-bound driver and dispatches a Task; does NOT change `application_version`, `parameters`, or `service_name_overrides`. Returns `None` and changes nothing for a `RESTORING` deployment. |
| `delete_deployment(deployment_id, uow)` | Request platform-driven teardown — see lifecycle below |
| `request_cluster_teardown(deployment_id) -> bool` | Set `spec.deletionRequested` on the deployment's `StyrminDeployment` CR, the same signal `delete_deployment` sends. It writes nothing to the database and checks no state, so it also works on the `RESTORING` counterpart deployments of a clone. It returns `False` instead of raising when the CR cannot be patched. Only `delete_environment` calls it. <!-- Extracted from specs/010-environment-clone on 2026-10-13 --> |
| `create_ingress_controller(environment_id, uow, created_by_user_id) -> Deployment` | Create the environment's internal ingress controller deployment from the latest version of the internal driver and dispatch it. Callers check first that no live controller exists. `_ensure_ingress_controller` calls it on the first deploy, and the cluster config fan-out calls it for a `CREATE` action. <!-- Extracted from specs/021-cluster-config-update on 2026-10-13 --> |
| `effective_dedicated_ingress(environment_config, cluster_config)` | The environment's own `dedicated_ingress`, else the cluster's. Any object, including `{}`, turns the controller on; only an absent or null value turns it off. |
| `rendered_dedicated_ingress(deployment)` | The `dedicated_ingress` value that the deployment's active instance was rendered with, or `None` without an active instance. |
| `tear_down_unused_ingress_controller(environment_id, uow) -> int` | Request the deletion of the environment's controller once no application depends on it (lifecycle step 5 below). Runs in the caller's transaction, does not commit, and returns the number of controllers whose deletion it requested. |

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
2. **Operator** — a `@kopf.on.update(field="spec.deletionRequested", new=True)` handler observes the flip and runs `_teardown_owned_resources` in reverse order (Services → HelmRelease → NetworkPolicies/Secrets), then issues a namespace delete.
3. **Reporter (active CR path)** — while teardown is in progress, the operator reports `displayState: Deleting`; the agent's status reporter (`agent/status/reporter.py`) maps it to `DeploymentState.DELETING`. The DB row's `deleted_at` is still NULL — `DELETING` rows remain visible in the default deployment list.
4. **Reporter (terminal transition)** — the `StyrminDeployment` CR is `scope: Namespaced` and lives in the deployment's own namespace, so deleting the namespace deletes the CR with it (see `dev/knowledge/agent/operator.md` § "Namespace co-location"). When the reporter sees DB `status == "deleting"` AND no CR present in the cluster, it synthesises a final `displayState: Deleted` report. The reporter is the **sole writer** of `Deployment.deleted_at`: it stamps `deleted_at = now()` atomically with the `DELETED` state flip in the same UnitOfWork commit, so readers cannot observe `status == DELETED` with `deleted_at IS NULL`. In that same commit it also deletes the deployment's `DeployedService` rows (`delete_services_for_deployment`): unlike the deployment row, these carry no audit value and are pure operational discovery/uniqueness state, so a tombstoned deployment must stop occupying its service names and stop leaking into other deployments' service-discovery context. See ADR-046.
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

Driver loading and application instantiation. The "loaders" pull a driver spec from a source (Git, local directory, or in-memory object), validate it, register its actions with Prefect, and persist the resulting `ApplicationDriver` / `ApplicationDriverVersion` rows.

Loading is **identity-aware** (spec 013): each load computes a provenance fingerprint — `content_hash` (SHA-256 over the canonical three-file input) for local source, `source_commit_sha` (resolved at HEAD) for git source — and looks up via `get_by_identity`. Same identity tuple → the existing row is returned, and nothing else is created or registered. New fingerprint at the same `(driver, source, version)` → a new row is created alongside the existing ones; no row is ever deleted by the load path. The Prefect action registration is keyed on the fingerprint short prefix so historical deployments keep resolving actions to the bytes they were deployed from.

When the identity matches, the load first compares the `icon`, `description` and `links` of the file with the stored columns. When any of them differs, it writes all three, commits, and returns the row read again. The identity tuple pins the file content, so this only fills in driver versions stored before spec 020 added the columns. No other column changes, no row is created, and the Prefect actions are not registered again ([ADR-053](../../adr/0053-driver-version-provenance-fingerprint.md)). When two loads of the same driver race and the insert of one fails on the unique identity index, that load returns the row of the other load unchanged.

| Function | Description |
|----------|-------------|
| `load_application_driver_from_object(driver_spec, uow, ...)` | Load a driver from an in-memory `DriverSpec` |
| `load_application_driver_from_git_repository(repository_url, branch, uow) -> LoadedDriverVersion` | Clone a driver from Git and load it |
| `load_application_driver_from_local_directory(path, uow) -> LoadedDriverVersion` | Load a driver from a local filesystem path |
| `instantiate_application(...)` | Instantiate an application from a loaded driver |

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
    async def get(self, repository_url: str, branch: str) -> Path:
        """Clone repository and return local path"""
```

**GitDriverProvider**: Clones Git repositories using Dulwich, optionally with GitHub credentials.

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
├── UnresolvableAffinityReferenceError
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
| [services/applications.py](backend/styrmin_backend/services/applications.py) | Driver management |
| [services/reconciliation/remediation.py](backend/styrmin_backend/services/reconciliation/remediation.py) | State reconciliation |
| [services/driver/provider.py](backend/styrmin_backend/services/driver/provider.py) | Git-based driver loading |
| [services/telemetry/payload.py](backend/styrmin_backend/services/telemetry/payload.py) | Data of the daily telemetry report |
| [api/auth/admin_guards.py](backend/styrmin_backend/api/auth/admin_guards.py) | Pure last-admin guard functions over `AdminSnapshot` |
| [api/auth/membership.py](backend/styrmin_backend/api/auth/membership.py) | Set-semantics membership replacement (diff-and-mutate) |
