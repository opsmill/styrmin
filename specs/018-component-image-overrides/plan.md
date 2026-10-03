# Implementation Plan: Per-Component Image Overrides via Post-Render

**Branch**: `fac/feat-docker-image-per-component-p62fy` | **Date**: 2026-10-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/018-component-image-overrides/spec.md`

## Summary

Add one image reference per component (`DeploymentConfig.components[<name>].image`), applied after
the chart renders to the driver-declared **component container** (ADR-057). Per component and
workload kind (`Deployment`, `StatefulSet`), the HelmRelease builder emits the existing
strategic-merge patch, which names the container (with env vars when they apply) and moves it to
`containers[0]`. A new JSON6902 patch then moves that container to a key that encodes the component
and container names, removes its `image` (which fails when the container was missing and got added
image-less), sets the override, and moves it back. The guard also runs for env-var-only components,
so a wrong container name fails the render whichever override targets it, and never adds a
container (research D-001 to D-003). The operator recognises the guard's error in the HelmRelease
status, for the current generation and in both the "waiting for HelmRelease" and `Ready` phases
(so updates of running deployments are covered), and fails the deployment with
`COMPONENT_CONTAINER_NOT_FOUND`, naming the component and the container (D-004).

`{{ app.version }}` is plain regex substitution against `context.app.version` (D-006). A
hand-written grammar check, shared with the frontend through one test-vector file (D-007), runs on
write, on `updateDeploymentVersion`, and at render (D-008). Reads expose stored and resolved
references and applicability (D-009). `get_component_images` puts the component container's image
first, and the in-repo upgrade actions use it (D-010). The UI upgrade dialog and `styrminctl apply`
warn about token-free overrides, computed client-side (D-011).

## Technical Context

**Language/Version**: Python 3.14+ (backend, operator, agent, SDK, CLI); TypeScript 5.9.3 / React 19 (frontend)

**Primary Dependencies**: Strawberry GraphQL, Pydantic v2, SQLModel, Prefect, kopf, kubernetes-asyncio;
Flux helm-controller v1.1.0 (Kustomize post-renderer: kyaml strategic merge and JSON6902);
TanStack Form/Query, Base UI, Zod; Cyclopts (CLI). No new dependency.

**Storage**: PostgreSQL via SQLModel. No schema change and no Alembic revision: `image` lives in
the existing `Deployment.config` JSON.

**Testing**: pytest (unit, functional GraphQL propagation, E2E on a per-session vCluster); Vitest +
React Testing Library; `kubectl kustomize` (v5.7.1) in unit tests for the patch semantics, skipped
when `kubectl` is absent.

**Target Platform**: Kubernetes clusters running Flux helm-controller v2 APIs, managed by the Styrmin
agent and operator.

**Project Type**: Web service (backend + frontend) with an in-cluster operator, SDK, CLI, and driver
bundles.

**Performance Goals**: No measurable reconcile cost: at most 2 extra JSON6902 patches per component
with overrides; validation is O(length of reference).

**Constraints**: Deterministic patches per context (no spurious rollouts, SC-003); no change for
deployments without component-container patches (SC-002); component-container patches stay last in
`postRenderers` (ADR-057 §3); Helm charts ship `resources.requests` only (unchanged).

**Scale/Scope**: ~10 backend modules (3 new), 1 GraphQL input field + 1 read type + 3 error codes,
1 operator handler change, 3 in-repo driver actions, 3 frontend components, SDK apply + CLI warning,
1 new E2E module (3 tests), 1 ADR, ~6 docs pages.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| §I Declarative reconciliation | ✅ | Patches are regenerated from the context on every render; clearing needs no marker; output is deterministic (SC-003). |
| §II Driver-based deployment | ✅ (justified) | The driver opts in by declaring the component container (ADR-057); the platform applies the override, as it does for env vars and scheduling. |
| §III Layered architecture | ✅ | Write validation in `services/deployment.py`; pure logic in `services/image_overrides/` and `services/component_container/`; GraphQL resolvers read through repositories; the operator only maps a status. |
| §IV Typed errors | ✅ | `INVALID_IMAGE_REFERENCE`, `UNKNOWN_COMPONENT_IMAGE_OVERRIDE`, `COMPONENT_CONTAINER_NOT_FOUND` as `ServiceError` subclasses; `COMPONENT_CONTAINER_NOT_DECLARED` extended additively. |
| §V Test-first, E2E, propagation | ✅ | 3 E2E tests in `test_deployment_image_override.py` (`shard_configuration`, 2 dual-entrypoint, 1 `api_only`); propagation tests for the input field, read type, and error codes (contracts/graphql-deltas.md). |
| §VI Format/lint | ✅ | `uv run invoke format lint`, `cd frontend && pnpm lint`. |
| §VII Documentation | ✅ | ADR-058, docs pages, `dev/knowledge`, `CONTEXT.md` (already drafted), towncrier fragments: all tasked in this change. |
| Governance gate: GraphQL schema | ⚠️ Pre-approved | Listed under "Governance Gates Crossed" in the idea brief. Contract: [graphql-deltas.md](contracts/graphql-deltas.md). |
| Governance gate: DB schema, deps, CI/CD, auth | ✅ Not crossed | |
| High-risk area: operator status handling | ⚠️ Called out | The timer gains one narrow, generation-aware match on HelmRelease failure messages in `CREATING_HELM_RELEASE` and `READY` (D-004); other failures keep today's path. Unit-tested and exercised by E2E test 3, which updates a running deployment. |

**Post-design re-check**: unchanged. Phase 1 artifacts introduce no new violation.

## Project Structure

### Documentation (this feature)

```text
specs/018-component-image-overrides/
├── spec.md
├── plan.md                    # This file
├── research.md                # D-001..D-014
├── critiques/critique-20261003.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── graphql-deltas.md
│   ├── errors.md
│   ├── post-render-patch.md
│   └── client-surfaces.md
├── checklists/requirements.md
└── tasks.md                   # /speckit-tasks output
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── context/models/config.py                          # + ComponentConfigBlock.image (+ placeholder-version validator)
├── context/models/components.py                      # + ResolvedComponentImageOverride, ComponentContext.image_override
├── services/image_overrides/                          # NEW package
│   ├── reference.py                                  # grammar, token substitution, has_app_version_token
│   ├── exceptions.py                                 # InvalidImageReferenceError, UnknownComponentImageOverrideError
│   ├── resolver.py                                   # ImageOverridesResolver (mirrors ContainerOverridesResolver)
│   └── validator.py                                  # write/upgrade validation helpers
├── services/component_container/                     # NEW package (shared guard)
│   ├── patch_builder.py                              # build_component_container_patches (absorbs build_env_var_patches)
│   └── exceptions.py                                 # ComponentContainerNotFoundError + guard-message parser
├── services/env_vars/patch_builder.py                # delegates to / is replaced by the shared builder
├── services/env_vars/exceptions.py                   # ComponentContainerNotDeclaredError gains `override`
├── services/context.py                               # + _populate_component_image_overrides
├── services/deployment.py                            # write validation (deploy, update) + upgrade re-validation
├── agent/service/kubernetes/resources/blocks/patches.py   # ContainerEnvPatch env optional; + ComponentContainerPatch (JSON6902)
├── agent/service/kubernetes/resources/builders/application.py  # call the shared builder last
├── agent/service/kubernetes/primitives.py            # get_component_images(container=...) ordering
├── actions/primitives.py                             # pass the component container through
├── operator/handlers/styrmin_deployment.py           # guard-failure detection in the timer
├── operator/reconciler.py                            # read the HelmRelease Ready condition message
└── api/definitions/deployment/{inputs,model}.py      # image input, ComponentImageOverride read type

