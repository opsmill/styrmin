# ADR-077: The Alias Flow Reads the Deletion State From the Cluster Before and After It Writes

**Status**: Accepted
**Date**: 2026-10-17
**Decision-makers**: Fatih Acar
**Source**: specs/archive/026-delete-service-aliases/research.md (R-003, R-004, R-005);
[issue #503](https://github.com/opsmill/styrmin/issues/503); [PR #516](https://github.com/opsmill/styrmin/pull/516)
**Related**: [ADR-076](0076-teardown-deletes-service-aliases-in-all-namespaces.md) (the teardown
deletes a deployment's aliases), [ADR-078](0078-alias-step-reads-current-services-from-server.md)
(the alias step reads the current services from the server)

## Context

The create, update and upgrade flows of a deployment end with the "Apply service aliases" flow
(`apply_service_aliases` in `agent/tasks/service_aliases.py`). It writes the aliases of the other
deployments' services into the flow's own namespace, and the aliases of its own services into the
other deployments' namespaces.

The server builds the flow's context before the flow starts and passes it as a parameter. While
another deployment of the environment is being deleted, the context still lists that deployment's
services, because the server deletes its `DeployedService` rows only when it reaches `DELETED`. A
context built before the user requested the deletion also does not show the request. So a flow
that ran during a deletion:

- wrote the deleted deployment's aliases again after the teardown had deleted them;
- called `apply_namespace` on the deleted deployment's namespace, to write its own aliases there,
  which created that namespace again when the flow ran after the namespace deletion and before
  the status became `DELETED`.

`delete_deployment` sets `spec.deletionRequested` on the StyrminDeployment before it writes
anything to the database. The status becomes `DELETING` only when the status reporter reports the
operator's `Deleting` phase, so the flag on the CR is the first record of the request.

Kubernetes' `NamespaceLifecycle` admission plugin refuses to create an object in a namespace that
is being deleted, with a 403 whose cause is `NamespaceTerminating`, and allows updates and deletes
there. A create in a namespace that does not exist returns 404.

## Decision drivers

- After the user requests a deletion, no flow of another deployment writes an alias of the deleted
  deployment's services, writes into its namespace, or creates that namespace. This includes a
  flow whose context was built before the request.
- Driver templates of other deployments keep seeing a `DELETING` deployment's services until it
  reaches `DELETED`. Templates render with `SilentUndefined`, so removing those services from the
  context would make templates render empty values without an error.
- No new component and no shared state between the operator and the flows.

## Considered options

1. Read the cluster before the writes, skip what touches a departing namespace, read again after
   the writes, and delete the written aliases of a deployment whose deletion the second read finds.
   Create no namespace.
2. Filter the services of `DELETING` deployments out of the context on the server.
3. One read before the writes, without a second read.
4. An admission webhook, or a lock that the operator and the flows share.

## Decision

We chose option 1.

- **First read.** Before it writes, the flow reads, for each namespace that an alias is written
  into or points into, and for the namespace of each stale alias, the Namespace and the
  StyrminDeployment named after it (`find_departing_namespaces`). A namespace is departing when
  the Namespace is missing or `Terminating`, or when its StyrminDeployment has
  `spec.deletionRequested: true` or a `metadata.deletionTimestamp`. A namespace that is `Active`
  and has no StyrminDeployment is not departing: a new deployment's flow is in that state between
  its namespace write and its CR write. The flow skips each alias that touches a departing
  namespace, and keeps each stale alias in a departing namespace.
- **Second read.** After its writes, the flow reads again, for the namespaces that the written
  aliases point into (`find_deleted_deployment_namespaces`). It follows the rule by which the
  operator's teardown deletes aliases (`teardown_deletes_aliases`): a namespace counts when its
  StyrminDeployment has `spec.deletionRequested: true`, or has a `metadata.deletionTimestamp`
  while the Namespace exists and is not `Terminating`. A Namespace that is missing or
  `Terminating` without a deletion request does not count, because a restore deletes the
  namespace in this way. The flow deletes each written alias whose owner namespace counts,
  whatever namespace holds the alias, with the `resourceVersion` that its write returned.
- **No namespace creation.** The flow no longer calls `apply_namespace`, and its `namespace_labels`
  parameter is removed. Each CRD flow creates its own namespace before it writes its
  StyrminDeployment, and writes aliases only after that, so a missing namespace always belongs to
  another deployment. When a write returns 404, or 403 because the namespace is terminating
  (`is_namespace_gone_error`), the flow logs it and skips that alias. Any other error, such as an
  RBAC 403, fails the step.

A read and a write cannot be one atomic operation, so a deletion requested between the first read
and a write lets that write through. When the request comes before the second read, the second
read finds it and the flow deletes the alias. When it comes after, the teardown lists the aliases
after the request and deletes it.

Option 2 does not cover a context built before the request, and the database status lags the CR
flag; it would also change what driver templates see. Option 3 leaves the window between the read
and the write open. Option 4 adds a component or shared state for a window of milliseconds that
the second read closes.

## Consequences

- Good, because a flow that runs during a deletion, including one whose context predates the
  request, leaves no alias of the deleted deployment, with the exception below, and never brings
  its namespace back.
- Good, because a change of another deployment completes while a namespace is being deleted.
  Before, Kubernetes refused the alias write into the terminating namespace and the step failed.
- Good, because the context, and so what driver templates render, does not change.
- Bad, because the flow makes two reads, a Namespace and a StyrminDeployment, per distinct
  namespace, before and after its writes. It reads at most 10 namespaces at the same time.
- Bad, because one case leaves an alias. When the StyrminDeployment is already removed at the
  second read, the read cannot tell a deletion from a restore and keeps the alias. An alias written
  after the delete handler's teardown listed the aliases, and before the StyrminDeployment was
  removed, can remain. The maintainer accepted this case.
- Bad, because a missing namespace counts as departing in the first read, whether its deployment
  was deleted or its flow has not created it yet. ADR-078 covers the second case.

## Confirmation

- `backend/tests/unit/agent/test_service_aliases.py` covers both reads and the writes, among them
  `test_find_departing_namespaces_state_table`, `test_find_deleted_deployment_namespaces_state_table`,
  `test_apply_service_aliases_writes_every_alias_and_no_namespace`,
  `test_apply_service_aliases_deletes_a_write_that_raced_the_request`,
  `test_apply_service_aliases_second_read_follows_the_teardown_rule` and
  `test_apply_service_aliases_raises_on_an_rbac_403`.
- `backend/tests/unit/services/test_context_deleting_peer_services.py` checks that a context built
  while a peer is `DELETING` still lists the peer's services.
- The race has no E2E test, because its timing cannot be reproduced reliably.

## More information

- [`dev/knowledge/backend/orchestration-flows.md`](../knowledge/backend/orchestration-flows.md#service-aliases)
  describes the flow and the state of both reads over a deletion.
- A deployment's own create, update or upgrade flow that runs after its own deletion was requested
  can still create its own namespace again in `_write_styrmin_deployment`. Issue
  [#527](https://github.com/opsmill/styrmin/issues/527) tracks it.
- Issue [#526](https://github.com/opsmill/styrmin/issues/526) asks for a cleanup of the aliases
  that stay.
