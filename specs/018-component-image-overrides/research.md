# Research: Per-Component Image Overrides via Post-Render

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-03

All Kustomize behaviour below was verified with `kubectl kustomize` (kustomize v5.7.1, the
version ADR-057's research used) against a fixture Deployment with
`initContainers: [init]`, `containers: [sidecar, main]` and a `Job` sharing the component label.
The E2E guard test (test 3) re-verifies the guard on the agent's real `fluxcd/helm-controller:v1.1.0`.

## D-001 — Image patch: name-only strategic merge, then JSON6902 on `containers/0`

**Decision**: For every component with a component container and an applicable image override,
emit per workload kind (`Deployment`, `StatefulSet`), targeted by the component's identifier label:

1. a strategic-merge patch `containers: [{name: <container>, env: [...]?}]` (the env entries
   only when env vars apply, see D-003). kyaml moves the named container to `containers[0]`,
   or adds an image-less container with that name when it is missing;
2. a JSON6902 patch that moves `containers/0` to a named key, replaces its `image`, and moves it
   back (D-002 gives the exact op list and why).

**Verified behaviour**:

| Case | Result |
|---|---|
| Strategic merge `{name: main, image: X}` on an existing `main` | `main` gets image X, moves to index 0, keeps env and `imagePullPolicy` |
| Strategic merge `{name: wrong, image: X}` (name missing) | **A new container `wrong` running X is added** — the API server accepts it. This is the hazard FR-007 forbids |
| Strategic merge `{name: main}` (name only) | `main` moves to index 0, nothing else changes |
| JSON6902 `replace /containers/0/image` on a container without `image` | **Succeeds** (the implementation adds the key) — `replace` cannot act as a guard |
| JSON6902 `remove /containers/0/image` on a container without `image` | Fails: `error in remove for path: '<path>': Unable to remove nonexistent key: image: missing value` |
| JSON6902 `test` with `value: null` on a missing key | Passes (missing reads as null) — the inverse of what a guard needs |
| JSON6902 `copy` from a missing key | Succeeds and writes `null` |
| JSON6902 `move` from a missing key | Fails, but the message names only the last key (`path: 'image'`) |
| JSON6902 target matching zero resources | No-op, no error |
| `initContainers`, other containers, `Job` sharing the label | Untouched |

**Rationale**: strategic merge is the only primitive that finds a container by name; JSON6902 is
the only one that can fail on a missing field. Chained, they set the image on the named container
and fail the render when the name is wrong, without ever adding a container.

**Alternatives considered**:

- *Strategic merge carrying `image`*: verified to add a working extra container on a wrong name.
- *Kustomize `images:` transformer*: release-wide, matches by image name, cannot target one
  component when several share an image (infrahub `server` / `task-worker`). Kept for the separate
  registry-mirror issue.
- *JSON6902 alone by index*: Styrmin does not know the chart's container index.
- *Values-template wiring*: rejected by the direction-change comment and ADR-057 (every driver
  must wire every override; silent no-op when it doesn't).

## D-002 — The guard names the component and the container in the error

**Problem**: the plain `remove /spec/template/spec/containers/0/image` error carries a fixed path,
so a failure cannot say which component or container is wrong.

**Decision**: the JSON6902 patch first moves the container object to a key that encodes both names,
operates on it there, then moves it back to index 0:

```yaml
- op: move
  from: /spec/template/spec/containers/0
  path: /spec/template/spec/styrmin.io~1component-container~1<component>~1<container>
# image override present:
- op: remove                     # guard: fails when the container was added image-less
  path: /spec/template/spec/styrmin.io~1component-container~1<component>~1<container>/image
- op: add
  path: /spec/template/spec/styrmin.io~1component-container~1<component>~1<container>/image
  value: <resolved reference>
# env vars only (D-003): save, guard, restore
#   copy  …/image → …/styrmin-image ; remove …/image ; move …/styrmin-image → …/image
- op: move
  from: /spec/template/spec/styrmin.io~1component-container~1<component>~1<container>
  path: /spec/template/spec/containers/0
```

`<component>` and `<container>` are JSON-pointer escaped (`~` → `~0`, `/` → `~1`). Verified: when
the container exists the output equals the plain strategic-merge result plus the new image; when
it is missing the build fails with
`error in remove for path: '/spec/template/spec/styrmin.io~1component-container~1server~1wrong/image': Unable to remove nonexistent key: image: missing value`.

**Rationale**: the error text now identifies the component and container, so the operator can turn
it into a typed status (D-004) without re-rendering anything. The temporary key never reaches the
API server: it is moved back in the same patch.

**Alternatives considered**: one plain `remove` and naming every candidate component in the status
(imprecise when several components carry overrides); an annotation marker (not tied to the
container's existence).

## D-003 — One guard for env vars and images (resolves the brief's open question)

**Decision**: yes. The guard runs for every component that receives any component-container patch:
an image override, env vars, or both. For env-var-only components the JSON6902 patch saves the
image, removes it (guard), and restores it. Verified: output is identical to the env-var strategic
merge alone when the container exists.

**Rationale**: without the guard, setting an image on a misnamed component would make the added
container valid, which also silences the loud failure env vars rely on today (ADR-057
consequences). One guard gives one typed failure for both overrides.

**SC-002 check**: deployments without any component-container patch get no new patches. Deployments
with env vars get the extra JSON6902 patch, which leaves the rendered workloads byte-identical, so
no pod restarts. Flux records one new Helm revision on the first reconcile after the Styrmin
upgrade, as for any `postRenderers` change.

## D-004 — Surfacing the guard failure (FR-007, SC-005)

**Finding**: the guard fails inside Flux's post-renderer, after the operator applied the
HelmRelease. Today the operator never reads a HelmRelease's failure: a failed release shows up only
as the 300 s readiness timeout ("Deployment did not reach Ready within 300s"), with no cause.

**Second finding (critique E1)**: on a spec update the operator keeps the conditions of the previous
rollout, so `HelmReleaseReady` is still `True`. The timer's `CREATING_HELM_RELEASE` branch then
skips the HelmRelease check and moves to `Ready`. `_check_helmrelease_ready` also ignores
generation. A check placed only on the "waiting for Ready" path would never see a guard failure on
an existing deployment.

**Decision**: on every tick in phase `CREATING_HELM_RELEASE` **or** `READY`, the operator's
StyrminDeployment timer reads the HelmRelease. When its `Ready` condition is not `True` (`False`, or
`Unknown` while the key is only under `Released`; reconciled 2026-10-04) for the current
generation (the condition's `observedGeneration`, else `status.lastAttemptedGeneration`, equals
`metadata.generation`, so a stale message from a fixed revision is ignored) and **any** condition
message contains the guard key `styrmin.io~1component-container~1` (robust to helm-controller
reporting it under `Ready` or `Released`), the operator parses the component and container from the
key and fails the deployment at once: `phase: Failed`, `displayState: Error`, condition reason
`ComponentContainerNotFound`, and the message of a typed `ComponentContainerNotFoundError`
(`COMPONENT_CONTAINER_NOT_FOUND`): *"Component 'server': component container 'wrong' was not found
in its rendered workload. Styrmin never adds a container; fix `components.server.container` in the
driver specification file."* The status reporter carries it to `Deployment.crdStatus.message`.

Only this signature is matched. Other HelmRelease failures keep today's behaviour (Flux
remediation, then the timeout), because they may be transient. The guard failure is deterministic
for a given config, so failing at once is safe. A later config or driver change re-applies the
HelmRelease and leaves `Failed` the usual way.

The failure is visible within one or two timer intervals (60 s by default): on an update, the first
tick may still advance to `Ready` from the stale condition, and the next one fails it.

**Alternatives considered**: surfacing every HelmRelease failure (broader behaviour change, out of
scope; recorded as a follow-up in ADR-058); resetting `HelmReleaseReady` on every update so the
existing readiness path re-checks (rejected: the 300 s readiness timeout counts from the CR's
creation timestamp, so every update of an older deployment would flash `Error`); parsing nothing
and relying on the timeout (fails SC-005, and never fires after an update).

## D-005 — Dependency gap: extension and upstream evaluation (research directive)

The gap: no Flux or Kustomize primitive says "patch the container named X, and fail if X is
missing".

| Route | Evaluation | Verdict |
|---|---|---|
| Flux `postRenderers[].kustomize.patches` with JSON6902 (the dependency's own extension point) | Expresses the guard and the named error (D-001, D-002) with no code outside patch generation | **Chosen** |
| Kustomize `replacements` with `containers.[name=X].image` field paths (fails on a missing target unless `create: true`) | Clean expression, but Flux's PostRenderer Kustomize API exposes only `patches`, `patchesStrategicMerge`, `patchesJson6902`, `images` | Not available |
| Upstream: add `replacements` to Flux helm-controller's Kustomize post-renderer | Feasible PR, but needs a Flux release and an agent chart bump (`helm/agent` pins `helm-controller:v1.1.0`); the chosen route already works on the pinned version | Rejected for v1; noted as a follow-up in ADR-058 |
| Upstream: a "must exist" strategic-merge directive in kyaml | No such directive in the Kubernetes strategic-merge spec; would diverge from apimachinery semantics; low acceptance odds | Rejected |
| Cluster-side ValidatingAdmissionPolicy | Cannot tell an added container from a chart one after the merge; adds cluster-scoped objects to every cluster | Rejected |
| Platform-side `helm template` pre-render to learn container names | Rejected by ADR-013 §1 and ADR-057 (heavy, couples Styrmin to chart internals) | Rejected |

## D-006 — `{{ app.version }}` substitution

**Decision**: plain substitution, regex `\{\{\s*app\.version\s*\}\}`, every occurrence. After
substitution, any remaining `{{`, `}}`, `{%` or `%}` is rejected (`INVALID_IMAGE_REFERENCE`, reason
`template_expression`). At render time the value is `context.app.version`; on write it is the
deployment's application version (the `deploy` request's version, or the stored one on
`updateDeployment`).

**Rationale**: the brief forbids Jinja rendering. A regex keeps the token predictable, cannot reach
the rendering context, and is reproducible client-side (FR-008).

**Alternatives considered**: a Jinja sandbox with one variable (rejected by the brief; error
messages leak template internals); a `$APP_VERSION` syntax (inconsistent with the
`{{ app.version }}` drivers already use in `values.j2.yml`).

## D-007 — Image-reference grammar (no new dependency)

**Decision**: a hand-written validator following the distribution/reference grammar:
`[domain[:port]/]path[:tag][@algorithm:hex]`, lowercase path components with `.`, `_`, `__` or `-`
separators, tag `[\w][\w.-]{0,127}`, digest hex of at least 32 characters, name at most 255
characters. An explicit tag or digest is required. Backend:
`services/image_overrides/reference.py`; frontend: `src/lib/image-reference.ts`. Both test suites
read one shared vector file (`frontend/src/lib/image-reference.vectors.json`), so the two
implementations cannot drift silently.

**Alternatives considered**: a Python package (`docker` or `oras`), rejected because the governance
gate says no new dependency and the frontend still needs its own copy.

## D-008 — Validation on write, on upgrade, and at render

**Decision**:

- **Write** (`deploy`, `updateDeployment`, and therefore `apply`): for each component block with a
  non-null `image`: unknown component → `UNKNOWN_COMPONENT_IMAGE_OVERRIDE`; grammar, missing
  tag/digest, or a foreign template expression → `INVALID_IMAGE_REFERENCE`, checked on the stored
  string with the token replaced, using the deployment's application version; adding or changing it
  on a component without a component container → `COMPONENT_CONTAINER_NOT_DECLARED` (now with
  metadata `override: "image"`). Removal and unchanged re-submission pass. On `updateDeployment` the
  `INVALID_IMAGE_REFERENCE` check skips entries equal to the stored reference (reconciled 2026-10-04,
  review finding R1): a stranded token override that the current version breaks would otherwise
  reject every later edit, since clients re-submit all stored blocks. All of these run before
  Pydantic config validation, like the env-var and container-override checks, so the typed codes
  reach GraphQL.
- **Upgrade** (`updateDeploymentVersion`): stored, applicable overrides are re-validated against the
  target application version before any task is dispatched. Without this check, the driver's
  `upgrade` action would stop the components before the render fails (the action stops `server`,
  then calls `upgrade_deployment_version`). This extends the brief's FR-009; the spec's FR-009 and
  User Story 4 Sc.5 were amended in the critique phase (E2).
- **Render** (operator, `build_component_container_patches`): substitution and validation run again;
  failure raises `InvalidImageReferenceError` (reason `after_substitution`), and the operator records
  `HelmRelease creation failed: <message>` (ADR-057 §4 path). No fallback to the chart image.

## D-009 — Storage, context, and read surface

**Decision**:

- `ComponentConfigBlock.image: str | None` in `context/models/config.py`, the only stored change.
  It sits in the existing `Deployment.config` JSON, so there is no migration. Full-replacement
  semantics: omitting or nulling `image` clears it.
- `ResolvedComponentImageOverride {reference: str, is_orphaned: bool}` in
  `context/models/components.py`, attached as `ComponentContext.image_override` only for live
  components with an override (orphans surface on read only, as for container overrides).
  `ImageOverridesResolver` mirrors `ContainerOverridesResolver`.
- GraphQL read: `Deployment.componentImageOverrides: [ComponentImageOverride!]!` with `component`,
  `reference`, `resolvedReference`, `isOrphaned`, `isApplicable`
  (`not isOrphaned and container != null`), matching `ComponentEnvVars.isApplicable`.
  `resolvedReference` is computed on read from the deployment's application version.
- GraphQL write: `ComponentConfigInput.image: String`. The SDK and `apply` manifests pick it up by
  codegen: a manifest sets it as `spec.config.components: [{name: server, image: …}]`, the list
  form `components` already uses (the brief's `spec.config.components.<name>.image` is that slot).

## D-010 — Action Jobs (FR-012)

**Finding**: `upgrade_instance_crd` writes the CR, then runs the driver's `upgrade` action. The
action's `upgrade_deployment_version` waits for the nested task, which completes when the CR is
written, not when the rollout is done. `get_component_images` therefore usually reads the
pre-upgrade pod template, which is why the in-repo actions rebuild the tag
(`image.rsplit(":", 1)[0] + ":" + target_version`).

**Decision**:

- `get_component_images(component, context)` keeps its signature and list contents. When the
  component declares a component container present in the pod template, that container's image is
  returned **first**. No new primitive.
- The in-repo `upgrade` actions (`simple-app`, `infrahub`, `infrahub-enterprise`) take `images[0]`
  instead of the first image matching a substring, and strip a digest before rebuilding the tag.
  The tag is stripped only when the part after the last `:` contains no `/`, so a registry port
  (`registry:5000/app`) survives (reconciled 2026-10-04; the planned one-liner
  `image.split("@", 1)[0].rsplit(":", 1)[0]` cut `registry:5000/app` to `registry`).
- With a token override the live image is `…-patched:<old>`, so the Job runs `…-patched:<target>`:
  the override is honoured. With a pinned override the Job still runs at the target version while
  the component stays pinned. That is the hazard FR-008's warning covers, and it is unchanged.

**Alternatives considered**: a new `get_component_container_image` primitive (out of scope per the
brief); returning a dict (breaking change for third-party actions).

## D-011 — Client-side pinned warning (FR-008)

**Decision**:

- **UI**: the upgrade dialog on the deployment detail page reads `componentImageOverrides` and
  lists every applicable override without the token, above the confirm button.
- **`styrminctl apply`**: the SDK's `_apply_update` compares `manifest.version` with the existing
  deployment's `applicationVersion`. On a change, it computes the components whose effective `image`
  has no token (the manifest's `components` when the manifest sets them, which replace the stored
  ones, else the stored config) and returns them as `ApplyOutcome.pinned_image_components`. The CLI
  prints one `warning:` line per affected deployment to stderr. Applicability is not consulted:
  `apply` has the raw config, and listing a stranded override is harmless. `apply` stays
  non-interactive.
- The token check is the D-006 regex, shared by `frontend/src/lib/image-reference.ts` and the SDK
  (`styrmin_sdk/models/image_reference.py`, a few lines with no dependency).
- No warning on `sdk.deployments.update_version()` (out of scope).

## D-012 — E2E design (`test_deployment_image_override.py`, `shard_configuration`)

- **Images**: the session fixtures already build `simple-app:0.1.0` and `simple-app:0.2.0` on the
  host Docker, which the vCluster nodes share; kubelet name-matches local images under the chart's
  `imagePullPolicy: IfNotPresent`. A module fixture adds `docker tag` aliases
  `registry.example/acme/simple-app-patched:0.1.0` and `:0.2.0`. `registry.example` never
  resolves, so a running pod proves the local re-tag was used.
- **Test 1** (US1 + US3, dual-entrypoint): its own module deployment; set the override through
  `scenario_driver.set_component_image` (new protocol method with API and UI implementations; the
  UI drives the configuration drawer's component section), assert the live `simple-app` container
  image, that the `initContainers` and env are unchanged, that there is no extra container, and the
  read surface (`reference`, `resolvedReference`, `isApplicable`); then clear it and assert the chart
  image is back.
- **Test 2** (US2 + FR-012, dual-entrypoint): its own deployment at 0.1.0 with
  `…-patched:{{ app.version }}`; `scenario_driver.upgrade_deployment` to 0.2.0; assert the `server`
  image is `…-patched:0.2.0`. The action Job `<release>-job` image is not asserted: the action's
  primitives call the API unauthenticated and fail under default-deny until #381, so the Job never
  runs; the `get_component_images` unit tests cover FR-012. Before that,
  with a pinned override set, `scenario_driver.pinned_image_components(deployment_id,
  target_version)` must return `["server"]`, and with the token override `[]`. The API driver
  computes it with the SDK's client-side helper over `componentImageOverrides`; the UI driver opens
  the upgrade dialog, picks the target version, reads the warning list, and cancels.
- **Test 3** (SC-005, `api_only`): publishes a `simple-app-misnamed` driver (metadata name changed,
  `components.server.container: wrong-name`) on a branch of the in-cluster git server (the
  `test_driver_version_reselection.py` pattern), deploys it, sets an override, and asserts the
  deployment's status message names `server` and `wrong-name` within one reconcile and that the live
  Deployment still has only the `simple-app` container.
- Reuse check: all three tests mutate deployment state, so none can share `deployed_simple_app`.
  The heavy session fixtures they depend on (`styrmin_resources`, `simple_app_image`,
  `simple_app_image_v2`, `git_server`) already have active consumers.

## D-013 — Documentation and ADR

ADR-058 "Image overrides and the component-container guard" extends ADR-057. It records the
`{{ app.version }}` token, the guard (D-001 to D-004), the shared env-var guard, and narrows
ADR-057's consequence "a wrong container name fails the release, but only once env vars are set" to
"a wrong container name fails the reconcile with `COMPONENT_CONTAINER_NOT_FOUND` whenever any
override targets it; Styrmin never adds a container". It also records the `get_component_images`
ordering and these follow-ups: the Flux `replacements` upstream route, a release-wide registry mirror
and image pull secrets (separate issues), generic HelmRelease failure surfacing, and showing each
token override's target reference in the upgrade dialog. Consequences note that a platform rollback
below this release needs image overrides cleared first: older platforms validate
`ComponentConfigBlock` with `extra="forbid"` and reject the `image` key.

## D-014 — Test placement (critique E5, E6, P5)

- Kustomize-semantics tests (`kubectl kustomize` over the builder's real output: existing,
  missing, multi-container, init container, zero-match, env-only identity) live in
  `backend/tests/integration/`. CI's integration job installs `kubectl`; the unit job does not.
- SC-002: a unit test asserts the builder emits no component-container patch for a context without
  overrides; the integration test asserts the env-only guard leaves the rendered workload identical
  to the env strategic merge alone.
- The JSON6902 block renders through `yaml.dump` only, never string formatting; unit tests cover
  the JSON-pointer escape with `~` and `/` in component names and a reference with every allowed
  separator.
