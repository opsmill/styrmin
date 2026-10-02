# ADR-055: Post-Render Component Overrides into a Declared Component Container

**Status**: Accepted
**Date**: 2026-10-02
**Source**: specs/017-post-render-env-vars/ (spec, plan, research D-001 – D-011, critique)
**Supersedes**: [ADR-013](0013-driver-env-var-consumption.md) §1 and the FR-026
non-feature it records ("no platform-side post-render env var injection"). ADR-013 §2
and §5 no longer describe how env vars reach pods; ADR-013 §3 (merged dicts) and the
resolver are unchanged.
**Narrows**: [ADR-045](0045-container-override-no-layering-and-omit-marker.md) §2 and §5 —
the operator replaces each HelmRelease spec key Styrmin writes on update instead of
merge-patching it (see §6).
**Related**: [ADR-035](0035-post-render-injection-toggles-and-kind-list.md) (the post-render
patch pipeline this extends), [ADR-004](0004-embed-context-in-deployment-crd.md) (the
StyrminDeployment CR carries the context), [ADR-012](0012-environment-config-fanout.md)
(environment env var fan-out), [ADR-048](0048-declarative-apply-client-side-orchestration.md)
(`apply` ordering).

## Context

Since 010 ([ADR-013](0013-driver-env-var-consumption.md)), a driver's `values.j2.yml`
injected user env vars by writing the chart's env key through the `component_env_vars`
filter. Helm replaces lists instead of merging them, so when a chart models env as a list,
writing that key dropped every env entry the chart ships. Bumping the `infrahub` driver to
chart `4.33.2` lost the task manager's `PROMETHEUS_MULTIPROC_DIR=/tmp` and
`PREFECT_UI_SERVE_BASE=/`; the task manager crash-looped while the deployment looked healthy
([#334](https://github.com/opsmill/styrmin/issues/334)). Driver authors worked around it by
copying chart defaults into the template and re-syncing them on every chart bump
([#385](https://github.com/opsmill/styrmin/issues/385)).

ADR-013 §1 rejected per-container strategic merge because the platform does not know the
chart's container names, and asking drivers to declare them looked more intrusive than
template wiring. In practice the template route needed per-chart wiring, chart-default
copies, and shape knowledge (map vs list) in every driver, while the declaration is one name
per component. Image overrides ([#20](https://github.com/opsmill/styrmin/issues/20)) need
the same answer to "which container?".

## Decision

### 1. Drivers declare one component container per component

`components.<name>.container` in the driver specification file names the **component
container**: the container in the component's pod template that receives per-component
post-render overrides. It is optional. A value that is not a Kubernetes container name
(DNS-1123 label, at most 63 characters) fails driver registration.

The name rides the component definition in existing JSON columns
(`ApplicationDriverVersion.components`, `ComponentConfig.config`, and each deployment's
`Component.config`, copied on deploy and on a driver-version switch). No schema change, no
Alembic revision. It is read through `ComponentConfig.container` (driver version) and
`Component.container` (deployment). One name per component in v1; it may widen later to a
list whose first entry is primary.

### 2. Env vars merge into that container by a strategic-merge post-render patch

`build_env_var_patches()` (`services/env_vars/patch_builder.py`) emits one
`ContainerEnvPatch` per workload kind in `(Deployment, StatefulSet)` for every component
that has a component container and non-empty, non-orphaned resolved env vars. Each patch is
targeted by the component's identifier label selector and names the component container,
with one `{name, value, valueFrom: null}` entry per env var in resolution order.

kyaml (the strategic-merge engine in Flux's Kustomize post-renderer) merges containers by
`name` and env entries by `name`, which gives:

- chart env entries the patch does not name survive;
- a same-name chart entry is replaced, including a `valueFrom` entry (`valueFrom: null`
  deletes it, so the result is a valid literal);
- other containers and init containers are untouched;
- `Job`, `CronJob`, and `DaemonSet` are never targeted. This is deliberately narrower than
  ADR-035's six-kind list: chart Jobs (migrations, hooks) often share the component label.

Resolution is unchanged: per-key deepest-wins, environment → deployment → component.
Components without a component container are skipped silently for deployment- and
environment-scope env vars. Disabled components still get patches; their replica count is
governed by the component state patch. Patches are regenerated on every render, so clearing
an env var needs no marker.

### 3. Env patches go last, and the ordering is observed, not guaranteed

kyaml's associative list merge emits the patch's elements first, in patch order, then the
destination's remaining elements (verified with kustomize v5.7.1, research D-002):

- user entries, new and replacing, come before the chart's remaining entries. A chart entry
  that references a user var with `$(USER_VAR)` expands; a user value that references a
  chart var with `$(CHART_VAR)` does not;
- the component container moves to `containers[0]`.

`ApplicationHelmReleaseBuilder.build()` appends the env patches after every other patch so
the scheduling `ResourcesPatch` (a JSON patch on `containers/0/resources`) still lands on the
chart's original first container. This ordering is kyaml implementation behaviour, not a
documented contract; tests assert outcomes (entries present, values replaced, resources on
the original container) rather than full order.

### 4. The `component_env_vars` filter fails rendering

The filter stays registered as a stub that raises `RetiredTemplateFilterError`
(`RETIRED_TEMPLATE_FILTER`, metadata `filter` and `migration_guide`). Rendering aborts
before a HelmRelease is built, so nothing partial is applied. The message tells deployment
users to upgrade the deployment and driver authors to declare containers, and names
`https://styrmin.pages.dev/docs/drivers/migrating-env-vars`. On the live path the typed code
and metadata do not survive the StyrminDeployment CR → operator hop: the operator records
`Failed to create HelmRelease: <message>` on the deployment, and the full message and URL
survive.

There is no deprecation window: Styrmin is pre-1.0 and third-party drivers are few.
`instance.config.env_vars` and `components[<name>].env_vars.config` stay in the rendering
context as read-only data (for example to build a ConfigMap). Writing them into a chart env
key brings the list-replacement problem back.

### 5. Writes that cannot reach a container are rejected; stored values are kept

`updateDeployment` and `deploy` raise `COMPONENT_CONTAINER_NOT_DECLARED` (metadata
`component_name`, `components_with_container`) when a component-scope block adds a key or
changes a value on a component that declares no component container in the deployment's
pinned driver version. Removals and unchanged re-submissions pass, so full-config edits of
other fields keep working and stranded values can be removed. Component rows stored before
this change carry no `container` key and count as containerless.

A driver upgrade that drops a component container keeps the stored values. They read back
with `ComponentEnvVars.isApplicable: false` (`not isOrphaned and container != null`) and are
never injected. `isOrphaned` keeps its meaning (the driver no longer declares the component).
The deployment edit drawer offers no env var editor for a containerless component; stored
values there are read-only and removable.

### 6. Styrmin replaces each spec key it writes on update

The operator applied the HelmRelease with JSON merge-patch (RFC 7386), which leaves keys the
new body omits in place. A deployment created before migration carries values-template env
entries in its live `spec.values`: list slots (`extraEnv`, `extraEnvVars`) survive when the
migrated template stops writing them, and map slots keep stale user keys next to the
hard-coded wiring. A merge-patch can delete a map key only through an explicit `null`, and
the template cannot know which keys an earlier render wrote, so no marker clears a map slot.
The chart would keep rendering the old value, and clearing an env var through Styrmin would
never reach the pod.

Both the HelmRelease apply (`operator/pipeline.py`) and the agent's StyrminDeployment CR
create, update, and upgrade applies (`agent/tasks/orchestration.py`) pass
`replace_spec_keys_on_update=True` to `upsert_custom_resource`. On a 409 it sends one JSON
Patch (`application/json-patch+json`): one `add` per top-level `spec` key the body sets
(`None` pruned), plus one `add` per `metadata.labels` and `metadata.annotations` key the body
sets (RFC 6901 escaping). The rule is: **Styrmin owns each top-level spec key it writes;
everything else merges.**

- Keys Styrmin writes are replaced, so nested keys it stopped writing disappear:
  `spec.values` on the HelmRelease, `spec.context` on the CR (dumped with
  `exclude_none=True`, so a cleared env var used to stay there; research D-003 addendum).
  Styrmin writes `postRenderers` on every render (the label patches are unconditional), so
  the list never goes stale.
- Spec keys Styrmin never writes survive, as with merge-patch: `spec.suspend` set by
  `flux suspend hr`, and the server-owned `spec.deletionRequested` on the CR (a whole-`spec`
  replace would reset it to `false`, which the CRD's CEL rule rejects after a delete
  request).
- Flux's finalizer and kopf's annotations are not touched. The create path is unchanged
  (`prune_none_on_create`). Every other custom resource keeps merge-patch.

Effect on ADR-045: §2 rejected a full replace because it "reshaped the apply path for every
resource"; this one is scoped to two callers and to the spec keys they write. Under
per-key replace, an omitted values key no longer lingers, so the always-present `[]` key from
§2 is no longer needed for clearing (it stays harmless and documented). The `null` marker
from §5 is pruned on create and on update, so it reads as absent on both paths and the chart
default applies, the same outcome as before.

## Consequences

- **Chart env defaults survive.** A chart bump needs no env edits in `values.j2.yml`. All
  seven in-repo drivers (28 components) declare containers and no longer wire env vars;
  `infrahub` and `infrahub-enterprise` moved `PREFECT_SERVER_ANALYTICS_ENABLED` to
  `global.prefect.env` and dropped their `prefect-server.server.env` override.
- **Unmigrated driver versions fail loudly.** A deployment pinned to a version whose template
  calls `component_env_vars` fails its next render, including the redeploy an environment env
  var edit fans out to it (ADR-012). Ready deployments are not re-rendered by the operator's
  resume or drift timer, so the failure appears on the next change. The remediation is to load
  migrated drivers and upgrade each deployment first; the migration guide orders the steps.
- **User env vars reach the component container only.** Chart Jobs, CronJobs, init
  containers, and other containers no longer receive them. A chart that fed the same values key
  into a migration Job (the prefect-server chart merges `server.env` into its migrations Job)
  stops passing user env vars there.
- **A wrong container name fails the release, but only once env vars are set.** The merge adds
  an image-less container and the API server rejects the workload
  (`spec.template.spec.containers[0].image: Required value`). In-repo names are verified by
  rendering each chart; a driver lint check is out of scope for v1.
- **Containerless components are skipped silently for broad scopes.** Only `isApplicable` and
  the driver detail Components tab ("None declared") show it. A hint in the deployment- and
  environment-scope editors is deferred (critique P1); every in-repo component declares a
  container, so the case arises only with third-party drivers.
- **Container order changes once.** Setting the first env var on a multi-container component
  moves the component container to index 0, which changes `kubectl logs`'s default container.
  Output is deterministic per resolved config, so steady-state reconciles do not roll pods.
- **`get_component_env` still reads `containers[0]`.** It
  (`agent/service/kubernetes/primitives.py`) copies the env of the pod template's first
  container into `execute_commands(env_from_component=...)` Jobs. With env vars set that is the
  component container, so action Jobs inherit user env vars as before; without them it is the
  chart's first container. Selecting the component container by name is a follow-up.
- **Platform rollback stops injection.** Rolling Styrmin back below this change after loading
  migrated drivers leaves env vars stored but uninjected: the old platform ignores `container`,
  and the migrated templates no longer wire env vars.
- **`styrminctl apply` validates its config write against the pre-switch version.** `apply`
  sends `updateDeployment` before `updateDeploymentVersion` (ADR-048). A manifest that both
  moves to a new driver version and adds component env vars is checked against the old
  version: it is rejected when the old version lacks the container, and stored inert when only
  the new version lacks it (flagged `isApplicable: false`, never injected). Validating against
  the target version in the apply path is a follow-up.
- **Images are next.** Image overrides (#20) reuse the component container and the same
  post-render placement.

## Alternatives Considered

- **Keep values-template injection and fix drivers one by one.** Rejected: every chart with
  list-shaped env needs copied defaults that drift on each chart bump; the defect recurs per
  driver.
- **JSON-patch `replace` on `/containers/0/env`** (the 008 design ADR-013 retired). Rejected:
  clobbers every chart entry.
- **JSON-patch `add` per entry.** Rejected: cannot replace a chart entry by name without
  knowing its index.
- **Re-render the chart server-side and patch by discovered container names.** Rejected for
  the reasons in ADR-013 §1: heavy, couples the platform to chart internals, doubles rendering.
- **Reuse `isOrphaned` for upgrade-stranded values.** Rejected: it would change its meaning
  and point users at the wrong fix (rename the component vs wait for a driver that declares a
  container).
- **Unregister `component_env_vars` instead of a raising stub.** Rejected: Jinja's generic
  "no filter named …" error carries no remediation or guide URL.
- **Clear stale values-template entries with markers in migrated templates** (`extraEnv: []`).
  Rejected: fixes list slots only, cannot delete unknown keys in map slots, and brings back the
  template boilerplate this change removes.
- **Diff the live HelmRelease and emit `null` for vanished keys.** Rejected: same outcome as
  replace, with a GET and a recursive diff on every reconcile.
- **Server-side apply.** Rejected for now: the native ownership model, but every existing
  HelmRelease and CR needs a one-time `managedFields` migration before stale keys are
  removed. A candidate for its own ADR.
- **Replace the whole HelmRelease `spec`** (`add /spec`, the first implementation).
  Rejected: drops spec keys Styrmin never writes, so the next update undoes `flux suspend hr`.
- **Replace the whole StyrminDeployment CR `spec`.** Rejected: resets the server-owned
  `spec.deletionRequested`, which the CEL rule forbids after a delete request; per-key replace
  of the keys the agent writes avoids it.
- **Keep merge-patch and drop FR-011.** Rejected: user env vars set in a map slot before
  migration could never be cleared through Styrmin.
