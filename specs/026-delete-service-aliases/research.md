# Research: Deleting a Deployment Deletes Its Service Aliases

Code references are to `develop` at d1a3105, which this branch is based on.

## R-001: Where the operator gets the deleted deployment's id

**Decision**: The teardown reads `spec.deploymentId` of the StyrminDeployment and deletes aliases only when the CR's namespace is `styrmin-<spec.deploymentId>` (`get_kubernetes_reference`). Otherwise it logs a warning and deletes no alias.

**Rationale**:

- `StyrminDeploymentSpec.deployment_id` (alias `deploymentId`) is required on every CR ([`operator/crd/schema.py`](../../backend/styrmin_backend/operator/crd/schema.py)). `build_styrmin_deployment_body` writes it from `context.instance.deployment_id`, and the context builder sets the namespace to `get_kubernetes_reference(deployment.id)` ([`services/context.py`](../../backend/styrmin_backend/services/context.py)). So for every CR that a flow writes, including an environment clone's counterpart, the namespace equals `styrmin-<deploymentId>`.
- A cross-target restore brings a copy of the source's CR into the counterpart's namespace. That copy carries the source's `deploymentId`, so a teardown keyed on it would delete the source's aliases while the source keeps running. The copy is annotated `styrmin.io/skip-teardown` ([`operator/restore_recovery.py`](../../backend/styrmin_backend/operator/restore_recovery.py), `_mark_skip_teardown`), so the delete handler skips the teardown (FR-006). The namespace check is a second guard for the same case: the copy's namespace is not `styrmin-<source id>`.

**Alternatives considered**:

- Derive the id from the namespace name. Rejected: for the restored copy it gives the counterpart's id, so a teardown that ran despite the annotation would delete the counterpart's aliases.
- Trust `spec.deploymentId` without the namespace check. Rejected: the annotation is then the only guard against deleting a running source's aliases.

## R-002: How the teardown finds and deletes the aliases

**Decision**: A new step at the start of `_teardown_owned_resources` lists the Services labelled `styrmin.io/service-alias=true` in all namespaces (`list_services_in_all_namespaces`), keeps those for which `is_alias_of_deployment(alias, deployment_id, namespace)` is true, and deletes each with `delete_service`. A listing error is logged and the step ends. A delete that returns `False` (404) counts as deleted. Any other error is logged with the alias's namespace and name, and the step continues with the next alias. The teardown then runs its existing steps.

**Rationale**:

- `is_alias_of_deployment` is the rule that #506 uses for stale aliases: the `styrmin.io/deployment-id` label when present, otherwise the namespace that `spec.externalName` points into. Reusing it keeps one definition of "the aliases of a deployment" (FR-002).
- The operator and the Prefect worker run in one process (`entrypoint/combined.py` imports both the kopf handlers and the Prefect worker), so importing from `agent/tasks/service_aliases.py` loads nothing new. The operator already calls the agent's injected Kubernetes primitives: `operator/reconciler.py` uses `apply_kubernetes_resource`.
- The primitives are called directly, not through the Prefect `@task` wrappers, because the teardown runs in a kopf handler, outside a flow.
- Both deletion paths call `_teardown_owned_resources`, so `kubectl delete styrmindeployment` also deletes the aliases (FR-005). The skip-teardown branch returns before it (FR-006).
- One list call per teardown. While a finalizer stays, the delete handler runs the teardown every 5 seconds; each later run finds no alias of the deployment.

**Alternatives considered**:

- Two label-selector lists (`deployment-id=<id>`, then `!styrmin.io/deployment-id` filtered by `externalName`). Rejected: two calls for the same result as one list and the existing predicate.
- Delete in the server when the status becomes `DELETED`. Rejected: the brief places the deletion in the operator's teardown, before the namespace deletion, and the server would act after the namespace is gone, so a race window would remain open longer.

## R-003: How a flow learns that a deployment is departing

