# Research: Deployment References Stored by Id

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-16

All code references are to the worktree at `66065158` plus this branch. Paths without a prefix are under `backend/styrmin_backend/`.

## R-001: Where each write path can replace a name with an id

**Decision**: one binding function runs on every config a write stores, at these points:

| Write | Today | Binding point |
| --- | --- | --- |
| `deploy` (`deploy_application`, `services/deployment.py` L1420-1755) | config validated at L1602; row created at L1671-1679 and flushed at L1695; instance built at L1714 | after the name is resolved (L1648-1668) and before `Deployment.create`, with the new deployment's id generated first so that a term can name the new deployment (FR-007) |
| `updateDeployment` (`update_deployment`, L535-715) | rename at L609-610 and config at L612-613 in memory; **saved and committed at L655-656 before the instance is built** at L676 | after L613 and before the save at L655, so a refused term saves nothing (FR-002) |
| `updateDeploymentVersion` (`update_deployment_version`, L800-1156) | config validated at L944-969, name at L970-974, components re-copied from the target driver version at L1028-1037, config and name set in memory at L1066-1067, instance built at L1092 | after L974, on the deployment config and on each re-copied component config, before the no-op comparison at L1106-1110 |
| `createEnvironment` (`create_environment`, `services/environments.py` L180-213) | shape check only (L203-208) | after the shape check; the environment has no deployment, so any reference is refused unless the caller passes the deployments it is about to create (the clone flow, R-008) |
| `updateEnvironment` (`update_environment`, L277-408) | shape check only (L348-352), saved at L357-359, then the fan-out | after L352 and before L357 |

The binding function needs to know about the deployment that the same write creates or renames, because the database does not show the change yet at the binding point in all three deployment paths (the new name is committed in `updateDeployment`, flushed in `deploy` and only in memory in `updateDeploymentVersion`). The function takes an "upcoming deployments" mapping of id to name after the write:

- a name that matches an upcoming deployment's name gives that id;
- a name found in the database that belongs to an upcoming deployment under its old name is not a match, because the write renames that deployment;
- an id of an upcoming deployment is accepted without a lookup.

`deploy` passes `{new id: resolved name}`, the two update paths pass `{deployment id: name after the request}`, and the clone flow passes every counterpart it is about to create (R-008).

**Rationale**: one function and one rule for all five writes. Binding before the save in `updateDeployment` is what makes FR-002's "saves nothing" true; today an unresolvable term in that path leaves the config saved, because phase 1 commits before the lookup.

**Alternatives considered**:

- Flush the renamed row before binding and rely on `get_by_name`: works for `deploy` and `updateDeployment` but not for `updateDeploymentVersion`, which saves nothing before L1092, and it would widen the transaction.
- Bind inside `validate_deployment_config` / `validate_environment_config`: these are synchronous Pydantic checks with no unit of work (`context/validators.py` L103-130).

## R-002: Binding works on the stored dict, and its output is canonical

**Decision**: configs are stored as raw snake_case JSON dicts (`db/models.py` L181 and L401). The binding function walks the dict, not the Pydantic model, at these sites:

- `scheduling.pod_affinity.required[i].deployment_ref`
- `scheduling.pod_affinity.preferred[i].term.deployment_ref`
- the same two under `scheduling.pod_anti_affinity`

`node_affinity` terms carry no deployment reference (`services/scheduling/validator.py` L136-158, `context/validators.py` L64-83). Each reference is rewritten to `{"deployment_id": "<lowercase UUID string>"}`, plus `components` when it was given. `deployment_name` is removed. An id given by the operator is rewritten in the canonical string form, so `ABC…` and `abc…` store the same value.

Each error gives the full path of the term in the config that was written: `environment.config.scheduling.pod_affinity.required[0]`, `deployment.config.scheduling.pod_anti_affinity.preferred[1].term`, or `component[<name>].config.scheduling…`. These prefixes are the ones `_extract_scheduling` already uses for `InvalidSchedulingConfigError` (`services/context.py` L330-342, L562-576).

**Rationale**: the stored dict is what the no-op checks compare (R-003), so the binding must produce exactly one stored form for one target. Walking the dict keeps every other key as the operator wrote it.

