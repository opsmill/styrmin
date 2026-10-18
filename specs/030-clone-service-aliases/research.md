# Research: A Clone Writes Its Own Service Aliases and Restores None of the Source's

Code references are to `develop` at `f4e60189`. Paths without a prefix are under `backend/styrmin_backend/`.

## R-001: How the cross-target restore leaves out the alias Services

**Decision**: On a cross-target restore only, the Velero Restore gets a `spec.labelSelector` that matches every object except the alias Services:

```yaml
labelSelector:
  matchExpressions:
    - key: styrmin.io/service-alias
      operator: NotIn
      values: ["true"]
```

`build_velero_restore` (`agent/service/kubernetes/resources/builders/backup.py`) sets it in the same branch that sets `namespaceMapping` and adds `CROSS_TARGET_EXCLUDED_RESOURCES`. `VeleroRestore` (`agent/service/kubernetes/velero/resources.py`) gets a `label_selector` field that `render()` writes only when it is set, so an in-place restore renders as today (FR-006).

**Rationale**: Styrmin deploys Velero 1.18.1 (chart `12.1.0`, `helm/styrmin/Chart.yaml`). In that version:

- `spec.labelSelector` is a full `metav1.LabelSelector`, so `matchExpressions` with `NotIn` is accepted, and `NotIn` also matches an object that has no such label ([`restore_types.go` L69-L83](https://github.com/vmware-tanzu/velero/blob/v1.18.1/pkg/apis/velero/v1/restore_types.go#L69-L83), [`restore.go` L192-L215](https://github.com/vmware-tanzu/velero/blob/v1.18.1/pkg/restore/restore.go#L192-L215)).
- Velero checks the selector only on the top-level items it reads from the backup ([`restore.go` L2349-L2352](https://github.com/vmware-tanzu/velero/blob/v1.18.1/pkg/restore/restore.go#L2349-L2352)). It creates the target namespace from the backed-up Namespace object without checking the selector ([`restore.go` L725-L760](https://github.com/vmware-tanzu/velero/blob/v1.18.1/pkg/restore/restore.go#L725-L760)), restores pod volumes for each restored pod ([`restore.go` L1739-L1743](https://github.com/vmware-tanzu/velero/blob/v1.18.1/pkg/restore/restore.go#L1739-L1743)), and restores additional items without checking it ([`restore.go` L1381-L1417](https://github.com/vmware-tanzu/velero/blob/v1.18.1/pkg/restore/restore.go#L1381-L1417)). Pods, PVCs, Secrets, the StyrminDeployment and the operator's own Services carry no `styrmin.io/service-alias` label, so they match.
- Restore hooks select pods with their own `labelSelector` ([`restore_types.go` L194](https://github.com/vmware-tanzu/velero/blob/v1.18.1/pkg/apis/velero/v1/restore_types.go#L194)).
- Velero issue [#7535](https://github.com/vmware-tanzu/velero/issues/7535), where a label selector broke data-mover restores, was fixed in 1.14 and concerns DataUploads, which Styrmin does not use (file-system backup).

The selector keeps the aliases out for the whole restore, so FR-001 holds while Velero runs. With `existingResourcePolicy: update`, an alias that a peer's alias step wrote into the counterpart's namespace while Velero runs is not replaced, because Velero no longer restores any alias.

**Dependency extension evaluation** (research directive):

| Mechanism | Can it leave out the aliases of a cross-target restore only? | Decision |
|-----------|---------------------------------------------------------------|----------|
| Restore `spec.labelSelector` (built in) | Yes, per Restore object | Chosen |
| Restore `spec.orLabelSelectors` (built in) | Yes, but no benefit; Velero refuses a Restore that sets both selector fields ([`restore_controller.go` L334](https://github.com/vmware-tanzu/velero/blob/v1.18.1/pkg/controller/restore_controller.go#L334)) | Rejected |
| Resource policies | Backup only; the Restore spec has no `resourcePolicy` ([`resource-filtering.md`](https://github.com/vmware-tanzu/velero/blob/v1.18.1/site/content/docs/v1.18/resource-filtering.md)) | Not available |
| Resource modifiers (the ConfigMap `velero-restore-pvc-patch`) | They patch, never drop, an object ([`resource_modifiers.go` L46-L58](https://github.com/vmware-tanzu/velero/blob/v1.18.1/internal/resourcemodifiers/resource_modifiers.go#L46-L58)). Patching `spec.externalName` needs a different target per clone, so a new ConfigMap per restore | Rejected |
| Restore item action plugin with `SkipRestore` | Yes, but Styrmin would build, publish and ship a Go plugin image, and retest it on each Velero upgrade | Rejected |
| `velero.io/exclude-from-backup` label on aliases | Applies to backups, so in-place restores would lose the aliases (FR-006) | Rejected |
| `excludedResources: [services]` | Drops every Service, not only aliases | Rejected |
| Upstream contribution | The built-in selector already covers the need | Not needed |

**Alternatives considered**: deleting the aliases after the Velero restore. Rejected because the counterpart's namespace would hold aliases to the source between the Velero restore and the deletion, which FR-001 forbids, and because with `existingResourcePolicy: update` Velero can first replace an alias that a peer wrote.

## R-002: Where the counterpart's aliases are written, and from which services

**Decision**: The USER flow `execute_velero_restore_flow` (`workflows/templates/backup.py`) runs the existing alias step after "Run the recovery" succeeds, for a cross-target restore only. The INTERNAL flow `execute_restore_workflow` passes it a new parameter, `counterpart_context: GlobalContext | None`, the counterpart's stored context, which it already loads in `_build_counterpart_crd_body`. The alias step is the one that the create, update and upgrade flows run:

1. `with_current_peer_services(context)` replaces the other deployments' services in the context with the list that the server returns for the environment when the step runs (`environmentServices`, ADR-078).
2. `compute_service_aliases(context)` builds the aliases in both directions.
3. `find_stale_service_aliases(context)` and `apply_service_aliases` write them, skipping departing namespaces (ADR-077).

**Rationale**:

- The counterpart's stored context has `labels.environment_id` set to the new environment (`services/context.py` L218-L221) and lists the counterpart's own services and those of the counterparts created before it (`services/deployment.py` L1843-L1859). The server's list at write time adds the counterparts created after it. So the counterpart whose restore ends last writes the aliases in both directions with every counterpart whose namespace exists.
- The server's list holds only deployments of the new environment, so no alias points to a source namespace (FR-001) and a source deployment without a counterpart gets none (FR-003).
- The USER flow has the action token of the restore (`_step_token`, `action_job_variables`). The token belongs to the `styrmin-actions` user with the `READ_WRITE` role (ADR-059), and `environmentServices` requires only an authenticated user (`api/schema/query.py` L492-L500).
- When the token is missing or the read fails, the step uses the context's list, with a warning, as the other flows do (ADR-078).

**Alternatives considered**:

- Computing the aliases in the INTERNAL flow, from the database, as the PRD's "Implementation decisions" place it. Rejected: the list would be read before the Velero restore, which can take many minutes, and would miss the counterparts created after the read. ADR-078 made the alias step read the services when it writes for the same reason. The INTERNAL flow still provides the context, which is the database-side input.
- Running a full update flow for the counterpart after the restore. Rejected: it re-renders the HelmRelease and runs driver hooks, which the deferred initial reconcile avoids (ADR-056).
- Writing the aliases in the operator's recovery (`operator/restore_recovery.py`). Rejected: the operator does not read the environment's services from the server, and the step would not be recorded on the restore.

## R-003: Sharing the alias step between the orchestration flows and the restore

**Decision**: Move `_apply_service_aliases_step` from `agent/tasks/orchestration.py` to `agent/tasks/service_aliases.py` as `apply_service_aliases_step(reporter, context)`. The three CRD flows and the restore USER flow call it.

**Rationale**: `workflows/templates/backup.py` should not import a private function of the orchestration module. `service_aliases.py` already holds the rest of the step. `agent/steps/reporter.py` and `domain/steps.py` do not import `service_aliases.py`, so the move adds no import cycle.

**Alternatives considered**: a copy of the four lines in `backup.py`. Rejected because two copies of the step can drift.

## R-004: What a failed alias write does

**Decision**: When the alias step raises, the USER flow:

- leaves the step "Create and delete service aliases" failed with the error (`StepReporter.step` records the failure and re-raises);
- calls `mark_failed` on the counterpart's StyrminDeployment with the error, as a failed recovery does;
- returns `recovery: {"recovered": false, "error": "Service alias step failed: <error>"}`.

The INTERNAL flow then sets the restore to `FAILED` with that error and the counterpart to `FAILED`, as for any failed recovery (`execute_restore_workflow`). The clone's derived status counts the failed restore (`derive_environment_clone_status`), and the entry reads `failed` (R-006).

The errors that fail the step are those that fail it in the other flows: any Kubernetes API error on a write or a deletion, except a 404 or a 409 for a namespace that is gone or terminating (`apply_single_alias`). A failed read of the server's list does not fail it (R-002).

**Rationale**: Without `mark_failed`, the status reporter reads the counterpart's StyrminDeployment, which recovery left `Running`, and moves the deployment back to `RUNNING` within one poll of about 5 seconds (`agent/status/reporter.py` L297-L324, `services/deployment_status.py` L171-L251). The restore would read `FAILED` while the deployment reads `RUNNING`. A StyrminDeployment in the `Error` state reports `FAILED`, and the operator's timer does not move a `Failed` StyrminDeployment forward (`operator/handlers/styrmin_deployment.py` L1002-L1031), so the deployment stays `FAILED` until its next change (R-005).

**Alternatives considered**: keeping the deployment `RUNNING` because its workloads run. Rejected: it hides from the admin that the counterpart cannot reach its peers (user story 3).

## R-005: Repairing a counterpart whose alias step failed (FR-005)

**Decision**: No code change. A `FAILED` counterpart is repaired by an update or an upgrade that changes it.

**Findings**:

- `updateDeployment` and `updateDeploymentVersion` refuse only internal deployments (`api/schema/mutation.py` L898-L900, L1404-L1406). The services do not check the status (`services/deployment.py` L543-L742, L827-L1205). `find_in_flight_restore` gates only new restores. The one indirect refusal: when the environment's dedicated ingress controller is `FAILED`, updates fail (`services/deployment.py` L1404-L1408).
- The reconcile runs `update_instance_crd`, or `upgrade_instance_crd` when the version changes, and both run the alias step after the StyrminDeployment write (`agent/tasks/orchestration.py`). The counterpart's StyrminDeployment has no instance-sequence annotation, so the write is not skipped. The spec change moves a `Failed` StyrminDeployment forward through the operator's update handler.
- Saving the same values is a no-op when the new instance equals the active one (`services/deployment.py` L714-L722, L1150-L1175). The new context re-reads `deployed_services`, so for a counterpart created before others it differs and the update runs; for the counterpart created last it can be a no-op. The user documentation of restores already tells users to make a change, because saving the same values runs no flow (#503). The clone documentation says the same.
- Styrmin has no "redeploy" mutation. "Redeploy" in the PRD means an update or an upgrade.

## R-006: The clone entry of a counterpart whose restore failed (FR-007)

**Decision**: A new pure function in `services/backup/clone.py`, `resolve_deployment_result(result, restores)`, returns the entry as users view it: a `cloned` entry whose restore row is `FAILED` becomes `failed`, with the reason `the restore failed: <restore error message>`, or `the restore failed` when the restore has no error message. Every other entry is returned unchanged. `EnvironmentClone.deployment_results` (`api/definitions/backup/environment_clone.py`) applies it with the `referenced_restores` that the query resolvers already load. `derive_environment_clone_status` uses the same function to count failures, so the status and the entries cannot disagree.

**Rationale**:

- The clone flow sets the entry to `cloned` when it dispatches the restore and does not wait for it (`workflows/templates/clone.py` L960-L968). The derived status already counts a `FAILED` restore as a failure (`services/backup/clone.py` L866-L876).
- All read resolvers pass the restore rows: `environmentClone`, `environmentClones` (`api/schema/query.py` L433, L448) and `Environment.clonedFrom` (`api/definitions/environment/model.py` L151-L152). `cloneEnvironment` returns the record before any restore exists.
- The CLI, the SDK and the frontend read `outcome` and `reason` from the API, so they show the change with no change of their own. The frontend's collapsed row counts outcomes, so it counts the failure.
- No GraphQL schema change. The field descriptions of `outcome` and `reason` get one sentence each.

**Alternatives considered**:

- The INTERNAL restore flow rewrites the clone's `deployment_results` when a cross-target restore fails. Rejected: the clone flow saves every entry at the end of its loop (`_save_progress`), so a restore that fails before that save would be overwritten back to `cloned`.
- Showing the restore's status in the frontend only. Rejected: the CLI and the SDK would still read `cloned`.

## R-007: Order of the counterpart restores, and the races

**Findings**:

- The clone creates the counterparts one at a time and dispatches each restore at once (`_run_environment_clone`), so restores run at the same time.
- A counterpart's namespace does not exist before its restore: the counterpart is created with no initial reconcile, and its restore deletes the namespace if it exists before Velero creates it. While it is missing or terminating, the other counterparts' alias steps skip it (ADR-077). Its own alias step, at the end of its restore, writes both directions with every counterpart whose namespace exists.
- After the Velero restore and before the recovery, the counterpart's namespace holds the source-named StyrminDeployment. The alias flow reads the StyrminDeployment named after the namespace (`read_styrmin_deployment(name=namespace, ...)`), finds none, and counts the namespace as present. An alias written into it then points to a counterpart and survives the Velero restore (R-001).
- The recovery deletes the source-named StyrminDeployment, annotated `styrmin.io/skip-teardown`. Its teardown deletes no alias (ADR-076).
- An alias that B's step writes into A's namespace is lost only if A's restore deletes A's namespace after that write. A's namespace exists before A's restore only if something created it, and A's restore deletes it before Velero runs. SC-001 detects such a loss.

## R-008: What stays the same for in-place and environment restores

- `build_velero_restore` sets the label selector only when the source and target namespaces differ.
- `execute_restore_workflow` passes `counterpart_context` only when `is_cross_target`, and the USER flow runs the alias step only when it receives one.
- An environment restore runs one in-place restore per constituent, so it does not change.

The #503 rule for in-place restores stays: a peer created or changed during the restore skips the aliases between the two, and the user makes a change to write them (spec "Out of Scope").

## R-009: E2E coverage

`test_environment_clone_lifecycle` and `test_environment_backup_and_restore_lifecycle` (`backend/tests/e2e/test_backup_restore.py`) both carry `ci` and `shard_env_backup` and run in both variants. Both use simple-app deployments with one service each, so aliases exist between the primary and the second deployment.

- First clone of `test_environment_clone_lifecycle` (both selected): after step 9, where both counterparts run, poll the alias Services of each counterpart's namespace until they equal the expected set (SC-001). The expected set for a counterpart is one alias for each service of every other deployment of the new environment, internal ones included, named after the service's resolved name and pointing to that deployment's namespace. The test reads each deployment of the new environment with `client.deployments.list(created_environment_id, include_internal=True)` and its services from `deployment.deployed_services[].resolved_name`, as the test's state snapshot already does.
- Re-clone (step at the end): select only the primary instead of no deployment, wait with `ENVIRONMENT_CLONE_TIMEOUT_SECONDS`, keep the `SKIPPED` and not-selected assertions for the peer, and check that no alias in the new environment names a namespace of the source environment and that the primary's counterpart has no alias named after the peer's service (SC-002). The comment that explains the empty selection (research D12 of spec 010) changes. This adds one counterpart restore, a few minutes per variant, to `shard_env_backup`.
- `test_environment_backup_and_restore_lifecycle`: after the environment restore and the deployment-count check, check that the primary's namespace still holds the alias for the second deployment's service, labelled with its id and pointing to its namespace (SC-003). Only the primary is restored there, in place.
- The helper `service_alias_external_names` of commit `472fe403` applies to the current file. Its second hunk does not, because the first clone now selects both deployments; the check is rewritten as above.

## R-010: Documentation

- `docs/docs/concepts-and-architecture/backups-and-restores.md`:
  - "Choosing which deployments come along": the paragraph from the PRD.
  - "What happens when you restore": the paragraph of #503 describes in-place restores; add that a clone's restore writes the aliases of the new environment instead.
  - "Watching a clone, and what its status means": a deployment whose restore failed is reported failed, with the restore's error.
- `docs/docs/concepts-and-architecture/ingress-and-networking.md`, "Service aliases": a clone writes the aliases of the new environment after each counterpart's restore.
- `dev/knowledge/backend/orchestration-flows.md`: the alias step also runs at the end of a cross-target restore; the sentence "After a restore, the namespace holds the aliases that Velero restored" applies to in-place restores.
- `dev/adr/0056-environment-clone-record-and-cross-target-restore.md`: a dated amendment to decision 2.
- `CONTEXT.md`: extend the entry "Service alias".
- `changelog/530.fixed.md`.

## R-011: Governance gates

- No database schema or migration change; no new dependency; no CI workflow change.
- No GraphQL schema change. FR-007 changes what `EnvironmentCloneDeploymentResult.outcome` and `reason` return for one case; the functional GraphQL test covers it (Constitution §V).
- The Velero Restore of a cross-target restore changes. Velero is deployed by Styrmin's Helm chart; the chart does not change.
