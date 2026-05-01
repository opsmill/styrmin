# Coverage Matrix — GraphQL ↔ Database Propagation

**Audit date**: 2026-05-01
**Audit scope**: `backend/styrmin_backend/api/schema/query.py` and `backend/styrmin_backend/api/schema/mutation.py`, plus the input/output types they reference.
**Existing test sources surveyed**:

- `backend/tests/functional/test_api.py` (~30 tests).
- `backend/tests/functional/test_api_scheduling_config.py` (~7 tests).
- `backend/tests/unit/api/definitions/service/test_deployed_service_fqdn.py` (4 tests; *not* a propagation test — only exercises `from_instance()`, no real repo / DB).

**Verdict legend**: `covered` (existing test asserts DB-level read-back or DB-state-driven projection) · `partial` (existing test exercises path but not via real-repo read-back; treat as gap for this feature) · `gap` (no propagation coverage today) · `excluded` (out of scope with rationale) · `prod-change` (production change required to make testable; needs sign-off before touching).

A row's verdict reflects the strict §V definition from `dev/guides/graphql-propagation-tests.md`. Tests that assert only on resolver return values are recorded as `partial`.

---

## Cluster (`cluster`)

| Element                                            | Schema location  | Direction | Existing coverage                                            | Verdict | Planned test                                                                | Notes                                                             |
|----------------------------------------------------|------------------|-----------|--------------------------------------------------------------|---------|-----------------------------------------------------------------------------|-------------------------------------------------------------------|
| `Mutation.createCluster(name, config)`             | mutation.py:97   | write     | functional/test_api.py::test_create_cluster_and_try_to_create_it_again | partial | propagation/test_cluster.py::test_create_cluster_persists_name_and_config | Existing test asserts resolver return value, not DB read-back     |
| `Mutation.deleteCluster(clusterId, clusterName)`   | mutation.py:104  | write     | functional/test_api.py::test_create_and_delete_cluster_with_error_support | partial | propagation/test_cluster.py::test_delete_cluster_removes_row    | Same as above                                                     |
| `Query.clusters`                                   | query.py:74      | read      | functional/test_api.py::test_list_clusters_returns_environments | partial | propagation/test_cluster.py::test_clusters_projects_seeded_rows | Existing test asserts shape, not all output fields                |
| `Query.cluster(clusterId, clusterName)`            | query.py:80      | read      | functional/test_api.py::test_get_cluster_returns_timestamps   | partial | propagation/test_cluster.py::test_cluster_by_id_projects_all_fields | Strengthen to assert all scalar output fields against seeded row |
| `Query.cluster(clusterName) lookup-by-name path`   | query.py:80      | read      | none                                                         | gap     | propagation/test_cluster.py::test_cluster_by_name_returns_seeded_row | Different code path than `clusterId`                              |
| Output `Cluster.id`, `name`, `config`, `createdOn`, `updatedOn` | api/definitions/cluster/model.py | read | functional/test_api.py::test_get_cluster_returns_timestamps | partial | rolled into above | One assertion block per scalar                                    |
| Output `Cluster.environments` (nested)             | model.py         | read      | functional/test_api.py::test_get_cluster_returns_environments | covered |                                                                             | Existing test seeds env, asserts nested projection                |

## Environment (`environment`)

| Element                                                                  | Schema location  | Direction | Existing coverage                                                         | Verdict | Planned test                                                                     | Notes |
|--------------------------------------------------------------------------|------------------|-----------|---------------------------------------------------------------------------|---------|----------------------------------------------------------------------------------|-------|
| `Mutation.createEnvironment(name, clusterId, clusterName, config)`        | mutation.py:118  | write     | functional/test_api.py::test_create_an_environment_and_try_to_create_it_again | partial | propagation/test_environment.py::test_create_environment_persists_fields | |
| `Mutation.deleteEnvironment(environmentId, environmentName, clusterId, clusterName)` | mutation.py:136  | write     | functional/test_api.py::test_create_and_delete_environment_with_error_support | partial | propagation/test_environment.py::test_delete_environment_removes_row | |
| `Query.environments`                                                      | query.py:122     | read      | none                                                                      | gap     | propagation/test_environment.py::test_environments_projects_seeded_rows | |
| `Query.environment(environmentId, environmentName, clusterId, clusterName)` | query.py:128     | read      | functional/test_api.py::test_get_an_environment_that_does_not_exist (negative only) | gap     | propagation/test_environment.py::test_environment_by_each_lookup_arg | Cover all four lookup paths |
| Output `Environment.cluster` (nested)                                     | api/definitions/environment/model.py | read | none                                                                      | gap     | propagation/test_environment.py::test_environment_projects_cluster_relation | |