**Alternatives considered**: validate into `DeploymentConfig`, change the model, and dump it back. Rejected: the dump would also canonicalise every unrelated field, so a write-back of an untouched config could differ from the stored dict, and older dicts would change shape on their next write.

## R-003: No-op detection keeps working because every stored config is bound

**Decision**: no change to the no-op checks. Each one compares stored or in-memory configs that are bound by the same function:

- `_update_is_noop` (`services/deployment.py` L457-492) compares the current and the candidate instance. The instance context holds the raw environment and deployment configs (`context/models/contexts.py` L70, L82) and the component configs (`context/models/components.py` L278). The candidate is built from the bound config, and the current instance was built from a bound config, so a write-back or a re-apply with names gives no diff (FR-009, SC-004).
- `update_deployment_version` compares `(new_name, effective_config, resolved_parameters)` with the stored values at L1106-1110. `effective_config` is replaced with the bound config before that line.
- `_deployment_already_at_config` (`services/environments.py` L103-139) compares the new environment config with the instance's environment config. Both are bound.

**Rationale**: binding at write time makes "same target" and "same stored dict" the same thing, which is what ADR-054 needs.

**Known effect**: an instance built before this change from a config that gives a name would compare as changed. The spec assumes no Styrmin is running yet, so no such instance exists.

## R-004: The reconcile-time resolver reads ids only and refuses a tombstoned deployment

**Decision**: `resolve_deployment_reference` (`services/scheduling/validator.py` L30-79) changes in three ways:

- it looks up ids only. A reference that still gives a name is refused with `UnresolvableAffinityReferenceError`, because no write stores one any more;
- a deployment found by id with `deleted_at` set is refused, and the error gives the deployment's last name and `deleted: true` (FR-004). Today `find` returns tombstoned rows (`repository/deployment.py` L318-330) and the term resolves to a selector that matches no pod;
- an id in the upcoming deployments of the current operation is accepted without a lookup (R-008).

`_populate_component_scheduling` (`services/context.py` L308-364) and the `resolvedScheduling` resolver (`api/definitions/deployment/model.py` L455-523) expand each level's terms before the merge, not after it, with the level prefix in the path. The environment and deployment levels are expanded once, not once per component as today. The merge (`_resolve_scheduling_config`) has no logic specific to `deployment_ref`, so expanding first gives the same merged result; only the path in an error changes, from an index in the merged list to the index in the level's own list (SC-005).

**Rationale**: FR-003 and FR-004. A path into the merged list does not tell the operator which config holds the term.

**Alternatives considered**: keep name lookup at reconcile as a fallback. Rejected: it keeps the #492 failure for any name that reaches storage, and the PRD's design says the resolver reads ids only.

## R-005: A component's terms come from the driver version

**Decision**: operators cannot write a component's scheduling. `ComponentConfigBlock` (`context/models/config.py` L546-585) has no `scheduling` field and forbids extra keys, and GraphQL `ComponentConfigInput` has none either. A component's scheduling comes from the `Component` row, which `deploy` (L1687-1692) and `updateDeploymentVersion` (L1028-1037) copy from the driver version's component definitions (`services/applications.py` L349-357). The binding runs on each copied component config at those two points, with the `component[<name>].config` prefix. No other write changes a `Component.config`; `update_component` changes only `enabled` (`domain/models.py` L130-134).

The spec's "component's config" requirements therefore apply to the configs that a driver version gives its components, bound when a deployment is created or moved to another driver version.

**Rationale**: FR-003 says no stored reference gives a name. A driver term that names a deployment by name would otherwise keep the #492 failure. A driver term that names a missing deployment is refused at `deploy` today (the instance build fails at L1714), so binding it at the same write changes no outcome.

**Alternatives considered**: leave component configs unbound. Rejected for the reason above.

## R-006: What `updateDeployment` saves when a reconcile-time term fails

**Decision**: no change to the two-phase structure of `update_deployment`. Binding runs before phase 1, so a term in the request that names a missing deployment saves nothing (FR-002). A term that was valid when written and fails at reconcile (FR-004, a tombstoned deployment named by the environment's config or by the deployment's own stored config) fails in phase 2, after phase 1 has committed the request's config. That is today's behaviour for every phase-2 failure; the operator gets the error and the deployment keeps its previous active instance.