backend/tests/
├── unit/services/image_overrides/                    # grammar (shared vectors), substitution, resolver, validator
├── unit/services/component_container/                # patch rendering (yaml.dump), pointer escaping, message parser, SC-002 no-patch golden
├── integration/test_component_container_kustomize.py # kubectl-kustomize semantics (CI integration job has kubectl; D-014)
├── unit/agent/                                       # builder ordering, get_component_images ordering
├── unit/operator/                                    # guard failure → Failed in both phases; stale generation ignored
├── unit/services/test_deployment_*                   # write/upgrade validation, no task on rejection
├── functional/graphql/                               # propagation tests (contracts/graphql-deltas.md)
└── e2e/
    ├── test_deployment_image_override.py             # NEW: 3 tests, shard_configuration
    ├── drivers/{protocol,api_driver,ui_driver}.py    # + set_component_image, pinned_image_components
    └── pages/                                        # deployment-detail page object: image field, upgrade warning

driver/examples/{simple-app,infrahub,infrahub-enterprise}/actions.py   # images[0] + digest-safe retag

python_sdk/src/styrmin_sdk/
├── graphql/get_deployment.graphql (+ new _full query)
├── models/image_reference.py                          # NEW token helper + pinned_image_components
├── models/deployment_manifest.py                      # ApplyOutcome.pinned_image_components
└── resources/deployments.py                           # _apply_update computes pinned components
cli/src/styrminctl/commands/deployments.py            # warning line on stderr

frontend/src/
├── lib/imageReference.ts (+ .test.ts, .vectors.json)
├── graphql/ (get_deployment operation)
├── components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx (+ test)
├── components/deployment/configuration/sections/read/ComponentOverridesSummary.tsx (+ test)
└── pages/deployments/DeploymentDetailPage.tsx + PinnedImageOverridesNotice.tsx (+ test)

schema.graphql, generated SDK + frontend types       # regenerated

dev/adr/0058-image-overrides-and-component-container-guard.md   # NEW
dev/knowledge/backend/deployment-env-vars.md                    # shared guard
dev/knowledge/backend/hooks-and-actions.md                      # get_component_images ordering
docs/docs/drivers/creating-a-driver.md                          # component container: images + guard
docs/docs/drivers/context.md                                    # components[<name>].image_override (read-only)
docs/docs/concepts-and-architecture/hooks-and-actions.md        # get_component_images ordering
docs/docs/concepts-and-architecture/image-overrides.md          # NEW user page: set/clear, token vs pin, upgrade warning,
                                                                #   guard failure, pull failures (Pods tab), unique tags,
                                                                #   admission policies, rollback note, v1 limits
