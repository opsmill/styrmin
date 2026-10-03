# Research: Platform-Owned Env Var Injection via Post-Render

**Feature**: 017-post-render-env-vars | **Date**: 2026-10-02 | **Spec**: [spec.md](spec.md)

Decisions below resolve the spec's assumptions and the brief's single open question. D-001 and
D-002 were verified empirically with `kubectl kustomize` (kustomize v5.7.1, the same kyaml
strategic-merge engine Flux helm-controller's post-renderer embeds); the fixtures live in the
session scratchpad and are reproduced inline where they matter.

---

## D-001 — Strategic merge keyed by container `name`, env keyed by env `name`

**Decision**: Emit one strategic-merge Kustomize patch per (component, workload kind) with
`spec.template.spec.containers: [{name: <component container>, env: [...]}]`, each env entry
rendered as `{name, value, valueFrom: null}`. Targets are `kind: Deployment` and
`kind: StatefulSet`, narrowed by the component's identifier `labelSelector`.

**Verified behaviour** (kustomize v5.7.1):

| Case | Result |
|---|---|
| User entry with a chart entry of the same name (literal) | Replaced in place by name |
| User entry with a chart `valueFrom` entry of the same name | `valueFrom: null` deletes the chart's `valueFrom`; the user `value` remains — valid pod spec |
| User entry with no chart counterpart | Added; `valueFrom: null` is dropped (no literal null in output) |
| Chart entries not named by the patch | Kept, in chart order |
| Other containers / `initContainers` | Untouched |
| `Job` sharing the identifier label | Untouched (kind-restricted target) |
| Container name absent from the matched workload | An image-less container with that name is **added** → API-server validation fails the Helm release (loud failure, matches the spec's edge case) |
| Target matching zero resources | No-op, no error |

**Rationale**: This is the only merge primitive that keeps chart entries and replaces by name.
`valueFrom: null` on every entry is unconditional and safe: deletion of an absent field is a
no-op, and it is the only way to replace a chart `valueFrom` without producing an invalid
`value`+`valueFrom` entry (FR-002, US1 Sc.2).

**Alternatives considered**:

- *JSON-patch `replace` on `/containers/0/env`*: the 008 design ADR-013 retired — clobbers chart
  entries.
- *JSON-patch `add` per entry*: cannot replace by name without knowing the chart's indices.
- *`$patch: merge` / `$setElementOrder` directives*: not needed; kyaml's default list merge
  already keys `env` by `name`.

---

## D-002 — Ordering: patched entries move first; the component container moves to index 0

**Finding** (contradicts the brief's "new entries are appended" assumption): kyaml's associative
list merge emits **patch elements first, in patch order**, followed by the destination's
remaining elements. This applies at two levels:

1. **Env entries**: every user entry (new *and* replacing) lands before the chart's remaining
   entries. A chart entry that references a user var via `$(USER_VAR)` therefore **does** expand;
   a user value referencing a chart var via `$(CHART_VAR)` does **not** (Kubernetes expands only
   references to earlier entries).
2. **Containers**: the patched component container moves to `containers[0]`. Example: a pod
   `[sidecar, main]` patched on `main` renders `[main, sidecar]`.

**Decision**:

- Accept the ordering and document it for driver authors (spec edge case corrected).
- Emit env entries in the resolver's merged-dict order (environment → deployment → component
  insertion order), which is what `component_env_vars` produced, so user-to-user `$(VAR)`
  references keep their current behaviour and output is deterministic across reconciles.
- **Append env patches after every existing post-render patch** in
  `ApplicationHelmReleaseBuilder.build()`. Kustomize applies patches in list order, so the
  scheduling `ResourcesPatch` (JSON patch on `containers/0/resources`) keeps hitting the chart's
  original first container. Verified: with the env patch first, resources moved to `main`; with
  it last, resources stayed on `sidecar` (today's behaviour).

**Consequences**:

- Pod templates are deterministic per resolved config, so steady-state reconciles cause no
  spurious rollouts. Setting the first env var on a multi-container component reorders its
  containers once (a rollout that the env change already implies).
- `actions/primitives.py::get_component_env` copies `containers[0]` env into action Jobs. With env
  vars set, `containers[0]` *is* the component container, so action Jobs inherit user env vars as
  they do today. Selecting the component container by name there is a natural follow-up, not
  required for this feature.

---

## D-003 — Stale values-template env on migrated deployments → replace each HelmRelease spec key on update

**Finding**: The operator applies the HelmRelease via `upsert_custom_resource`, which on update
sends `application/merge-patch+json` (RFC 7386, ADR-045). Merge-patch merges maps recursively and
leaves keys the new body omits untouched. A deployment created before this change carries
values-template env entries in its live `spec.values`:

- **List slots** (`extraEnv`, `extraEnvVars`, the task-manager `env` list): if the migrated
  template stops writing the key, the stale list survives verbatim.
- **Map slots** (infrahub `infrahubServer.infrahubServer.env`, task-worker `env`, neo4j `env`):
  the migrated template still writes the map for its hard-coded wiring, and merge-patch keeps
  every stale user key alongside it. No template-side marker can delete unknown keys.

Either way the chart keeps rendering the old user value from `spec.values`, so clearing it
through Styrmin never reaches the pod — SC-004 fails for every pre-existing deployment that had
env vars set, including the flagship infrahub driver.

**Decision**: On **update**, the operator's HelmRelease apply replaces `spec` wholesale (with
`None` values pruned, exactly as the create path already does) instead of merge-patching it.
Metadata keeps merge-patch semantics so labels, annotations, and Flux's finalizer are preserved.
Scope is the HelmRelease apply in `operator/pipeline.py` only, behind an opt-in flag on
`upsert_custom_resource`; every other custom resource keeps merge-patch.

**Rationale**:

- Styrmin owns the HelmRelease `spec` end to end and rebuilds it from the instance context on
  every reconcile; nothing else writes it (no `suspend` toggling, `patch_helm_release` has no
  callers, Flux writes only `status` and `metadata.finalizers`). Replace semantics make the live
  spec equal the rendered desired state — Constitution §I.
- ADR-045's null markers keep working: `args: null` is pruned → absent → chart default, the same
  outcome merge-patch deletion produced. `command: []` is kept and still skipped by the chart's
  `with` guard.
- ADR-045 §2 rejected full replace because it "reshaped the apply path for **every** resource".
  This decision is scoped to one caller, which answers that objection; the new ADR records the
  narrowed reversal.

**Implementation shape** (detail for tasks): one JSON Patch request
(`application/json-patch+json`) carrying `{"op": "add", "path": "/spec", "value": <pruned spec>}`
plus `add` ops for each owned `metadata.labels` / `metadata.annotations` key (escaped per
RFC 6901). `add` on an existing member replaces it. A single request keeps the generation bump
atomic.

**Alternatives considered**:

- *Document the limitation*: rejected — users could never clear an env var set before the
  migration on infrahub.
- *Clearing markers in migrated templates* (`extraEnv: []`): fixes list slots only; map slots
  stay broken, and it reintroduces template boilerplate the feature exists to remove.
- *Agent-side diff of the live object to emit `null` for vanished keys*: equivalent outcome with a
  GET and a recursive diff on every reconcile; more code, same risk.
- *Server-side apply*: needs field-manager migration of every existing HelmRelease; heavier.

**Spec impact**: adds FR-011 and an edge case (stale values-template entries are removed on the
first reconcile on a migrated driver version). It is the engineering condition for SC-004 on
pre-existing deployments, not new user-facing scope.

**Addendum (found by the US1 E2E, T021)**: the operator builds the HelmRelease from the
StyrminDeployment CR's `spec.context`, and the agent wrote that CR with merge-patch as well. The
context is dumped with `exclude_none=True`, so a cleared env var (or any key dropped from a dict)
stayed in the CR and kept reaching the post-render patches. The agent's three CR applies
(`create_instance_crd`, `update_instance_crd`, `upgrade_instance_crd`) now go through
`_apply_styrmin_deployment_crd`, which passes `replace_spec_keys_on_update=True`: one JSON Patch
with an `add` op per top-level spec key the body sets. `spec.context` is replaced wholesale,
while the server-owned `spec.deletionRequested` (CEL-guarded, never in the agent's body) is left
alone; a full `spec` replace would reset it to its `false` default and be rejected after a delete
request.

**Revision (post-review, 2026-10-02)**: the HelmRelease apply now uses the same per-key mode
(`replace_spec_keys_on_update=True`) and the wholesale `add /spec` mode is removed. "Nothing else
writes the spec" held for Styrmin code but not for people: `flux suspend hr` sets `spec.suspend`,
and a whole-`spec` replace undid it on the next update. Per-key replace still drops stale nested
keys under `spec.values` (the FR-011 fix) and keeps spec keys Styrmin never writes, as merge-patch
did. `spec.postRenderers` is written on every render (the label patches are unconditional), so it
cannot go stale. Rule for both callers: Styrmin owns each top-level spec key it writes; everything
else merges (ADR-057 §6).

---

## D-004 — Driver specification: optional `components.<name>.container`

**Decision**: Add `container: str | None = None` as a typed field on the driver-side component
model (`services/driver/models/resources/driver.py::ArbitrarySectionModel`) and on the
context-side model (`context/models/components.py::ArbitrarySectionModel`). Validate as a
Kubernetes container name (DNS-1123 label: `^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`, ≤ 63 chars); a
malformed value fails driver registration (FR-001).

**Storage**: none new. The component definition dict already lands in
`ApplicationDriverVersion.components` (JSON) and `ComponentConfig.config` (JSON), and is copied
to each deployment's `Component.config` on deploy and on driver-version switch
(`services/deployment.py`). Because both Pydantic models already use `extra="allow"`, the value
round-trips today; the typed field adds validation and a stable accessor. **No Alembic revision.**

**Interaction with `container_overrides[].container`**: stays informational (out of scope). No
cross-validation in v1; noted as a follow-up when `command`/`args` move to post-render.

---

## D-005 — FR-005 read flag: new `ComponentEnvVars.isApplicable`, not a reuse of `isOrphaned`

**Decision**: Add `isApplicable: Boolean!` to the `ComponentEnvVars` GraphQL type. It is `false`
when the block cannot reach any container: the component is orphaned (`isOrphaned: true`) **or**
the driver declares no component container for it. `isOrphaned` keeps its current meaning.

**Rationale**:

- Reusing `isOrphaned` would change its documented meaning ("the driver no longer declares this
  component") and send users to the wrong fix (rename vs. wait for a driver that declares a
  container).
- "Applicable" names a condition, not a timing state; "applied" would read as "rolled out yet?".
- Computing it in the GraphQL resolver from the driver version's component configs keeps the
  pure resolver and the stored instance-context schema (`ResolvedComponentEnvVars`) unchanged.

**Alternatives considered**: an enum `notAppliedReason`; deriving from a nullable
`componentContainer` on the entry. Both carry more than the UI needs today.

---

## D-006 — Component container on the GraphQL read paths

**Decision**: Add `container: String` to:

- `ComponentConfig` (driver version, `ApplicationDriverVersion.componentConfigs`) — the brief's
  "driver-version read path"; shown in the driver detail Components tab
  (`frontend/src/pages/drivers/driver-detail/tabs/ComponentsTab.tsx`) and in SDK `load_version`
  results.
- `Component` (deployment, `Deployment.components`) — what the deployment configuration editor
  already iterates, so FR-006 needs no extra query.

Both resolve from the stored component definition (`config["container"]`). Each gets a
propagation test (Constitution §V).

---

## D-007 — FR-003 write validation: new `COMPONENT_CONTAINER_NOT_DECLARED`

**Decision**: New `ComponentContainerNotDeclaredError(ServiceError)` in
`services/env_vars/exceptions.py`, `error_code = "COMPONENT_CONTAINER_NOT_DECLARED"`, metadata
`{component_name, components_with_container}`. Raised by a new validator in
`services/deployment.py` that runs next to `_validate_component_env_var_targets` on every write
path that already calls it (`update_deployment`, `deploy`), before any task is submitted.

**Rule**: for a component without a component container **in the target driver version**, reject
the submitted component-scope block when it **adds a key or changes a value** relative to the
stored block. Unchanged re-submissions and removals (submitted ⊆ stored, compared as dicts) pass.

| Submitted vs stored (containerless component) | Result |
|---|---|
| identical | accepted |
| subset (keys removed) | accepted |
| new key | `COMPONENT_CONTAINER_NOT_DECLARED` |
| changed value | `COMPONENT_CONTAINER_NOT_DECLARED` |

**Target version**: the driver version the deployment will be pinned to after the mutation
(resolved in `update_deployment` before any task is submitted, where it is the current version
since `updateDeployment` never switches versions; on `deploy`, the selected version). This
deliberately differs from `_validate_component_env_var_targets`, which checks the pre-switch
version: validating the pre-switch version would let a version-switching write store
values on a component that loses its container (inert, violating SC-005) and wrongly reject
values on a component that gains one. The existing unknown-component check is left unchanged.

**Rationale**: after a driver upgrade drops a component container (FR-005), stored values must
stay. The frontend submits the full `components` list, and `styrminctl apply` submits full
manifests; rejecting an unchanged re-submission would block every unrelated edit on that
deployment, and rejecting removals would break the FR-006 remove control. Added or changed
values are still rejected 100% of the time (SC-005). (Critique E1, E2.)

---

## D-008 — FR-007 retired filter: typed render error

**Decision**: Keep `component_env_vars` registered in `get_jinja_environment()` as a stub that
raises `RetiredTemplateFilterError(ServiceError)` (`error_code = "RETIRED_TEMPLATE_FILTER"`,
metadata `{filter, migration_guide}`), with a message naming
`https://styrmin.pages.dev/docs/drivers/migrating-env-vars`. Raising from inside the filter
aborts rendering before a HelmRelease is built, so nothing partial is applied. The operator
pipeline's existing `except Exception` path records the message on the instance.

**Alternatives considered**:

- *Unregister the filter*: Jinja raises a generic `TemplateAssertionError` ("no filter named…")
  with no pointer to the migration.
- *Also reject at driver load*: friendlier, but outside the brief's FR-007; existing registered
  versions still need the render-time error. Recorded as a follow-up.

`component_command` / `component_args` stay (out of scope).

---

## D-009 — Patch builder placement and skips

**Decision**: New `build_env_var_patches(context)` in a new module
`services/env_vars/patch_builder.py` (mirrors `services/scheduling/patch_builder.py`), returning
`list[TargetPatch]` of a new `ContainerEnvPatch(Patch)` block in `blocks/patches.py`. For each
component in `context.components`:

- skip when `config.container` is `None` (FR-004, FR-005);
- skip when `env_vars` is `None` or `env_vars.config` is empty (nothing to inject; clearing works
  because patches are regenerated each reconcile — FR-010);
- skip orphans (they never reach `context.components`; unchanged);
- emit one patch per kind in `("Deployment", "StatefulSet")`.

Disabled components still get patches (replica count is governed by the existing
`SpecPatch(replicas=0)`). With no components declared, deployment-scope env vars have no effect
(spec out-of-scope bullet). Patches are eagerly rendered and serialisation failures raise a typed
`OPERATION_FAILED` error, like `_validate_renders` for scheduling.

---

## D-010 — In-repo driver container names

**Decision**: Every component of every in-repo example driver declares a component container
(FR-008). Names below come from `helm template` of each chart with the driver's
`fullnameOverride`; implementation re-verifies them by rendering each driver.

| Driver | Component → container |
|---|---|
| simple-app | server → `simple-app`; database → `postgresql` |
| db-test | server → `db-test`; mariadb → `mariadb`; mongodb → `mongodb` |
| infrahub (4.33.2), infrahub-enterprise (4.19.2) | server → `infrahub-server`; task-worker → `infrahub-task-worker`; database → `neo4j`; cache → `redis`; message-queue → `rabbitmq`; task-manager → `prefect-server`; task-manager-db → `postgresql` |
| infrahub-mcp | server → `infrahub-mcp` |
| semaphore | server → `semaphore`; database → `postgresql` |
| slurpit | portal → `slurpit-portal`; warehouse → `styrmin-slurpit-warehouse`; scanner → `slurpit-scanner`; scraper → `slurpit-scraper`; mariadb → `slurpit-mariadb`; mongodb → `styrmin-slurpit-mongodb` |

Each migrated `values.j2.yml` drops every `component_env_vars` call and keeps only hard-coded
chart wiring. For infrahub and infrahub-enterprise, the task-manager `prefect-server.server.env`
override would still carry the hard-coded `PREFECT_SERVER_ANALYTICS_ENABLED` and so still replace
the chart's list. The prefect-server subchart merges a secondary list, `global.prefect.env`, under
`server.env` (dedupe by name, `server.env` wins — `_helpers.tpl`). The migrated templates move
the flag to `global.prefect.env` and drop the `server.env` override entirely, so the chart's
`server.env` defaults render untouched without being copied (SC-002, SC-003). Verified: the
prefect-server `deployment.yaml` renders `global.prefect.env` ahead of `server.env` in both the
4.33.2 and 4.19.2 bundled subcharts (`templates/deployment.yaml:134-138`).

Each migrated driver bumps its `spec.version` so a new driver version row is registered
(ADR-053); deployments pinned to old versions hit the FR-007 error on their next render until
upgraded.

---

## D-011 — E2E coverage (reuse before you boot)

- **US1** — new test in `backend/tests/e2e/test_deployment_env_vars.py` reusing the module's
  `env_vars_deployment` (simple-app): set component-scope `LOG_LEVEL=debug` on `server`, assert it
  plus `STYRMIN_CHART_DEFAULT=marker`; override `STYRMIN_CHART_DEFAULT` and
  `STYRMIN_CHART_DEFAULT_FROM` (a new harmless chart-default entry with
  `valueFrom.fieldRef: metadata.name`, added to the simple-app chart so US1 Sc.2 is E2E-covered —
  critique P5); clear all three and assert both chart defaults are back. **Dual-entrypoint**: drives a new `ScenarioDriver.set_component_env_vars`
  method (SDK on `[api-chromium]`, deployment Configuration editor on `[ui-chromium]`). Also seeds
  a stray `extraEnv` entry into the live HelmRelease `spec.values` via kr8s, triggers a reconcile,
  and asserts it is gone (D-003).
- **US2** — existing `test_us2` / `test_us3` re-run against the migrated simple-app; no new node.
- **SC-003** — read-only assertion added to
  `test_infrahub_services.py::test_infrahub_task_manager_service_exposes_prefect_ui` on the
  already-booted `deployed_infrahub_enterprise_app`: the `prefect-server` container is Ready and
  carries the chart default `PREFECT_UI_SERVE_BASE=/` (the enterprise 4.19.2 chart's prefect env
  default; it renders no `PROMETHEUS_MULTIPROC_DIR`). The community chart's
  `PROMETHEUS_MULTIPROC_DIR=/tmp` is pinned by a unit test asserting the migrated `infrahub`
  `values.j2.yml` renders no `prefect-server.server.env` key. Booting the community stack for one
  assertion would resurrect a fixture whose only consumer is skipped.
- **US4/US5** — unit, propagation, and frontend component tests (no user flow beyond a rejected
  mutation or a read flag).