**Rationale**: changing the phase order is outside this feature and touches every phase-2 failure.

## R-007: The clone request check

**Decision**: `clone_environment` (`services/backup/clone.py` L1203-1444) checks the terms before it creates anything (before L1336). The mutation is `cloneEnvironment` (`api/schema/mutation.py` L1041-1042); the PRD's "createEnvironmentClone" is corrected in the spec. The check:

1. Binds the terms in `config_override` against the source environment, so a name in the override becomes the source deployment's id, and a name that matches no deployment is refused with `UnresolvableAffinityReferenceError` and a `config_override.scheduling…` path. The override can carry terms because it is an `UpdateEnvironmentInput` (`api/definitions/environment/inputs.py` L35). The bound override is the one stored on the clone record.
2. Builds the new environment's config the way the flow will, with `merge_environment_config(source.config, bound override, cleared fields)` (`services/backup/clone.py` L283-356). The capture records `source.config` and each `deployment.config` in the same transaction (`services/backup/environment.py` L320, L503), so the check reads exactly what the flow will copy.
3. Takes the deployments the clone will copy: the entries that `_plan_deployment_results` (L1143-1200) leaves `PENDING`. A deployment that is selected but skipped (no active instance, internal, tombstoned) is not copied.
4. Collects every id named by a term in the merged environment config, in each copied deployment's config, and in each copied deployment's `Component` rows.
5. Refuses with the new `UnclonedDeploymentReferenceError` when any named id is not a copied deployment. The error lists each such deployment (id, name, or last name when tombstoned) and the path of every term that names it.

**Rationale**: FR-005. Every input of the check is known at request time, so the operator learns about the problem before a backup is taken.

**Alternatives considered**: check only in the flow. Rejected: the capture would already have run, and the operator would get a `FAILED` clone instead of a refused request.

## R-008: The clone flow gives counterparts their ids before it creates them

**Decision**: the flow (`workflows/templates/clone.py`, `_run_environment_clone` L696-822) changes as follows:

1. **Cascade capture failures, before anything is created.** After `_classify_captured_constituents`, a usable snapshot whose config names a deployment whose capture failed is attributed `failed`, with the new reason "an affinity term names deployment <name>, which was not cloned". This repeats until no new snapshot fails. When the merged environment config names such a deployment, the flow writes a fatal clone error with the new step `referenced_deployment_not_cloned`, fails the pending entries, and creates no environment (FR-005).
2. **Give each remaining counterpart an id.** The flow generates one UUID per remaining snapshot, keyed by the source deployment id.
3. **Replace source ids with counterpart ids.** A function without side effects rewrites every `deployment_id` in the merged environment config and in each snapshot config with the mapping (FR-008). An id with no entry in the mapping is reported; after steps 1 and R-007 it can only come from a defect, and the flow then treats it like a failed named deployment.
4. **Create the environment** with the rewritten config and the counterparts as upcoming deployments, so `create_environment` accepts terms that name them.
5. **Create the counterparts in order.** Counterparts named by the environment's config come first; the rest follow so that each comes after the counterparts its terms name; a cycle keeps the order of the source deployment names. Each `deploy_application` call gets its counterpart's id, the rewritten config and every counterpart as upcoming deployments. The binding accepts the peers' ids, a driver component term that gives a name resolves to the counterpart with that name, and the reconcile-time resolver accepts the peers' ids (R-004), so the order of creation does not decide whether a term resolves (FR-008, SC-003).
6. **Cascade creation failures.** Before a counterpart is created, the flow fails it when one of its terms names a counterpart that has failed. When a counterpart that the environment's config names fails, the flow writes the fatal `referenced_deployment_not_cloned` error and attempts no further counterpart.

`deploy_application` gains `deployment_id` and `upcoming_deployments` keyword arguments, and `generate_instance_from_deployment`, `generate_context_from_deployment`, `_populate_component_scheduling` and the resolver pass `upcoming_deployments` down, the way `release_reference` is already passed for the clone. A counterpart is still created and built in one transaction, so a failure leaves no row, as today.

**Known limit**: inside a cycle of terms, a counterpart created before a peer whose creation then fails keeps a term with the peer's id. The clone attributes it `cloned`, and its next reconcile is refused with the term's path. A creation failure after a successful capture needs the driver version to disappear or the database to fail, so this is recorded rather than handled.

