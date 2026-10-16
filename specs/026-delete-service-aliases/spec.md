# Feature Specification: Deleting a Deployment Deletes Its Service Aliases

**Feature Branch**: `fac/services-cleanup-zk1ti`

**Created**: 2026-10-16

**Status**: Draft

**Input**: Design brief "Design brief for the fix" — [opsmill/styrmin#503 (comment)](https://github.com/opsmill/styrmin/issues/503#issuecomment-6226003710). Seed issue: [#503](https://github.com/opsmill/styrmin/issues/503). The brief's links point to `develop` at [d1a3105](https://github.com/opsmill/styrmin/tree/d1a3105bdee724d9a434dda096f32f0c0b2f87d5), which includes [#506](https://github.com/opsmill/styrmin/pull/506), the fix for [#491](https://github.com/opsmill/styrmin/issues/491).

## Context

Each deployment runs in its own namespace, `styrmin-<deployment id>`. So that a pod can reach a service of another deployment of its environment by the service's short name, the create, update and upgrade flows write a **service alias**: an `ExternalName` Service named after the service's resolved name, pointing to `<name>.styrmin-<owner id>.svc.<cluster domain>` ([`service_aliases.py`](../../backend/styrmin_backend/agent/tasks/service_aliases.py)). A flow writes two sets:

- the aliases of the other deployments' services, into its own namespace;
- the aliases of its own services, into the namespaces of the other deployments that have services.

Each alias carries the labels `styrmin.io/service-alias=true` and, since #506, `styrmin.io/deployment-id=<id of the deployment that owns the service>`. Aliases written before #506 have no `styrmin.io/deployment-id` label; #506 finds their owner from the namespace that `spec.externalName` points into.

When a user deletes a deployment, the operator's teardown deletes Services only in the deployment's own namespace, selected by the `styrmin.io/release-reference` label, and then requests the deletion of that namespace ([`styrmin_deployment.py`](../../backend/styrmin_backend/operator/handlers/styrmin_deployment.py), `_teardown_owned_resources` and `_request_namespace_deletion`). Aliases carry no `styrmin.io/release-reference` label, and the aliases of the deleted deployment's services are in other namespaces. So they stay in the other deployments' namespaces after the deployment reaches `DELETED`. [ADR-073](../../dev/adr/0073-kubernetes-objects-named-and-found-by-record-id.md) lists this as the known case that does not follow its decision yet.

The brief also records a race. The server deletes a deployment's `DeployedService` rows only when the deployment reaches `DELETED` ([`deployment_status.py`](../../backend/styrmin_backend/services/deployment_status.py)). Until then, the context built for another deployment of the environment lists the deleted deployment's services ([`context.py`](../../backend/styrmin_backend/services/context.py)), and that context is built before the flow starts and passed to it as a parameter ([`orchestration.py`](../../backend/styrmin_backend/agent/tasks/orchestration.py)). A flow of another deployment that runs while the deployment is `DELETING` therefore:

- writes the aliases of the deleted deployment's services into its own namespace again;
- runs `apply_namespace` on `styrmin-<deleted id>` to write its own aliases there, which creates that namespace again if the flow runs after the namespace is deleted and before the status becomes `DELETED`.

The operator and the Prefect worker use the same ClusterRole, which already allows every verb on Services in all namespaces ([`roles.yaml`](../../helm/agent/templates/roles.yaml)).

## Clarifications

### Session 2026-10-16 (autonomous, from the design brief)

The brief's seven decisions are recorded here so later phases do not reopen them.

- Q: When must the aliases be gone? → A: When the deployment's status becomes `DELETED`, no namespace contains an alias of its services. The operator's teardown deletes them before it requests the deletion of the deployment's namespace (decision 1).
- Q: How does the teardown find the aliases? → A: In all namespaces, among Services labelled `styrmin.io/service-alias=true`: by the label `styrmin.io/deployment-id=<deployment id>`, and, for an alias without that label, by the namespace that `spec.externalName` points into, as #506 does (decision 2).
- Q: What happens when an alias deletion fails? → A: Deleting the aliases is best-effort, like the rest of the teardown. A 404 counts as deleted. Any other error is logged, and the deployment continues to `DELETED`. The changelog says that a failed deletion can leave an alias (decision 3).
- Q: What must flows of other deployments stop doing during a deletion? → A: After the user requests the deletion, no flow of another deployment writes an alias of the deleted deployment's services, writes into the deleted deployment's namespace, or creates that namespace. This includes a flow whose context was built before the request. The implementation plan chooses how (decision 4).
- Q: Do driver templates of other deployments still see the services of a `DELETING` deployment? → A: Yes, until it reaches `DELETED`, as today. Templates render with `SilentUndefined`, so removing those services from the context would make templates render empty values without an error (decision 5).
- Q: Does the fix delete aliases that deletions made before the upgrade left? → A: No. The changelog says that they stay (decision 6).
- Q: Does a StyrminDeployment annotated `styrmin.io/skip-teardown` get its aliases deleted? → A: No. It is deleted without teardown, so its aliases are not deleted either. A cross-target restore sets this annotation on its copy of the source's StyrminDeployment, and the source deployment keeps running (decision 7).
- Q: The brief leaves open whether the fix adds a unit test for this case: a failed teardown left an alias, and another deployment later uses that name for its own Service. Is a test added? → A: Yes. One unit test checks that when the operator writes a deployment's `ClusterIP` Service and the create returns 409 because an alias with that name is in the namespace, the operator replaces the alias with the `ClusterIP` Service. It is the only coverage of how a deployment recovers from an alias that a failed teardown left, and it starts no deployment. A unit test cannot show that the Kubernetes API server accepts the change of `spec.type`; the plan's research records what the Kubernetes documentation says about it. This answer was not in the brief and is flagged for the maintainer to confirm.

### Session 2026-10-16 (planning research, [research.md](research.md))

- Q: Which signal tells a flow that the user requested a deployment's deletion? → A: The deployment's StyrminDeployment: `spec.deletionRequested: true` or a `deletionTimestamp`, or its namespace missing or `Terminating`. The server sets `spec.deletionRequested` before the database status becomes `DELETING`, so the flow reads the cluster at write time instead of the status in its context (R-003).
- Q: Can a flow guarantee that it writes nothing after the request? → A: A read and a write cannot be one atomic operation, so a write can still follow the request by a few milliseconds. The flow reads before it writes and again after it writes, and deletes each alias of a departing deployment that it wrote in between. Together with the teardown, which lists the aliases only after the request, no alias of the deleted deployment remains (R-004). A write into the deleted deployment's namespace in that window is removed by the namespace deletion, and the flow never creates a namespace, so the namespace is not created again (R-005).
- Q: How does the teardown know which deployment's aliases to delete? → A: From `spec.deploymentId`, and only when the CR's namespace is `styrmin-<spec.deploymentId>`. This second guard keeps the copy of a source's CR that a cross-target restore deletes from deleting the running source's aliases (R-001).

### Session 2026-10-16 (critique, [critique-20261016-1.md](critiques/critique-20261016-1.md))

- Q: A restore deletes the target namespace, which deletes its StyrminDeployment and runs the delete handler's teardown. Does that teardown delete the aliases? → A: No. The teardown deletes aliases only when `spec.deletionRequested` is true, or when the StyrminDeployment is deleted while its namespace is not being deleted (`kubectl delete styrmindeployment`). A restored deployment keeps running, and Velero restores only its own namespace, so deleting its aliases in the other namespaces would stop the other deployments from reaching it by short name (FR-017, research R-011).
- Q: FR-007 and FR-008 as first written asked that no write follows the request. → A: They now state the outcome a flow can guarantee: it writes nothing for a deployment whose deletion it can read, removes what it wrote just before it could read the request, and never creates another deployment's namespace (research R-004).

## User Scenarios & Testing *(mandatory)*

Three people use this feature:

- A **user** who deletes a deployment from an environment in which other deployments keep running.
- A **driver author** whose templates read the services of the other deployments of the environment.
- An **administrator** who upgrades Styrmin on a cluster where deployments were deleted before the upgrade.

The user needs:

1. As a user who deletes a deployment, I want the other deployments' namespaces to contain no alias of its services once its status is `DELETED`, so that the namespaces hold only Services of deployments that exist.
2. As a user who deletes a deployment while another deployment of the environment is being created, updated or upgraded, I want that other change to leave no alias of the deleted deployment's services and to not create the deleted deployment's namespace again.
3. As a user, I want a deployment's deletion to still reach `DELETED` when one alias cannot be deleted, as the rest of the teardown does today.
4. As a driver author, I want my templates to keep seeing a `DELETING` deployment's services until it reaches `DELETED`, so that a deletion in progress does not make my templates render empty values.
5. As an administrator, I want the changelog to say which aliases the fix does not delete, so that I know which aliases stay after the upgrade.

### User Story 1 - The teardown deletes the deployment's aliases in all namespaces (Priority: P1)

A user deletes deployment A from an environment in which deployment B, which also has services, keeps running. Before the operator requests the deletion of A's namespace, it deletes every alias of A's services in every namespace: those labelled with A's id and those without the label whose `spec.externalName` points into `styrmin-<A id>`. When the user views A as `DELETED`, B's namespace holds no alias of A's services. Aliases of other deployments' services stay.

**Why this priority**: It is the defect that #503 reports.

**Independent Test**: Delete one deployment of the service-discovery E2E module and, once its status is `DELETED`, list the Services of the other deployment's namespace.

**Acceptance Scenarios**:

1. **Given** deployments A and B, both with services, run in one environment, **When** the user deletes A and waits until its status is `DELETED`, **Then** no Service in B's namespace has the label `styrmin.io/deployment-id=<A id>`, and none has a `spec.externalName` that points into `styrmin-<A id>`.
2. **Given** an alias of A's service without the `styrmin.io/deployment-id` label, written before #506, is in B's namespace, **When** the teardown of A runs, **Then** that alias is deleted.
3. **Given** aliases of B's services and of a deployment of another environment on the same cluster are in other namespaces, **When** the teardown of A runs, **Then** those aliases stay.
4. **Given** deployment C of the environment has no services, so its namespace holds aliases of A's services but no Service of its own, **When** the teardown of A runs, **Then** the aliases of A's services in C's namespace are deleted.
5. **Given** an operator deletes A's StyrminDeployment with `kubectl delete styrmindeployment`, **When** the delete handler runs the teardown, **Then** the aliases of A's services are deleted, and a later run of the same teardown, while the finalizer stays, treats each 404 as deleted.

---

### User Story 2 - Flows of other deployments do not write the aliases again during a deletion (Priority: P1)

While deployment A is `DELETING`, a create, update or upgrade flow of deployment B runs. This includes a flow queued, with its context already built, before the user requested the deletion of A. The flow writes no alias of A's services into any namespace, writes nothing into `styrmin-<A id>`, and does not create that namespace. B's driver templates still see A's services until A reaches `DELETED`.

**Why this priority**: Without it, a flow that runs during the deletion writes the aliases back after the teardown deleted them, or creates A's namespace again, so User Story 1 does not hold.

**Independent Test**: Unit tests build B's context while A is `DELETING`, and build it before A's deletion is requested, then run the alias step of B's flow and check what it writes.

**Acceptance Scenarios**:

1. **Given** A is `DELETING`, **When** a context is built for B and B's flow runs, **Then** the flow writes no alias of A's services and nothing into `styrmin-<A id>`, and does not create that namespace.
2. **Given** B's context was built before the user requested A's deletion, **When** B's flow runs after the request, **Then** the flow writes no alias of A's services and nothing into `styrmin-<A id>`, and does not create that namespace.
3. **Given** B's flow read A's state before the user requested A's deletion and writes after it, **When** the flow ends, **Then** no alias of A's services that the flow wrote remains: the flow deleted it, or A's teardown deleted it.
4. **Given** A is `DELETING`, **When** a context is built for B, **Then** the context still lists A's services for B's driver templates.
5. **Given** A is `DELETING` and B's flow runs, **When** the flow writes the aliases of B's services and of the other deployments' services, **Then** those aliases are written as today, in every namespace other than `styrmin-<A id>`.
6. **Given** A's namespace is being deleted, **When** B's change runs, **Then** B's change completes. Today B's flow can fail at its service-aliases step, because Kubernetes refuses to create B's alias in a namespace that is being deleted.

---

### User Story 3 - A failed alias deletion does not block the deletion (Priority: P2)

When the teardown cannot delete an alias, it logs the error and continues. The deployment's namespace deletion is still requested, and the deployment still reaches `DELETED`. The changelog says that a failed deletion can leave an alias, and that aliases left by deletions made before the upgrade stay. A StyrminDeployment annotated `styrmin.io/skip-teardown` is deleted without teardown, so no alias is deleted for it.

**Why this priority**: It keeps today's behaviour of the teardown, which logs errors and continues. It does not add a way for a deletion to fail.

**Independent Test**: Unit tests make the alias deletion return 404 and another error, and set the `styrmin.io/skip-teardown` annotation.

**Acceptance Scenarios**:

1. **Given** an alias of A's services is deleted by another process before the teardown deletes it, **When** the delete returns 404, **Then** the teardown counts it as deleted and continues.
2. **Given** the delete of an alias returns an error other than 404, **When** the teardown runs, **Then** the error is logged with the alias's namespace and name, the remaining aliases are still deleted, and the namespace deletion is still requested.
3. **Given** listing the aliases fails, **When** the teardown runs, **Then** the error is logged and the namespace deletion is still requested.
4. **Given** A's StyrminDeployment is annotated `styrmin.io/skip-teardown: "true"`, **When** it is deleted, **Then** no alias is deleted.

---

### Edge Cases

- **Environment deletion**: all of the environment's namespaces are deleted, so most alias deletions return 404, which count as deleted.
- **Several environments on one cluster**: the teardown selects aliases by the owner's id, or by the owner's namespace for aliases without the label, so it deletes no alias of another environment.
- **A later deployment takes a service name of the deleted deployment**: its namespace is new, so it holds no remaining alias. Its flow writes its aliases into the other deployments' namespaces with a create, then a replace when the create returns 409, so it overwrites a remaining alias with the same name.
- **A failed teardown left an alias, and another deployment later uses that name for its own Service**: the operator writes the Service with the same create-then-replace function, so it is expected to replace the alias with its `ClusterIP` Service. A unit test covers this (see Clarifications).
- **A deployment without services keeps a remaining alias** until its own flow runs again, if the teardown failed to delete it. This is accepted under the best-effort rule.
- **What a pod resolves through a remaining alias**: Kubernetes answers a lookup of an `ExternalName` Service with a CNAME record. After the target namespace is deleted, the CNAME target is expected to have no record, so the lookup fails as it would without the alias. This was not checked in a cluster.
- **A restore deletes and restores a deployment's namespace**: the namespace deletion deletes the deployment's StyrminDeployment, and the operator runs the teardown of its delete handler. That teardown deletes no alias, because the user did not request the deletion and the deployment keeps running (FR-017). While the namespace is being deleted or is gone, the flows of the other deployments skip it and do not create it again.
- **A Velero restore copies aliases** from a source namespace into a counterpart deployment's namespace: out of scope.

## Requirements *(mandatory)*

### Functional Requirements

**Teardown**

- **FR-001**: The operator's teardown MUST delete, in all namespaces, the aliases of the deleted deployment's services before it requests the deletion of the deployment's namespace.
- **FR-002**: The teardown MUST find these aliases among the Services labelled `styrmin.io/service-alias=true` as follows:
  - an alias with the label `styrmin.io/deployment-id` belongs to the deployment whose id the label holds;
  - an alias without that label belongs to the deployment whose namespace its `spec.externalName` points into, the same rule as #506.
- **FR-003**: The teardown MUST NOT delete an alias of another deployment's services, including those of deployments of other environments on the same cluster.
- **FR-004**: Deleting the aliases MUST be best-effort:
  - a 404 counts as deleted;
  - any other error when listing or deleting is logged, with the alias's namespace and name when known;
  - the teardown continues, the namespace deletion is still requested, and the deployment continues to `DELETED`.
- **FR-005**: Both deletion paths MUST delete the aliases: the platform-driven path (`spec.deletionRequested`) and `kubectl delete styrmindeployment`. Running the teardown again while the finalizer stays MUST NOT fail on aliases already deleted.
- **FR-006**: A StyrminDeployment annotated `styrmin.io/skip-teardown: "true"` MUST be deleted without deleting any alias.
- **FR-017**: When a StyrminDeployment without `spec.deletionRequested: true` is deleted because its namespace is being deleted, as a restore does, the teardown MUST NOT delete any alias. When the teardown cannot read the namespace, it MUST NOT delete any alias and MUST log why.

**Flows of other deployments during a deletion**

- **FR-007**: A create, update or upgrade flow of another deployment MUST NOT write an alias of the services of a deployment whose deletion it can read at write time. This includes a flow whose context was built before the request. When the request comes between the flow's read and its write, the flow MUST delete the aliases of that deployment it wrote, so that, together with the teardown, none remains.
- **FR-008**: A flow of another deployment MUST NOT write into the namespace of a deployment whose deletion it can read at write time, and MUST NOT create the namespace of another deployment. A write that comes between the flow's read and the request is removed when the namespace is deleted.
- **FR-009**: Apart from FR-007 and FR-008, a flow MUST write its aliases as today.
- **FR-010**: The context built for another deployment MUST still list the services of a `DELETING` deployment for driver templates until that deployment reaches `DELETED`.

**Changes this fix does not make**

- **FR-011**: The fix MUST NOT delete aliases left by deletions made before the upgrade, and MUST NOT add a cleanup, in flows, of aliases that a failed teardown left.

**Changelog and documentation**

- **FR-012**: The fix MUST add `changelog/503.fixed.md`, which says that a deployment's deletion deletes its service aliases, that a failed deletion can leave an alias, and that aliases left by deletions made before the upgrade stay.
- **FR-013**: The same change MUST update:
  - `CONTEXT.md`: a new entry "Service alias", with the text the brief proposes;
  - [`dev/knowledge/agent/operator.md`](../../dev/knowledge/agent/operator.md): the teardown steps;
  - [`dev/knowledge/backend/orchestration-flows.md`](../../dev/knowledge/backend/orchestration-flows.md), section "Service aliases";
  - [`docs/docs/drivers/generic-app.md`](../../docs/docs/drivers/generic-app.md), section "Networking";
  - [ADR-073](../../dev/adr/0073-kubernetes-objects-named-and-found-by-record-id.md), "More information": remove the known case for deployment deletion.

**Tests**

- **FR-014**: Unit tests MUST cover:
  - the teardown deletes aliases with the label and aliases without it, and the aliases of other deployments stay;
  - a 404 counts as deleted, and another error is logged while the namespace deletion still runs;
  - a flow of another deployment writes no alias of a deployment whose deletion was requested, writes nothing into its namespace and does not create it, both for a context built while the deployment is `DELETING` and for a context built before the request;
  - the context still lists the services of a `DELETING` deployment;
  - no alias is deleted when the `styrmin.io/skip-teardown` annotation is set;
  - no alias is deleted when the StyrminDeployment has no deletion request and its namespace is being deleted, or when the namespace cannot be read; aliases are deleted when the request is set and the namespace is being deleted;
  - the operator's write of a `ClusterIP` Service replaces an alias with the same name (see Clarifications).
- **FR-015**: A new E2E test MUST be added at the end of [`test_service_discovery.py`](../../backend/tests/e2e/test_service_discovery.py), marked `api_only` and `shard_general`. It deletes `intent`, waits until its status is `DELETED`, then checks that `executor`'s namespace holds no Service with the label `styrmin.io/deployment-id=<intent id>` and none whose `spec.externalName` points into `styrmin-<intent id>`. It reuses the deployments of the module's `discovery_deployments` fixture, starts no new deployment, and runs last in the module, because the other tests of the module use `intent`.
- **FR-016**: The race of FR-007 and FR-008 has no E2E test, because its timing cannot be reproduced reliably.

### Key Entities

- **Service alias**: an `ExternalName` Service in the namespace of one deployment that points a service's short name to the service in its owner's namespace. Labelled `styrmin.io/service-alias=true` and, since #506, `styrmin.io/deployment-id=<owner id>`. Owned by the deployment that owns the service, not by the deployment whose namespace holds it.
- **Deployment deletion**: starts when the user requests it. The server first sets `spec.deletionRequested: true` on the StyrminDeployment; the status becomes `DELETING` when the operator reports its teardown. It ends when the status becomes `DELETED`, when the server deletes the deployment's `DeployedService` rows.
- **Deployment context**: built by the server before a flow starts and passed to the flow. Its `services` are what driver templates read; its `deployed_services` are what the flow builds aliases from.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the E2E test, after `intent` reaches `DELETED`, `executor`'s namespace holds 0 Services labelled `styrmin.io/deployment-id=<intent id>` and 0 Services whose `spec.externalName` points into `styrmin-<intent id>`.
- **SC-002**: In unit tests, a flow of another deployment that reads a deletion request writes 0 aliases of the deleted deployment's services and 0 objects into its namespace, and creates 0 namespaces, for both context timings. When the request comes between the flow's two reads, 0 aliases of that deployment that the flow wrote remain.
- **SC-003**: When an alias deletion fails with an error other than 404, the deployment still reaches `DELETED`, and each teardown run that fails to delete the alias logs the failure with the alias's namespace and name.
- **SC-006**: In unit tests, a teardown that a restore's namespace deletion starts deletes 0 aliases.
- **SC-004**: Driver templates of other deployments render the same values for a `DELETING` deployment's services as before the fix.
- **SC-005**: The E2E suite gains 1 test node and 0 new deployments; the `shard_general` api cell grows only by the time to delete `intent`.

## Assumptions

- The ClusterRole that the operator and the Prefect worker share already allows listing and deleting Services in all namespaces, so the fix changes no authorization rule.
- The fix changes no database schema, GraphQL schema, dependency or CI workflow.
- The operator can derive the deleted deployment's id from the StyrminDeployment it tears down; the plan confirms the field it reads.
- The E2E module's `intent` is used by every other test of the module, so the new test must run last; pytest runs the tests of a module in file order.
- Kubernetes refuses to create objects in a namespace that is being deleted. The plan's research confirms this and what that means for FR-008.

## Out of Scope

- Aliases left by deletions made before the upgrade.
- A later cleanup, in flows, of aliases that a failed teardown left.
- Aliases that a Velero restore copies from the source namespace into a counterpart deployment's namespace.
- An E2E test for the race of FR-007 and FR-008.
