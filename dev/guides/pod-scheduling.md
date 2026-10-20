# Pod scheduling configuration

This guide summarises how operators configure hierarchical pod scheduling
on Styrmin deployments, and how the platform injects those values onto
pod templates without driver-side changes. The authoritative reference is
`specs/001-pod-scheduling-config/`; the quickstart walks through each
feature step-by-step.

## Where to set

Styrmin resolves `scheduling` from three levels, deepest-wins per field:

```
environment.config.scheduling → deployment.config.scheduling → component.config.scheduling
```

Every field is optional; missing values inherit from the next shallower
level. Clearing a deeper level (omitting the key) reverts the effective
value to the shallower one (FR-020).

## Supported features

| Feature | Field | Merge rule |
|--|--|--|
| Pod affinity / anti-affinity | `pod_affinity`, `pod_anti_affinity` | required + preferred accumulate; `replace: true` per kind resets shallower terms |
| Node affinity | `node_affinity` | as pod affinity, except that required terms of different levels are combined: one term per combination of one term from each level, so a node must match a term of every level; `topology_key` ignored ([ADR-033](../adr/0033-scheduling-merge-semantics.md)) |
| Topology spread | `topology_spread_constraints` | union keyed by `(topology_key, when_unsatisfiable)`; deepest wins per key |
| Resources | `resources.requests.*`, `resources.limits.*`, `extended` map | per-field deepest wins |
| Tolerations | `tolerations` | union with stable dedup on the full tuple |
| Runtime class | `runtime_class` | deepest wins; must be DNS-1123 and exist in the cluster |

## Affinity by deployment reference

Instead of a raw `label_selector`, a pod affinity or pod anti-affinity
term can carry a `deployment_ref` that names another deployment of the
same environment. Add `components:` to select only the pods of some
components of that deployment. At each reconcile, Styrmin turns the
reference into a selector on the `styrmin/deployment_id` label that it
puts on every pod template it manages
([ADR-034](../adr/0034-affinity-by-deployment-reference-via-label.md)).
Node affinity terms select nodes and take no deployment reference.

