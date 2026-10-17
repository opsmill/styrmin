# ADR-075: Deployment References Stored by Id

**Status**: Accepted
**Date**: 2026-10-16
**Decision-makers**: Fatih Acar
**Source**: [issue #508](https://github.com/opsmill/styrmin/issues/508) and its
[PRD comment](https://github.com/opsmill/styrmin/issues/508#issuecomment-6226052128);
[issue #492](https://github.com/opsmill/styrmin/issues/492) (the failure);
[PR #504](https://github.com/opsmill/styrmin/pull/504) (closed: the option rejected);
`specs/027-deployment-reference-by-id/` (spec, research R-001 to R-015, critique)
**Related**: [ADR-034](0034-affinity-by-deployment-reference-via-label.md) (amended here: a
stored reference gives an id, so a reconcile looks up no name),
[ADR-054](0054-backend-authoritative-noop-detection.md) (a write-back or a re-apply must start
no reconcile), [ADR-056](0056-environment-clone-record-and-cross-target-restore.md) (the
environment clone that copies the terms),
[ADR-073](0073-kubernetes-objects-named-and-found-by-record-id.md) (the same rule for the
Kubernetes objects of a record)

## Context

A pod affinity or pod anti-affinity term in a `scheduling` config can name another deployment of
the same environment with a deployment reference, which gives `deployment_id` or
`deployment_name` (`DeploymentReference` in `context/models/config.py`). Operators write terms in
an environment's config and a deployment's config. A component's terms come from the component
definitions of the deployment's driver version, which `deploy` and `updateDeploymentVersion` copy
to the deployment's components.

Styrmin stored a name as written and looked it up each time it built an instance for a deployment
that the term applies to ([ADR-034](0034-affinity-by-deployment-reference-via-label.md): "The
reference is re-expanded on every reconcile"). After the named deployment was renamed, the lookup
found no deployment and raised `UnresolvableAffinityReferenceError` (#492). From the code, as the
PRD of #508 records:

- every later update of a deployment whose term named the renamed deployment was refused;
- every config fan-out redeploy in an environment whose config had such a term failed;
- the rename itself was refused when the environment's config had a term that named the
  deployment being renamed, because the rename set the new name before it built the new instance.

Two related failures existed at the same time:

- An environment clone copied the configs of the source environment and the source deployments
  unchanged. A term that gave an id named a deployment of the source environment, and the lookup
  for the counterpart deployment refused it, because the named deployment was in another
  environment.
- A term that gave the id of a tombstoned deployment resolved, because the lookup by id also
  returns tombstoned rows, and gave a selector that matched no pod.

## Decision drivers

- A rename of a deployment must not change which deployment a term names.
  [ADR-073](0073-kubernetes-objects-named-and-found-by-record-id.md) sets the same rule for the
  Kubernetes objects of a record.
- An environment restore must not bring back a value that no longer names the deployment. PR #504
  found that a restore writes back the environment config of the backup.
- Operators must still be able to give names in manifests and requests: ids differ in each
  environment.
- Re-applying an unchanged manifest, or writing back a config as it was read, must start no
  reconcile ([ADR-054](0054-backend-authoritative-noop-detection.md)).
- The terms of an environment clone must name the clone's own counterpart deployments.

## Considered options

1. Keep names stored, and on each rename rewrite the name in the terms of the environment and of
   every deployment of the environment, in the rename's transaction (PR #504).
2. Store the id: every write replaces a name with the named deployment's id before it saves, and a
   reconcile resolves ids only.
3. Keep names stored and look them up at each reconcile, as before.

## Decision

We chose option 2, as decided in the review of PR #504 and recorded in #508.

- **Every write that stores a config replaces names with ids.** `createEnvironment`,
  `updateEnvironment`, `deploy`, `updateDeployment` and `updateDeploymentVersion`, and therefore
  `styrminctl deployments apply`, replace each name with the id of the non-tombstoned deployment
  of the same environment that has that name, before anything is saved or dispatched
  (`bind_deployment_references` in `services/scheduling/references.py`). The component configs
  that `deploy` and `updateDeploymentVersion` copy from the driver version get the same treatment.
  A name is looked up after the request's own changes, so a term can name the new deployment of a
  `deploy`, or the new name of a rename in the same request. The stored reference gives
  `deployment_id` as a lowercase UUID string and keeps `components`; every other key of the config
  is stored as written.
- **A write that names a missing deployment is refused.** A name that no non-tombstoned deployment of
  the environment has, an id that matches no deployment, an id of another environment's
  deployment, and the id of a tombstoned deployment are refused with
  `UnresolvableAffinityReferenceError` (`VALIDATION_ERROR`) and the term's path, and nothing is
  saved. The binder checks each reference with the `DeploymentReference` model first, so a
  component config from a driver version is refused with the same error and path when a
  reference gives both or neither of `deployment_id` and `deployment_name`, has a key other than
  `deployment_id`, `deployment_name` and `components`, gives a `components` value that is not a
  list of strings, or gives an id that is not a UUID. `createEnvironment` refuses every term that
  names a deployment, because a new environment has no deployment, except the deployments that the
  caller is about to create (an environment clone).
- **A reconcile resolves ids only.** `resolve_deployment_reference` refuses a reference that gives
  a name, an id that is not a deployment of the environment, and a tombstoned deployment, which it
  reports with `deleted: true` and the deployment's last name. Each level (environment,
  deployment, component) is resolved before the levels are merged, with its own path prefix
  (`environment.config.scheduling`, `deployment.config.scheduling`,
  `component[<name>].config.scheduling`).
- **An environment clone gives counterparts their ids in advance.** The clone flow chooses one id
  per counterpart before it creates the new environment, rewrites every copied id to the
  counterpart's id (`remap_deployment_references`), and passes the counterparts to
  `create_environment` and `deploy_application` as the deployments about to be created, so a term
  can name a counterpart that does not exist yet. `cloneEnvironment` refuses, before it creates any
  record or backup, a request whose copied terms name a deployment that the clone does not copy
  (`UnclonedDeploymentReferenceError`, `VALIDATION_ERROR`).
- **An environment restore writes the captured config back as captured.** It replaces and checks
  no reference, so a captured term that names a deployment deleted since the backup does not stop
  the restore. Each redeploy of the restore's fan-out runs in its own savepoint, so one refused
  redeploy keeps the others.
- **The GraphQL surface changes in its descriptions only.** `DeploymentReferenceInput` keeps both
  fields, and its descriptions say that a name is replaced with the id when the config is written.

This amends [ADR-034](0034-affinity-by-deployment-reference-via-label.md): the reference is still
resolved at every reconcile, but a stored reference gives an id, so a reconcile looks up no name.

Option 1 fails the second driver: an environment restore writes back the backup's environment
config, which gives the name the deployment had at backup time (PR #504). It also writes the
configs of other deployments on every rename, and it would not fix the clone, whose copied ids
name source deployments. Option 3 keeps the failure of #492 and the clone failure.

## Consequences

- Good, because a rename changes no stored term and no resolved selector, so it restarts no pod
  of the deployments whose terms name the renamed deployment, and their later updates and
  fan-out redeploys succeed. `test_pod_anti_affinity_cross_deployment_via_graphql` checks this in
  a cluster (`specs/027-deployment-reference-by-id/e2e-evidence.md`).
- Good, because an environment restore brings back ids, which name the same deployments as at
  backup time, because a restore creates and deletes no deployment.
- Good, because a term that names a missing deployment is refused when it is written, with its
  path. A term in an environment's config was checked only for its shape before, and failed at
  the next reconcile.
- Good, because a request that gives names and the stored config that gives ids produce the same
  stored form, so a write-back of a read config and a re-apply of an unchanged manifest that gives
  names start no reconcile (ADR-054).
- Bad, because deleting a deployment gives no warning about the terms that name it. A deleted
  deployment's id is never given to another deployment, so the terms keep naming it. Every later
  update of a deployment whose terms name it fails with the term's path, the last name and
  `deleted: true`, and the config fan-outs fail those redeploys and keep the others, until the
  terms are written again. After a re-create under the same name, writing the terms again with the
  name, for example by re-applying the unchanged manifest, stores the new deployment's id. A
  warning at delete time is out of scope.
- Bad, because `createEnvironment` and `styrminctl environments create -c` refuse every term that
  names a deployment. Before, the write was accepted and the term failed at the first reconcile.
- Bad, because a term that a deeper level discards with `replace: true` is still resolved, so a
  term that names a deleted deployment fails the reconcile even when a deeper level replaces it.
- Bad, because a driver version can give only a name. Styrmin looks the name up again each time
  it copies the driver version's component definitions: at `deploy`, at an
  `updateDeploymentVersion` that moves the deployment to another driver version, and when a clone
  creates a counterpart. After the named deployment is renamed, the stored id keeps working at
  reconcile, but these copies are refused with the `component[<name>]` path and the name when
  the driver version's definitions give the old name. Fixing
  this needs drivers that do not name deployments.
- Bad, because `styrminctl deployments get` and the GraphQL `config` show only an id. Showing which
  deployment a term names next to the id is a follow-up; the issue is not filed yet.
- The clone flow changes shape. Each counterpart is created after the counterparts that its terms
  name; among those that can come next, the ones that the environment's config names come first,
  then the others in source-name order, and a cycle of terms is broken in source-name order
  (critique E1). Counterparts without terms are therefore created in source-name order instead
  of snapshot order. A deployment whose captured data cannot be used, or whose counterpart
  fails, fails the counterparts whose terms name it, with the new step
  `referenced_deployment_not_cloned` when the new environment's config names it. The request check
  merges the source config and the override at request time, so a source config that no longer
  validates is refused at request time instead of failing the clone.
- Known limit: inside a cycle of terms, a counterpart created before a peer whose creation then
  fails keeps a term with the peer's id. The clone attributes it `cloned`, and its next reconcile
  is refused with the term's path. A creation failure after a successful capture needs the driver
  version to disappear or the database to fail (research R-008).
- Rollback: the code before this change resolves stored ids, so reverting it leaves the stored
  configs valid, and there is no migration to reverse (critique E9). After a revert, a term that
  names a tombstoned deployment resolves again to a selector that matches no pod, and an
  environment clone again copies ids that name source deployments, as before this change.

## Confirmation

- Unit tests: `backend/tests/unit/services/scheduling/test_references.py`,
  `backend/tests/unit/services/test_scheduling_validator.py`,
  `backend/tests/unit/services/test_deployment_reference_binding.py`, and the clone tests in
  `backend/tests/unit/services/backup/test_environment_clone_service.py`.
- Functional tests: the GraphQL propagation rows for `deploymentRef.deploymentName`,
  `backend/tests/functional/graphql/test_deployment_reference_scenarios.py` (rename, delete,
  re-create, restore) and `backend/tests/functional/graphql/test_environment_clone.py`.
- E2E: `test_pod_anti_affinity_cross_deployment_via_graphql` (`shard_compute`) and
  `test_environment_clone_lifecycle` (`shard_env_backup`), with local evidence in
  `specs/027-deployment-reference-by-id/e2e-evidence.md`.

## More information

- [`dev/guides/pod-scheduling.md`](../guides/pod-scheduling.md#affinity-by-deployment-reference)
  describes what an operator writes and views.
- [`dev/knowledge/backend/backup-restore.md`](../knowledge/backend/backup-restore.md#affinity-terms-in-a-clone)
  describes the clone flow.
- While this change was made, a defect in `SqlModelUnitOfWork.__aexit__` was fixed: a failure in
  two nested unit-of-work blocks inside a caller's savepoint rolled back the caller's whole
  transaction. The rule is recorded in
  [ADR-066](0066-cluster-config-fanout.md) (amended 2026-10-17).
