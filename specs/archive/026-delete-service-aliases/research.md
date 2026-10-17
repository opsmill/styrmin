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

> Changed on 2026-10-17, after the code review. The second read now follows the rule by which the operator's teardown deletes aliases (R-011), not the departing rule of R-003, and the flow deletes a written alias whatever namespace holds it. The first version had two faults. When a restore deleted the owner's namespace between the two reads, the flow deleted the valid alias that it had just written, and no flow wrote it again after the restore. It also kept an alias held in a departing namespace, on the assumption that the namespace's deletion removes it, which `kubectl delete styrmindeployment` does not do.

**Decision**: After it writes, the flow reads the Namespace and the StyrminDeployment again for the owner namespaces of the aliases it wrote (`find_deleted_deployment_namespaces`). An owner namespace counts when one of these holds:

- its StyrminDeployment has `spec.deletionRequested: true`, whatever the phase of the Namespace;
- its StyrminDeployment has a `metadata.deletionTimestamp` while the Namespace exists and is not `Terminating` (`kubectl delete styrmindeployment`).

A Namespace that is missing or `Terminating` without a deletion request does not count. The flow deletes each alias it wrote whose owner namespace counts, whatever namespace holds the alias, with a `resourceVersion` precondition taken from its own write, and logs whether the delete deleted the alias.

**Rationale**: A read and a write cannot be one atomic operation, so a flow can read "no deletion requested" just before the request and write just after it. With the second read, an alias of a deleted deployment remains only in the last case of this list:

- Let the flow's write complete at time *w* and its second read happen at *c*, with *w* < *c*. Let the request set `spec.deletionRequested` at *f*, and the teardown list the aliases at *l*, with *f* < *l*, because the teardown starts on that update.
- The flag can be read until the StyrminDeployment is removed, at *g*. The namespace deletion that follows the teardown runs the delete handler, whose teardown lists the aliases again at *l2*. kopf removes the StyrminDeployment only after that handler returns, so *l* < *l2* < *g*.
- If *f* ≤ *c* < *g*, the second read returns the flag, and the flow deletes the alias.
- If *c* < *f*, then *w* < *c* < *f* < *l*, so the teardown's list returns the alias and the teardown deletes it.
- If *c* ≥ *g* and *w* < *l2*, the delete handler's list returns the alias and its teardown deletes it.
- If *l2* < *w* < *g* ≤ *c*, the alias remains: the second read finds no StyrminDeployment, and without it the read cannot tell a deletion from a restore.
- Reads from the Kubernetes API server without a `resourceVersion` are consistent reads, so a read after a write returns that write.

A missing or `Terminating` Namespace does not count, because a restore deletes the target namespace without a deletion request (R-011). Velero restores the namespace later and no flow runs, so an alias of the restored deployment that the flow deleted would stay missing until a create, update or upgrade flow of the environment runs. The `metadata.deletionTimestamp` that the namespace deletion sets on the StyrminDeployment counts only while the Namespace is not `Terminating`, for the same reason. This is the rule of `_delete_service_aliases` in the operator.

The flow deletes a written alias whatever namespace holds it, because on the `kubectl delete styrmindeployment` path the namespace that holds the alias is not deleted. Kubernetes' `NamespaceLifecycle` plugin allows deletes in a `Terminating` namespace, and `delete_service` returns `False` on a 404.

The precondition keeps the second step from deleting an alias that another flow replaced in between, the same protection #506 gives stale aliases (`StaleAlias.resource_version`).

The flow never creates the deleted deployment's namespace (R-005). On the platform-driven path, the namespace deletion removes the aliases of other deployments' services written into it, including a write that races with the request; the spec's Clarifications record this.

**Alternatives considered**:

- One read before the write, with no second read. Rejected: it leaves the window described above, so an alias can remain.
- A Kubernetes admission webhook or a lock shared by the operator and the flows. Rejected: a new component or new shared state for a window of milliseconds that the second read closes.
- A second read with the departing rule of R-003, and no delete of an alias whose holder namespace is departing. This was the first version; rejected after the review for the reasons in the note above.

## R-005: Never creating another deployment's namespace

> Changed on 2026-10-17, after CI run [39030125607](https://github.com/opsmill/styrmin/actions/runs/39030125607) and the review of PR #516. The rationale below said that a missing namespace belongs to another deployment whose own flow writes both sets of aliases, so a peer that skips it "loses nothing". That holds only when the other deployment's flow lists the deployment that skipped. A flow's context lists the deployments that existed when the change was requested, so when B is requested just after A, A's context does not list B. When B's alias step runs before A's flow has created A's namespace, B skips the aliases between the two, and A's flow, with its context alone, never writes them. Before this fix, B's flow created A's namespace and wrote both. R-012 closes the gap: the alias step reads the current services from the server.

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

## R-012: Reading the current services in the alias step

> Added on 2026-10-17, after CI run [39030125607](https://github.com/opsmill/styrmin/actions/runs/39030125607) of PR #516 failed the three tests of `test_service_discovery.py`: neither `intent`'s nor `executor`'s namespace held the other's alias.

**Decision**: Before it computes the aliases, the alias step (`_apply_service_aliases_step`) calls `with_current_peer_services`. It reads the services of the environment from the server with the `environmentServices` query, sent with the flow's action token (ADR-059), and replaces the other deployments' entries of `deployed_services` with that list. The deployment's own entries stay as the context lists them. The environment id comes from the context's `labels.environment_id`. When the token is missing or the read fails, the step logs a warning and uses the context's list. The rule that a missing namespace counts as departing does not change.

**Rationale**:

- The server builds the context in `apply_state` when the change is requested, and a deployment's `DeployedService` rows exist from its request on. So a context lists every deployment requested before it, and none requested after it.
- Each flow creates its own namespace in `_write_styrmin_deployment` before its alias step. Of two alias steps, the one that runs last therefore finds both namespaces, and with the server's list it knows both deployments, so it writes both sets. The skip of a missing namespace loses nothing as long as the step that runs last reads the server's list.
- The deployment's own services come from the context, because they are the Services that this flow deploys. A rename requested after this flow's context would otherwise point the aliases at a Service that this flow does not create.
- The server's list no longer holds a deployment that reached `DELETED`, because the server deletes its `DeployedService` rows then. A deployment that is `DELETING` is still listed, and the cluster read skips it, as before.
- No GraphQL schema change: `environmentServices` exists, and the actions service account has the `READ_WRITE` role.

**Alternatives considered**:

- Wait up to 60 seconds for a missing namespace (commit `c4fd1534`). Replaced: it covers the CI case only when the peer's flow creates its namespace within the wait, not a peer with a long setup pre-hook or a queued flow. It also adds the full wait to each flow whose context still lists a deployment whose namespace was deleted.
- Count a missing owner namespace as not departing, as the review proposed. Rejected: it writes only one direction of the pair, and a flow whose context was built before a peer reached `DELETED` writes that peer's aliases again after its namespace is gone, which is the defect of #503.
- Create the missing namespace, as before this fix. Rejected by FR-008: the namespace of a deleted deployment would come back.
- Add the environment id to `EnvironmentContext`. Not needed: `labels.environment_id` holds it, and the context model is part of the driver template surface.

**Not covered**: a deployment created or changed while a peer is being restored. The restored deployment's namespace is terminating or missing, so the step skips the aliases between the two, and no flow runs when the restore ends. The maintainer chose to document this and its recovery (spec, Session 2026-10-17).