## Deployment (`deployment`)

| Element                                                                                          | Schema location  | Direction | Existing coverage                                                  | Verdict | Planned test | Notes |
|--------------------------------------------------------------------------------------------------|------------------|-----------|--------------------------------------------------------------------|---------|--------------|-------|
| `Mutation.deploy(driver, environmentId, environmentName, clusterId, clusterName, version, name, config, parameters, serviceNameOverrides)` | mutation.py:401 | write | none (E2E only) | gap | propagation/test_deployment.py::test_deploy_persists_deployment_and_task | Mock Prefect; assert `Deployment` row, `Task` row, and that the input `config`/`parameters`/`serviceNameOverrides` reached the DB |
| Input `ServiceNameOverride.driverServiceName, overrideName`                                      | api/definitions/service/model.py | write | none | gap | rolled into above | Override mapping must be persisted on the deployment service rows |
| `Mutation.updateDeployment(deploymentId, name, config, parameters, serviceNameOverrides)`        | mutation.py:442 | write | none | gap | propagation/test_deployment.py::test_update_deployment_persists_changes | Mock Prefect; assert config/name updates land in DB |
| `Mutation.updateDeploymentVersion(deploymentId, version, parameters)`                            | mutation.py:734 | write | none | gap | propagation/test_deployment.py::test_update_deployment_version_persists_version | Mock Prefect; assert version row write |
| `Mutation.stopComponents(deploymentId, components)`                                              | mutation.py:682 | write | none | gap | propagation/test_components.py::test_stop_components_creates_task_with_components | Assert `Task` row carries the components list |
| `Mutation.startComponents(deploymentId, components)`                                             | mutation.py:698 | write | none | gap | propagation/test_components.py::test_start_components_creates_task_with_components | Same |
| `Mutation.runJob(deploymentId, commands, env, image)`                                            | mutation.py:714 | write | none | gap | propagation/test_run_job.py::test_run_job_persists_job_task | Assert `Task` row carries `image`, `commands`, and `env` payload |
| `Query.deployment(deploymentId)`                                                                  | query.py:147 | read | functional/test_api.py::test_deployment_environment_resolver, test_deployment_adv_resolver, test_deployment_backward_compat | covered | — | Existing tests seed via real models and assert nested projection |
| Output `Deployment.environment` (nested)                                                          | api/definitions/deployment/model.py | read | functional/test_api.py::test_deployment_environment_resolver | covered | — | |
| Output `Deployment.applicationDriverVersion` (nested)                                             | api/definitions/deployment/model.py | read | functional/test_api.py::test_deployment_adv_resolver | covered | — | |
| Output `Deployment.environmentId`, `applicationDriverVersionId`                                  | api/definitions/deployment/model.py | read | functional/test_api.py::test_deployment_backward_compat | covered | — | |
| Internal-deployment exclusion (`Query.deployment` returning `None` when `internal=True`)         | query.py:154 | read | none | gap | propagation/test_deployment.py::test_internal_deployment_returns_null | Seed an internal deployment, expect `null` |
| `Mutation.updateDeployment` rejects internal deployment (`InternalDeploymentError`)              | mutation.py:455 | write | none | gap | propagation/test_deployment.py::test_update_internal_deployment_raises | |
| `Mutation.updateDeploymentVersion` rejects internal deployment                                   | mutation.py:744 | write | none | gap | propagation/test_deployment.py::test_update_version_internal_deployment_raises | |