**Rationale**: the environment config and the counterparts' configs must name the counterparts, but the environment must exist before the counterparts and the counterparts must exist before their instances. Ids known in advance let every config be written once, in its final form.

**Alternatives considered**:

- Create every counterpart row first, without an instance, then rewrite the configs and build the instances. Rejected: rows without an instance are a new state for the rest of the code, a failed build would need a new hard delete of one deployment, and the environment config would be written twice.
- Create the environment without `scheduling` and add it later. Rejected: a crash between the two writes leaves an environment whose pods are placed without the terms, with no error.
- Rewrite the ids by name after the clone, as PR #504 did on rename. Rejected for the same reasons as in #508.

## R-009: An environment restore puts the captured config back unchanged

**Decision**: `restore_environment_backup` keeps the direct assignment of the captured config (`services/backup/environment.py` L979-983) and checks no term, so a term that names a deployment deleted since the backup does not stop the restore (FR-006). One change is needed for FR-006 to hold: the restore's fan-out loop (L1062-1089) calls `redeploy_for_environment_update` without a savepoint. When one redeploy fails, the inner `async with uow` blocks roll back the whole transaction (`services/unit_of_work.py` L216-227; ADR-066), which drops the redeploys already written in the loop. Each redeploy is wrapped in `uow.session.begin_nested()`, as the config fan-out does (`services/cluster_config_fanout.py` L375-400).

**Rationale**: after this change, a term that names a tombstoned deployment is refused at every redeploy (FR-004). Without the savepoint, one such term in the restored environment config would drop the redeploys of the other deployments, which blocks part of the recovery that US7 protects.

## R-010: Error types

**Decision**:

- `UnresolvableAffinityReferenceError` (`services/exceptions.py` L664-701) gains a `deleted: bool = False` keyword. When it is true, the message reads "Affinity term at <path> names deployment <last name> (<id>), which was deleted", and `error_metadata` adds `deleted: true` next to `deployment_id`, `deployment_name` and `path`. The `error_code` stays `VALIDATION_ERROR`.
- New `UnclonedDeploymentReferenceError(ServiceError)`, `error_code = "VALIDATION_ERROR"`, `default_message = "An affinity term names a deployment that the clone does not copy"`. `error_metadata` is `{"deployments": [{"deployment_id", "deployment_name", "paths": [...]}]}`. `VALIDATION_ERROR` is an existing code, so the SDK's and the CLI's error mapping need no change.

**Rationale**: Constitution §IV. The PRD left the new error's name and code open.

## R-011: GraphQL, SDK and frontend surface

**Decision**:

- `DeploymentReferenceInput` (`api/definitions/config/inputs.py` L100-106) gets field descriptions: `deploymentId` "Id of a deployment in the same environment.", `deploymentName` "Name of a deployment in the same environment. Styrmin stores the id of that deployment instead of the name when the config is written.", and the type description says the config stores the id only. No field is added or removed. `schema.graphql` and the SDK and frontend generated types are regenerated (`uv run invoke generate`).
- Reads keep returning the stored JSON (`Deployment.config`, `Environment.config` are `JSON!`), which now gives `deployment_id` only.
- Frontend: no change. The configuration drawer sends back the stored reference with `normalizeDeploymentRef` (`frontend/src/lib/deployment-input.ts` L209-215). `schedulingSanitize.ts` is imported nowhere. The environment form refuses to save a config that has `scheduling` (`EnvironmentConfigurationTab.tsx` L199-219).
- SDK and CLI: no change. `deployments apply` sends the manifest's config as written through `updateDeploymentVersion` and reports `unchanged` when the backend returns a null `Task` (`python_sdk/src/styrmin_sdk/resources/deployments.py` L762-818).

## R-012: Third-party dependencies

**Decision**: no dependency lacks a capability this feature needs, so no extension or upstream contribution is required.

- Kubernetes pod affinity has no notion of a Styrmin deployment; the existing `styrmin/deployment_id` pod label covers that (ADR-034), and it does not change.
- SQLAlchemy savepoints (`AsyncSession.begin_nested`) give the per-redeploy isolation of R-009; the config fan-out already uses them.
- Pydantic, Strawberry and Prefect are used as they are today. The binding walks plain dicts (R-002).

