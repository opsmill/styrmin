# Implementation Plan: Hierarchical Pod Scheduling & Resource Configuration

**Branch**: `001-pod-scheduling-config` | **Date**: 2026-04-20 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-pod-scheduling-config/spec.md`

## Summary

Extend the existing hierarchical configuration model (Environment → Deployment → Component; Cluster level intentionally excluded per research §2) with a new `scheduling` section that carries pod affinity/anti-affinity, node affinity, topology spread constraints, resource requests/limits (CPU, memory, ephemeral-storage, plus an opaque `extended` map), tolerations, and runtime class. The resolved per-component configuration is exposed in the driver template `GlobalContext` (with per-field provenance) and — by default — injected into every pod-template-bearing resource rendered by the driver via new Kustomize post-render patches appended to the existing FluxCD `HelmRelease.postRenderers` pipeline. Operators can opt out per feature and per scope (deployment or component) when a driver or a custom CRD controller needs to own a field.

Affinity rules may reference target deployments by platform identifier; the resolver expands those references into a `labelSelector` against the existing platform-generated `styrmin/deployment_id` and `styrmin/environment_id` identity labels placed on pod templates by the post-renderer. A new `styrmin/deployment_id` label (alongside the existing `styrmin/environment_id`) is added to `context.labels` so it is stamped onto every pod template by the already-present `TemplateLabelPatch` pipeline — no driver-side plumbing is required.

## Technical Context

**Language/Version**: Python 3.12+ (backend), TypeScript 5+ / React 19 (frontend)
**Primary Dependencies**:
- Backend: Strawberry (GraphQL), Pydantic v2, SQLModel, Prefect, Jinja2, `kubernetes`, PyYAML
- Frontend: React 19, Vite, urql, Tailwind, Base UI (read-only display only in this feature's scope)
- Rendering pipeline: FluxCD `HelmRelease.spec.postRenderers` with Kustomize JSON/strategic-merge patches (existing `TargetPatch` infrastructure in `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py`)
**Storage**: Existing SQLModel tables — `Cluster.config`, `Environment.config`, `Deployment.config`, `Component.config` (JSON columns). No new tables for the core feature. Audit trail reuses the existing deployment timeline / task-history machinery.
**Testing**: `pytest` (unit + functional); E2E tests run against a real vcluster with FluxCD, Prefect, and the kopf operator installed (see `tests/integration/operator/`).
**Target Platform**: Linux server (backend + Prefect worker + kopf operator), browsers (frontend), Kubernetes 1.28+ target clusters.
**Project Type**: Web application with Prefect agent and kopf operator — backend + frontend layout already established under `backend/` and `frontend/`.
**Performance Goals**: Resolution of a single deployment's effective scheduling configuration in <50 ms. Post-renderer patch generation MUST not add more than 10% rollout latency (SC-006).
**Constraints**:
- Must extend (not replace) the existing `BaseConfigSection` / `ClusterConfig` / `EnvironmentConfig` / `DeploymentConfig` / `ResolvedConfig` hierarchy without breaking existing consumers.
- Must preserve determinism: same inputs → same resolved output regardless of sibling evaluation order (FR-011).
- Injection must apply to every pod-template-bearing kind rendered by the driver (Deployment, StatefulSet, DaemonSet, Job, CronJob, ReplicaSet, and any other kind with `spec.template.spec`).
- Must not require driver-side changes (FR-013, SC-003 ≥ 80% drivers unchanged).
**Scale/Scope**: Hundreds of deployments × ~5 components each × 6 scheduling feature groups. Patch lists per HelmRelease may reach ~50 entries; Kustomize must continue to complete within existing rollout SLO.

## Constitution Check

The Styrmin Constitution (v1.1.0) defines six principles. Gate evaluation below.

| Principle | Status | Notes |
|---|---|---|
| I. Declarative State Reconciliation | PASS | The feature is a pure extension of the desired-state `config` payload; resolution is idempotent (same inputs → same output) and reconciliation already re-renders and re-applies on config change (FR-019). No new out-of-band state. |
| II. Driver-Based Deployment | PASS | No ad-hoc deployment logic is introduced; everything flows through the existing driver/helm-release pipeline. Drivers continue to be self-contained; scheduling injection is applied by the platform's post-renderer without requiring driver awareness. Drivers that opt in read from `GlobalContext` as they do for every other field. |
| III. Layered Architecture | PASS | New code lives in the existing layers: Pydantic/SQLModel models in `backend/styrmin_backend/context/models/` and `db/models.py` (no schema migration — reuses JSON columns), service logic in `backend/styrmin_backend/context/resolvers.py` and new helpers in `services/scheduling/`, repository access unchanged, GraphQL layer unchanged (same `config: JSON` mutations). Prefect workflows are not restructured. |
| IV. Type Safety and Typed Errors | PASS | New models are fully typed Pydantic v2 with `ConfigDict(extra="forbid")`. New errors subclass `ServiceError` with `error_code` / `default_message` (e.g., `InvalidSchedulingConfigError`, `UnknownComponentInConfigError`, `UnresolvableAffinityReferenceError`). No union-return error handling. |
| V. Test-First Development | PASS | Tests are listed up front in tasks and must land together with each user story's implementation. Unit tests cover the resolver (merge semantics, `replace: true`, list union, `replace`-per-kind scope, topology-spread keyed union). Functional tests cover GraphQL mutations with validation errors. E2E tests against vcluster validate that rendered pod specs carry the expected fields for each user story (US1–US6). A user story is not "done" until its E2E assertion passes. |
| VI. Format and Lint Before Commit | PASS | Existing `uv run invoke format lint` pipeline covers new files; no exceptions requested. |

**Gate result**: PASS — no violations to justify; Complexity Tracking table is empty.

Governance Gates (explicit-discussion areas):

- **Database schema or migration changes**: None. The feature reuses existing `config` JSON columns on `Cluster`, `Environment`, `Deployment`, `Component`. No Alembic migration.
- **GraphQL schema modifications**: None to the schema surface — `config: JSON` mutations already accept the new fields. Optionally we add a `resolvedScheduling` field on `Deployment` (read-only) in a follow-up; for the MVP the resolved view is delivered via the existing deployment status view consuming `context.instance.config`. Any additive field would be gated through the normal review.
- **New dependencies**: None. Kustomize patches use the existing FluxCD-provided Kustomize post-renderer. No new Python or JS packages.
- **CI/CD workflow changes**: None required for the backend path. E2E tests run in the existing vcluster pipeline (adopted on `develop` per commit `8956728`).
- **Authentication/authorization changes**: None — per assumption in the spec, editing a level's scheduling config reuses that level's existing edit permission.

## Project Structure

### Documentation (this feature)

```text
specs/001-pod-scheduling-config/
├── plan.md              # This file (/speckit.plan command output)
├── spec.md              # Feature spec (input)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── scheduling-config.schema.json     # Pydantic → JSON Schema export of SchedulingConfig
│   └── graphql-excerpt.graphql           # Additive GraphQL snippets (read-only resolved view)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── context/
│   │   ├── models/
│   │   │   ├── config.py                 # + SchedulingConfig, ResourceSpec, AffinityBlock, RuntimeClassRef, Toleration, etc.
│   │   │   │                             # + add scheduling: SchedulingConfig | None to BaseConfigSection
│   │   │   │                             # + add scheduling: ComponentSchedulingConfig | None on ComponentContext
│   │   │   └── contexts.py               # GlobalContext.components[*].config exposes resolved scheduling + provenance
│   │   ├── resolvers.py                  # + _resolve_scheduling_config(env, deployment, component, driver_components)
│   │   │                                 #   Implements FR-007..FR-011 and Story 5 provenance map.
│   │   └── exceptions.py                 # + InvalidSchedulingConfigError, UnknownComponentInConfigError,
│   │                                     #   UnresolvableAffinityReferenceError, RuntimeClassNotFoundError
│   ├── services/
│   │   ├── scheduling/                   # NEW package
│   │   │   ├── __init__.py
│   │   │   ├── models.py                 # Domain models for SchedulingConfig (mirrors / re-exports context models)
│   │   │   ├── resolver.py               # Thin wrapper that calls context.resolvers for API consumers
│   │   │   ├── validator.py              # Component-name validation, resource-quantity validation,
│   │   │   │                             # runtime-class existence check (delegates to cluster capabilities),
│   │   │   │                             # deployment-reference resolution for affinity rules.
│   │   │   └── patch_builder.py          # Translates resolved SchedulingConfig → list[TargetPatch]
│   │   └── context.py                    # Pass driver-declared components to resolver for FR-005 validation;
│   │                                     # add "deployment_id" to context.labels (for affinity-by-reference).
│   └── agent/
│       └── service/
│           └── kubernetes/
│               └── resources/
│                   ├── blocks/
│                   │   └── patches.py    # + AffinityPatch, ResourcesPatch, TolerationsPatch,
│                   │                     #   RuntimeClassPatch, TopologySpreadPatch, NodeAffinityPatch
│                   │                     #   (strategic-merge YAML against pod-template-bearing kinds)
│                   └── builders/
│                       └── application.py # + build_scheduling_post_rendering_patches(self.context) honouring
│                                          #   per-feature opt-outs; wire into build() after component labels.
└── tests/
    ├── unit/
    │   ├── context/
    │   │   ├── test_scheduling_resolver.py          # FR-007..FR-011 merge semantics
    │   │   └── test_scheduling_replace_semantics.py # replace: true per affinity-kind
    │   ├── services/
    │   │   ├── test_scheduling_validator.py         # Component name, quantity, runtime-class, deployment ref
    │   │   └── test_scheduling_patch_builder.py     # TargetPatch generation per feature, opt-outs, label selectors
    │   └── agent/
    │       └── test_application_builder_scheduling.py # Integration of patches into HelmRelease build
    ├── functional/
    │   └── test_api_scheduling_config.py            # GraphQL: set/clear at each level, validation errors
    └── ...