## Backup (`backup`)

| Element                                                                | Schema location | Direction | Existing coverage                                  | Verdict | Planned test | Notes |
|------------------------------------------------------------------------|-----------------|-----------|----------------------------------------------------|---------|--------------|-------|
| `Mutation.createBackup(instanceId, name)`                              | mutation.py:472 | write     | none                                               | gap     | propagation/test_backup.py::test_create_backup_persists_row | Mock Prefect dispatch; assert `Backup` row carries `instance_id`, optional `name`, status `PENDING`, target_namespace |
| `Mutation.deleteBackup(backupId)`                                      | mutation.py:547 | write     | none                                               | gap     | propagation/test_backup.py::test_delete_backup_removes_row | |
| `Mutation.createRestore(backupId, targetNamespace, targetInstanceId)`  | mutation.py:558 | write     | none                                               | gap     | propagation/test_restore.py::test_create_restore_persists_row | Mock Prefect; assert `Restore` row carries `backup_id`, `target_namespace`, `target_instance_id` |
| `Query.backup(backupId)`                                               | query.py:158    | read      | functional/test_api.py::test_backup_instance_resolver, test_backup_with_instance_query | partial | propagation/test_backup.py::test_backup_projects_all_scalars | Add scalar-by-scalar assertions across `Backup` type |
| `Query.backups(instanceId, status)`                                    | query.py:165    | read      | functional/test_api.py::test_list_backups_rejects_invalid_status, test_list_backups_accepts_valid_status | partial | propagation/test_backup.py::test_backups_filters_by_status_and_instance | Existing tests assert input validation, not DB-driven filtering with two seeded rows |
| `Query.restore(restoreId)`                                             | query.py:177    | read      | functional/test_api.py::test_restore_backup_resolver | partial | propagation/test_restore.py::test_restore_projects_all_scalars | |
| `Query.restores(backupId, status)`                                     | query.py:186    | read      | functional/test_api.py::test_list_restores_rejects_invalid_status, test_list_restores_accepts_valid_status | partial | propagation/test_restore.py::test_restores_filters_by_status_and_backup | |
| Output `Backup.componentStatuses`                                       | api/definitions/backup/backup.py | read | none | gap | propagation/test_backup.py::test_backup_projects_component_statuses | Seed component-status rows linked to backup |
| Output `Backup.instance`, `Restore.backup`                             | model files | read | functional/test_api.py covers shapes | covered | — | |

## Backup Schedule (`backup_schedule`)

| Element                                                                                  | Schema location | Direction | Existing coverage                            | Verdict | Planned test | Notes |
|------------------------------------------------------------------------------------------|-----------------|-----------|----------------------------------------------|---------|--------------|-------|
| `Mutation.createBackupSchedule(deploymentId, name, cronExpression, retentionCount, enabled)` | mutation.py:596 | write | none | gap | propagation/test_backup_schedule.py::test_create_schedule_persists_all_fields | |
| `Mutation.updateBackupSchedule(scheduleId, name, cronExpression, retentionCount, enabled)`   | mutation.py:618 | write | none | gap | propagation/test_backup_schedule.py::test_update_schedule_persists_changes | Cover each Optional field arg |
| `Mutation.deleteBackupSchedule(scheduleId)`                                                  | mutation.py:640 | write | none | gap | propagation/test_backup_schedule.py::test_delete_schedule_removes_row | |
| `Query.backupSchedule(scheduleId)`                                                            | query.py:198    | read | functional/test_api.py::test_backup_schedule_deployment_resolver | partial | propagation/test_backup_schedule.py::test_schedule_projects_all_scalars | |
| `Query.backupSchedules(deploymentId)`                                                         | query.py:207    | read | none | gap | propagation/test_backup_schedule.py::test_schedules_filters_by_deployment | |

## Backup Storage Location (`backup_storage_location`)