docs/docs/reference/styrminctl.md                               # manifest image field, pinned warning, apply race
docs/docs/concepts-and-architecture/glossary.md                 # Image override
CONTEXT.md                                                      # already drafted (Image override, Component container)
changelog/20.added.md, changelog/20.changed.md                  # towncrier
```

**Structure Decision**: existing web-service layout. The shared guard gets its own
`services/component_container/` package because it serves both env vars and images; the
image-specific pure logic mirrors `services/container_overrides/`.

## Design Notes

1. **Shared builder** (D-001 to D-003): `build_component_container_patches(context)` iterates
   components once and decides per component: env (applicable resolved env vars), image
   (`image_override`, substituted and validated), or nothing. It emits the strategic-merge patch and
   then the JSON6902 patch for each of the two kinds. `build_env_var_patches` is folded in (its tests
   move with it). Logs one line per component (`component`, `container`, env count, `image_override`
   true/false, never values).
2. **Validation layering** (D-008): `reference.validate(ref, *, version) -> str` returns the resolved
   string or raises `InvalidImageReferenceError` with a reason. The model validator uses placeholder
   version `0`; write and upgrade use the real version; the builder uses `context.app.version`.
3. **Write path order** in `update_deployment` / `deploy_application`: unknown-component check →
   grammar/token pre-validation → `validate_deployment_config` → container-declared check (generalized
   `_validate_component_container_targets(submitted, stored, containers, slots=("env_vars", "image"))`).
4. **Upgrade path**: `update_deployment_version` resolves the target driver version, then validates
   each stored override whose component has a container in that version against the target
   application version, before no-op detection and task dispatch.
5. **Operator** (D-004, critique E1/E3): a new `read_helmrelease_guard_failure(namespace,
   release_reference) -> (component, container) | None` in `operator/reconciler.py` GETs the
   HelmRelease and returns a match only when `Ready` is `False` for the current generation
   (condition `observedGeneration`, else `status.lastAttemptedGeneration`, equals
   `metadata.generation`) and any condition message carries the guard key
   (`parse_guard_failure(message)`). The timer calls it on every tick in `CREATING_HELM_RELEASE`
   (before the readiness check) and in `READY` (before drift detection). On a match it sets
   `Failed`/`Error`, the `HelmReleaseReady` condition `False` with reason
   `ComponentContainerNotFound`, and the typed message, then returns. The existing readiness flow,
   conditions handling, and 300 s timeout are unchanged. Unit-tested with captured helm-controller
   messages, a stale-generation message (ignored), and both phases.
6. **No-op detection**: `image_override` is `None` unless set, so instance contexts of deployments
   without overrides keep their shape; adding, changing, or clearing an override changes the
   context and is never a no-op.
7. **Frontend**: the image input lives in `ComponentOverrideBody` next to command/args. The Zod
   schema gains `image: z.string().optional()` with a refinement calling
   `validateImageReference`. Form-to-input mapping sends `image: null` when empty. The upgrade
   dialog renders `PinnedImageOverridesNotice` from the deployment query.
8. **E2E harness**: a session fixture `simple_app_override_images` runs `docker tag` on the two built
   images. A helper publishes the `simple-app-misnamed` driver on a git-server branch.
   `ScenarioDriver` gains `set_component_image` and `pinned_image_components` with API and UI
   implementations.

## Risks

| Risk | Mitigation |
|---|---|
| helm-controller v1.1.0 vendors a JSON-patch implementation whose error text differs from v5.7.1 | The guard key is in the op path, so any error mentioning the path matches; E2E test 3 runs on the real controller; the parser matches the key anywhere in the message |
| A component's label matches several workloads, not all with `C` | The guard fails the render (correct: an override cannot apply). Documented for driver authors |
| Moving `C` to `containers[0]` for image-only components changes `kubectl logs`' default container | Same accepted consequence as ADR-057 for env vars; documented |
| `copy` from a missing `image` succeeds and writes `null` (env-only guard) | It writes `G/styrmin-image`, not `G/image`, so the following `remove G/image` still fails. Covered by a unit test |
| Upgrade action stops components before a render failure | Up-front re-validation in `updateDeploymentVersion` (D-008, spec FR-009) |
| Stale `HelmReleaseReady=True` after an update hides the guard failure | Generation-aware guard check in both `CREATING_HELM_RELEASE` and `READY` (D-004) |
| Stale guard message from an older HelmRelease generation falsely fails a fixed deployment | Match only when the failing condition's generation equals `metadata.generation` |
| Platform rollback below this release: older `ComponentConfigBlock` (`extra="forbid"`) rejects `image` | ADR-058 consequence and `changed` fragment: clear overrides before rolling back |
| Override and version change in one `apply` race the upgrade action's image read | Documented in the apply docs (same race as env vars) |

## Complexity Tracking

No constitution violations to justify.
