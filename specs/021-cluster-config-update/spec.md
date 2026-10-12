# Feature Specification: Update a Cluster's Config in Place

**Feature Branch**: `fac/cluster-settings-9vkqq`

**Created**: 2026-10-12

**Status**: Draft

**Input**: PRD "Update a cluster's config in place" — [opsmill/styrmin#423 (comment)](https://github.com/opsmill/styrmin/issues/423#issuecomment-6123640046). Seed issue: [#423](https://github.com/opsmill/styrmin/issues/423). Related: [#301](https://github.com/opsmill/styrmin/issues/301) (cluster detail edit form), [#366](https://github.com/opsmill/styrmin/issues/366) (a cluster can be deleted only once it has no environments), [ENG-140](https://opsmill.atlassian.net/browse/ENG-140) (a declared change to a cluster is applied without recreating the cluster).

## Context

An administrator sets a **cluster**'s **config** only when they create the cluster. The config holds the shared ingress class, the FQDN suffix, the standard and fast storage classes, the runtime class, the node selector, the external URL settings and the dedicated ingress settings. To change any of these values today, the administrator deletes every **deployment** and every **environment** of the cluster, deletes the cluster, and creates it again ([#423](https://github.com/opsmill/styrmin/issues/423)).

Environments and deployments take the cluster's value for every setting they do not set themselves. The **resolved config** of a deployment is the merge of the cluster config, then the environment config, then the deployment config, where the deepest value wins. Each **instance** records the resolved config it was rendered with (`InstanceContext.config`). One cluster value therefore reaches the deployments of every environment that does not override it.

With this feature, the administrator submits a new cluster config from the same JSON file they used to create the cluster. Styrmin saves the new config and redeploys each deployment whose resolved config changes. This follows the environment update, which saves the environment config and then starts a **config fan-out**: one redeploy for each deployment that is not yet at the new config ([ADR-012](../../dev/adr/0012-environment-config-fanout.md)). When the cluster's `dedicated_ingress` setting changes, Styrmin also creates, redeploys or removes the **dedicated ingress controller** of each environment that takes the cluster's value. The dedicated ingress controller is the internal deployment that serves the applications of one environment when `dedicated_ingress` is set.

In this document, "administrator" means a signed-in user with the `ADMIN` role. The word "operator" is kept for the Styrmin **operator** that reconciles StyrminDeployment CRDs ([CONTEXT.md](../../CONTEXT.md)).

## Clarifications

### Session 2026-10-12 (decisions made while drafting, from the PRD and the current code)

- Q: What happens to the applications of an environment whose dedicated ingress controller has failed or is being removed when the cluster update runs (PRD open question)? → A: It depends on whether the update changes that environment's effective `dedicated_ingress` value:
  - The value does not change: Styrmin redeploys the applications as for any other environment and leaves the controller as it is. A redeploy does not create a controller, so the reason that today's deploy refuses such an environment (a second controller would collide with the first one) does not apply. The environment update behaves the same way today.
  - The value is turned on or its values change, and the controller has failed: Styrmin redeploys the controller with the new values first, and moves the applications once the controller is ready.
  - The value is turned on, and the controller is being removed: Styrmin does not create a second controller and leaves the applications on their current config, where they stay reachable through the shared ingress class. They are counted as skipped. A resubmission after the removal has finished creates the controller and moves them.
  - The value is turned off, and the controller has failed: Styrmin redeploys the applications to the shared ingress class and then removes the controller.
- Q: Does "the controller is created before the applications are redeployed" mean that the redeploy of the controller is started first, or that the controller is ready first? → A: The controller is ready first. The PRD gives the reason for the order as "so that the applications stay reachable" (user stories 7 and 8), and an application that moves to a controller that does not answer yet is not reachable. In the same way, the controller is removed only after the redeploys of the applications in that environment have finished.
- Q: Does a change to a cluster value that no deployment's resolved config reads start redeploys? → A: No. Redeploys depend only on the resolved config. Today the resolution does not read the cluster's `scheduling` value (only the environment and deployment `scheduling` values are merged), so a change to it is saved and starts no redeploys. Changing that resolution rule is out of scope.
- Q: The PRD names the invalid-config error `INVALID_CONTEXT`. Which error is meant? → A: `InvalidContextError`, the error that `createCluster` raises for an invalid config. Its error code is `VALIDATION_ERROR` ([exceptions.py](../../backend/styrmin_backend/services/exceptions.py)). `INVALID_CONTEXT` appears only in code comments.
- Typed GraphQL input or JSON argument for `updateCluster`, and whether the rules that differ from ADR-012 need a new ADR: left to the plan, as the PRD asks.

## User Scenarios & Testing *(mandatory)*

The primary actor is the **administrator** who maintains the cluster as its infrastructure changes: a new ingress class, a new DNS suffix, a new storage class, or a dedicated ingress controller per environment. The administrator uses `styrminctl`, the SDK or GraphQL, and in a second phase the cluster detail page. The secondary actor is the **application owner** whose deployments are redeployed when a cluster value they take changes.

### User Story 1 - Change a cluster config value without recreating the cluster (Priority: P1)

The administrator edits the cluster config file they passed to `styrminctl clusters create` and submits it with `styrminctl clusters update <cluster> --config @cluster.json`, with the SDK, or with GraphQL. Styrmin saves the new config, recomputes the cluster **capabilities**, and redeploys each deployment, in every environment of the cluster, whose resolved config is different from the resolved config of its **active instance**. No deployment, environment or cluster is deleted. Deployments in an environment that overrides the changed value are not redeployed. A resubmission of the stored config starts no redeploy. An invalid config, an update while an **environment clone** is in progress, and an update by a user without the `ADMIN` role are refused, and nothing is saved.

**Why this priority**: Without this story, the only way to change a cluster value is to delete everything that runs on the cluster (PRD user stories 1 to 6, 9 to 13; ENG-140).

**Independent Test**: On a cluster with `ingress_class: traefik`, create environment A that sets no `ingress_class` and environment B that sets `ingress_class: traefik`, each with one running deployment. Submit a cluster config with `ingress_class: nginx`. Confirm that the cluster stores `nginx`, that the deployment in A gets a redeploy task and its Ingress uses `nginx`, and that the deployment in B gets no task. Submit the same file again and confirm that no new task is created.

**Acceptance Scenarios**:

1. **Given** a cluster with `ingress_class: traefik`, environment A that sets no `ingress_class` and has one running deployment, and environment B that sets `ingress_class: traefik` and has one running deployment, **When** the administrator submits a cluster config with `ingress_class: nginx`, **Then** the cluster stores `nginx`, the deployment in A gets a redeploy task and its Ingress uses `nginx`, and the deployment in B gets no task.
2. **Given** a cluster whose stored config was just applied to every deployment, **When** the administrator submits the same config again, **Then** no deployment gets a redeploy task and no timeline entry is added.
3. **Given** a cluster update during which the redeploy of one deployment could not be started, **When** the administrator submits the same config again, **Then** only that deployment gets a redeploy task.
4. **Given** a cluster config file that leaves out `fqdn_suffix`, **When** the administrator submits it, **Then** the cluster no longer stores an FQDN suffix, because the update replaces the whole config.
5. **Given** a cluster config file that leaves out `ingress_class` and `runtime_class`, **When** the administrator submits it, **Then** the cluster stores `ingress_class: traefik` and `runtime_class: default`, the same defaults as when the cluster is created.
6. **Given** a cluster without `fqdn_suffix`, **When** the administrator submits a config that adds `fqdn_suffix`, **Then** the cluster capabilities include the ingress capability as soon as the update returns.
7. **Given** a cluster that has running deployments, **When** the administrator changes `standard_storage` or `fast_storage`, **Then** the new storage class is saved and the deployments that take it get a redeploy task.
8. **Given** a cluster config that does not pass validation, **When** the administrator submits it, **Then** the update is refused with `InvalidContextError` (error code `VALIDATION_ERROR`) and the stored config is unchanged.
9. **Given** an environment of the cluster that an environment clone is still building, **When** the administrator submits a new cluster config, **Then** the update is refused with `EnvironmentOperationInProgressError` and the stored config is unchanged.
10. **Given** an environment backup or an environment restore in progress, and no clone in progress, **When** the administrator submits a new cluster config, **Then** the update is accepted.
11. **Given** a signed-in user without the `ADMIN` role, **When** they submit a cluster config through GraphQL, the SDK or `styrminctl`, **Then** the update is refused and the stored config is unchanged.
12. **Given** any cluster update, **When** it returns, **Then** the server log has one line for the update that gives the number of deployments evaluated, redeployed, skipped and failed.

---

### User Story 2 - Turn the cluster's dedicated ingress on or off and keep the applications reachable (Priority: P1)

The administrator turns `dedicated_ingress` on, changes its values, or turns it off in the cluster config. In each environment that takes the cluster's value and has applications, Styrmin creates or redeploys the dedicated ingress controller and moves the applications to it once it is ready. When the setting is turned off, Styrmin moves the applications back to the shared `ingress_class` and removes the controller once they have moved.

**Why this priority**: The dedicated ingress setting is the cluster value whose change has the largest effect on reachability. The PRD's P1 journey includes it (PRD user stories 7 and 8).

**Independent Test**: On a cluster without `dedicated_ingress`, with one environment that takes the cluster's value and has one running application, turn `dedicated_ingress` on. Confirm that the controller reaches `RUNNING` before the application's redeploy starts, and that the application answers on its external URL through the controller. Turn the setting off. Confirm that the application is redeployed to the shared `ingress_class`, that the controller is removed after the redeploy has finished, and that the application answers through the shared ingress class.

**Acceptance Scenarios**:

1. **Given** a cluster without `dedicated_ingress` and one environment that takes the cluster's value and has one running application, **When** the administrator turns `dedicated_ingress` on, **Then** Styrmin creates the dedicated ingress controller in that environment, redeploys the application only after the controller is ready, and the application answers on its external URL through the controller.
2. **Given** the state after scenario 1, **When** the administrator turns `dedicated_ingress` off, **Then** Styrmin redeploys the application to the shared `ingress_class`, removes the controller only after that redeploy has finished, and the application answers through the shared ingress class.
3. **Given** a cluster with `dedicated_ingress` on and an environment that takes the cluster's value, **When** the administrator changes a value inside `dedicated_ingress` (for example the controller's service settings), **Then** Styrmin redeploys the controller first and redeploys the applications once the controller is ready.
4. **Given** an environment that sets its own `dedicated_ingress` value, **When** the administrator turns the cluster's `dedicated_ingress` on or off, **Then** that environment's controller and applications are not redeployed.
5. **Given** an environment that takes the cluster's value and has no applications, **When** the administrator turns `dedicated_ingress` on, **Then** no controller is created in that environment, and the controller is created on the first deploy, as today.
6. **Given** a cluster config file that leaves out `dedicated_ingress`, **When** the administrator submits it, **Then** `dedicated_ingress` is turned off and the controllers of the environments that take the cluster's value are removed after their applications have moved.