| Element                                                                                                                       | Schema location | Direction | Existing coverage | Verdict | Planned test | Notes |
|-------------------------------------------------------------------------------------------------------------------------------|-----------------|-----------|-------------------|---------|--------------|-------|
| `Mutation.createBackupStorageLocation(name, endpoint, bucket, region, accessKeyId, secretAccessKey)`                          | mutation.py:156 | write     | none              | gap     | propagation/test_backup_storage_location.py::test_create_bsl_persists_all_credentials | Assert each scalar lands in DB |
| `Mutation.updateBackupStorageLocation(backupStorageLocationId, name, endpoint, bucket, region, accessKeyId, secretAccessKey)` | mutation.py:179 | write     | none              | gap     | propagation/test_backup_storage_location.py::test_update_bsl_persists_changes | Test each Optional independently |
| Credential-change side-effect (Prefect dispatch when keys change)                                                              | mutation.py:204 | write     | none              | gap     | propagation/test_backup_storage_location.py::test_update_bsl_credentials_dispatches_sync | Assert prefect_manager_mock called with new credentials |
| `Mutation.deleteBackupStorageLocation(backupStorageLocationId)`                                                                | mutation.py:227 | write     | none              | gap     | propagation/test_backup_storage_location.py::test_delete_bsl_removes_row | |
| `Mutation.assignBackupStorageLocation(environmentId, backupStorageLocationId)`                                                 | mutation.py:239 | write     | none              | gap     | propagation/test_backup_storage_location.py::test_assign_bsl_persists_link | Assert `Environment.backup_storage_location_id` updated; mock prefect dispatch |
| `Mutation.unassignBackupStorageLocation(environmentId)`                                                                        | mutation.py:329 | write     | none              | gap     | propagation/test_backup_storage_location.py::test_unassign_bsl_clears_link | Assert link cleared; mock prefect |
| `Query.backupStorageLocations`                                                                                                  | query.py:92     | read      | none              | gap     | propagation/test_backup_storage_location.py::test_list_bsls_projects_seeded | Assert all scalar output fields |
| `Query.backupStorageLocation(backupStorageLocationId)`                                                                          | query.py:100    | read      | none              | gap     | propagation/test_backup_storage_location.py::test_get_bsl_projects_all_fields | Includes `environmentCount` derived field |
| Output `BackupStorageLocation.environmentCount` (computed)                                                                      | api/definitions/backup_storage_location/model.py | read | none | gap | rolled into above | Seed two envs to assert non-trivial count |

## Application Driver (`application_driver`)

| Element                                                                       | Schema location | Direction | Existing coverage                                | Verdict | Planned test | Notes |
|-------------------------------------------------------------------------------|-----------------|-----------|--------------------------------------------------|---------|--------------|-------|
| `Mutation.loadLocalApplicationDriverVersion(path)`                            | mutation.py:381 | write     | none                                             | gap     | propagation/test_application_driver.py::test_load_local_driver_persists_rows | Mock filesystem/loader at the service boundary; assert `ApplicationDriver` + `ApplicationDriverVersion` rows |
| `Mutation.loadRemoteApplicationDriverVersion(repositoryUrl, branch)`          | mutation.py:391 | write     | none                                             | gap     | propagation/test_application_driver.py::test_load_remote_driver_persists_rows | Mock git clone at the boundary |
| `Query.applicationDrivers`                                                     | query.py:218    | read      | functional/test_api.py::test_adv_application_driver_resolver | partial | propagation/test_application_driver.py::test_application_drivers_projects_seeded | Strengthen to cover all scalar fields of `ApplicationDriver` and nested `versions` |
| `Query.applicationDriver(applicationDriverId)`                                 | query.py:227    | read      | functional/test_api.py::test_adv_application_driver_resolver | partial | propagation/test_application_driver.py::test_application_driver_projects_all_scalars | |
| Output `ApplicationDriverVersion.{components, sourceType, sourceRepository, sourceBranch, sourcePath, defaultVersion, supportedVersions}` | api/definitions/application_driver/model.py | read | none | gap | rolled into above | These scalars have no propagation test today |
| Output `ApplicationDriverVersion.{services, parameters, componentConfigs, helmChart, actions}` (nested) | model | read | none | gap | propagation/test_application_driver.py::test_driver_version_projects_nested_collections | Seed each related row, assert projection |

