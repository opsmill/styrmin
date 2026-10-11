# ADR-058: Image Overrides and the Component-Container Guard

**Status**: Accepted
**Date**: 2026-10-04
**Source**: specs/archive/018-component-image-overrides/ (spec, plan, research D-001 – D-014, critique)
**Extends**: [ADR-057](0057-post-render-component-overrides.md) — image overrides are the second
post-render override into the declared component container.
**Narrows**: ADR-057's consequence "a wrong container name fails the release, but only once env
vars are set". A wrong name now fails the reconcile with `COMPONENT_CONTAINER_NOT_FOUND` whenever
any override (env vars or image) targets it, and Styrmin never adds a container (§3, §4).
**Related**: [ADR-035](0035-post-render-injection-toggles-and-kind-list.md) (the post-render patch
pipeline), [ADR-029](0029-config-additions-via-baseconfigsection-no-migration.md) (config additions
ride the existing JSON columns), [ADR-045](0045-container-override-no-layering-and-omit-marker.md)
(component scope, no layering), [ADR-048](0048-declarative-apply-client-side-orchestration.md)
(`apply` writes config before the version).

## Context

A component's image is fixed by the Helm chart bundled with the deployment's driver version. A
user who runs a custom or patched build of one component had to fork the driver
([#20](https://github.com/opsmill/styrmin/issues/20)). ADR-057 gave every in-repo component a
driver-declared **component container** and a post-render patch that targets it, so the platform
can change one container of one component without values-template wiring.

Setting an image by strategic merge has a hazard. kyaml merges containers by `name`; when the name
is missing it adds a container. With env vars only, the added container has no image and the API
server rejects the workload, which is the loud failure ADR-057 relies on. With an image in the
patch, the added container is valid: the pod gains a second container running the override, and
the API server accepts it (verified with kustomize v5.7.1, research D-001). Setting an image would
also silence the env var failure on the same component.

## Decision

### 1. One image reference per component, stored in the deployment config

`ComponentConfigBlock.image: str | None` (`Deployment.config.components.<name>.image`), component
scope only, no layering. It rides the existing JSON column: no schema change, no Alembic revision.
Under full-replacement semantics, omitting or nulling `image` clears it. The model validator checks
a stored value with the placeholder version `"0"` because the real application version is unknown
at that point.

The read surface is `Deployment.componentImageOverrides { component reference resolvedReference
isOrphaned isApplicable }`. `resolvedReference` substitutes the deployment's application version on
read; `isApplicable` is `not isOrphaned and container != null`, as for `ComponentEnvVars`. The
rendering context carries `components[<name>].image_override` (`reference`, unsubstituted) for live
components only.

### 2. `{{ app.version }}` is plain substitution, and the grammar is hand-written

Every match of `\{\{\s*app\.version\s*\}\}` (ASCII whitespace only, so Python and TypeScript agree)
is replaced with the deployment's application version at render time. It is not Jinja: any `{{`,
`}}`, `{%`, or `%}` left after substitution is rejected. A literal tag or a digest pins the image.

`services/image_overrides/reference.py` validates the result against the distribution/reference
grammar (`[domain[:port]/]path[:tag][@algorithm:hex]`, name at most 255 characters) and requires an
explicit tag or digest. Failures raise `INVALID_IMAGE_REFERENCE` with a `reason`: `grammar`,
`missing_tag_or_digest`, `template_expression`, or `after_substitution` (valid with the placeholder
version, invalid with the real one). `frontend/src/lib/image-reference.ts` mirrors the grammar; both
test suites read `frontend/src/lib/image-reference.vectors.json`. The SDK mirrors only the token
check (`styrmin_sdk.models.image_reference`). No new dependency.

### 3. One guard for env vars and images

`build_component_container_patches()` (`services/component_container/patch_builder.py`) replaces
`build_env_var_patches()`. For every component with a component container and at least one
applicable override (non-empty, non-orphaned env vars, or a live image override), it emits per
workload kind (`Deployment`, `StatefulSet`), targeted by the first identifier label:

1. a strategic-merge `ContainerEnvPatch` that names the component container, with env entries only
   when env vars apply. kyaml moves the container to `containers[0]`, or adds an image-less one when
   the name is missing;
2. a JSON6902 `ComponentContainerPatch` that moves `containers/0` to the guard key
   `/spec/template/spec/styrmin.io~1component-container~1<component>~1<container>` (both names
   JSON-pointer escaped), removes its `image`, sets the image, and moves it back to `containers/0`.
   With an image override the image is the substituted reference; with env vars only, the patch
   copies the chart image aside and restores it.

`remove` is the only JSON6902 op that fails on a missing key (`replace`, `copy`, and `test` with
`null` succeed), so an added, image-less container fails the render with
`error in remove for path: '…/styrmin.io~1component-container~1<component>~1<container>/image'`.
The temporary key never reaches the API server. Env-var-only output leaves the rendered workloads
byte-identical to the strategic merge alone. Components without overrides get no patch. Overrides
on containerless or orphaned components are kept but never rendered. The patches stay last in
`postRenderers` (ADR-057 §3).

An image that is invalid after substitution at render time raises `InvalidImageReferenceError`
(`after_substitution`); the operator records `HelmRelease creation failed: <message>`. There is no
fallback to the chart image.

### 4. The operator turns the guard failure into `COMPONENT_CONTAINER_NOT_FOUND`

The guard fails inside Flux's post-renderer, after the operator applied the HelmRelease. Before
this change the operator never read a HelmRelease failure, and after a spec update the
`HelmReleaseReady` condition still read `True` from the previous rollout.

On every timer tick in `CreatingHelmRelease` (before the readiness check) and `Ready` (before drift
detection), `read_helmrelease_guard_failure()` (`operator/reconciler.py`) reads the HelmRelease. It
matches when `Ready` is not `True` and a condition observed for the current generation (its
`observedGeneration`, else `status.lastAttemptedGeneration`, equals `metadata.generation`) carries
the guard key followed by `/image` in its message. helm-controller v1.1.0 reports it under both
`Ready=False` and `Released=False` with reason `UpgradeFailed` (observed in E2E). The operator then
sets `phase: Failed`, `displayState: Error`, and `HelmReleaseReady=False` and `Ready=False` with
reason `ComponentContainerNotFound`, and the message of `ComponentContainerNotFoundError`:

```text
Component 'server': component container 'wrong-name' was not found in its rendered workload.
Styrmin never adds a container; fix components.server.container in the driver specification file.
```

The status reporter carries it to `Deployment.crdStatus.message`; the deployment reads
`status: failed`. The code is in the message only: it does not reach GraphQL `extensions.code`.
Only this signature fails the deployment at once, because it is deterministic for a given config.
Other HelmRelease failures keep the old path (Flux remediation, then the readiness timeout). A later
config or driver change re-applies the HelmRelease and leaves `Failed` the usual way.

> **Note (#432, #433):** the agent chart now installs helm-controller v1.6.5. After the guard
> failure, it records the new post-renderers as applied and reports the previous release `Ready`
> without retrying, so the operator also reads the guard key from FluxCD's `UpgradeFailed` Event.
> See [A failed change reported in sync](../knowledge/agent/operator.md#a-failed-change-reported-in-sync).

### 5. Writes and upgrades are validated before any task starts

`deploy` and `updateDeployment` check, in order: `UNKNOWN_COMPONENT_IMAGE_OVERRIDE` (the driver
version does not declare the component), then `INVALID_IMAGE_REFERENCE` at the deployment's
application version (the request's version on `deploy`, the stored one on `updateDeployment`),
then config validation, then `COMPONENT_CONTAINER_NOT_DECLARED` with metadata `override: "image"`
when an image is added or changed on a containerless component. Removal and unchanged
re-submission pass, as for env vars (ADR-057 §5). On `updateDeployment` the reference check also
skips entries equal to the stored value: they were checked when written, and applicable ones are
re-checked on every version change. Without the skip, a stranded `{{ app.version }}` override that
the current version breaks would reject every later edit, since clients re-submit all stored blocks.
Environment clone creates counterparts through `deploy`, so it gets the same checks.

`updateDeploymentVersion` re-validates every stored override whose component has a component
container in the target driver version against the target application version, before no-op
detection and task dispatch. Without this check, the driver's `upgrade` action would stop
components before the render fails.

### 6. `get_component_images` returns the component container's image first

The action primitive keeps its signature and returns the same images. When the component declares
a component container present in the pod template, its image is element 0; the rest keep
pod-template order. Action Jobs that build their image from the component therefore see the
override. The in-repo `upgrade` actions (`simple-app`, `infrahub`, `infrahub-enterprise`) take
`images[0]` instead of the first image matching a substring, drop any `@digest`, and strip the tag
only when the part after the last `:` contains no `/`, so `registry:5000/app` keeps its port. This
replaces research D-010's `rsplit(":", 1)` one-liner, which would have cut a registry port.

### 7. Pinned overrides are flagged client-side

The UI upgrade dialog lists every applicable override without the token, with its reference, above
the confirm button. `styrminctl deployments apply` prints a `warning:` line on stderr when a
manifest changes an existing deployment's application version and the effective config carries
token-free overrides (once at submit with `--wait`). The SDK returns them as
`ApplyOutcome.pinned_image_components`, with `ApplyOutcome.target_version` set only on an
`updated` outcome that changes the version. The exit code is unchanged and `apply` stays
non-interactive. The SDK and CLI see only the raw config, so they list every token-free override,
including ones that do not apply; the UI lists only applicable ones.

## Consequences

- **A custom build needs no driver change** once the driver declares the component container.
- **A wrong container name fails loudly for both overrides.** The API-server rejection of an
  image-less container no longer occurs: the guard fails the render first, and the deployment goes
  `Failed` with a message naming the component and the container. No container is ever added.
- **The failure appears within one or two timer intervals** after helm-controller reports it,
  because the two loops are not aligned. The interval is `STYRMIN_OPERATOR_RECONCILE_INTERVAL`
  (60 s by default; the E2E agent uses 5 s).
- **The component container moves to `containers[0]` for image-only components too**, which
  changes `kubectl logs`' default container (as ADR-057 records for env vars). `get_component_env`
  still reads `containers[0]`, which is now the component container whenever env vars or an image
  override apply.
- **No restarts from the upgrade itself.** Deployments without overrides get no new patches.
  Deployments with env vars get the extra guard patch, which renders identical workloads; Flux
  records one new Helm revision on the first reconcile, as for any `postRenderers` change.
- **Rolling Styrmin back needs image overrides cleared first.** Older platforms validate
  `ComponentConfigBlock` with `extra="forbid"` and reject the `image` key.
- **Override plus version change in one `apply` races the upgrade action.** `apply` writes the
  config first, but the action may read the workload before the override is rendered, so its first
  Job can use the previous image repository. Env vars have the same race. Setting the override in
  a separate apply avoids it. The config write is also validated against the pre-switch driver
  version ([#388](https://github.com/opsmill/styrmin/issues/388), ADR-057).
- **A pinned override diverges from upgrade Jobs.** The in-repo actions rebuild the tag from
  `images[0]`, so with a pinned override the Job runs the override's repository at the target
  version while the component stays pinned. The warning (§7) is the mitigation.
- **Pull and policy problems are the cluster's.** Styrmin does not pre-check registries or change
  `imagePullPolicy`: a bad reference shows as `ImagePullBackOff` in the Pods tab, rebuilt images
  need a new tag or a digest, and registry allow-lists belong to cluster admission policies.
- **A label that matches several workloads must find the container in each.** Otherwise the guard
  fails the render, which is correct: the override cannot apply.
- **The Kustomize behaviour is observed, not contracted.** Integration tests run `kubectl
  kustomize` over the builder's real output, and E2E runs the guard on the agent's
  `helm-controller:v1.1.0`; the operator matches the guard key anywhere in a condition message, so
  a wording change in the JSON-patch library does not break it.

## Alternatives Considered

- **Strategic merge carrying `image`.** Rejected: a wrong name adds a working extra container.
- **Kustomize `images:` transformer.** Rejected: release-wide, matches by image name, and cannot
  target one component when several share an image (infrahub `server` and `task-worker`). Kept for
  the registry mirror.
- **JSON6902 alone, by index.** Rejected: Styrmin does not know the chart's container index.
- **Values-template wiring.** Rejected by ADR-057: every driver must wire every override, and a
  missing wire is a silent no-op.
- **A plain `remove` on `containers/0/image`.** Rejected: the error carries a fixed path, so it
  cannot name the component or the container.
- **Kustomize `replacements` with `containers.[name=X].image`.** Fails on a missing target, but
  Flux's post-renderer exposes only `patches`, `patchesStrategicMerge`, `patchesJson6902`, and
  `images`.
- **Adding `replacements` to helm-controller upstream.** Rejected for v1: needs a Flux release and an
  agent chart bump; the chosen route works on the pinned version.
- **A "must exist" strategic-merge directive in kyaml.** Rejected: not in the Kubernetes
  strategic-merge spec, low acceptance odds.
- **A cluster ValidatingAdmissionPolicy.** Rejected: cannot tell an added container from a chart
  one after the merge, and adds cluster-scoped objects to every cluster.
- **`helm template` pre-render to learn container names.** Rejected by ADR-013 §1 and ADR-057.
- **Surfacing every HelmRelease failure.** Rejected for now: a broader behaviour change, and many
  failures are transient. Recorded as a follow-up.
- **Resetting `HelmReleaseReady` on every update.** Rejected: the 300 s readiness timeout counts
  from the CR's creation, so every update of an older deployment would flash `Error`.
- **Relying on the readiness timeout.** Rejected: no cause, and it never fires after an update.
- **A Jinja sandbox or a `$APP_VERSION` syntax for the token.** Rejected: Jinja leaks template
  internals into errors; `{{ app.version }}` is what drivers already use in `values.j2.yml`.
- **A new `get_component_container_image` primitive, or a dict return.** Rejected: out of scope, and
  a breaking change for third-party actions.
- **An interactive confirmation in `apply`.** Rejected: `apply` stays non-interactive.

## Follow-ups

- Add `replacements` to Flux helm-controller's Kustomize post-renderer upstream, then consider
  replacing the move/remove/add guard with it.
- Release-wide registry mirror and image pull secrets (separate issues).
- Surface other HelmRelease failures with their cause instead of the readiness timeout.
- Show each token override's target reference in the upgrade dialog, next to the pinned notice.
- Validate `apply`'s config write against the target driver version (#388).
- Driver `upgrade` action Jobs fail under default-deny auth because the action primitives call the
  API unauthenticated ([#381](https://github.com/opsmill/styrmin/issues/381)). Pre-existing; until it
  is fixed, the image-override E2E does not assert the upgrade Job's image.
