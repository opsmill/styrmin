# Implementation Plan: Platform-Owned Env Var Injection via Post-Render

**Branch**: `fac/feat-operator-env-vars-chart-s-deployment-334-3xvoh` | **Date**: 2026-10-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/017-post-render-env-vars/spec.md`

## Summary

Move user env var injection out of driver `values.j2.yml` templates and into the platform.
Drivers declare one **component container** per component (`components.<name>.container`); the
HelmRelease builder appends one strategic-merge Kustomize patch per component and workload kind
(`Deployment`, `StatefulSet`) to `spec.postRenderers`, merging the resolved env vars into that
container by env `name`. Chart entries survive and same-name entries (including `valueFrom`) are
replaced. Writes that target a component without a container are rejected up front, upgrades that
drop a container keep and flag stored values, the `component_env_vars` filter fails rendering
with a pointer to a migration guide, and every in-repo driver is migrated. The HelmRelease update
switches from merge-patch to replacing each top-level spec key Styrmin writes, so values-template
env entries written before migration do not linger while keys Styrmin never writes
(`spec.suspend`) survive (research D-003 and its revision).

## Technical Context

**Language/Version**: Python 3.14+ (backend, agent, operator, SDK); TypeScript 5.9.3 / React 19 (frontend)

**Primary Dependencies**: Strawberry GraphQL, Pydantic v2, SQLModel, Jinja2, Prefect, kopf
operator, kubernetes-asyncio client; Flux helm-controller (Kustomize post-renderer, kyaml
strategic merge); TanStack Form/Query, Base UI. No new dependency.

**Storage**: PostgreSQL via SQLModel — no schema change, no Alembic revision. The component
container rides in existing JSON columns (`ApplicationDriverVersion.components`,
`ComponentConfig.config`, `Component.config`).

**Testing**: pytest (unit, functional GraphQL propagation, E2E on per-session vCluster); Vitest +
React Testing Library (frontend); `kubectl kustomize` for the offline merge check.

**Target Platform**: Kubernetes clusters running Flux helm-controller v2 APIs, managed by the
Styrmin agent/operator.

**Project Type**: Web service (backend + frontend) with an in-cluster operator and driver bundles.

**Performance Goals**: No measurable reconcile cost: at most 2 extra patches per component; patch
rendering is O(env vars).

**Constraints**: Deterministic output per resolved config (no spurious rollouts); env patches
must come after every existing post-render patch (research D-002); Helm charts ship
`resources.requests` only (unchanged).

**Scale/Scope**: 7 in-repo drivers, 30 components; ~6 backend modules, 2 GraphQL types + 1 field,
1 frontend section, 1 E2E module extended, 1 E2E test extended.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| §I Declarative reconciliation | ✅ | Patches regenerate from resolved context each render; clearing converges without markers. D-003's `spec` replace makes the live HelmRelease equal desired state, removing merge-patch residue. |
| §II Driver-based deployment | ✅ (mild tension, justified) | Injection becomes platform logic, but the driver still declares the target container — the same split as ADR-035 scheduling. |
| §III Layered architecture | ✅ | Write validation in the service layer (`services/deployment.py`); patch builder in `services/env_vars/`; GraphQL resolvers read through existing repositories. |
| §IV Typed errors | ✅ | `COMPONENT_CONTAINER_NOT_DECLARED`, `RETIRED_TEMPLATE_FILTER` as `ServiceError` subclasses; no union error types. |
| §V Test-first, E2E, propagation | ✅ | US1 E2E extends `test_deployment_env_vars.py` (dual-entrypoint, reuses module fixture); SC-003 extends `test_infrahub_services.py` on the already-booted enterprise stack; propagation tests for all three GraphQL additions (D-011). |
| §VI Format/lint | ✅ | `uv run invoke format lint`, frontend `pnpm lint`. |
| §VII Documentation | ✅ | New ADR, guide rewrite, knowledge, docs pages, migration guide, CONTEXT.md, towncrier fragments — all tasked in this change. |
| Governance gate: GraphQL schema | ⚠️ Pre-approved | The #385 brief lists the GraphQL changes (container on driver-version read path, FR-003 code, FR-005 flag) under "Governance Gates Crossed". Contract: [graphql-deltas.md](contracts/graphql-deltas.md). |
| Governance gate: DB schema, deps, CI/CD, auth | ✅ Not crossed | |
| High-risk area: operator HelmRelease apply | ⚠️ Called out | D-003 changes the update request shape for HelmRelease only, behind an opt-in flag. Unit-tested and exercised by the US1 E2E stale-values step. |

**Post-design re-check**: unchanged — no new violations introduced by Phase 1 artifacts.

## Project Structure

### Documentation (this feature)

```text
specs/017-post-render-env-vars/
├── spec.md
├── plan.md                 # This file
├── research.md             # D-001..D-011
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── graphql-deltas.md
│   ├── errors.md
│   └── post-render-patch.md
├── checklists/requirements.md
└── tasks.md                # /speckit-tasks output
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── services/driver/models/resources/driver.py        # + Component container field + validation (FR-001)
├── context/models/components.py                      # + container on context ArbitrarySectionModel
├── services/env_vars/
│   ├── exceptions.py                                 # + ComponentContainerNotDeclaredError (FR-003)
│   └── patch_builder.py                              # NEW build_env_var_patches (FR-002, FR-004, FR-005)
├── services/exceptions.py                            # + RetiredTemplateFilterError (FR-007)
├── services/deployment.py                            # + container validator on write paths (FR-003)
├── agent/service/kubernetes/resources/
│   ├── blocks/patches.py                             # + ContainerEnvPatch (strategic merge)
│   └── builders/application.py                       # retire component_env_vars filter; append env patches last
├── agent/service/kubernetes/primitives.py            # + replace-spec-on-update option (FR-011)
├── operator/pipeline.py                              # HelmRelease apply opts into replace-spec
└── api/definitions/
    ├── deployment/model.py                           # Component.container, ComponentEnvVars.isApplicable
    └── application_driver/model.py                   # ComponentConfig.container