## Task (`task`)

| Element                       | Schema location | Direction | Existing coverage                              | Verdict | Planned test | Notes |
|-------------------------------|-----------------|-----------|------------------------------------------------|---------|--------------|-------|
| `Query.task(taskId)`          | query.py:110    | read      | functional/test_api.py::test_task_deployment_resolver | partial | propagation/test_task.py::test_task_projects_all_scalars | Assert all scalar output fields, not just nested deployment |
| `Query.tasks`                 | query.py:116    | read      | none                                           | gap     | propagation/test_task.py::test_tasks_projects_seeded | |
| Output `Task.deployment` (nested) | api/definitions/task/model.py | read | functional/test_api.py::test_task_deployment_resolver | covered | — | |

## Pod Status (`pod_status`)

| Element                                                                       | Schema location | Direction | Existing coverage | Verdict | Planned test | Notes |
|-------------------------------------------------------------------------------|-----------------|-----------|-------------------|---------|--------------|-------|
| `Mutation.reportPodStatuses(reports: [DeploymentPodStatusReport!]!)`          | mutation.py:755 | write     | none              | gap     | propagation/test_pod_status.py::test_report_pod_statuses_upserts_and_removes_stale | Assert pod rows upserted with all PodStatusInput fields; seeded stale pod removed |
| Input `DeploymentPodStatusReport.deploymentId, pods`                          | api/definitions/pod_status/model.py | write | none | gap | rolled into above | |
| Input `PodStatusInput.{podName, namespace, phase, ready, restartCount, containerStatuses, nodeName, startedAt}` | model | write | none | gap | rolled into above | Each scalar must be on the persisted row |
| `Query.podStatuses(deploymentId, environmentId, clusterId)`                   | query.py:267    | read      | none              | gap     | propagation/test_pod_status.py::test_pod_statuses_filters_by_each_arg | Seed two rows; assert each filter arg restricts |
| Output `PodStatus` scalar fields                                              | model           | read      | none              | gap     | rolled into above | |

## Deployment Status (`deployment_status`)

| Element                                                                                 | Schema location | Direction | Existing coverage | Verdict | Planned test | Notes |
|-----------------------------------------------------------------------------------------|-----------------|-----------|-------------------|---------|--------------|-------|
| `Mutation.reportDeploymentStatuses(reports: [DeploymentStatusReportInput!]!)`           | mutation.py:796 | write     | none              | gap     | propagation/test_deployment_status.py::test_report_deployment_statuses_upserts_snapshot | Assert status snapshot row + `Deployment.state` updated |
| Input `DeploymentStatusReportInput.{deploymentId, instanceId, phase, displayState, message, conditions, managedResourceCounts}` | api/definitions/deployment_status/model.py | write | none | gap | rolled into above | |
| Input `DeploymentCondition.{type, status, reason, message, lastTransitionTime}`         | model | write | none | gap | rolled into above | |
| Input `ManagedResourceCounts.{networkPolicies, secrets, helmReleases, services, middlewares}` | model | write | none | gap | rolled into above | |

## Deployment Timeline (`deployment_timeline`)

| Element                                          | Schema location | Direction | Existing coverage | Verdict | Planned test | Notes |
|--------------------------------------------------|-----------------|-----------|-------------------|---------|--------------|-------|
| `Query.deploymentTimeline(deploymentId)`         | query.py:258    | read      | none              | gap     | propagation/test_deployment_timeline.py::test_timeline_projects_tasks_with_versions | Seed multiple tasks, assert ordering and version metadata |
| Output `DeploymentTimelineEntry` scalar fields    | api/definitions/deployment_timeline/model.py | read | none | gap | rolled into above | |