tests/
└── integration/
    └── operator/
        └── test_pod_scheduling_e2e.py               # Real vcluster E2E for all user stories (US1–US6)

frontend/
└── src/
    └── pages/
        ├── environments/EnvironmentDetailPage.tsx   # Read-only display of scheduling under the existing config tab
        └── deployments/DeploymentDetailPage.tsx     # Read-only display + resolved-effective-config view per component
```

**Structure Decision**: The project is a web application with the backend + frontend layout already in place. This feature adds files inside the existing `backend/styrmin_backend/` tree (no new top-level packages outside the intentional `services/scheduling/` submodule) and extends the existing frontend detail pages with a read-only view. No restructuring is required.

## Complexity Tracking

> No Constitution violations — the table below is intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|

---

## Phase 0 — Outline & Research

Completed. See [research.md](./research.md) for decisions on: config model extension strategy, affinity merge semantics, topology-spread keyed union, post-renderer patch shapes, affinity-by-deployment-reference resolution, runtime-class validation surface, and opt-out wiring.

## Phase 1 — Design & Contracts

Completed. Artifacts:

- [data-model.md](./data-model.md) — full entity and field definitions for the extended configuration.
- [contracts/scheduling-config.schema.json](./contracts/scheduling-config.schema.json) — JSON Schema for the `scheduling` section, produced from the Pydantic model definition.
- [contracts/graphql-excerpt.graphql](./contracts/graphql-excerpt.graphql) — additive (read-only) GraphQL surface for resolved scheduling visibility.
- [quickstart.md](./quickstart.md) — end-to-end walk-through for a platform operator configuring each level and verifying the rendered pod specs.

**Agent context update**: Skipped per constitution ("Never execute the script `update-agent-context.sh`"). Agent context files are maintained manually.

## Post-Design Constitution Re-check

Re-evaluated after Phase 1 artifacts were produced — all six principles still PASS. Governance-gated areas (DB migrations, GraphQL schema, new deps, CI, auth) remain unchanged by the design. No new violations surfaced.
