# ADR-076: The Operator's Teardown Deletes a Deployment's Service Aliases in All Namespaces

**Status**: Accepted
**Date**: 2026-10-17
**Decision-makers**: Fatih Acar
**Source**: specs/archive/026-delete-service-aliases/research.md (R-001, R-002, R-011);
[issue #503](https://github.com/opsmill/styrmin/issues/503); [PR #516](https://github.com/opsmill/styrmin/pull/516)
**Related**: [ADR-073](0073-kubernetes-objects-named-and-found-by-record-id.md) (objects found by the
record's id), [ADR-056](0056-environment-clone-record-and-cross-target-restore.md) (cross-target
restore and the `styrmin.io/skip-teardown` annotation),
[ADR-077](0077-alias-flow-reads-deletion-state-at-write-time.md) (the alias flow's guard during a
deletion)

## Context

So that a pod can reach a service of another deployment of its environment by its short name, the
create, update and upgrade flows write a service alias: an `ExternalName` Service in each other
deployment's namespace, which points to the service in its owner's namespace
(`agent/tasks/service_aliases.py`). An alias carries the labels `styrmin.io/service-alias=true`
and, since [#506](https://github.com/opsmill/styrmin/pull/506), the fix for
[#491](https://github.com/opsmill/styrmin/issues/491), `styrmin.io/deployment-id=<id of the
deployment that owns the service>`. Aliases written before #506 have no `styrmin.io/deployment-id`
label.

When a user deleted a deployment, the operator's teardown deleted Services only in the deployment's
own namespace, selected by the `styrmin.io/release-reference` label, and then requested the
deletion of that namespace. Aliases carry no release-reference label, and the aliases of the
deleted deployment's services are in the other deployments' namespaces. So they stayed after the
deployment reached `DELETED` (#503).

Two cases delete a StyrminDeployment without a user's deletion request:

- A restore deletes the target namespace and waits until it is gone before it creates the Velero
  `Restore` (`execute_velero_restore`). The namespace deletion deletes the StyrminDeployment in
  it, and kopf runs the delete handler's teardown. Velero restores only that namespace, and the
  restore flows write no alias. The restored deployment keeps running.
- A cross-target restore brings a copy of the source deployment's StyrminDeployment into the
  counterpart's namespace. The copy carries the source's `spec.deploymentId`, and the source
  keeps running. The copy is annotated `styrmin.io/skip-teardown`.

## Decision drivers

- When a deployment's status becomes `DELETED`, no namespace holds an alias of its services.
- A teardown must never delete the aliases of a deployment that keeps running: a restored
  deployment, or the source of a cross-target restore.
- The teardown stays best-effort: a failed step must not keep a deletion from reaching `DELETED`.
- One rule decides which aliases belong to a deployment, shared with the stale-alias deletion of
  #506.

## Considered options

1. A first teardown step in the operator that lists the aliases in all namespaces and deletes
   those of the deployment, guarded by the CR's namespace and by the deletion request.
2. The server deletes the aliases when the deployment's status becomes `DELETED`.
3. The restore flow sets `styrmin.io/skip-teardown` before it deletes the namespace, and the
   teardown deletes aliases without the deletion-request guard.

## Decision

We chose option 1. `_teardown_owned_resources` in `operator/handlers/styrmin_deployment.py` runs
`_delete_service_aliases` as its first step, before it deletes the deployment's own Services and
requests the namespace deletion. Both deletion paths run it: the platform-driven path
(`spec.deletionRequested`) and `kubectl delete styrmindeployment`.

The step:

- Reads the deployment id from `spec.deploymentId`, and acts only when the CR's namespace is
  `styrmin-<spec.deploymentId>`. Otherwise it logs a warning and deletes nothing, so a CR copied
  into another deployment's namespace cannot delete the aliases of the deployment it was copied
  from. The `styrmin.io/skip-teardown` annotation already skips the whole teardown; this check is a
  second guard for the same case.
- When `spec.deletionRequested` is false, reads the Namespace, and acts only when it exists and is
  not `Terminating` (`teardown_deletes_aliases` in `agent/service/kubernetes/service_alias_rules.py`).
  A namespace deletion without a deletion request, as a restore or `kubectl delete namespace`
  makes, deletes no alias. When the read fails, it logs the error and deletes no alias.
- Lists the aliases in all namespaces with two label selectors:
  `styrmin.io/service-alias=true,styrmin.io/deployment-id=<id>` and
  `styrmin.io/service-alias=true,!styrmin.io/deployment-id`. It keeps those for which
  `is_alias_of_deployment` is true: the id label holds the deployment's id, or, without the label,
  `spec.externalName` points into the deployment's namespace.
- Deletes each alias with the `resourceVersion` of the listing, so it does not delete a Service
  that replaced the alias since, such as another deployment's `ClusterIP` Service with the same
  name.
- Logs a 404 or a 409 as no error, logs every other failure with the alias's namespace and name,
  continues with the next alias, and never raises.

Option 2 acts after the namespace is gone, so the window in which another deployment's flow can
write the aliases again stays open longer. Option 3 would also skip the rest of the teardown during a restore, which this
fix does not intend to change.

## Consequences

- Good, because a deployment deleted through Styrmin, or with `kubectl delete styrmindeployment`,
  leaves no alias of its services in the other namespaces.
- Good, because the operator and the flow use the same rules from `service_alias_rules.py`, which
  imports no Prefect code, so the operator does not load Prefect modules to use them.
- Good, because a restore's namespace deletion keeps the restored deployment's aliases, so the
  other deployments can still reach it by short name after the restore.
- Bad, because some aliases stay, and nothing deletes them later:
  - an alias whose deletion failed;
  - the aliases of a deployment whose namespace was deleted directly, with `kubectl delete
    namespace`, which the teardown cannot tell apart from a restore;
  - the aliases of a StyrminDeployment annotated `styrmin.io/skip-teardown`;
  - aliases that deletions made before this version left.
- Bad, because each teardown makes two list calls on Services in all namespaces. While the
  finalizer stays, the delete handler runs the teardown again every 5 seconds; each later run
  finds no alias of the deployment.

## Confirmation

- `backend/tests/unit/test_deployment_deletion_operator.py` covers each rule, among them
  `test_delete_service_aliases_deletes_only_the_aliases_of_the_deployment`,
  `test_delete_service_aliases_makes_no_api_call_outside_the_deployment_namespace`,
  `test_delete_service_aliases_keeps_aliases_when_the_namespace_goes_without_a_request`,
  `test_delete_service_aliases_keeps_aliases_when_the_namespace_cannot_be_read` and
  `test_delete_handler_with_skip_teardown_makes_no_alias_call`.
- The E2E test `test_deleted_deployment_leaves_no_alias` in
  `backend/tests/e2e/test_service_discovery.py` deletes a deployment and checks that the other
  deployment's namespace holds no alias of its services.

## More information

- Users find and delete the aliases that stay with the step in
  [Ingress and networking](../../docs/docs/concepts-and-architecture/ingress-and-networking.md#service-aliases).
- Issue [#526](https://github.com/opsmill/styrmin/issues/526) asks for a cleanup of the aliases
  that stay.