## Deployed Service (`service`)

| Element                                            | Schema location | Direction | Existing coverage                                                              | Verdict | Planned test | Notes |
|----------------------------------------------------|-----------------|-----------|--------------------------------------------------------------------------------|---------|--------------|-------|
| `Query.environmentServices(environmentId)`         | query.py:238    | read      | none                                                                           | gap     | propagation/test_service.py::test_environment_services_projects_seeded | Seed `DeployedService` rows; assert projection |
| `Query.deploymentServices(deploymentId)`           | query.py:248    | read      | none                                                                           | gap     | propagation/test_service.py::test_deployment_services_projects_seeded | |
| Output `DeployedService.primaryFqdn`, `humanReadableFqdn`, `primaryUrl`, `humanReadableUrl` (computed) | api/definitions/service/model.py | read | unit/api/definitions/service/test_deployed_service_fqdn.py (4 tests) | partial | propagation/test_service.py::test_deployed_service_fqdns_via_query | Existing tests bypass GraphQL transport; add an HTTP-driven assertion |

## Callback (`callback`)

| Element                                                                | Schema location | Direction | Existing coverage                                  | Verdict | Planned test | Notes |
|------------------------------------------------------------------------|-----------------|-----------|----------------------------------------------------|---------|--------------|-------|
| `Mutation.callback(taskId, stateName, stateMessage, stateType)`        | mutation.py:651 | write     | functional/test_api.py::test_callback_mutation_on_unified_endpoint | partial | propagation/test_callback.py::test_callback_persists_task_state | Existing test asserts the unified endpoint dispatch but not the `Task.state` DB write |
| Output `CallbackResponse.{message, success}`                            | api/definitions/callback/model.py | read | functional/test_api.py::test_callback_mutation_on_unified_endpoint | covered | — | Plain projection of resolver-built object; covered by existing test |

## Health (`health`)

| Element        | Schema location | Direction | Existing coverage                                    | Verdict  | Planned test | Notes                                                                |
|----------------|-----------------|-----------|------------------------------------------------------|----------|--------------|----------------------------------------------------------------------|
| `Query.ok`     | query.py:285    | read      | functional/test_api.py::test_ok_health_check_on_unified_endpoint | excluded | n/a          | Pure constant resolver; no DB or service call. Constitution §V does not apply. |

---

## Summary counts

- **Total rows**: 90 (queries: 18, mutations: 27, output-scalar groups: 25, input-field groups: 12, computed fields: 5, special paths: 3).
- **Currently covered (strict §V)**: 7 rows.
- **Currently partial** (asserts on resolver only or via `from_instance`): 16 rows. Treated as gaps for this feature.
- **Gap (no coverage)**: 66 rows.
- **Excluded with rationale**: 1 row (`Query.ok`).
- **Production change required**: 0 rows.

A row's "rolled into above" entry indicates it shares a planned test with the row immediately above it; the planned test must assert all rolled-in elements before it can be marked closed.

## Estimated test functions

Aggregating the planned tests across rows: **~60 new `pytest` test functions** spread across 14 new test modules under `backend/tests/functional/graphql/`. This matches the 60–90 range in `plan.md`.

---

## Closed in this PR

The following rows are now `covered` by HTTP-driven propagation tests under `backend/tests/functional/graphql/`. Each cited test file drives `client.post("/graphql", ...)` and reads persisted state back through `session.get(...)` per `contracts/propagation-test-contract.md`.

