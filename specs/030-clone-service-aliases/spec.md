# Feature Specification: A Clone Writes Its Own Service Aliases and Restores None of the Source's

**Feature Branch**: `fac/alias-clone-fix-l1vzt`

**Created**: 2026-10-18

**Status**: Draft

**Input**: PRD "A clone writes its own service aliases and restores none of the source's" — [opsmill/styrmin#530 (comment)](https://github.com/opsmill/styrmin/issues/530#issuecomment-6248901847). Seed issue: [#530](https://github.com/opsmill/styrmin/issues/530). The PRD's links point to `develop` at [`5444f0e6`](https://github.com/opsmill/styrmin/tree/5444f0e6bd991f1657a08ba8b80270227e9fe7c3). This spec is written against `develop` at `f4e60189`, which adds the fix for [#503](https://github.com/opsmill/styrmin/issues/503) (spec 026, ADRs 076 to 078).

## Context

Each deployment runs in its own namespace, `styrmin-<deployment id>`. So that an application can call a service of another deployment of its environment by the service's short name, Styrmin writes a **service alias** into the namespace of every other deployment of the environment: an `ExternalName` Service named after the service's resolved name, labelled `styrmin.io/service-alias=true` and `styrmin.io/deployment-id=<owner id>`, pointing to `<name>.styrmin-<owner id>.svc.<cluster domain>` ([`service_aliases.py`](../../backend/styrmin_backend/agent/tasks/service_aliases.py)). The create, update and upgrade flows write the aliases in their step "Create and delete service aliases" ([`orchestration.py`](../../backend/styrmin_backend/agent/tasks/orchestration.py), `_apply_service_aliases_step`). Since #503, that step reads the other deployments' services from the server when it runs ([ADR-078](../../dev/adr/0078-alias-step-reads-current-services-from-server.md)) and skips the aliases written into, or pointing into, a namespace that is missing, terminating, or whose deployment is being deleted ([ADR-077](../../dev/adr/0077-alias-flow-reads-deletion-state-at-write-time.md)).

An environment clone creates one counterpart deployment per selected source deployment, with no initial reconcile, and then restores the source deployment's backup into the counterpart's namespace with a cross-target restore ([`clone.py`](../../backend/styrmin_backend/workflows/templates/clone.py), [ADR-056](../../dev/adr/0056-environment-clone-record-and-cross-target-restore.md)). From the code:

- A deployment's backup includes its whole namespace, alias Services included ([`builders/backup.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py), `build_velero_backup`).
- The cross-target restore maps the source namespace to the counterpart's namespace and writes back every object of the backup, except the HelmRelease and CiliumEndpoints, with `existing_resource_policy="update"` ([`builders/backup.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py), `build_velero_restore`; [`workflows/templates/backup.py`](../../backend/styrmin_backend/workflows/templates/backup.py), `execute_restore_workflow`). Each restored alias keeps its name, its `styrmin.io/deployment-id` label of the source deployment, and its `spec.externalName`, which names a namespace of the source environment.
- Restore recovery re-applies the operator's own Services, not the aliases ([`restore_recovery.py`](../../backend/styrmin_backend/operator/restore_recovery.py)).
- No create, update or upgrade flow runs for a counterpart during the clone, so no flow writes the counterpart's aliases.
- A later update of a counterpart deletes only the aliases that carry the counterpart's own deployment id (`select_stale_aliases`), so a restored alias for a peer that was not cloned stays.

So an application in a clone that calls a peer by its short service name reaches a deployment of the source environment. The user documentation states the opposite: applications in a clone reach each other in the clone, not back to production ([ingress-and-networking.md](../../docs/docs/concepts-and-architecture/ingress-and-networking.md), "Self-contained cloned environments"). Issue #530 records the output of an E2E run that found it: the alias for the peer's service in the counterpart's namespace had `spec.externalName` `envclone76472b72.styrmin-5691a1af-….svc.cluster.local`, the namespace of the source deployment.

## Clarifications

### Session 2026-10-18 (maintainer decisions, from the PRD)

The PRD records these decisions, made with the maintainer on 2026-10-18. They are listed here so that later phases do not reopen them.

- Q: What does the clone's cross-target restore do with the source's aliases? → A: It does not write them back. At no point does a counterpart's namespace hold an alias that points to the source environment.
- Q: Which aliases does a counterpart get? → A: After the restore's recovery step, the restore writes the counterpart's aliases from the services that the server records for the new environment, in the step "Create and delete service aliases". An alias for a peer that has a counterpart points to that counterpart.
- Q: What happens to an alias for a peer that was not cloned? → A: The counterpart gets no alias for it, so a call to it by short name fails instead of reaching the source.
- Q: What happens when the aliases cannot be written? → A: The counterpart's restore fails and the clone reports `PARTIAL`.
- Q: Do in-place restores and environment restores change? → A: No.
- Q: Are clones made before the fix repaired? → A: No. No Styrmin installation ran before this change.
- Q: Which E2E tests cover the fix? → A: Existing test nodes, with no new node: `test_environment_clone_lifecycle` and `test_environment_backup_and_restore_lifecycle`. The alias check written for spec 029 (commit `472fe403`, FR-016 of #518) moves into this change.

### Session 2026-10-18 (autonomous, while writing this spec)

These answers were not in the PRD. They are flagged for the maintainer to confirm.

- Q: `develop` moved from `5444f0e6` to `f4e60189` after the PRD was written, with the fix for #503. Does the fix use the alias step of #503? → A: Yes. The cross-target restore runs the same step "Create and delete service aliases" as the create, update and upgrade flows. That step reads the other deployments' services from the server when it runs, so the counterpart whose restore ends last writes the aliases in both directions between it and each counterpart whose restore ended before.
- Q: FR-002 of the PRD says "whatever that deployment's state". Since #503, the alias step skips a peer whose namespace is missing or terminating. Does the fix change that rule for a clone? → A: No. A counterpart whose namespace is missing or terminating when another counterpart's alias step runs gets its aliases from its own alias step, at the end of its own restore, or from its next create, update or upgrade flow. A counterpart whose restore failed and whose namespace exists gets the aliases like any other deployment of the environment. SC-001 counts only deployments whose namespace exists when the clone ends.
- Q: The PRD asks that the clone report the counterpart's entry as failed, with the reason given, when its restore fails (user story 4, P3, FR-004). Today a counterpart whose restore failed keeps the entry outcome `cloned`: the clone's status counts the failed restore, but the entry does not show it ([`services/backup/clone.py`](../../backend/styrmin_backend/services/backup/clone.py), `derive_environment_clone_status`; [`environment_clone.py`](../../backend/styrmin_backend/api/definitions/backup/environment_clone.py)). Does the fix change this? → A: Yes. The clone record reports the entry of a counterpart whose restore failed as `failed`, with the restore's error as the reason. This applies to any failed counterpart restore, because an alias write failure is reported as a restore failure. It changes what the existing fields return, not the GraphQL schema.
- Q: `develop` now has a "Service alias" entry in `CONTEXT.md` (#503). The PRD says the fix adds one. → A: The fix extends that entry with what a clone does with aliases.

### Session 2026-10-18 (critique, [critique-20261018-1.md](critiques/critique-20261018-1.md))

- Q: Does the counterpart stay `FAILED` after its alias step failed? → A: No. The plan first marked the counterpart's StyrminDeployment failed. The operator's rollout of the recovered spec can run after that write and replace the failed status, and the status reporter then reports `RUNNING` (critique E1). The restore still sets the counterpart to `FAILED`, as any failed restore does, and its status then follows its workloads. The signals that last are the restore, `FAILED` with the error and the failed step, and the clone, `PARTIAL` with the entry `failed` and the reason (FR-004, FR-007).
- Q: Does FR-007 apply to a restore that failed for a cause other than the alias step? → A: Yes, for one rule across causes. It stays flagged for the maintainer (critique P1).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Clone every deployment, and each counterpart reaches the other counterparts (Priority: P1)

An admin clones an environment with all its deployments. Each counterpart reaches the other counterparts by short service name, so the clone works like the source.

**Why this priority**: This is the defect of #530. A clone whose applications call the source can read or write the source's data, which the user documentation says cannot happen.

**Independent Test**: In an environment with deployments A and B, each with an alias for the other's services, clone the environment with A and B selected. When the clone reports `COMPLETED`, list the alias Services in A's counterpart namespace and in B's.

**Acceptance Scenarios**:

1. **Given** an environment with deployments A and B, each with an alias for the other's services, **When** the admin clones it with A and B selected and the clone reports `COMPLETED`, **Then** A's counterpart namespace has one alias for each of B's services, pointing to B's counterpart namespace, and no other alias.
2. **Given** the same clone, **When** the admin lists the aliases in B's counterpart namespace, **Then** it has one alias for each of A's services, pointing to A's counterpart namespace, and no other alias.
3. **Given** the same clone, **When** the admin views a counterpart's restore, **Then** its steps include "Create and delete service aliases", after "Run the recovery".

---

### User Story 2 - Clone some deployments, and a peer that was not cloned cannot be reached (Priority: P2)

An admin clones an environment with only some of its deployments. No counterpart reaches a deployment of the source environment, during or after the clone, so work in the clone cannot change the source's data.

**Why this priority**: It is the same defect for a partial clone, where the restored alias for a peer that was not cloned has no counterpart to point to.

**Independent Test**: In the same environment, clone it with only A selected, and list the aliases in A's counterpart namespace while the clone runs and after it ends.

**Acceptance Scenarios**:

1. **Given** an environment with deployments A and B, **When** the admin clones it with only A selected and the clone reports `COMPLETED`, **Then** A's counterpart namespace has no alias for B's services, and B is reported `skipped` with the not-selected reason.
2. **Given** the same clone, **When** the restore of A's counterpart runs, **Then** at no time does A's counterpart namespace hold an alias that points to a namespace of the source environment.

---

### User Story 3 - The aliases cannot be written, and the clone reports it (Priority: P3)

The alias write of one counterpart fails. The admin views the failure on the clone and repairs the counterpart by updating or redeploying it, without cloning again.

**Why this priority**: A counterpart without its aliases does not work like the source. The admin has to know that, and has to be able to repair it.

**Independent Test**: In a unit test, make the Kubernetes API refuse the alias write of a counterpart's restore, and check the restore's status, its steps and the clone's entry.

**Acceptance Scenarios**:

1. **Given** a clone in progress, **When** the Kubernetes API refuses the alias write of counterpart A, **Then** A's restore fails with the error, and its step "Create and delete service aliases" records the error.
2. **Given** that failure and another counterpart whose restore completed, **When** the admin views the clone, **Then** the clone reports `PARTIAL`, A's entry is `failed`, and its reason gives the restore's error.
3. **Given** that failure, **When** the admin lists the aliases in A's counterpart namespace, **Then** no alias points to a namespace of the source environment.
4. **Given** a counterpart whose alias step failed, **When** the admin updates or redeploys it, **Then** its flow writes its aliases and the aliases of its services in the other counterparts' namespaces.

---

### User Story 4 - Restores of a deployment or of an environment keep their aliases (Priority: P3)

An admin restores a deployment or an environment. Each restored namespace keeps the aliases it has today, so this change does not break restores.

**Why this priority**: The change targets the cross-target restore only. An in-place restore that lost its aliases would cut the restored application off from its peers.

**Independent Test**: After an environment restore, list the aliases in the primary deployment's namespace.

**Acceptance Scenarios**:

1. **Given** an environment with deployments A and B, each with an alias for the other's services, **When** the admin restores the environment and the restore completes, **Then** A's namespace still holds its alias for each of B's services.
2. **Given** a deployment, **When** the admin restores one of its backups into it, **Then** the restore writes back the same aliases as before the change, and adds no step "Create and delete service aliases".

### Edge Cases

- A counterpart whose restore failed for another reason: when its namespace exists, the other counterparts still get aliases for its services, pointing to its namespace in the clone. When its namespace is missing, they get them from its next create, update or upgrade flow, as for any deployment since #503 (ADR-077, ADR-078).
- Counterpart A's restore ends before counterpart B is created: A has no alias for B until B's alias step runs, and that step writes the aliases in both directions. The clone creates counterparts one at a time and dispatches each restore at once ([`clone.py`](../../backend/styrmin_backend/workflows/templates/clone.py), `_run_environment_clone`).
- An alias that B's step writes into A's namespace is lost if A's restore deletes its namespace after that write. From the code, this can happen only if A's restore flow waits in the queue longer than B's whole restore. SC-001 detects it.
- A peer's alias step writes into a counterpart's namespace while Velero restores it: the restore no longer writes aliases, so it does not replace the alias that the peer wrote.
- A clone of a clone: the same rule applies. The source's aliases point to its own environment and are not restored.
- Internal deployments of the new environment, such as its ingress controller: they get aliases like any deployment of the environment that has recorded services.
- A counterpart whose alias step failed: its workloads run, so its status follows its StyrminDeployment and can read `RUNNING` a few seconds after the restore failed. The failed restore and the clone entry give the failure, and the user documentation says so.
- The server's list of the environment's services cannot be read during the alias step: the step uses the services that the counterpart's context lists, as the create, update and upgrade flows do since #503 (ADR-078). That list holds the counterparts created before this one.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST never write into a counterpart's namespace an alias that points to a namespace of the source environment, including during the restore. Until the correct alias exists, a call by short service name fails.
- **FR-002**: System MUST, after a cross-target restore's recovery step, write into the counterpart's namespace one alias for each service of every other deployment of the new environment that has recorded services, whatever that deployment's state, and into those deployments' namespaces one alias for each of the counterpart's services. The rule of #503 that skips a namespace that is missing or terminating, or whose deployment is being deleted, still applies (ADR-077).
- **FR-003**: System MUST NOT write an alias for a source deployment that has no counterpart (not selected, skipped, or never created).
- **FR-004**: System MUST, when the alias write fails, fail the counterpart's restore with the error, record the error on the step "Create and delete service aliases", and report the clone as `PARTIAL`, or `FAILED` when no other counterpart succeeded, with the counterpart's entry set to `failed` and the restore's error as the reason. The restore sets the counterpart to `FAILED`, as any failed restore does. Its status then follows its StyrminDeployment, whose workloads run, so it can read `RUNNING` again.
- **FR-005**: Users MUST be able to repair a counterpart whose alias step failed by updating or redeploying it. A failed restore sets the deployment to `FAILED` ([`workflows/templates/backup.py`](../../backend/styrmin_backend/workflows/templates/backup.py), `_set_deployment_status_failed`). Whether every update and redeploy path accepts a `FAILED` counterpart is not verified yet; the planning step checks it.
- **FR-006**: System MUST leave an in-place restore and an environment restore writing back the same aliases as today, with no step "Create and delete service aliases".
- **FR-007**: The clone record MUST report the entry of a counterpart whose restore failed as `failed`, with the restore's error as the reason, for any cause of the restore failure. The clone's status does not change: it already counts such a restore as a failure.

### Key Entities

All entities exist already; no new entity is needed.

- **Environment clone**: its counterparts now get the new environment's service aliases. An entry whose restore failed now reads `failed`.
- **Counterpart deployment**: its namespace holds only aliases that point to deployments of the new environment.
- **Cross-target restore**: no longer writes back service aliases, and gains the step "Create and delete service aliases", which already exists for the create, update and upgrade flows ([`steps.py`](../../backend/styrmin_backend/domain/steps.py), `SERVICE_ALIASES`).
- **Service alias**: defined in [`CONTEXT.md`](../../CONTEXT.md) since #503. The fix adds what a clone does with aliases.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: When a clone reports `COMPLETED` or `PARTIAL`, each counterpart's namespace holds exactly one alias for each service of every other deployment of the new environment that has recorded services and a namespace, each pointing to that deployment's namespace, and no other alias. Checked in both E2E variants.
- **SC-002**: In a clone of some of the deployments, no alias in the new environment names a namespace of the source environment. Checked in both E2E variants.
- **SC-003**: After an environment restore, each restored namespace still holds its alias for each service of the environment's other deployments. Checked in both E2E variants.
- **SC-004**: When the alias write of a counterpart's restore fails, the restore is `FAILED`, its step "Create and delete service aliases" is failed with the error, and the clone's entry for the counterpart is `failed` with that error as the reason. Checked in unit tests.

## Testing Decisions

- A good test here checks which aliases are in which namespace after a clone or a restore, not how the restore request is built.
- Unit tests, agreed with the maintainer:
  - Cross-target restore request: a cross-target request leaves out the aliases, and an in-place request is unchanged.
  - Alias computation for the counterpart: covers a cloned peer and a failed counterpart, and includes no source namespace and no peer without a counterpart.
  - Alias step in the restore: a failed alias write fails the restore and records the failed step.
- Unit test added by this spec: the clone entry of a counterpart whose restore failed reads `failed` with the restore's error as the reason, through the GraphQL resolver (FR-007).
- Integration tests: none needed. There is no GraphQL schema change.
- E2E scenarios, in existing test nodes, with no new node:
  - [`test_environment_clone_lifecycle`](../../backend/tests/e2e/test_backup_restore.py): the first clone, which selects the primary and the peer, checks SC-001. The re-clone at the end selects only the primary instead of no deployment, and checks SC-002. The peer is still `SKIPPED` with the not-selected reason. The alias check written for spec 029 (commit `472fe403`, FR-016 of #518) moves into this change; it is on branch `fac/demo-beta-presentation-bhshh`, which is not pushed.
  - [`test_environment_backup_and_restore_lifecycle`](../../backend/tests/e2e/test_backup_restore.py): after the environment restore, checks SC-003 on the primary's namespace.
- Prior art: [`test_service_aliases.py`](../../backend/tests/unit/agent/test_service_aliases.py), [`test_backup_builders.py`](../../backend/tests/unit/agent/test_backup_builders.py), [`test_restore_steps.py`](../../backend/tests/unit/workflows/test_restore_steps.py).

## Documentation

The change ships with:

- a paragraph in [`backups-and-restores.md`, "Choosing which deployments come along"](../../docs/docs/concepts-and-architecture/backups-and-restores.md): an application in the clone reaches the clone's other deployments by short service name, and a deployment that was not cloned cannot be reached by short service name from the clone;
- in the same page, "Watching a clone, and what its status means": a deployment whose restore failed is reported `failed` with the restore's error; a counterpart whose alias step failed can read `Running`, because its workloads run; the admin repairs it with a change to its configuration or parameters, or an upgrade;
- a dated amendment to ADR-056 that records the alias decision and its reason;
- the extension of the `CONTEXT.md` entry "Service alias";
- the changelog fragment `changelog/530.fixed.md`, which names both changes: the clone's aliases, and the clone entry of a failed restore.

## Governance Gates

From the "Ask first" list in [`AGENTS.md`](../../AGENTS.md):

- Database schema or migration change: none.
- GraphQL schema change: none. FR-007 changes what the existing fields `outcome` and `reason` of a clone entry return, not the schema.
- New dependency: none.
- CI/CD workflow change: none. The re-clone adds one counterpart restore, a few minutes per variant, to the `shard_env_backup` shard.
- Authentication or authorization change: none.
- Skipping E2E coverage: not skipped.
- Shipping without documentation: not skipped.

## Assumptions

- No Styrmin installation was running before this change, so no clone made before the fix needs to be repaired.
- Counterparts are created through `deploy_application` ([`clone.py`](../../backend/styrmin_backend/workflows/templates/clone.py), `_create_counterpart`), so the server records the new environment's services. Only the alias Services in the cluster are wrong today.
- The flow that runs the cross-target restore in the cluster has an action token ([ADR-059](../../dev/adr/0059-driver-action-api-tokens.md)), so its alias step can read the environment's services from the server as the create, update and upgrade flows do.

## Out of Scope

- Repairing clones made before the fix. No docs page or changelog text describes them.
- Removing aliases whose owner deployment was deleted ([#526](https://github.com/opsmill/styrmin/issues/526)).
- Changing which aliases an in-place restore or an environment restore writes back.
- Writing aliases after an in-place restore for a peer that changed during the restore. The user documentation of restores describes that case and its recovery (#503).

## Related Work

- [#518](https://github.com/opsmill/styrmin/issues/518): its demo 4 shows that a clone's Semaphore reads the clone's Infrahub, and it waits for this fix.
- [#503](https://github.com/opsmill/styrmin/issues/503) and [#526](https://github.com/opsmill/styrmin/issues/526): aliases that stay after their deployment is deleted.
- [ADR-056](../../dev/adr/0056-environment-clone-record-and-cross-target-restore.md): environment clone record and cross-target restore.
- [ADR-073](../../dev/adr/0073-kubernetes-objects-named-and-found-by-record-id.md): Kubernetes objects are named and found by the record's id; aliases already carry the owner's id.
- [ADR-077](../../dev/adr/0077-alias-flow-reads-deletion-state-at-write-time.md) and [ADR-078](../../dev/adr/0078-alias-step-reads-current-services-from-server.md): the alias step of #503.