backend/tests/
├── unit/agent/                                       # patch rendering, builder ordering, filter retirement, upsert replace
├── unit/services/env_vars/                           # patch builder skips; container validator
├── unit/services/driver/                             # container field load/validation; in-repo drivers load
├── functional/graphql/                               # propagation: container x2, isApplicable, error code
└── e2e/
    ├── test_deployment_env_vars.py                   # US1 dual-entrypoint test (+ stale-values step)
    ├── test_infrahub_services.py                     # SC-003 read-only assertion
    └── drivers/{protocol,api_driver,ui_driver}.py    # + set_component_env_vars

driver/examples/*/driver.styrmin.yml                  # declare container on every component (FR-008)
driver/examples/*/values.j2.yml                       # drop component_env_vars wiring
driver/examples/simple-app/src/helm/templates/deployment.yaml  # + STYRMIN_CHART_DEFAULT_FROM valueFrom marker

frontend/src/
├── graphql/get_deployment.graphql                    # components { container }
├── components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx (+ test)  # FR-006
└── pages/drivers/driver-detail/tabs/ComponentsTab.tsx (+ test)  # show component container

python_sdk/src/styrmin_sdk/graphql/*.graphql          # isApplicable, componentConfigs.container
schema.graphql, generated SDK + frontend types        # regenerated

dev/adr/0057-post-render-component-overrides.md       # NEW, supersedes ADR-013 §1 + FR-026, narrows ADR-045 §2
dev/guides/driver-env-var-consumption.md              # rewrite
dev/knowledge/backend/deployment-env-vars.md          # update
docs/docs/drivers/{creating-a-driver,context}.md      # update
docs/docs/drivers/migrating-env-vars.md               # NEW migration guide
CONTEXT.md                                            # Component container (already drafted)
changelog/385.removed.md, changelog/385.changed.md    # towncrier
```

**Structure Decision**: existing web-service layout (backend + frontend + drivers); the new
patch builder mirrors `services/scheduling/patch_builder.py`, the new patch block lives with its
siblings in `blocks/patches.py`.

## Design Notes

1. **Patch builder** (D-009): pure function over `GlobalContext`; for each component with a
   container and non-empty `env_vars.config`, emit `ContainerEnvPatch` for `Deployment` and
   `StatefulSet` targeted by the identifier label. Eagerly render; typed error on failure. Log one
   info line per component with patches (`component`, `container`, env var count — never values).
   Unit tests round-trip scalar edge values (`"true"`, `"null"`, `"0123"`, `""`, multi-line,
   `$(VAR)`) through `yaml.safe_load` of the rendered patch and get strings back (critique E5, E8).
2. **Builder ordering** (D-002): `build()` appends env patches after scheduling patches. A unit
   test pins the position. Tests assert outcomes (entries present, values replaced, resources on
   the chart's original first container), not kyaml's full ordering (critique E9).
3. **Filter retirement** (D-008): `component_env_vars` stays registered as a raising stub whose
   message tells deployment users to upgrade the deployment and driver authors to migrate
   (critique P3). `instance.config.env_vars` and `components[<name>].env_vars` stay in the
   rendering context. Tests that pin the old filter contract
   (`test_render_value_template_env_vars.py`) are rewritten to the new contract, not deleted
   (critique E6).
4. **Write validation** (D-007): `_validate_component_env_var_containers(submitted, stored,
   containers_by_component)` runs in `update_deployment` once the target driver version is
   resolved (before any task is submitted) and in `deploy` against the selected version. It
   rejects additions and value changes for containerless components; removals and unchanged
   re-submissions pass. Test matrix: add / change / remove / unchanged × stable / switching
   driver version (critique E1, E2, X1).
5. **Read flags** (D-005, D-006): `ComponentEnvVars.isApplicable` computed in the resolver from
   driver-version component configs; `Component.container` and `ComponentConfig.container` read
   `config["container"]`.
6. **HelmRelease apply** (D-003): `upsert_custom_resource(..., replace_spec_keys_on_update=True)`
   sends a single JSON Patch (one `add /spec/<key>` per spec key the body sets, pruned, + per-key
   metadata `add` ops) on 409; the agent's StyrminDeployment CR applies use the same mode; other
   callers unchanged. Unit tests pin that kopf annotations and Flux's finalizer survive an update and
   that the builder always sets both metadata maps the per-key ops rely on (critique E3).
7. **Drivers** (D-010): add `container` to all 30 components, verified by rendering each driver
   with `helm template` — the command and matched container per component are recorded in the
   implementation notes (critique E4); strip env wiring from every `values.j2.yml`; move
   infrahub's `PREFECT_SERVER_ANALYTICS_ENABLED` to `global.prefect.env`; bump each driver's
   `spec.version`. The simple-app chart gains a harmless `STYRMIN_CHART_DEFAULT_FROM` entry
   (`valueFrom.fieldRef: metadata.name`) so the US1 E2E covers `valueFrom` replacement
   (critique P5).
8. **Frontend** (FR-006): editor disabled with an explanation when `component.container` is
   null; stored blocks shown read-only with a remove control (orphan-row precedent). The driver
   detail `ComponentsTab` shows each component's container (critique P4).
9. **Docs** (§VII): the migration guide (`docs/docs/drivers/migrating-env-vars.md`) covers, in
   order, loading migrated drivers, upgrading every deployment before editing environment env
   vars (fan-out would otherwise fail every old-version deployment), declaring containers,
   removing the filter, ordering (D-002), and that user env vars no longer reach chart Jobs or
   init containers (critique P2, P3). The ADR records the narrowed ADR-045 §2 reversal, platform
   rollback stopping injection (critique E7), and the deferred UI hint for silently skipped
   components (critique P1).

## Risks

| Risk | Mitigation |
|---|---|
| Wrong container name in an in-repo driver breaks releases once env vars are set | Render-verify every name and record it (D-010, Design Note 7); US1/US2 E2Es exercise simple-app; failure mode documented. |
| `spec` replace removes something a non-Styrmin actor wrote into the HelmRelease spec | Nothing else writes `spec` today (D-003); metadata keeps merge semantics; ADR records the narrowed contract. |
| Container reorder surprises `kubectl logs` / `get_component_env` | Documented (D-002); `get_component_env` gets the component container at index 0 when env vars are set. Name-based selection is a follow-up. |
| Deployments pinned to unmigrated driver versions fail on next render, including an environment env var fan-out | Intended (FR-007); the typed error states the remediation; migration guide orders the steps; changelog `removed` fragment flags it. |
| Kustomize/Flux version drift changes merge ordering | Outcome-based unit and E2E assertions (Design Note 2). |
| Platform rollback after migrated drivers are loaded stops env injection | Recorded in ADR consequences and release notes. |

## Complexity Tracking

No constitution violations to justify. The §II tension is recorded in the Constitution Check.