Operators write these terms in an environment's config and in a
deployment's config, through GraphQL, the SDK or a `styrminctl`
manifest. The UI cannot show or edit a deployment reference: the
configuration form sends back the reference it read. A component's
terms come from the component definitions of the deployment's driver
version (see
[Terms from a driver version](#terms-from-a-driver-version-are-looked-up-by-name-at-each-copy)).

The decision is recorded in
[ADR-075](../adr/0075-deployment-references-stored-by-id.md).

### A name is replaced with the id when the config is written

A write can give `deployment_id` or `deployment_name`:

```yaml
scheduling:
  pod_anti_affinity:
    preferred:
      - weight: 100
        term:
          topology_key: kubernetes.io/hostname
          deployment_ref:
            deployment_name: postgres
            components: [primary]
```

Before it saves the config, Styrmin replaces the name with the id of
the deployment of the same environment that has that name. The stored
reference gives the id only, in lowercase, and keeps `components`.
Reading the config back (`Deployment.config`, `Environment.config`)
gives:

```yaml
          deployment_ref:
            deployment_id: 7f0c2a3e-1b2c-4d5e-8f90-0a1b2c3d4e5f
            components: [primary]
```

The read gives no name next to the id
([#521](https://github.com/opsmill/styrmin/issues/521)).

Every write that stores a config does this:

- `createEnvironment` and `updateEnvironment`, for the environment's
  config;
- `deploy`, `updateDeployment` and `updateDeploymentVersion`, for the
  deployment's config. `styrminctl deployments apply` calls `deploy`
  for a new deployment and `updateDeploymentVersion` for an existing
  one;
- `deploy` and `updateDeploymentVersion`, for the component configs that
  they copy from the driver version.

A name is looked up after the request's own changes: a term in the
config of a new deployment can name that deployment, and a term in a
request that renames the deployment is looked up by the new name.

### Writes that are refused

A write is refused with `VALIDATION_ERROR`, and saves nothing, when a
term names a deployment that the environment does not have: a name that
no live deployment of the environment has, an id that matches no
deployment, an id of a deployment of another environment, or the id of a
tombstoned deployment. The error's `extensions` give
the term's `path` and the `deployment_name` or `deployment_id` that the
term gives. The path starts with the config that holds the term:
`environment.config`, `deployment.config` or `component[<name>].config`,
for example `environment.config.scheduling.pod_anti_affinity.preferred[0].term`.
Paths use the snake_case keys of the stored config, as a read gives them.
The message gives the same path, the environment's name and the reason,
because `styrminctl` shows only the message. A program that uses the
Python SDK reads the error's extensions in the `extensions` attribute of
the `OperationFailedError`, or in the `error_extensions` of a failed
apply outcome ([#522](https://github.com/opsmill/styrmin/issues/522)).
The environment's name and the reason are only in the message. An
example message:

```text
Affinity term at deployment.config.scheduling.pod_affinity.required[0] names
deployment 'postgres', which is not a deployment of environment 'prod'.
```

The same error, with the term's path, refuses a `deployment_ref` that:

- gives both or neither of `deployment_id` and `deployment_name`;
- has a key other than `deployment_id`, `deployment_name` and
  `components`;
- gives a `components` value that is not a list of strings;
- gives a `deployment_id` that is not a UUID.

The API checks the environment and
deployment configs for these before it looks names up; for the
component configs that a driver version gives, this check is the first.

Two consequences:

- `createEnvironment` and `styrminctl environments create -c` refuse
  every term that names a deployment, because a new environment has no
  deployment yet. The message says so. Add the terms with
  `updateEnvironment` once the named deployments exist.
- `styrminctl deployments apply` applies the manifests one at a time,
  in order. A manifest whose term names a deployment that a later
  manifest creates is refused. Put the named deployment first.

### Each reconcile resolves the stored id

At each reconcile, Styrmin resolves the ids of the environment's terms,
the deployment's terms and each component's terms to
`styrmin/deployment_id=<id>`, each in its own level, and then merges the
levels. An error gives the path of the term in its own level, such as
`deployment.config.scheduling.pod_affinity.required[1]`.

A term that a deeper level discards with `replace: true` is dropped
before it is resolved. A deployment can therefore discard a term of the
environment's config that names a deleted deployment: set `replace: true`
on the same kind (`pod_affinity` or `pod_anti_affinity`) in the
deployment's config. The `resolvedScheduling` field resolves the levels
the same way.

### A rename changes no term

Renaming a deployment changes no stored term. The resolved selector was
already `styrmin/deployment_id=<id>`, so the rename restarts no pod of
the deployments whose terms name the renamed deployment, and their later
updates and config fan-out redeploys succeed. The E2E test
`test_pod_anti_affinity_cross_deployment_via_graphql` checks this in a
cluster. Before this change, a rename made every later update of these
deployments fail, and the rename itself was refused when the
environment's config named the renamed deployment
([#492](https://github.com/opsmill/styrmin/issues/492)).

### A deleted deployment fails the terms that name it

Deleting a deployment gives no warning about the terms that name it
([#523](https://github.com/opsmill/styrmin/issues/523)). Styrmin never
gives its id to another deployment, so the terms keep naming the deleted
deployment. Once it is tombstoned:

- Every `updateDeployment` and `updateDeploymentVersion` of a deployment
  whose own config names it is refused, and saves nothing. The error
  gives the term's path, the deleted deployment's last name as
  `deployment_name`, and `deleted: true`. This includes an update that
  changes only the deployment's name, because Styrmin checks the whole
  stored config on every update.
- When the environment's config names it, every `updateEnvironment` that
  keeps the term is refused and saves nothing. Every `updateDeployment`
  of a deployment that the term applies to is refused too, before it
  saves anything, unless the request's config discards the term with
  `replace: true`. `updateDeploymentVersion` of such a deployment fails
  when Styrmin builds the new instance.
- When a component's config, copied from the driver version, names it,
  every `updateDeployment` of that deployment is refused and saves
  nothing.
- The environment and cluster config fan-outs fail the redeploys of the
  deployments that such a term applies to, count them as failed, and
  keep the other redeploys. `updateCluster` lists those deployments in
  `failedToStart`.

The message of each refusal says how to fix the term:

- a term of the environment's config: change or remove it with
  `updateEnvironment`, which needs the ADMIN role, or discard the
  environment's terms of that kind in the deployment's config with
  `replace: true`, which `updateDeployment` allows with the READ_WRITE
  role;
- a term of the deployment's config: change or remove it;
- a term of a component's config: move the deployment to a driver
  version whose component definitions do not name the deleted
  deployment.

For example:

```text
Affinity term at environment.config.scheduling.pod_anti_affinity.preferred[0].term
names deployment 'postgres' (7f0c2a3e-1b2c-4d5e-8f90-0a1b2c3d4e5f), which was
deleted. To fix it, change or remove the term in the environment's config with
updateEnvironment, which needs the ADMIN role, or discard the environment's terms
of this kind in the deployment's config with replace: true.
```

### A re-created deployment needs the terms written again

After the deleted deployment is tombstoned, a new deployment can take
its name. The terms still give the old id and fail as above. Write each
term again with the name, for example by applying the unchanged manifest
whose term gives `deployment_name`: the name now gives the new
deployment, and Styrmin stores its id. `styrminctl deployments apply`
refuses a manifest whose driver differs from the existing deployment's
driver (`DriverMismatchError`). To change the driver, you delete the
deployment and apply the manifest again, which creates a new deployment,
so this applies to that case too.

### Re-applying an unchanged manifest starts no reconcile

Writing back a config exactly as it was read returns a null `Task`
([ADR-054](../adr/0054-backend-authoritative-noop-detection.md)).
Re-applying an unchanged manifest whose terms give `deployment_name`
also starts no reconcile, and `styrminctl deployments apply` reports
`unchanged`, because the name gives the same id as the stored term. This
holds while the name still gives the same deployment.

### Terms from a driver version are looked up by name at each copy

A driver version's component definitions can give only a name, because
a deployment's id differs in each environment. Styrmin looks the name up
each time it copies the definitions to a deployment's components:

- at `deploy`;
- at `updateDeploymentVersion`, only when the request moves the
  deployment to another driver version. With the same driver version,
  the stored component configs stay as they are;
- when an environment clone creates a counterpart deployment.

After the named deployment is renamed, the stored id keeps working at
each reconcile, but the next copy looks the driver's name up again and
finds no deployment. A `deploy` with that driver version, an
`updateDeploymentVersion` to a driver version whose definitions give the
old name, and a clone that copies a deployment of that driver version
are refused, with the name and the `component[<name>]` path. This case
is tracked in [#524](https://github.com/opsmill/styrmin/issues/524).

### An environment clone points copied terms at its counterparts

An environment clone gives each counterpart deployment its id before it
creates anything. Every copied term, in the new environment's config and
in each counterpart's config, then names the counterpart of the
deployment it named, so the clone's pods are placed relative to each
other and not to the source's pods. Terms that name each other work in
either order. Driver terms are looked up by name among the counterparts.

`cloneEnvironment` refuses a request, before it creates a clone record
or a backup, when a copied term names a deployment that the clone does
not copy: one left out of the selection, or one skipped as not eligible.
The terms checked are those of the new environment's config (after the
override and the cleared fields), of each copied deployment's config,
and of the component definitions of its driver version. The error is
`VALIDATION_ERROR`, and `extensions.deployments` lists each such
deployment with `deployment_id`, `deployment_name`, the `paths` of the
terms that name it, and the `reason` the clone does not copy it, such as
`not included in the requested deployment selection`. `deployment_id` is
`null` for a name, given by a driver version, that no live deployment of
the source environment has. The message lists the same deployments,
reasons and paths, then the three ways to fix the request. The terms are
checked after the environment-operation guard: while another environment
operation runs on the source, the request gets
`EnvironmentOperationInProgressError` first.
A name in the clone's
`configOverride` is looked up among the source environment's
deployments. The details of the clone flow are in
[backup-restore.md](../knowledge/backend/backup-restore.md#affinity-terms-in-a-clone).

### An environment restore writes the captured terms back unchanged

An environment restore writes the captured environment config back as
it was captured, and looks no name or id up. It succeeds when a captured
term names a deployment deleted since the backup; the term then fails as
described in
[A deleted deployment fails the terms that name it](#a-deleted-deployment-fails-the-terms-that-name-it).
Each redeploy of the restore's fan-out runs in its own savepoint, so a
failed redeploy keeps the others. The failure is written only to the
server log, not on the `EnvironmentRestore` record:
`env_restore_fanout_dispatch_error` gives the `environment_restore_id`,
the `deployment_id`, the `error_code` and the term's `path`, and
`env_restore_fanout_dispatched` counts the failure in
`config_redeploy_failed` and in `dispatch_failed`. Listing the refused
redeploys on the restore is tracked in
[#520](https://github.com/opsmill/styrmin/issues/520).

## Per-feature opt-out

Every feature group can be opted out at the deployment or component
scope via `scheduling.inject.*`. Component-level flags override
deployment-level flags per-field (not whole-object).

```yaml
scheduling:
  inject:
    pod_affinity: false     # keep driver template's affinity untouched
    resources: true         # still inject resource requests/limits
```

A `None` flag at every level resolves to `True` (inject).

## Post-renderer precedence (FR-015)

Scheduling patches are appended to the HelmRelease
`spec.postRenderers` pipeline **after** driver-template-derived patches,
so Kustomize applies them last — post-renderer wins over driver
template values. Flip the per-feature `inject.*` flag to opt out.

## Reading resolved values in drivers

Drivers that want to branch on the resolved scheduling (e.g. to set a
probe threshold based on resource limits) read
`context.components[*].scheduling.config` and
`context.components[*].scheduling.provenance` in their Jinja values
template. The same shape is available read-only via the GraphQL
`Deployment.resolvedScheduling` field for the UI.