**Decision**: Before it writes, the "Apply service aliases" flow reads, for each namespace that its aliases are written into or point into, the Namespace and the StyrminDeployment named after the namespace. A namespace is **departing** when one of these holds:

- the Namespace does not exist;
- the Namespace's `status.phase` is `Terminating`;
- the StyrminDeployment exists and has `spec.deletionRequested: true` or a `metadata.deletionTimestamp`.

A namespace whose StyrminDeployment does not exist but whose Namespace is `Active` is not departing. The flow writes into it as today.

**Rationale**:

- `delete_deployment` patches `spec.deletionRequested` before it writes anything to the database ([`services/deployment.py`](../../backend/styrmin_backend/services/deployment.py), `_patch_deletion_requested`). The database status becomes `DELETING` only when the status reporter reports the operator's `Deleting` phase. So the flag on the CR is the first record of the user's request, and the database status lags it. Environment deletion sets the same flag (`request_cluster_teardown`).
- The flow runs on the agent from a context built before it started ([`orchestration.py`](../../backend/styrmin_backend/agent/tasks/orchestration.py)), so only a read at write time covers a flow whose context was built before the request (FR-007, FR-008).
- `metadata.deletionTimestamp` covers `kubectl delete styrmindeployment` and the namespace deletion, which deletes the CR. A missing or `Terminating` Namespace covers the time after the namespace deletion is requested and after the CR is gone.
- A missing CR with an `Active` namespace occurs while a new deployment's flow is between its namespace write and its CR write, during a restore of that namespace, and for any deployment without a CR. Treating it as departing would change today's behaviour in these cases for no gain.
- The worker's ClusterRole already allows reading StyrminDeployments and Namespaces in all namespaces ([`helm/agent/templates/roles.yaml`](../../helm/agent/templates/roles.yaml)).
- Reading the flow's own namespace too means that a deployment whose own deletion was requested while its flow runs writes no alias of its services either. That deletion is allowed from `PENDING`, `DEPLOYING`, `RUNNING` and `FAILED` (`_DELETE_ALLOWED_STATES`). It follows from the same rule and adds no requirement.

**Alternatives considered**:

- Filter the services of `DELETING` deployments out of `deployed_services` when the server builds the context. Rejected as the only guard: the database status lags the CR flag, and a context built before the request still lists the services. Not added next to the agent-side read either, because the read already covers the case.
- Check the database from the agent. Rejected: flows on the agent do not read the server's database; they get their data from the context and the cluster.

## R-004: Closing the race between the check and the write

**Decision**: After it writes, the flow reads the same state again for the owners of the aliases it wrote. It deletes each alias it wrote whose owner's namespace has become departing, with a `resourceVersion` precondition taken from its own write. Aliases that it wrote into a namespace that became departing are left to that namespace's deletion.

**Rationale**: A read and a write cannot be one atomic operation, so a flow can read "no deletion requested" just before the request and write just after it. With the second read, an alias of a deleted deployment cannot remain:

- Let the flow's write complete at time *w* and its second read happen at *c*, with *w* < *c*. Let the request set `spec.deletionRequested` at *f*, and the teardown list the aliases at *l*, with *f* < *l*, because the teardown starts on that update.
- If *c* ≥ *f*, the second read returns the flag, and the flow deletes the alias.
- If *c* < *f*, then *w* < *c* < *f* < *l*, so the teardown's list returns the alias and the teardown deletes it.
- Reads from the Kubernetes API server without a `resourceVersion` are consistent reads, so a read after a write returns that write.

The precondition keeps the second step from deleting an alias that another flow replaced in between, the same protection #506 gives stale aliases (`StaleAlias.resource_version`).

For writes into the departing deployment's own namespace, the namespace deletion removes what was written, and the flow never creates that namespace (R-005). A write that races with the request can still reach that namespace before its deletion; the spec's Clarifications record this.

**Alternatives considered**:

- One read before the write, with no second read. Rejected: it leaves the window described above, so an alias can remain.
- A Kubernetes admission webhook or a lock shared by the operator and the flows. Rejected: a new component or new shared state for a window of milliseconds that the second read closes.

## R-005: Never creating another deployment's namespace

**Decision**: `apply_service_aliases` no longer calls `apply_namespace`. The flow writes each alias into a namespace that exists; when the create or replace returns 404 (namespace not found) or 403 with the cause `NamespaceTerminating`, the flow logs it and skips that alias. The `namespace_labels` parameter, used only for those `apply_namespace` calls, is removed.

**Rationale**:

- The three CRD flows create their own namespace in `_write_styrmin_deployment` before they write the StyrminDeployment, and they write aliases only after that write succeeds. So every namespace that `apply_service_aliases` needs to create belongs to another deployment. A deployment's own flow creates its namespace and writes both sets of aliases, its peers' into its namespace and its own into theirs, so a peer that skips a missing namespace loses nothing.
- Kubernetes' `NamespaceLifecycle` admission plugin refuses to create an object in a namespace that is being deleted, with a 403 Forbidden whose status cause type is `NamespaceTerminating`, and it allows updates and deletes there. A create in a namespace that does not exist returns 404.
- Today `apply_kubernetes_namespace` swallows every error, so the flow could create a deleted deployment's namespace again (the brief's race). Without the call, a deleted namespace stays deleted (FR-008).
- An RBAC 403 has no `NamespaceTerminating` cause, so it still fails the step as today.

**Alternatives considered**:

- Keep `apply_namespace` but call it only for the flow's own namespace. Rejected: the flow's own namespace already exists at that point.

## R-006: Driver templates keep seeing a `DELETING` deployment's services

**Decision**: The context builder does not change. A unit test checks that a context built while a peer is `DELETING` lists the peer's services in `services` and `deployed_services` (FR-010).

**Rationale**: The guard of R-003 acts in the alias flow only, so the context that templates render with is the same as today. The server deletes the `DeployedService` rows at `DELETED` ([`deployment_status.py`](../../backend/styrmin_backend/services/deployment_status.py)), so templates stop seeing those services from that point, as today.

## R-007: A remaining alias replaced by a deployment's own Service

**Decision**: Add a unit test of `apply_kubernetes_resource` for a `Service`: when the create returns 409, the function replaces the object with the given `ClusterIP` manifest (spec Clarifications).

**Rationale**:

- The operator writes a deployment's Services through `reconcile_resources`, which calls `apply_kubernetes_resource` ([`operator/reconciler.py`](../../backend/styrmin_backend/operator/reconciler.py)). An alias that a failed teardown left carries no `styrmin.io/release-reference` label, so the operator's diff does not list it as an existing resource. The operator therefore creates the Service, gets 409, and replaces the alias.
- No unit test covers the `Service` branch of `apply_kubernetes_resource` today (`replace_namespaced_service` appears in no test).
- Kubernetes allows changing a Service's `spec.type` from `ExternalName` to `ClusterIP` on update and allocates a cluster IP, because an `ExternalName` Service has no cluster IP to keep. Services allow updates without a `resourceVersion`. A unit test with a mocked API cannot check this; it is recorded here from the Kubernetes Service documentation and API behaviour, not from a cluster run.

## R-008: The E2E test

**Decision**: `test_deleted_deployment_leaves_no_alias` at the end of [`test_service_discovery.py`](../../backend/tests/e2e/test_service_discovery.py), marked `api_only` and `ci`, in the module's `shard_general`.

- It deletes `intent` with `client.deployments.delete`, waits up to 300 seconds until its status is `deleted`, then lists the Services of `executor`'s namespace.
- It asserts that none has the label `styrmin.io/deployment-id=<intent id>` and none has a `spec.externalName` whose second part is `styrmin-<intent id>`.
- Before it deletes `intent`, it asserts that the alias of `intent` is in `executor`'s namespace, so the test cannot pass when no alias was written.

**Rationale**:

- pytest runs a module's tests in file order. The two existing tests use `intent`: the discovery test probes it, and the rename test checks `executor`'s alias in `intent`'s namespace. So the new test goes last.
- The `[ui-chromium]` variant of the module runs only the discovery test, which does not delete. `api_only` keeps the delete out of that variant, because the delete runs through the SDK only.
- It reuses `discovery_deployments`, which other active tests already consume, so it boots no deployment (Constitution §V, "Reuse before you boot").
- The wait pattern follows [`test_delete_deployment_api.py`](../../backend/tests/e2e/test_delete_deployment_api.py): the status reaches `deleted` after the namespace is gone. The new test keeps a small local polling helper instead of importing a helper from another test module.
- The shared scenario environment keeps `executor` running after the module; no later module uses `intent`.

## R-009: Dependencies and governance gates

**Decision**: No new dependency. No change to the database schema, the GraphQL schema, CI workflows or RBAC.

**Rationale**: Kubernetes and kopf already provide every capability needed (listing across namespaces, delete preconditions, consistent reads, the namespace lifecycle rules). No third-party library falls short, so the research directive on extending a constrained dependency does not apply.

## R-010: Observed but not part of this fix

- A deployment's own create, update or upgrade flow that runs after its own deletion was requested calls `apply_kubernetes_namespace` on its own namespace in `_write_styrmin_deployment`, so it can create that namespace again. The brief does not cover a deployment's own flows; this is recorded for a separate issue.
- The legacy flows `create_instance`, `update_instance` and `upgrade_instance` in `orchestration.py` also call `apply_service_aliases`. They are not registered in the Prefect catalogue ([`workflows/catalogue.py`](../../backend/styrmin_backend/workflows/catalogue.py) registers only the `_crd` flows), so they never run. They get the same guard through the shared flow; their call sites drop the removed `namespace_labels` argument.

## R-011: A restore's namespace deletion must not delete aliases

**Decision**: `_delete_service_aliases` deletes aliases only when one of these holds:

- `spec.deletionRequested` is true: the platform-driven path, environment deletion, and discarding a clone;
- the Namespace exists and is not `Terminating`: `kubectl delete styrmindeployment`.

Otherwise, when `spec.deletionRequested` is false and the Namespace is `Terminating` or gone, it logs that the namespace is being deleted without a deletion request and deletes no alias. When reading the Namespace fails, it logs the error and deletes no alias.

**Rationale**:

- `execute_velero_restore` deletes the target namespace and waits for it to be gone before it creates the Velero `Restore` ([`workflows/templates/backup.py`](../../backend/styrmin_backend/workflows/templates/backup.py)). The namespace deletion deletes the StyrminDeployment in it, and kopf runs `kopf_on_styrmin_deployment_delete`, which runs `_teardown_owned_resources` ([`operator.md`](../../dev/knowledge/agent/operator.md), "Deletion", describes this for restores).
- Velero restores only the target namespace. The aliases of the restored deployment's services are in the other namespaces, and the restore flows write no alias: no module other than `service_aliases.py` and `orchestration.py` calls the alias functions. So aliases that the teardown deleted during a restore would stay missing until a create, update or upgrade flow of that environment runs.
- `spec.deletionRequested` is set before any teardown of a real deletion, so the delete handler that the later namespace deletion starts still deletes aliases on that path; by then it finds none.
- A failed read leaves aliases rather than deleting those of a running deployment. A left alias is overwritten by the next flow that writes that name; a deleted alias of a running deployment breaks name resolution until then.
- The `deletionRequested` handler calls the step without the namespace read, because the flag is set on that path.

**Alternatives considered**:

- Have the restore flow set `styrmin.io/skip-teardown` before it deletes the namespace. Rejected: it would also skip the rest of the teardown during restores, which this fix does not intend to change.
- Delete aliases only on the platform-driven path. Rejected: the brief expects `kubectl delete styrmindeployment` to delete them too.
