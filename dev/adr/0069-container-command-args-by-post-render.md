# ADR-069: Container `command` and `args` Overrides Applied by Post-Render

**Status**: Accepted
**Date**: 2026-10-14
**Source**: specs/archive/022-post-render-container-overrides/ (spec, plan, research D-001 to D-012, contracts); [issue #457](https://github.com/opsmill/styrmin/issues/457)
**Supersedes**: [ADR-045](0045-container-override-no-layering-and-omit-marker.md) §2 (the empty-list
marker and the chart `{{- with }}` guard) and §5 (the `null` clear marker for charts without that
guard). Both described how a driver template passed `command` and `args` to the chart, and no
template does that any more.
**Keeps**: ADR-045 §1 (component scope only, no layering), §3 (per-field typed errors) and §4 (a
set value is a non-empty list of strings; `[]` is rejected).
**Extends**: [ADR-058](0058-image-overrides-and-component-container-guard.md) to `command` and
`args`. The strategic-merge patch and the JSON6902 guard that ADR-058 builds for env vars and image
overrides now also carry these two fields, so a wrong container name fails the reconcile with
`COMPONENT_CONTAINER_NOT_FOUND` also when `command` or `args` is the only override.
**Related**: [ADR-057](0057-post-render-component-overrides.md) (the component container, §3 patch
order, §4 retired-filter precedent, §6 per-key replace on update); the user migration guide
[Migrating Container Overrides](../../docs/docs/drivers/migrating-container-overrides.md).

## Context

A user can set a container override: the `command` or `args` of one component in one deployment.
Before this change, the override reached the pod only when the driver's `values.j2.yml` passed the
`component_command` or `component_args` filter to a value that the Helm chart exposes
(ADR-045 §2 and §5). This had three effects:

- When a driver did not call the filters, Styrmin stored the override, did not apply it and
  reported no error. The deployment edit drawer showed the Command and Args editors for every
  component.
- A user could override only the fields that the chart exposes as values. The infrahub chart has no
  `command` value, so the `server` and `task-worker` components of the `infrahub` and
  `infrahub-enterprise` drivers accepted `args` only.
- Each driver author wrote template code that matched how the chart reads the value, so that the
  chart's own value applied when no override was set: an empty list for `simple-app`, whose chart
  skips an empty list, and `null` for the infrahub charts, which render `args` without a check.

Env vars (ADR-057) and image overrides (ADR-058) already reached pods through post-render patches
to the component container that the driver declares, with no template code. `command` and `args`
were the only per-component container overrides left on the values template.

## Decision

### 1. The container merge patch carries `command` and `args` (research D-001)

`ContainerEnvPatch` is renamed `ContainerMergePatch`
(`agent/service/kubernetes/resources/blocks/patches.py`) and gains `command: list[str] | None` and
`args: list[str] | None` next to `env`. The patch names the component container and writes each
field only when it is set, so a field without an override keeps the value the chart renders. The
JSON6902 guard `ComponentContainerPatch` and the order inside `spec.postRenderers` do not change
(ADR-057 §3, ADR-058 §3).

`command` and `args` are lists of strings with no `patchMergeKey` in the Kubernetes schema, so
kustomize's strategic merge replaces the whole list. This was checked on 2026-10-14 with
`kubectl kustomize` (kustomize v5.7.1) on a Deployment with an init container, a sidecar and the
component container, with the guard applied after the merge:

- an `args` patch replaced the whole `args` list of the component container and kept the chart's
  `command`;
- the sidecar and the init container did not change;
- the component container moved to `containers[0]`;
- the strings `'yes'`, `'8000'`, `''`, `'null'` and `$(HOME)` came out as the same strings;
- a wrong container name failed the render at the guard, which `parse_guard_failure` reads as
  `COMPONENT_CONTAINER_NOT_FOUND`.

The patch is serialised with `yaml.dump` only. User strings are never formatted into YAML text, so
a value that contains a newline and `- op: remove` stays one list element and cannot add patch
operations.

### 2. One rule decides whether an override applies (research D-002)

`services/component_container/overrides.py` holds the rule and the value it produces:

- `override_applies(container, is_orphaned)` returns true only when the component declares a
  component container and the override is not orphaned.
- `ApplicableOverrides` is a frozen dataclass with `env`, `image`, `command` and `args`, and an
  `is_empty` property.
- `applicable_overrides(name, component, version)` builds that value from a `ComponentContext`,
  with every override checked by `override_applies`. The image override has `{{ app.version }}`
  replaced by `version` and is validated, as before. It replaces `applicable_env` and
  `applicable_image`.

The patch builder and the action primitives (`get_component_images`, `execute_commands`) call
`applicable_overrides`. The GraphQL read fields `ComponentEnvVars.isApplicable`,
`ComponentImageOverride.isApplicable` and the new `ComponentContainerOverrides.isApplicable` call
`override_applies` with the deployment's component container and the entry's orphan flag, because
the read path has no `ComponentContext`.

`execute_commands(env_from_component=...)` now also resolves the image override when it reads the
env vars, so an image reference that is invalid at the context's application version raises
`InvalidImageReferenceError` there. Such a reference is already rejected on write and before an
application version change (ADR-058 §5), so the sources expect no new failure in practice.

### 3. The patches are built when any override applies (research D-003)

`build_component_container_patches` builds the merge patch and the guard for a component when
`applicable_overrides(...).is_empty` is false. A component whose only override is `command` or
`args` therefore gets the guard, and a wrong container name fails the reconcile with
`COMPONENT_CONTAINER_NOT_FOUND` (spec FR-004). The log line records `command_set` and `args_set` as
booleans and never the values, because `args` often carry flags such as `--password=...`.

A cleared override needs no marker. The patches are built again on every render; with no stored
value the field is not in the merge patch, or no patch is built when nothing else applies, so the
chart's own `command` and `args` reach the pod. The change to `spec.postRenderers` reaches the
HelmRelease because the operator replaces each spec key it writes on update (ADR-057 §6). The E2E
run recorded in `specs/archive/022-post-render-container-overrides/e2e-evidence.md` read the container
after a clear and found the values captured before any override was set; the operator's change
detection needed no fix (research D-012).

### 4. The `component_command` and `component_args` filters are retired (research D-004)

Both filters stay registered in `get_jinja_environment()` as stubs that raise
`RetiredTemplateFilterError` (`RETIRED_TEMPLATE_FILTER`, metadata `filter` and `migration_guide`),
as `component_env_vars` does (ADR-057 §4). The helper `_resolved_container_override` is deleted.

`RetiredTemplateFilterError` builds its message from the filter name. For the two container
override filters the message tells deployment users to move the deployment to a driver version
that no longer calls the filter, tells driver authors to remove the filter call and declare
`components.<name>.container`, and links `CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL`
(`https://styrmin.pages.dev/docs/drivers/migrating-container-overrides`, in
`services/exceptions.py`). The `component_env_vars` message and URL do not change.

The stubs raise whatever the context holds, so a driver version that calls them fails its next
render also when no override is set. The operator records `Failed to create HelmRelease:
<message>` and applies no HelmRelease, so the pods that run keep running. There is no deprecation
period, because Styrmin is before version 1.0 and few third-party drivers exist (spec A-003).

A driver version that calls a retired filter is also rejected when it is loaded (added after the PR
review). `JinjaTemplateValidator` (`services/driver/validators.py`) walks the `Filter` nodes of the
parsed `values.j2.yml`, also inside conditions and filter blocks, and raises
`RetiredTemplateFilterError` with `retired_filter_load_message()`, which names the line of the call.
This covers `component_env_vars` too. The render-time stubs stay registered for driver versions
loaded before this check.

### 5. A component without a component container accepts no `command` or `args` (research D-005)

In `services/deployment.py`:

- `ComponentContainerSlot` (now in `services/env_vars/exceptions.py`) is
  `Literal["env_vars", "image", "command", "args"]`, and `_validate_component_container_targets`
  checks all four slots by default.
- `_slot_adds_or_changes` treats `command` and `args` like `image`: a write adds or changes the
  slot when the submitted value is not `None` and differs from the stored value. A removal (`null`
  or an omitted key) and the same list sent again pass.
- `ComponentContainerNotDeclaredError` accepts `override="command"` and `override="args"`, and its
  message names the field.

The order of checks does not change: unknown component and list shape first, the container check
last, on `deploy`, `updateDeployment` and `updateDeploymentVersion`. The SDK, `styrminctl apply`
and the UI call these mutations, so they get the same check. The check reads the driver version
that the deployment is pinned to after the write.

### 6. `spec.container_overrides` is removed (research D-006 to D-008)

The block only documented which components accepted an override; the component container now
answers that question. It is removed from the driver format, the database and the API:

- `Specification` no longer has the field. A driver file that still contains the block fails to
  load: a `before` model validator raises a `removed_key` error that names the block and links
  `CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL` (changed after the PR review from the generic
  `extra_forbidden` error, which named neither). Other unknown keys under `spec` keep the generic
  error. The old validator, its loader call and `DriverContainerOverrideDocComponentMismatchError`
  (`DRIVER_CONTAINER_OVERRIDE_DOC_COMPONENT_MISMATCH`) are deleted.
- The Alembic revision `faf47e166160` drops `applicationdriverversion.container_overrides`. Its
  downgrade adds the column back, nullable and empty.
- GraphQL loses `ApplicationDriverVersion.containerOverrides` and the `DriverContainerOverrideDoc`
  type, and the SDK loses `get_driver_container_override_docs`.

No error code is added (spec FR-011).

## Consequences

- A driver needs no template code for `command` and `args`; declaring the component container is
  enough. A user can override `command` on the infrahub `server` and `task-worker` components,
  which the old templates could not pass.
- The example drivers moved to new versions: `simple-app` 3, `infrahub` 4 and
  `infrahub-enterprise` 3. A deployment pinned to an older version of these drivers fails its next
  render until it moves to a migrated version.
- Some stored overrides apply for the first time after the move, for example `command` on the
  infrahub `server` component, or any stored value on a driver whose template never called the
  filters. The migration guide tells users to review stored values before the move.
- An override reaches the component container only. Other containers, init containers, and
  `Job`, `CronJob` and `DaemonSet` workloads are not patched. In the in-repo charts the `command`
  and `args` values reached only the component container (spec A-002), so stored overrides give
  the same container `command` and `args` before and after the move. The parity test
  `backend/tests/integration/test_container_override_migration_parity.py` checks this for the
  three example drivers.
- Once any override applies, the component container is `containers[0]`, which changes the default
  container of `kubectl logs` for pods with several containers (ADR-057 §3).
- An empty list is still rejected, so an override cannot remove the chart's `command` to fall back
  to the image's `ENTRYPOINT`.
- The deployment edit drawer shows the Command and Args editors only on a component with a
  component container. A stored value on a component without one is shown read-only with a **not
  applied** badge and can be removed.
- `styrminctl deployments apply` reads `isApplicable` back for env vars, image overrides and
  `command`/`args` overrides, and warns about a component whose submitted overrides do not apply.
- The action primitives use the env vars and the image override from `applicable_overrides`.
  `command` and `args` overrides do not reach action Jobs.
- Rolling Styrmin back below this change after loading migrated drivers stops container overrides:
  the older release applies them only through the filters, which the migrated templates no longer
  call. The stored values are kept.
- The `prune_none_on_create` flag that ADR-045 §5 added to the HelmRelease apply is unchanged.
- The list replacement is observed kustomize behaviour, not a documented contract. The E2E reads
  the pod template after set, change and clear on the helm-controller that the agent chart
  installs.

## Alternatives Considered

- JSON6902 `add` operations for `/command` and `/args` inside the guard patch. RFC 6902 `add`
  replaces an existing member, so this also works. Rejected because it puts value overrides into
  the guard, which only moves and checks the container, and because the PRD chose the merge patch.
- A separate strategic-merge patch per field. Rejected: more patches per workload with no gain.
- Keeping the name `ContainerEnvPatch`. Rejected: the name would describe one of three fields.
- Adding `applicable_command` and `applicable_args` next to `applicable_env` and
  `applicable_image`. Rejected: four copies of the same condition.
- Building a `ComponentContext` in the GraphQL read fields. Rejected: the read path would need the
  whole rendering context for one boolean.
- Unregistering the two filters. Rejected: Jinja would fail with "No filter named ...", which names
  no migration guide.
- Keeping the template route and fixing drivers one at a time. Rejected for the reasons in the
  Context: a driver that does not call the filters stores overrides without applying them, and each
  driver repeats chart-specific template code.

## Out of Scope

The spec leaves these out; no decision was taken on them:

- removing a `command` or `args` that the chart renders, so that the image's `ENTRYPOINT` or `CMD`
  applies;
- overrides on init containers, other containers, or `Job`, `CronJob` and `DaemonSet` workloads;
- more than one component container per component;
- environment-scope or deployment-scope `command` and `args`;
- a UI or CLI list of the overrides that start to apply after the move to a migrated driver
  version;
- a way to find the deployments pinned to driver versions that call the retired filters;
- `{{ app.version }}` substitution in `command` and `args`.