## R-013: E2E coverage

**Decision**: extend two existing tests; add no test node.

- `test_pod_anti_affinity_cross_deployment_via_graphql` (`tests/e2e/test_pod_scheduling.py` L706-829, `shard_compute`, `api_only`). Today it writes mutual preferred anti-affinity terms by id and checks the rendered pod templates; it renames nothing. Extension:
  1. write A's term with `deploymentName` of B, and check that A's stored config gives B's id;
  2. record the uids of A's pods, rename B with `updateDeployment`, and check that A's pods have the same uids;
  3. write A's config back as read and check that the `Task` is null (FR-009);
  4. update A with a changed environment variable, wait for `running`, and check that the rendered pod template still selects `styrmin/deployment_id=<B's id>`;
  5. rename B back in the cleanup, because the module-scoped fixtures name it `scheduling-b`.
- `test_environment_clone_lifecycle` (`tests/e2e/test_backup_restore.py` L2102-2668, `shard_env_backup`, both variants). Today it clones one deployment: the peer it creates at L2163-2171 is left out of the selection. The planning answer to the PRD's open question: it needs the peer cloned too. Extension:
  1. give the peer a preferred pod affinity term that names the primary by name, through the SDK, and wait for the peer to run again;
  2. check that a clone request that selects only the peer is refused with `UnclonedDeploymentReferenceError`, which lists the primary and the peer's term path, and that no clone record is created;
  3. select both deployments in the clone; adjust the attribution, capture and counterpart assertions to two `CLONED` entries;
  4. check that the peer's counterpart's term gives the primary's counterpart id, and that no term in the new environment gives an id of a source deployment.

  The not-selected `SKIPPED` reason stays covered by the re-clone with an empty selection (L2572-2616). The extra cost is one constituent backup and one cross-target restore of a `simple-app` deployment per variant.
- Mutual terms and both snapshot orders (FR-008, SC-003) are covered by the functional clone tests, which run the real flow and the real `deploy_application` (`tests/functional/graphql/test_environment_clone.py`, `_run_clone_flow` L906-960). Snapshot order has no `ORDER BY` (`repository/deployment.py` L348-356), so E2E cannot pick it.

## R-014: Documentation

**Decision**: update in the same change (Constitution §VII):

- `dev/guides/pod-scheduling.md`, "Affinity by deployment reference": a name is replaced with the id on write, the id is resolved at each reconcile, the effect of a rename, delete and re-create, and clones.
- `CONTEXT.md`: new entries **Affinity term** and **Deployment reference**; the **Environment clone** entry says that copied terms name the counterparts and that a request that leaves out a named deployment is refused.
- `dev/adr/0075-deployment-references-stored-by-id.md`: the decision, the alternative rejected in PR #504, the effect on delete and re-create, and the clone's ids given in advance. It amends ADR-034's "re-expanded on every reconcile" for names. 0074 is taken on another branch.
- `dev/knowledge/backend/backup-restore.md`: the clone flow steps of R-008 and the request check of R-007.
- `dev/knowledge/backend/data-models.md` (L797, `DeploymentReference`): stored form.
- `dev/knowledge/backend/services.md` (L272, `deploy_application` signature): the two new keyword arguments.
- `docs/docs/concepts-and-architecture/backups-and-restores.md`, "Choosing which deployments come along": one row in the table for a request refused because a term names a deployment the clone leaves out, and one sentence that copied terms name the counterparts. This page describes the clone's refusals, so it would be incomplete without the new one. No public page describes deployment references, and a public page about them stays out of scope.
- Changelog fragments `changelog/492.fixed.md` and `changelog/508.changed.md`.

## R-015: Existing behaviour that stays as it is

- A failed redeploy during an environment's config fan-out is logged and counted, not returned (`services/cluster_config_fanout.py` L375-400). What the operator views on the deployment is still not known (#492).
- `deployments apply` applies manifests one at a time in order (`python_sdk/src/styrmin_sdk/resources/deployments.py` L963-964), so B's manifest that names A, applied before A's, is refused.
- The `deployment_detail.py` page object's `_fill_affinity_term` (L376-399) fills labels that the frontend no longer has. No test touched by this feature calls it.
