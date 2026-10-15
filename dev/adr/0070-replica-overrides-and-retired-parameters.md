# ADR-070: Replica Overrides by Post-Render and the Rule for Retired Parameters

**Status**: Accepted
**Date**: 2026-10-15
**Source**: specs/023-per-component-replicas/ (spec, plan, research D-001 to D-015, data-model, contracts); [issue #202](https://github.com/opsmill/styrmin/issues/202)
**Extends**: [ADR-057](0057-post-render-component-overrides.md) §2. The component state patch that
set `spec.replicas: 0` on a stopped component is replaced by the component replica patch, which
writes the stopped state and the replica count in one patch at the same place in
`spec.postRenderers`.
**Related**: [ADR-029](0029-config-additions-via-baseconfigsection-no-migration.md) (config
additions without a migration), [ADR-058](0058-image-overrides-and-component-container-guard.md)
(the check against the target driver version before a version change),
[ADR-065](0065-apply-writes-config-with-the-version.md) (`styrminctl apply` writes the config with
the version), [ADR-069](0069-container-command-args-by-post-render.md) (`command` and `args` by
post-render); the user pages [Replica Overrides](../../docs/docs/concepts-and-architecture/replica-overrides.md)
and [Migrating Replica Parameters](../../docs/docs/drivers/migrating-replica-parameters.md).

## Context

Before this change, a user could change the number of pods of a component only when the driver
author declared a parameter for it and passed that parameter to the chart in `values.j2.yml`. Of
the example drivers, only `infrahub` and `infrahub-enterprise` did this, for `server` and
`task-worker` (`replicas_server`, `replicas_task_worker`). No driver could mark a component, such
as a database, as one that must never run more than one pod.

Stopping a component already used a post-render patch: `build_components_state_post_rendering_patches`
in `ApplicationHelmReleaseBuilder` wrote `spec.replicas: 0` on the component's `Deployment` and
`StatefulSet` workloads. A second patch that writes another count on the same field would make the
result depend on the order of the patches in the kustomize list.

Retiring the two infrahub parameters needed a rule for stored parameter values. Before this change,
`validate_parameter_values` rejected any key that the target driver version did not declare with
`OPERATION_FAILED` "Unknown parameter". `validate_parameter_values` stores every default, so every
`infrahub` deployment holds both parameters, also when the user never set them.

## Decision

### 1. The override is stored in the deployment config (research D-001)

`ComponentConfigBlock` (`context/models/config.py`) gains `replicas: int | None`, stored in
`Deployment.config` under `components.<name>.replicas`. There is no column and no Alembic revision
(ADR-029); a config stored before the change has no key and reads as `None`. A `mode="before"`
validator, and a matching check in `DeploymentConfig.components`, raise
`InvalidReplicaCountError` (`INVALID_REPLICA_COUNT`, metadata `component_name`,
`requested_replicas`) for a `bool`, a value that is not an `int`, a value below 1 or a value above
2147483647 (`MAX_REPLICA_COUNT`, Kubernetes `int32`). The message tells the user to stop the
component instead of setting 0. `None` means no override.

GraphQL exposes it as `ComponentConfigInput.replicas: Int`, on `deploy`, `updateDeployment` and
`updateDeploymentVersion(input:)`. `null` or an omitted field clears the override (full
replacement). The override has component scope only and no layering.

### 2. The driver declares `replicas` and `singleton` (research D-002)

`ReplicaDeclaration` (`context/models/components.py`) types two keys of a component declaration:
`replicas: StrictInt | None` (1 to 2147483647) and `singleton: StrictBool = False`. Both
`ArbitrarySectionModel` classes, the driver-load model
(`services/driver/models/resources/driver.py`) and the context model, inherit from it, so the two
type the keys the same way.

- A model validator rejects `singleton: true` with `replicas` greater than 1. The error becomes a
  `DriverLoadingError` with the field path (`spec.components.<name>`), and no driver version is
  stored. `singleton: true` with `replicas: 1` loads.
- A `model_serializer(mode="wrap")` leaves `replicas` out of a dump when it is `None` and
  `singleton` when it is `false`. A declaration that uses neither key dumps to the same dict as
  before the change, so the stored declaration, the context in the `StyrminDeployment` resource and
  the instance that the no-op check compares do not change (critique E1).
- Driver versions stored before the change may hold an untyped `replicas` or `singleton` extra
  that the typed fields reject. `parse_stored_component_declaration` parses stored declarations
  for the context resolver, the write checks and the read field; when dropping both keys makes the
  declaration valid, it drops them and logs a warning that names the driver version and the
  component. The driver load path does not use it, so new driver versions are checked strictly.

GraphQL exposes the two keys as `ComponentConfig.replicas: Int` and `ComponentConfig.singleton:
Boolean!`, which default to `null` and `false` for rows that do not have them.

### 3. One order of precedence (FR-002, research D-003)

`services/replicas/resolver.py` holds the order of precedence:

- `resolve_replicas(declared_replicas, singleton, override, is_orphaned)` returns
  `ResolvedReplicas(count, source, override_applies)`:
  1. An orphaned override (the bound driver version does not declare the component) never applies.
  2. An override applies, with source `OVERRIDE`.
  3. Otherwise the driver default applies, with source `DRIVER_DEFAULT`: `declared_replicas`, or 1
     for a singleton component that declares no `replicas`.
  4. Otherwise `count` is `None`, with source `CHART`: no patch, and the chart's count applies.
     Styrmin does not read that count.
  5. An override greater than 1 on a singleton component cannot be written (§5). If one is read, it
     does not apply, and the singleton's count of 1 applies.
- `replica_patch_count(resolved, enabled)` returns 0 for a stopped component and `resolved.count`
  otherwise.

The patch builder (§4) and the read field `Deployment.componentReplicas` call these two functions.
`resolve_replicas` does not take the stopped state into account, so the read field reports the
count that a stopped component returns to when it is started, and
`Deployment.components[].enabled` reports the stopped state.

### 4. One replica patch per kind per component, which also carries the stopped state (research D-004)

`build_component_replica_patches(context)` (`services/replicas/patch_builder.py`) replaces
`build_components_state_post_rendering_patches` and is called at the same place in
`ApplicationHelmReleaseBuilder.build()`. The order in `spec.postRenderers[0].kustomize.patches`
stays:

1. utility patches (ingress);
2. label patches;
3. component label patches;
4. component replica patches;
5. backup annotation patches;
6. scheduling patches;
7. component container patches (merge, then guard; last, ADR-057 §3).

For each component in the context and each kind in `("Deployment", "StatefulSet")`, the builder
emits at most one `SpecPatch(specs={"replicas": N})`, targeted by the kind and the component's
label selector (`identifier.label.label_selectable()`): `N` is 0 for a stopped component and the
resolved count for a running one, and no patch is emitted when the source is `CHART`. The patch is
a JSON6902 `add` on `/spec/replicas`, which replaces an existing value and creates a missing one.

- No two patches write `/spec/replicas` on the same workload, so the result does not depend on the
  order of the list.
- The patch targets the workload, not a container, so a component without a component container
  gets it. `Job`, `CronJob` and `DaemonSet` workloads are never targeted (ADR-057 §2). A selector
  that matches no workload changes nothing.
- The count is an `int` read from the context, never a user string.
- The patches are built again on every render. Clearing an override removes its patch, and the
  operator replaces `spec.postRenderers` as a whole key on update (ADR-057 §6), so Helm applies the
  chart's count again.
- A deployment whose driver declares no `replicas` and no `singleton`, and that has no override,
  gets the same patch list as before the change (SC-006).

The update task waits as it did before the change: the operator marks the rollout complete when
FluxCD reports the HelmRelease `Ready` for its current generation. The E2E reads the workload once
after each update task completes, for 1 to 2 pods and for 2 to 1, and finds `spec.replicas`,
`status.replicas` and the updated, ready and available counts equal to the requested count.

### 5. Write checks against the driver version bound after the write (research D-005, D-006)

`validate_replica_overrides(config, components, stored_config, checked_against)`
(`services/replicas/validator.py`) runs from `_validate_config_write` in `services/deployment.py`
(on `updateDeployment` with the bound driver version, and on `updateDeploymentVersion(input:)` with
the target driver version) and from `deploy_application` with no stored config. It runs after the
config is parsed, so a count below 1 reports `INVALID_REPLICA_COUNT` first, and before any task,
flow run or ingress dispatch:

- `UNKNOWN_COMPONENT_REPLICA_OVERRIDE` (metadata `component_name`, `known_components` sorted,
  `checked_against`): a write adds or changes an override on a component that the driver version
  does not declare. The stored value sent again is accepted, so an orphaned override is kept
  (FR-009); a removal is always accepted.
- `SINGLETON_REPLICA_OVERRIDE` (metadata `component_name`, `requested_replicas`,
  `checked_against`): an override greater than 1 on a component that the driver version marks
  `singleton: true`, also when it equals the stored value, because the stored count breaks the rule
  of the driver version the deployment is bound to after the write. An override of 1 is accepted.

`updateDeploymentVersion` without `input` runs the same check on the stored config against the
target driver version. A version change to a driver version that marks a component as singleton is
therefore rejected while the deployment stores an override greater than 1 on it, unless `input`
lowers the override to 1 or clears it in the same request. `styrminctl deployments apply` sends
`updateDeploymentVersion(input:)` (ADR-065), so the checks cover it.

`COMPONENT_CONTAINER_NOT_DECLARED` does not apply to `replicas`: `_validate_component_container_targets`
keeps its four slots (`env_vars`, `image`, `command`, `args`).

### 6. A singleton component limits the count, not the pods of a rollout

`singleton: true` means that Styrmin sets the count to 1 and rejects a count above 1. It does not
change the chart's update strategy, so a rolling update can run a second pod for a short time. The
user documentation states this limit.

### 7. The rule for parameters that the target driver version no longer declares (FR-010, research D-007)

In `update_deployment_version`, when the target driver version differs from the bound one,
`drop_retired_parameters` (`services/parameters/retired.py`) runs on the merged parameter map (the
`parameters` argument, or the stored values when it is null, with `input.parameters` on top),
before `validate_parameter_values` checks the map against the target driver version. For each
parameter that the current driver version declares and the target does not:

- the value is dropped when it equals the parameter's default in the current driver version, with
  the same type (`type(value) is type(default) and value == default`, so `"1"`, `1.0` and `True`
  do not equal `1`); an info log line records the drop;
- otherwise `RetiredParameterValueError` (`RETIRED_PARAMETER_VALUE`, metadata `parameter_name`,
  `value`, `default`, `checked_against`) is raised before any task starts. When several values
  differ, the first parameter by name is reported. The message prints the value and the default as
  JSON, says to remove the parameter or reset it to its default, says to carry a replica count over
  as a replica override first, and links the migration guide
  (`https://styrmin.pages.dev/docs/drivers/migrating-replica-parameters`).

A key that neither driver version declares is left to `validate_parameter_values`, which still
rejects it with `OPERATION_FAILED` "Unknown parameter". `updateDeployment` and `deploy` do not
change the driver version and do not run the rule. The nested `updateDeploymentVersion` that an
upgrade hook sends through the `upgrade_deployment_version` primitive targets the driver version
that the deployment is already bound to, so the rule does not run a second time.

The rule applies to any driver that retires a parameter. The `infrahub` driver version 5 and
`infrahub-enterprise` driver version 4 use it: they remove `replicas_server` and
`replicas_task_worker`, declare `server` with `replicas: 1` and `task-worker` with `replicas: 2`
(the old parameter defaults), and mark `database`, `task-manager-db` and `cache` as singleton
components. `simple-app` version 4 marks `database` as singleton.

## Consequences

- A user can change the replica count of any component of any driver without a change to the
  driver.
- A component's count follows one order of precedence, and `Deployment.componentReplicas`,
  the configuration view and `styrminctl deployments get` show the count and its source. The
  source `CHART` has no number.
- A deployment that kept the default values of the two infrahub parameters moves to the new driver
  version with no manual step and no change of pod count. A deployment with a changed value is
  rejected until the user carries the value over as a replica override. The API, the SDK and
  `styrminctl` do this in one request; the upgrade dialog sends only the versions, so the UI needs
  two steps: set the override and reset the parameter in the edit drawer, then upgrade. The
  override applies on the old driver version too, because the post-render patch replaces the count
  that the values template passes to the chart.
- A driver version loaded before this change that already declares an integer
  `components.<name>.replicas` starts to have it applied as the driver default. No in-repo driver
  declared the key. The changelog states this.
- `ComponentContext` keeps `extra="forbid"` and gains `replica_override`, so an agent from an
  earlier release rejects a context that carries an override. The agent chart is upgraded with the
  server, as for image overrides (critique E2).
- An earlier server rejects a stored `replicas` key (`ComponentConfigBlock` has
  `extra="forbid"`). Replica overrides must be cleared before Styrmin is rolled back (critique E9).
- A component whose pods share a `ReadWriteOnce` volume, such as the infrahub `server`, cannot run
  extra pods on other nodes; those pods stay `Pending` and the update task fails when its wait
  limit runs out. Styrmin does not check this or the cluster's capacity.
- The infrahub driver upgrade has no E2E test; functional tests load the old driver versions from
  `backend/tests/functional/fixtures/legacy_drivers/` and the new ones from `driver/examples/`.

## Alternatives Considered

- Storing 0 as the stopped state. Rejected: `Component.enabled` already records it, and the PRD
  keeps scaling and stopping separate.
- A `STOPPED` source. Rejected: the PRD lists three sources, and
  `Deployment.components[].enabled` reports the stopped state.
- A second patch next to the stop patch, relying on list order. Rejected: two writes to one field,
  and the order is kyaml behaviour, not a documented contract (ADR-057 §3).
- Writing the count into the values template. Rejected by the PRD (ADR-057).
- A validator that reads `__pydantic_extra__["replicas"]`, like the backup validator. Rejected:
  `replicas` and `singleton` are two scalars that the model can type directly.
- Patching 1 when no source is set. Rejected: it would scale down every chart that renders more
  than one pod.
- Dropping every retired parameter value silently. Rejected: a changed value would change a pod
  count without the user's knowledge.
- A driver format feature that maps a retired parameter to a replica override. Out of scope in the
  PRD.
- Reading the chart's rendered count from the cluster to fill `count` for `CHART`. Rejected: the
  read field must not depend on cluster access.

## Out of Scope

The spec leaves these out; no decision was taken on them:

- detecting a `HorizontalPodAutoscaler` that a chart ships, and working with it;
- replica defaults at environment or cluster level;
- a separate scale action;
- making sure that only one pod of a singleton component runs during a rolling update;
- checking cluster capacity before a scale-up;
- an upgrade dialog that sends config with the version change.
