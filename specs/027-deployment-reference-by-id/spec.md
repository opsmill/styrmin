# Feature Specification: Deployment References Stored by Id

**Feature Branch**: `fac/affinity-by-id-zsdtf`

**Created**: 2026-10-16

**Status**: Draft

**Input**: PRD "Deployment references stored by id" — [opsmill/styrmin#508 (comment)](https://github.com/opsmill/styrmin/issues/508#issuecomment-6226052128). Seed issue: [#508](https://github.com/opsmill/styrmin/issues/508). The failure it fixes: [#492](https://github.com/opsmill/styrmin/issues/492). The approach rejected for it: [PR #504](https://github.com/opsmill/styrmin/pull/504).

## Context

An affinity term in the `pod_affinity` or `pod_anti_affinity` block of a `scheduling` config can name another deployment of the same environment with a deployment reference. The reference gives either `deployment_id` or `deployment_name` ([`config.py`](../../backend/styrmin_backend/context/models/config.py), `DeploymentReference`). Terms can be written in three configs: the environment's, the deployment's, and a component's (under the deployment's `components`).

Today Styrmin stores a name as written and looks it up each time it builds an instance for a deployment that the term applies to ([`validator.py`](../../backend/styrmin_backend/services/scheduling/validator.py)). The lookup gives the label selector `styrmin/deployment_id=<id>`. After the named deployment is renamed, the lookup finds no deployment and raises `UnresolvableAffinityReferenceError`. From the code at [66065158](https://github.com/opsmill/styrmin/tree/66065158e678ba77f961ada307673dab39a6597c), as the PRD records:

- Every later update of a deployment whose term names the renamed deployment is refused.
- Every config fan-out redeploy in an environment whose config has such a term fails.
- The rename itself is refused when the environment's config has a term that names the deployment being renamed, because the rename sets the new name before it builds the new instance ([`deployment.py`](../../backend/styrmin_backend/services/deployment.py)).

What the operator views on the deployment that has the term when the error is raised during a fan-out is not known ([#492](https://github.com/opsmill/styrmin/issues/492)).

A second, existing failure is tied to the fix. An environment clone copies the configs of the source deployments and the source environment unchanged ([`clone.py`](../../backend/styrmin_backend/workflows/templates/clone.py)). A term that gives an id therefore names a deployment of the source environment, and the lookup for the clone's counterpart deployment refuses it, because the named deployment is in another environment. After this change every stored term gives an id, so the clone must point the copied terms at the counterparts in the same change.

This feature changes what Styrmin stores:

- An operator can still give a name in a deployment reference when they write a term. Styrmin replaces the name with the id of the deployment that has that name in the same environment, and refuses the write when no deployment has it.
- Reading a config back gives the id.
- A rename changes nothing for the terms that name the renamed deployment. The resolved selector is already `styrmin/deployment_id=<id>`, so no pod restarts.
- An environment clone points each copied term at the clone's counterpart of the named deployment.

[ADR-073](../../dev/adr/0073-kubernetes-objects-named-and-found-by-record-id.md) sets the same rule for the Kubernetes objects of a record: find them by the record's id, never by a name a user can change. PR #504 instead rewrote the name in the environment's terms on every rename. An environment restore then brought back the old name from the backup ([`environment.py`](../../backend/styrmin_backend/services/backup/environment.py)). With ids this does not happen, because a restore creates and deletes no deployment.

Terms that name a deployment are written through GraphQL, the SDK and `styrminctl` manifests. The UI cannot show or edit a deployment reference ([`AffinityTermEditor.tsx`](../../frontend/src/components/deployment/configuration/sections/edit/scheduling/AffinityTermEditor.tsx)). It sends back the reference it read when the configuration form is saved ([`schedulingSanitize.ts`](../../frontend/src/components/deployment/configuration/sections/edit/schedulingSanitize.ts)).

## Clarifications

### Session 2026-10-16 (autonomous, from the PRD)

The PRD's decisions were confirmed one at a time by the author of [#508](https://github.com/opsmill/styrmin/issues/508). The two "What is not known" points of #508 are answered here so later phases do not reopen them.

- Q: How do the UI and `styrminctl` show a term that gives an id? → A: They show the id, as they show any stored value today. Showing which deployment a term names, next to the id, is out of scope and goes into a follow-up issue. The UI does not change.
- Q: What happens when a term names a deployment that does not exist yet, for example a `deployments apply` that creates the named deployment after the deployment that has the term? → A: The write is refused (FR-002). In `deployments apply`, the order of manifests matters for terms in a deployment's config, as it does today. Making `apply` resolve terms after the whole batch is out of scope.
- Q: What does a term that names a tombstoned deployment do? → A: It is refused with `UnresolvableAffinityReferenceError`, and the error gives the deployment's last name (FR-004). Today such a term resolves and gives a selector that matches no pod.
- Q: What does an environment restore do with a term that names a deployment deleted since the backup? → A: The restore puts back the captured config unchanged and succeeds. The term fails at the next reconcile (FR-006).
- Q: Does the change need a data migration for configs or backups stored with names? → A: No. No Styrmin is running yet, so no stored config or backup gives a name. Upgrading existing installations is out of scope.
- Q: Does `createEnvironment` accept a term that names a deployment? → A: No. A new environment has no deployment yet, so every such term names a missing deployment and is refused.
- Q: Which E2E tests cover the change? → A: Two existing tests are extended, and no new heavy test is added: `test_pod_anti_affinity_cross_deployment_via_graphql` (`shard_compute`, `api_only`) and `test_environment_clone_lifecycle` (`shard_env_backup`). The planning phase decides whether `test_environment_clone_lifecycle` already clones two deployments or needs a second one.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Rename a deployment that affinity terms name (Priority: P1)

An operator renames deployment A. The terms that name A, in the environment's config, in a deployment's config or in a component's config, keep placing pods relative to A. Every later update of the other deployments and every config fan-out redeploy succeeds, and the rename restarts no pod of the deployments whose terms name A.

**Why this priority**: This is the failure reported in [#492](https://github.com/opsmill/styrmin/issues/492). Today a rename blocks every later update of the deployments whose terms name the renamed deployment, and can block the rename itself.

**Independent Test**: Write a term with `deployment_name: A` in B's config and in E's config, rename A, then update B and E. Every write succeeds and B's resolved scheduling still selects `styrmin/deployment_id=<A's id>`.

**Acceptance Scenarios**:

1. **Given** deployments A and B in environment E, a pod affinity term in B's config written with `deployment_name: A`, and a pod anti-affinity term in E's config written with `deployment_name: A`, **When** the operator renames A to A2 with `updateDeployment`, **Then** the rename succeeds.
2. **Given** the state after scenario 1, **When** the operator runs `updateDeployment` on B, **Then** the update succeeds.
3. **Given** the state after scenario 1, **When** the operator runs `updateEnvironment` on E with a changed config, **Then** the config fan-out redeploys every deployment and no redeploy fails.
4. **Given** the state after scenario 1, **When** the operator reads B's `resolvedScheduling`, **Then** it still gives `styrmin/deployment_id=<A's id>`.
5. **Given** the state before scenario 1 with B's pods running, **When** A is renamed, **Then** no pod of B restarts.

---

### User Story 2 - Give a name when writing a term (Priority: P1)

An operator writes a manifest or a GraphQL request whose terms name deployments by name, so they do not have to look up ids. Styrmin stores the id of the named deployment, and a read of the config gives the id.

**Why this priority**: Operators write manifests by hand. Requiring ids would make every manifest depend on values that differ in each environment.

**Independent Test**: Write `deployment_name: A` in the environment's, a deployment's and a component's config, read each config back, and get `deployment_id: <A's id>`.

**Acceptance Scenarios**:

1. **Given** deployment A in environment E, **When** the operator writes a term with `deployment_name: A` in E's config with `updateEnvironment`, **Then** reading E's config gives the term with `deployment_id: <A's id>` and no `deployment_name`.
2. **Given** deployment A in E, **When** the operator writes the same term in B's config or in a component's config of B with `deploy`, `updateDeployment` or `updateDeploymentVersion`, **Then** reading B's config gives `deployment_id: <A's id>`.
3. **Given** a new deployment A whose own config has a term that names A, **When** the operator runs `deploy` for A, **Then** the stored term gives A's new id.
4. **Given** a request that renames B to B2 and adds a term in B's config that names B2, **When** the request is applied, **Then** the term resolves against the new name and stores B's id.

---

### User Story 3 - A term that names a missing deployment is refused when written (Priority: P1)

An operator writes a term that names a deployment that is not in the environment, by a wrong name, by an id of another environment, or by the id of a tombstoned deployment. The write is refused when the operator makes it, the error gives the term's path and the deployment it names, and nothing is saved.

**Why this priority**: After this change a name is looked up only at write time, so the write is the only point at which a wrong name can be reported. Today a term in an environment's config is not looked up until a reconcile.

**Independent Test**: Run `updateEnvironment` with a term that names a missing deployment, get `UnresolvableAffinityReferenceError` with the term's path, and read the environment's config unchanged.

**Acceptance Scenarios**:

1. **Given** environment E with no deployment named X, **When** the operator runs `updateEnvironment` with a term that gives `deployment_name: X`, **Then** the request is refused with `UnresolvableAffinityReferenceError`, the error gives the term's path and `X`, and E's config is unchanged.
2. **Given** the same E, **When** the operator runs `createEnvironment` with a term that names any deployment, **Then** the request is refused, because the new environment has no deployment.
3. **Given** the same E, **When** the operator runs `updateDeployment` on B with a term that names X, **Then** the request is refused with the term's path and `X`, and B's config is unchanged.
4. **Given** a term that gives the id of a deployment of another environment, **When** it is written at any level, **Then** the write is refused with the term's path and the id.

---

### User Story 4 - Delete and re-create a named deployment (Priority: P2)

An operator deletes deployment A and creates a new deployment with the same name, for example to change its driver, which `deployments apply` can do only by delete and re-create. The terms that named A keep the old id. Each later update or redeploy of a deployment that the terms apply to is refused with an error that gives the term's path and A's last name, so the operator knows which terms to write again. Re-applying the unchanged manifest whose terms give the name is enough, because the name now resolves to the new id.

**Why this priority**: A deleted deployment's id is never reused, so the terms cannot follow the new deployment on their own. The error must say which deployment is gone, because the stored config shows only an id.

**Independent Test**: Delete A, update B, and get an error that gives the term's path and A's last name.

**Acceptance Scenarios**:

1. **Given** a term in B's config that names A, **When** A is deleted and the operator runs `updateDeployment` on B, **Then** the update is refused with `UnresolvableAffinityReferenceError`, and the error gives the term's path and A's last name.
2. **Given** a term in E's config that names A, **When** A is deleted and a config fan-out redeploys B, **Then** B's redeploy fails with the same error.
3. **Given** the state after scenario 1 and a new deployment named A, **When** the operator re-applies B's manifest whose term gives `deployment_name: A`, **Then** the write succeeds and the stored term gives the new A's id.

---

### User Story 5 - An environment clone points the copied terms at the counterparts (Priority: P1)

An operator clones an environment whose terms name its deployments. Each term in the new environment, in the environment's config, a counterpart's config or a counterpart's component config, names the counterpart deployment, not the source deployment. The clone's pods are placed relative to each other and not to the source environment's pods.

**Why this priority**: This ships in the same change as User Story 1. After the change every term gives an id, so without it every clone of an environment whose terms name its deployments would fail for those counterparts. This already happens today to terms saved with `deployment_id`.

**Independent Test**: Clone E with A and B selected, where B's config and E's config name A, and read the configs in E2.

**Acceptance Scenarios**:

1. **Given** environment E with deployments A and B, a term in B's config that names A, and a term in E's config that names A, **When** the operator clones E into E2 and selects A and B, **Then** both counterparts are attributed `cloned`, whether B's snapshot comes before or after A's.
2. **Given** the clone of scenario 1, **When** the operator reads the configs of E2 and of B's counterpart, **Then** the terms give the id of A's counterpart, and no term in E2 gives an id of a deployment in E.
3. **Given** A's config names B and B's config names A, **When** the operator clones E with A and B selected, **Then** the clone ends `COMPLETED` and each counterpart's term gives the other counterpart's id.

---

### User Story 6 - A clone request that leaves out a named deployment is refused (Priority: P2)

An operator requests a clone whose selection leaves out a deployment that a term names. The request is refused before the clone starts, and the error lists each left-out deployment and the path of each term that names it, so the operator can change the selection or the config.

**Why this priority**: A clone with a left-out named deployment would create counterparts whose terms cannot resolve in the new environment. Refusing at request time avoids a clone that ends with failed counterparts.

**Independent Test**: Clone E with only B selected, where B's config names A, and get the refusal that lists A and the term's path.

**Acceptance Scenarios**:

1. **Given** a term in B's config that names A, **When** the operator requests a clone of E that selects B and not A, **Then** `createEnvironmentClone` is refused with a typed error that lists A and the path of B's term.
2. **Given** a term in E's config that names A, **When** the operator requests a clone that leaves out A, **Then** the request is refused with A and the path of E's term.
3. **Given** scenario 2, **When** the operator clears or replaces E's `scheduling` with `cleared_config_fields` or `config_override` in the same request, **Then** the request is accepted.
4. **Given** a term in B's config that names A, both selected, **When** the capture of A fails during the clone, **Then** B's counterpart is attributed `failed` with a reason that names A, and the clone ends `PARTIAL`.
5. **Given** a term in E's config that names A, A selected, **When** the capture of A fails, **Then** the clone is attributed `FAILED`.

---

### User Story 7 - Restore an environment backup with a term that names a deleted deployment (Priority: P3)

An operator restores an environment backup after a deployment that a term names was deleted. The restore succeeds, so one term does not block a recovery. The term fails at the next reconcile with the error of User Story 4.

**Why this priority**: A recovery must not be blocked by a scheduling term. The term is reported at the next reconcile, where the operator can fix it.

**Independent Test**: Back up E, delete A, and restore E. The restore succeeds, and B's next update fails with an error that gives A's last name.

**Acceptance Scenarios**:

1. **Given** an environment backup of E whose captured config has a term that names A, **When** A is deleted and the operator restores the backup, **Then** the restore succeeds and E's config is the captured config, unchanged.
2. **Given** the state after scenario 1, **When** the operator updates B, **Then** the update is refused with the term's path and A's last name.

---

### User Story 8 - Re-apply an unchanged manifest without a reconcile (Priority: P2)

An operator re-applies an unchanged manifest whose terms give names, or writes back a config exactly as it was read. Styrmin accepts the write and starts no reconcile.

**Why this priority**: The no-op detection of [ADR-054](../../dev/adr/0054-backend-authoritative-noop-detection.md) compares the request to the stored config. A request with a name and a stored config with an id must compare as equal, or every `apply` of an unchanged manifest would start a redeploy. The UI's configuration form sends back the reference it read, so writing back a read config is the UI's normal save.

**Independent Test**: Read B's config, write it back with `updateDeployment`, and get a null `Task`. Re-apply B's manifest that gives `deployment_name: A` and get no reconcile.

**Acceptance Scenarios**:

1. **Given** B's stored config with a term that gives `deployment_id: <A's id>`, **When** the operator writes back the config exactly as it was read, **Then** the write is accepted and returns a null `Task`.
2. **Given** the same B, **When** the operator re-applies B's manifest whose term gives `deployment_name: A`, **Then** the write is accepted and starts no reconcile.

### Edge Cases

- The named deployment is deleted and re-created with the same name: the terms keep the old id and fail with the error of FR-004. The operator writes the terms again with the name (User Story 4).
- The named deployment is left out of a clone's selection: the request is refused (FR-005). The capture of the named deployment fails during the clone: the counterpart that names it is attributed `failed`.
- Two deployments name each other and are cloned together: the clone creates every counterpart record before it resolves any term (FR-008). Today the clone creates and builds one counterpart at a time, in the order of the snapshots ([`clone.py`](../../backend/styrmin_backend/workflows/templates/clone.py)), so mutual terms would fail in every order.
- A restored environment backup names a deployment deleted since the backup: the restore succeeds, and the term fails at the next reconcile (FR-006).
- A term names the deployment that carries it, or a request renames the deployment and changes its terms: the names resolve after the request's own changes (FR-007).
- In `deployments apply`, B's manifest comes before the manifest of A, which B names: B is refused, as today.
- A term names a deployment in the `DELETING` state: the deployment is not tombstoned yet, so the write is accepted. Once it is tombstoned, the term fails as in FR-004.
- A node affinity term: it has no deployment reference and passes through unchanged, as today.
- A term with a `label_selector` instead of a deployment reference: it is stored and resolved unchanged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When a term gives a name, Styrmin MUST store the id of the non-tombstoned deployment in the same environment that has that name at the time of the write. This applies to the environment's, the deployment's and the component's config, in `deploy`, `updateDeployment`, `updateDeploymentVersion`, `createEnvironment` and `updateEnvironment`.
  - Verify: write `deployment_name: A` at each level, read the config back, and get `deployment_id: <A's id>`.
- **FR-002**: Styrmin MUST refuse a write in which a term names, by name or by id, a deployment that is not a non-tombstoned deployment of the same environment. The write returns `UnresolvableAffinityReferenceError` with the term's path and saves nothing.
  - Today, terms in a deployment's or a component's config are already looked up during the request.
  - For an environment's config, the refusal is new. Today `createEnvironment` and `updateEnvironment` check only the shape of the config ([`environments.py`](../../backend/styrmin_backend/services/environments.py)). After the change, `createEnvironment` cannot accept a term that names a deployment, because the environment has no deployment yet.
  - Verify: `updateEnvironment` with a term that names a missing deployment is refused, and the environment's config is unchanged.
- **FR-003**: Every stored deployment reference MUST give an id, never a name. Styrmin looks up a name only during a write.
  - Verify: after writes with names at all three levels, no stored config holds `deployment_name`.
- **FR-004**: When a term gives the id of a tombstoned deployment, Styrmin MUST refuse with `UnresolvableAffinityReferenceError` and give the term's path and the deployment's last name.
  - Today such a term resolves without an error, because the lookup by id also returns tombstoned deployments ([`repository/deployment.py`](../../backend/styrmin_backend/repository/deployment.py)). The term then gives a selector that matches no pod.
  - Verify: delete A, update B, and get an error that gives A's last name.
- **FR-005**: `createEnvironmentClone` MUST refuse a selection that leaves out a deployment named by a term in the source environment's config or in a selected deployment's config, including its components' configs. The error lists each left-out deployment and the path of each term that names it.
  - The operator can add the named deployment to the selection, leave out the deployment whose term names it, or, for a term in the environment's config, clear or replace `scheduling` with `cleared_config_fields` or `config_override` ([`services/backup/clone.py`](../../backend/styrmin_backend/services/backup/clone.py)).
  - When the capture of a named deployment fails, the counterpart whose term names it is attributed `failed` with a reason that names the deployment, and the clone ends `PARTIAL`. When a term in the environment's config names that deployment, the clone is attributed `FAILED`.
  - Verify: clone E with only B selected, and get the refusal.
- **FR-006**: Restoring an environment backup MUST put back the captured environment config unchanged, as it does today. A term that names a deployment deleted since the backup does not make the restore fail. It fails at the next reconcile with the error of FR-004.
  - Verify: back up E, delete A, and restore E. The restore succeeds, and B's next update fails with an error that gives A's last name.
- **FR-007**: In `deploy`, `updateDeployment` and `updateDeploymentVersion`, Styrmin MUST resolve the names in the request's terms after it applies the request's own changes:
  - a term in a new deployment's config that names that deployment stores the new deployment's id
  - a term in a renaming request resolves against the new name
  - Verify: `deploy` A with a term that names A, and the stored term gives A's id.
- **FR-008**: An environment clone MUST replace each id of a source deployment in the copied terms, in the environment's, the counterparts' and their components' configs, with the id of that deployment's counterpart, whatever the order in which the snapshots come. This includes terms that name each other (A names B and B names A).
  - Verify: run the User Story 5 scenario with A's snapshot before B's and after B's, and with mutual terms.
- **FR-009**: Reading a config MUST return each term with the stored id. Writing back a config exactly as it was read MUST be accepted and MUST start no reconcile ([ADR-054](../../dev/adr/0054-backend-authoritative-noop-detection.md)). Re-applying an unchanged request whose terms give names MUST also start no reconcile.
  - Verify: read B's config, write it back with `updateDeployment`, and get a null `Task`.
- **FR-010**: A rename MUST NOT change any stored term and MUST NOT change the resolved selector of any term that names the renamed deployment, so no pod of the deployments that carry those terms restarts.
  - Verify: rename A, then read B's stored config and resolved scheduling, both unchanged.
- **FR-011**: The descriptions of the GraphQL deployment reference input MUST say that a name is replaced with the id of the named deployment when the config is written. `schema.graphql` and the SDK types are regenerated. No GraphQL field is added or removed.
- **FR-012**: Documentation MUST be updated in the same change (Constitution §VII):
  - [`dev/guides/pod-scheduling.md`](../../dev/guides/pod-scheduling.md), section on `deployment_ref`
  - two new [`CONTEXT.md`](../../CONTEXT.md) entries: affinity term and deployment reference
  - changelog fragments `492.fixed.md` and `508.changed.md`
  - a short ADR, "Deployment references stored by id", related to ADR-073, that records the alternative rejected in PR #504 and the effect on delete and re-create

### Key Entities *(include if feature involves data)*

No new entity and no column change. `CONTEXT.md` has no entry for the first two concepts, so the change adds both.

- **Affinity term** (existing, `AffinityTerm`): one entry in the `required` or `preferred` list of a `pod_affinity`, `pod_anti_affinity` or `node_affinity` block. It selects pods or nodes by a `label_selector`, or, for pod affinity and pod anti-affinity, by a deployment reference. #492 and #508 say "affinity rule". The code and the [node affinity page](../../docs/docs/concepts-and-architecture/node-affinity.md) say "term".
- **Deployment reference** (existing, `DeploymentReference`): stores an id only after the change. A name is accepted on write and replaced with the id. It can narrow the selector to some of the named deployment's components.
- **Deployment, environment, environment clone, counterpart deployment, environment backup and tombstoned deployment**: unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After a deployment is renamed, 100% of later updates and config fan-out redeploys of the deployments whose terms name it succeed.
- **SC-002**: A rename restarts 0 pods of the deployments whose terms name the renamed deployment.
- **SC-003**: A clone with every named deployment selected ends `COMPLETED` in every order of snapshots, including mutual terms. 0 terms in the new environment name a deployment of the source environment.
- **SC-004**: Re-applying an unchanged manifest whose terms give names starts 0 reconciles. Writing back a config exactly as it was read starts 0 reconciles.
- **SC-005**: Every refusal caused by a term gives the term's path and the deployment it names, so the operator can find the term without reading the stored config.
- **SC-006**: 0 stored configs hold `deployment_name` after any write.

## Assumptions

- No Styrmin is running yet, so no stored config or backup gives a name. No data migration is needed.
- A deployment's id never changes and is never reused.
- Only pod affinity and pod anti-affinity terms use a deployment reference. The resolver passes node affinity terms through unchanged, as today.
- The order of manifests in `deployments apply` matters for terms in a deployment's config, as today.
- The frontend does not change. The configuration form already sends back the reference it read.
- No new SDK method or `styrminctl` command is needed.
- A clone still needs the `ADMIN` role.
- The name and error code of the new typed error for a clone selection that leaves out a named deployment are not decided. The planning phase picks them.

## Out of Scope

- Showing which deployment a term names, next to the id. This goes into a follow-up issue.
- Writing or showing deployment references in the UI.
- A public documentation page for pod affinity by deployment reference. No page under `docs/docs/` describes deployment references today, so no public page becomes wrong.
- Terms that name a deployment in another environment.
- Pointing terms at a new deployment that reuses a deleted deployment's name.
- Upgrading existing installations: a data migration, or names in older backups.
- Making `deployments apply` resolve terms after the whole batch, so that the order of manifests would not matter.