---

### User Story 3 - Edit the cluster config from the cluster detail page (Priority: P2)

On the cluster detail page, the administrator edits the cluster config in a form and saves. Styrmin applies the change as in User Story 1 and keeps every value the administrator did not change ([#301](https://github.com/opsmill/styrmin/issues/301)).

**Why this priority**: The CLI, the SDK and GraphQL cover the need. The form removes the need for these tools for a small change (PRD user story 14).

**Independent Test**: On a cluster whose config sets `dedicated_ingress`, `scheduling` and a storage class, change only the FQDN suffix in the form and save. Confirm that the cluster stores the new FQDN suffix and keeps the other values.

**Acceptance Scenarios**:

1. **Given** a cluster whose config sets `dedicated_ingress`, `scheduling` and a storage class, **When** the administrator changes only the FQDN suffix in the form and saves, **Then** the cluster stores the new FQDN suffix and keeps `dedicated_ingress`, `scheduling` and the storage class unchanged.
2. **Given** a user without the `ADMIN` role, **When** they open the cluster detail page, **Then** they view the cluster config and cannot edit it.

---

### Edge Cases

- **A stateful deployment fails to redeploy after a storage class change.** Kubernetes refuses any change to the volume claim templates of an existing StatefulSet ([Kubernetes validation](https://github.com/kubernetes/kubernetes/blob/1999683eee27372c7bcca8bd15d01cff59e8cbcb/pkg/apis/apps/validation/validation.go#L262)), and the application driver templates write the storage class there ([infrahub values template](../../driver/examples/infrahub/values.j2.yml)). The deployment is marked failed. Styrmin makes the new instance active before the rollout runs, so a later update finds the deployment already at the new config and does not retry it. To recover, the administrator sets the old storage class back or recreates the deployment. The environment update behaves the same way today.
- **An environment overrides the changed value.** Its deployments get no redeploy.
- **An environment takes the cluster's `dedicated_ingress` and has no applications.** No controller is created when the setting is turned on. The controller is created on the first deploy, as today.
- **The config file leaves out `dedicated_ingress`.** The update turns it off and removes the controllers, because the update replaces the whole config.
- **The redeploy of one deployment cannot be started.** The other redeploys still start. A resubmission starts only the missed redeploys.
- **The dedicated ingress controller does not become ready after `dedicated_ingress` is turned on.** The applications of that environment stay on their current config and stay reachable through the shared ingress class. A resubmission after the controller is repaired moves them.
- **The dedicated ingress controller has failed or is being removed.** See Clarifications.
- **Two updates overlap.** The update saved last wins, as for environments in ADR-012.
- **A deleted (tombstoned), internal or `RESTORING` deployment.** It is not redeployed by the general rule. The dedicated ingress controller is redeployed only by the rules of User Story 2.
- **A changed cluster value that no resolved config reads** (today the cluster's `scheduling` value). The value is saved and no deployment is redeployed.
- **The cluster does not exist.** The update is refused with `ClusterNotFoundError`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST save the new cluster config before it starts any redeploy, then redeploy the affected deployments in every environment of the cluster.
  - Verified by: a unit test that checks the cluster row is committed before the first task is created.
- **FR-002**: The system MUST redeploy a deployment only when its resolved config, computed from the new cluster config, differs from the resolved config of its active instance.
  - Deleted (tombstoned), internal and `RESTORING` deployments are skipped.
  - A redeploy that cannot be started does not stop the redeploys of the other deployments.
  - A resubmission of the same config redeploys only the deployments that did not get the new config.
  - Verified by: a unit test with an environment that overrides the changed value, and a unit test that resubmits after a forced failure.
- **FR-003**: The system MUST accept a change to any cluster config value while deployments exist, including `standard_storage` and `fast_storage`.
  - Verified by: a unit test that checks a storage class change is saved and starts redeploys.
- **FR-004**: When the effective `dedicated_ingress` value of an environment changes because of the cluster update, and the environment has applications, the system MUST manage that environment's dedicated ingress controller in an order that keeps the applications reachable:
  - Turned on, or its values changed: the controller is created or redeployed first, and the applications are redeployed only after the controller is ready.
  - Turned off: the applications are redeployed first, and the controller is removed only after their redeploys have finished.
  - The cases where the controller has failed or is being removed follow the decisions in Clarifications.
  - Verified by: the P1 E2E test and a unit test of the ordering.
- **FR-005**: The update MUST replace the whole cluster config. A value left out of the submitted config is cleared, except `ingress_class` and `runtime_class`, which get the same defaults as when the cluster is created (`traefik` and `default`).
  - Verified by: a unit test that leaves out a value and checks it is cleared, and a unit test that leaves out `ingress_class` and checks `traefik` is stored.
- **FR-006**: The system MUST refuse the update with `EnvironmentOperationInProgressError`, and save nothing, while any environment of the cluster has an environment clone in progress. Environment backups and environment restores in progress do not block the update.
  - Verified by: a unit test.
- **FR-007**: The system MUST recompute the cluster capabilities in the same transaction as the config ([ADR-026](../../dev/adr/0026-capabilities-recalculation-in-service-layer.md)).
  - Verified by: a unit test that adds `fqdn_suffix` and checks the ingress capability appears.
- **FR-008**: The system MUST refuse an invalid config with `InvalidContextError` (error code `VALIDATION_ERROR`) and save nothing.
  - Verified by: a unit test.
- **FR-009**: Users with the `ADMIN` role MUST be able to update the cluster config through GraphQL, the SDK and `styrminctl clusters update`. Other users are refused.
  - `styrminctl clusters update` takes the config with `--config`, as inline JSON or as `@file`, like `styrminctl clusters create`.
  - Verified by: the GraphQL propagation test, a CLI command test and a test that a user without the `ADMIN` role is refused.
- **FR-010**: The system MUST log one line per update with the number of deployments evaluated, redeployed, skipped and failed. The skipped count distinguishes the deployments already at the new config, the `RESTORING` deployments, and the deployments that wait for their dedicated ingress controller.
  - Verified by: a unit test of the cluster config fan-out.
- **FR-011** (P2): Administrators MUST be able to edit the cluster config from the cluster detail page. The form submits the whole config and keeps every value the administrator did not change, including `dedicated_ingress`, `scheduling` and the storage classes.
  - Verified by: a frontend unit test of the form.

### Key Entities

- **Cluster** (existing): its config is replaced in place, and its capabilities are recomputed. No new field.
- **Environment** (existing): no change. Its config still overrides the cluster's values.
- **Deployment and instance** (existing): a redeploy creates a new active instance from the new resolved config, as the environment update does today.
- **Dedicated ingress controller** (existing internal deployment): a cluster update can now create, redeploy or remove it.
- **Config fan-out** (existing concept from ADR-012): extended from environment updates to cluster updates. The CONTEXT.md entry is updated to cover the cluster case.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a cluster that has environments and deployments, an administrator changes any cluster config value with one `styrminctl clusters update` command and deletes nothing.
- **SC-002**: After an update, every non-deleted deployment whose resolved config changed has a redeploy task, and no other deployment has one.
- **SC-003**: A resubmission of the stored config starts zero redeploys and adds zero timeline entries.
- **SC-004**: After `dedicated_ingress` is turned on at the cluster, each application in an environment that takes the cluster's value answers through the dedicated ingress controller once its redeploy has finished. After it is turned off, the controller is removed and the applications answer through the shared `ingress_class`.
- **SC-005**: During the change of `dedicated_ingress` in SC-004, the application is redeployed only after the controller is ready, and the controller is removed only after the application's redeploy has finished.

## Assumptions

- Styrmin supports exactly one cluster ([ADR-039](../../dev/adr/0039-single-cluster-platform-scope.md)).
- When two updates overlap, the update saved last wins, as for environments in ADR-012.
- No process changes the cluster config except the service layer, so recomputing the capabilities in the update keeps them correct (ADR-026).
- The cluster config stays in the existing JSON column. No database migration is needed.
- The update reuses the existing errors `ClusterNotFoundError`, `InvalidContextError` (`VALIDATION_ERROR`) and `EnvironmentOperationInProgressError`.
- The `ADMIN` role that `createCluster` requires also protects the update. No authorization rule changes.
- The documentation is updated in the same change: the CLI and GraphQL pages in `docs/`, [architecture.md §3.5](../../dev/knowledge/architecture.md), [data-models.md](../../dev/knowledge/backend/data-models.md), the CONTEXT.md config fan-out entry and a changelog fragment.

## Out of Scope

- Renaming the cluster.
- Partial updates that change only the submitted values.
- The same dedicated ingress controller gap in the environment update: `updateEnvironment` neither creates, redeploys nor removes the controller when `dedicated_ingress` changes. It needs a separate issue.
- Moving existing volumes to a new storage class.
- Deleting a cluster that has environments ([#366](https://github.com/opsmill/styrmin/issues/366)).
- Declaring the cluster config in `styrminctl apply` manifests.
- Making the resolution read the cluster's `scheduling` value.