| Domain row                                  | Covering test                                                                                       |
|---------------------------------------------|-----------------------------------------------------------------------------------------------------|
| Cluster `createCluster` write               | `test_cluster.py::test_create_cluster_persists_name_and_config`                          |
| Cluster `deleteCluster` write               | `test_cluster.py::test_delete_cluster_removes_row`                                       |
| Cluster `clusters` / `cluster(id)` read     | `test_cluster.py::test_clusters_projects_seeded_rows`, `::test_cluster_by_id_projects_all_fields` |
| Cluster `cluster(name)` lookup path         | `test_cluster.py::test_cluster_by_name_returns_seeded_row`                               |
| Cluster.environments nested                 | `test_cluster.py::test_cluster_projects_environments_relation`                           |
| Cluster `cluster(id)` not-found projection  | `test_cluster.py::test_cluster_by_unknown_id_returns_null`                               |
| Environment `createEnvironment`             | `test_environment.py::test_create_environment_persists_with_cluster_id`, `::test_create_environment_persists_with_cluster_name` |
| Environment `deleteEnvironment`             | `test_environment.py::test_delete_environment_by_id_removes_row`, `::test_delete_environment_by_name_and_cluster_name_removes_row` |
| Environment `environments` / `environment(args)` reads | `test_environment.py::test_environments_projects_seeded_rows`, `::test_environment_by_each_lookup_arg[*]`, `::test_environment_projects_cluster_relation` |
| BSL `createBackupStorageLocation`           | `test_backup_storage_location.py::test_create_bsl_persists_all_credentials`              |
| BSL `updateBackupStorageLocation` per-field | `test_backup_storage_location.py::test_update_bsl_persists_field_changes[*]`             |
| BSL credentials write                       | `test_backup_storage_location.py::test_update_bsl_credentials_dispatches_sync`           |
| BSL `deleteBackupStorageLocation`           | `test_backup_storage_location.py::test_delete_bsl_removes_row`                            |
| BSL assign/unassign env links               | `test_backup_storage_location.py::test_assign_bsl_persists_link`, `::test_unassign_bsl_clears_link` |
| BSL `backupStorageLocations` / `backupStorageLocation(id)` reads (incl. computed `environmentCount`) | `test_backup_storage_location.py::test_list_bsls_projects_seeded`, `::test_get_bsl_projects_all_fields_and_environment_count` |
| BackupSchedule `createBackupSchedule`       | `test_backup_schedule.py::test_create_schedule_persists_all_fields`                      |
| BackupSchedule `updateBackupSchedule` per-field | `test_backup_schedule.py::test_update_schedule_persists_field_changes[*]`             |
| BackupSchedule `deleteBackupSchedule`       | `test_backup_schedule.py::test_delete_schedule_removes_row`                              |
| BackupSchedule `backupSchedule(id)` read    | `test_backup_schedule.py::test_schedule_projects_all_scalars`                            |
| BackupSchedule `backupSchedules(deploymentId)` filter | `test_backup_schedule.py::test_schedules_filters_by_deployment`                |
| Task `task(id)` / `tasks` reads             | `test_task.py::test_task_projects_all_scalars`, `::test_tasks_projects_seeded`           |
| Callback Task-state mapping persists        | `test_callback.py::test_callback_running_state_persists_task_status`, `::test_callback_completed_state_persists_task_success` |
| Callback unknown-task negative              | `test_callback.py::test_callback_unknown_task_returns_error_response`                    |
| PodStatus `reportPodStatuses` upsert+stale-removal | `test_pod_status.py::test_report_pod_statuses_upserts_and_removes_stale`         |
| PodStatus `podStatuses` filter-by-each-arg  | `test_pod_status.py::test_pod_statuses_filters_by_each_arg[*]`                            |
| Deployment internal-deployment exclusion (read) | `test_deployment.py::test_internal_deployment_returns_null`, `::test_non_internal_deployment_projects_fields` |
| Deployment internal-deployment guards (write) | `test_deployment.py::test_update_internal_deployment_raises`, `::test_update_version_internal_deployment_raises` |

**Counts after this PR**:

- Closed (this PR): ~30 row-equivalents across 8 domains.
- Pre-existing covered: 7 rows.
- Still gap (deferred to follow-up): ~52 row-equivalents — see `tasks.md` Phase 7.
- Excluded with rationale: 1 row (`Query.ok`).

The harness (`conftest.py`, `seeds.py`, `quickstart.md`, `contracts/propagation-test-contract.md`) is in place. Closing the deferred rows is now mechanical per-domain work using the recipe.
