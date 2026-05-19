# Developer Documentation

Internal documentation for contributors. For user-facing docs, see `/docs/`.

## Quick Navigation

| I want to... | Go to |
|--------------|-------|
| Understand the architecture | `knowledge/` |
| Follow coding standards | `guidelines/` |
| Learn why we made a decision | `adr/` |
| Complete a specific task | `guides/` |
| See what's being built | `../specs/` |
| Use agent workflows | `../.agents/skills/` and `../.agents/commands/` |

## Directory Guide

- **specs/**: Approved designs at repo root (`../specs/`). Living during development, then archived.
- **guidelines/**: Prescriptive rules. How code should be written.
  - `backend/` - Python backend standards
- **knowledge/**: Descriptive reference. How the system works.
  - `backend/` - Backend architecture and patterns
- **guides/**: Step-by-step procedures for specific tasks.
- **adr/**: Architecture Decision Records. Why we chose what we chose.
- **prompts/**: Prompt templates for common thinking tasks. Currently empty.

Agent workflows live at the repo root under `.agents/skills/` and `.agents/commands/`.

## Document Lifecycle

```text
explorations/ → specs/ → knowledge/ or guidelines/
   (rough)     (approved)      (stable)
```

Mark deprecated docs clearly. Don't delete—update with pointers to replacements.

## Current Guidelines

- [backend/python.md](guidelines/backend/python.md) - Python coding standards, tooling, patterns
- [frontend/routing.md](guidelines/frontend/routing.md) - TanStack Router conventions: `$param` syntax, type registration, navigation
- [frontend/data-fetching.md](guidelines/frontend/data-fetching.md) - TanStack Query + GraphQL codegen: invalidation, polling, conditional fetch
- [frontend/forms.md](guidelines/frontend/forms.md) - TanStack Form + Zod: field bindings, subscriptions, dynamic fields
- [frontend/ui-primitives.md](guidelines/frontend/ui-primitives.md) - Base UI wrapper layer, data-attribute selectors, polymorphic Button
- [cyclopts.md](guidelines/cyclopts.md) - Cyclopts CLI conventions: parameters, validators, type aliases, lazy loading
- [markdown.md](guidelines/markdown.md) - Markdown conventions and document structure

## Current ADRs

- [adr-001-alembic-database-migrations.md](adr/adr-001-alembic-database-migrations.md) - Adopt Alembic for versioned database migration management
- [adr-002-shared-async-event-loop-kopf-prefect.md](adr/adr-002-shared-async-event-loop-kopf-prefect.md) - Shared async event loop for kopf operator and Prefect agent
- [adr-003-leader-election-kopf-peering.md](adr/adr-003-leader-election-kopf-peering.md) - Priority-based leader election via kopf peering
- [adr-004-embed-context-in-deployment-crd.md](adr/adr-004-embed-context-in-deployment-crd.md) - Embed GlobalContext in StyrminDeployment CRD for autonomous reconciliation
- [adr-005-ordered-phase-deployment-sub-handlers.md](adr/adr-005-ordered-phase-deployment-sub-handlers.md) - Ordered phase-based deployment via kopf sub-handlers
- [adr-006-prefect-crd-intent-declaration.md](adr/adr-006-prefect-crd-intent-declaration.md) - Prefect flows declare intent via CRD instead of direct resource management
- [adr-007-pod-status-records-observed-state-not-declared-state.md](adr/adr-007-pod-status-records-observed-state-not-declared-state.md) - Pod-status records observed runtime state, not declared component intent
- [adr-008-deployment-soft-delete-tombstoning.md](adr/adr-008-deployment-soft-delete-tombstoning.md) - Soft-delete tombstoning with the agent status reporter as the sole writer of `Deployment.deleted_at`
- [adr-009-forensic-cr-retention-janitor.md](adr/adr-009-forensic-cr-retention-janitor.md) - Forensic-retention CR janitor: TTL-gated reaping of `phase: Deleted` CRs, never reaps `Deleting`-stuck ones
- [adr-010-tombstone-visibility-conflation.md](adr/adr-010-tombstone-visibility-conflation.md) - Tombstoned-record visibility: `NOT_FOUND` conflation on writes + opt-in `includeDeleted` filter on reads
- [adr-011-scoped-tombstone-aware-name-uniqueness.md](adr/adr-011-scoped-tombstone-aware-name-uniqueness.md) - Per-environment, tombstone-aware deployment name uniqueness via partial unique index
- [adr-012-environment-config-fanout.md](adr/adr-012-environment-config-fanout.md) - Environment-config update — typed `UpdateEnvironmentInput`, per-deployment fanout, clean replace
- [adr-013-driver-env-var-consumption.md](adr/adr-013-driver-env-var-consumption.md) - Deployment env vars: free-form `dict[str, str]`, three-scope deepest-wins, consumed driver-side via the values template (no platform post-render injection)
- [adr-014-schema-walking-input-propagation-tests.md](adr/adr-014-schema-walking-input-propagation-tests.md) - Schema-walking propagation tests for Strawberry input completeness against Pydantic config models
- [adr-015-frontend-value-transform-boundary.md](adr/adr-015-frontend-value-transform-boundary.md) - Frontend value-transform layer at the GraphQL submit boundary for full-replacement inputs
- [adr-016-authentication-and-sessions.md](adr/adr-016-authentication-and-sessions.md) - Opaque server-side session tokens with dual transport (HttpOnly cookie + bearer header), 30-day absolute / 7-day idle lifetime, argon2id passwords
- [adr-017-authorization-model.md](adr/adr-017-authorization-model.md) - Three-tier role-based authorization (`READ_ONLY` / `READ_WRITE` / `ADMIN`) with default-deny `RequiresAuthentication` extension and per-resolver `RequiresRole`
- [adr-018-typed-update-deployment-input.md](adr/adr-018-typed-update-deployment-input.md) - Typed `UpdateDeploymentInput` — list-shaped named-dict fields with typed duplicate detection, `parameters`-merge asymmetry, shared leaf inputs under `config/inputs.py`
- [adr-019-crd-phase-and-task-callback-coexist.md](adr/adr-019-crd-phase-and-task-callback-coexist.md) - CRD phase reports and Prefect task callbacks both write `Deployment.status` via last-write-wins; CRD phase → status mapping
- [adr-020-separate-crd-status-reporting-mutation.md](adr/adr-020-separate-crd-status-reporting-mutation.md) - Dedicated `reportCrdStatuses` mutation alongside `reportPodStatuses` to keep observed-state channels orthogonal
- [adr-021-deployment-crd-status-snapshot-table.md](adr/adr-021-deployment-crd-status-snapshot-table.md) - One-to-one `DeploymentCrdStatus` snapshot table with JSON conditions/managed-resource counts, mirroring the PodStatus observed-state pattern
- [adr-022-compute-service-fqdns-at-runtime.md](adr/adr-022-compute-service-fqdns-at-runtime.md) - Compute service FQDNs at runtime instead of persisting; both UI resolver and driver-context call sites stay live against the resolved config hierarchy
- [adr-023-dedicated-mutation-per-observed-state-channel.md](adr/adr-023-dedicated-mutation-per-observed-state-channel.md) - Each observed-state channel gets its own `report<X>Statuses` GraphQL mutation rather than overloading `callback()` or bundling channels
- [adr-024-two-pronged-stale-data-cleanup.md](adr/adr-024-two-pronged-stale-data-cleanup.md) - Observed-state tables cleaned via server-side stale-set diff per cycle + FK cascade on deployment delete; agent only sends "active set"
- [adr-025-capabilities-as-extensible-json-column.md](adr/adr-025-capabilities-as-extensible-json-column.md) - Cluster/Environment `capabilities` persisted as JSON column with extensible nested-dict schema `{category: {sub: details}}`, exposed as `JSON` GraphQL scalar
- [adr-026-capabilities-recalculation-in-service-layer.md](adr/adr-026-capabilities-recalculation-in-service-layer.md) - Capabilities recalculated synchronously in service-layer mutations within the same `UnitOfWork`; no triggers, no background tasks, no event bus
- [adr-027-environment-capabilities-computed-independently.md](adr/adr-027-environment-capabilities-computed-independently.md) - Environment capabilities computed directly from environment's own config + relationships, not by copying/filtering cluster capabilities
- [adr-028-deployment-history-derived-from-existing-data.md](adr/adr-028-deployment-history-derived-from-existing-data.md) - `deploymentTimeline` query derives version + context diff at read time from existing `Task` and `ApplicationInstance.context` rows — no schema additions
- [adr-029-config-additions-via-baseconfigsection-no-migration.md](adr/adr-029-config-additions-via-baseconfigsection-no-migration.md) - Default pattern for operator-tunable config knobs: add to `BaseConfigSection`, no DB migration, no GraphQL schema change — rides existing JSON columns and `config: JSON` mutations
- [adr-030-lockstep-gating-middleware-annotation-and-resource.md](adr/adr-030-lockstep-gating-middleware-annotation-and-resource.md) - Rendered name-references (e.g., Traefik `router.middlewares` annotation → `Middleware` resource) gated on the same condition as their referent; both render or neither does
- [adr-031-dual-identifier-resolution-service-layer.md](adr/adr-031-dual-identifier-resolution-service-layer.md) - GraphQL operations accept `<resource>Id` / `<resource>Name` optional pair; service-layer `resolve_<resource>` helpers validate mutual exclusivity and own the name → entity lookup (`AmbiguousIdentifierError`)
- [adr-032-resourcespec-first-class-plus-extended-map.md](adr/adr-032-resourcespec-first-class-plus-extended-map.md) - `ResourceSpec` types CPU/memory/ephemeral-storage as first-class fields plus an `extended: dict[str, str]` map (hugepages, GPUs, vendor resources) with quantity validation only
- [adr-033-scheduling-merge-semantics.md](adr/adr-033-scheduling-merge-semantics.md) - Scheduling merge: Environment → Deployment → Component, affinity accumulate with per-kind `replace:true`, topology-spread keyed by `(topologyKey, whenUnsatisfiable)`; no cluster-level scheduling
- [adr-034-affinity-by-deployment-reference-via-label.md](adr/adr-034-affinity-by-deployment-reference-via-label.md) - Affinity-by-deployment-reference expands to a `labelSelector` against the `styrmin/deployment_id` pod label, stamped by `TemplateLabelPatch` on every platform-managed pod template
- [adr-035-post-render-injection-toggles-and-kind-list.md](adr/adr-035-post-render-injection-toggles-and-kind-list.md) - Post-render injection: six per-feature `inject.*` booleans at deployment/component scope (no environment scope), patches target a static six-kind list (`Deployment`, `StatefulSet`, `DaemonSet`, `Job`, `CronJob`, `ReplicaSet`)
- [adr-036-scheduling-provenance-map.md](adr/adr-036-scheduling-provenance-map.md) - Resolved scheduling carries a parallel `provenance: dict[str, "environment" | "deployment" | "component"]` map keyed by dotted paths so operators can see which level contributed each value
- [adr-037-sdk-typed-bindings-outer-wrapper-and-facade.md](adr/adr-037-sdk-typed-bindings-outer-wrapper-and-facade.md) - SDK keeps `Transport.execute()` + `load_query()`, swaps hand-written models for ariadne-codegen outer-wrapper validation, re-exports canonical names from `models/__init__.py` as a facade
- [adr-038-scenario-driver-protocol-and-parametrized-fixture.md](adr/adr-038-scenario-driver-protocol-and-parametrized-fixture.md) - E2E `ScenarioDriver` Protocol with API/UI implementations + parametrized fixture; one scenario body produces `[api-chromium]` and `[ui-chromium]` variants; `-k` is the single selection axis
- [adr-039-single-cluster-platform-scope.md](adr/adr-039-single-cluster-platform-scope.md) - Platform is single-cluster — enforced at service layer (`ClusterLimitReachedError`), no DB constraint, default name `"default"`; multi-cluster is a future architectural project
- [adr-040-cosign-keyless-image-signing.md](adr/adr-040-cosign-keyless-image-signing.md) - Container images signed with cosign keyless via GitHub Actions OIDC; sign by digest, not tag; one signature on the multi-arch manifest list covers all architectures
- [adr-041-release-workflow-orchestration.md](adr/adr-041-release-workflow-orchestration.md) - Release pipeline split into `release.yml` orchestrator + reusable child workflows (`docker-publish.yml`, `publish-helm-chart.yml`); static concurrency group with `cancel-in-progress: false` so an in-flight release is never killed mid-write
- [adr-042-multiarch-via-native-runner-matrix.md](adr/adr-042-multiarch-via-native-runner-matrix.md) - Multi-arch Docker built on native runners (`ubuntu-24.04` + `ubuntu-24.04-arm64`) via a matrix + `imagetools` manifest merge, not QEMU emulation; per-arch pushes by digest only, manifest signed as one
- [adr-043-docs-site-and-documentation-lifecycle.md](adr/adr-043-docs-site-and-documentation-lifecycle.md) - User-facing docs live in Docusaurus at `docs/`; `dev/knowledge/`, `dev/guides/`, `dev/adr/` stay contributor-internal; promotion from `dev/` to `docs/` is a deliberate authoring step, not automatic extraction

## Current Knowledge

- [architecture.md](knowledge/architecture.md) - High-level system architecture: server↔agent topology, declarative state, context model. Companion to the constitution.

Backend (server) architecture documentation in [knowledge/backend/](knowledge/backend/):

- [overview.md](knowledge/backend/overview.md) - Architecture overview, directory structure, request flow
- [api.md](knowledge/backend/api.md) - GraphQL API (public and internal), types, response patterns
- [data-models.md](knowledge/backend/data-models.md) - Database, domain, and context models
- [services.md](knowledge/backend/services.md) - Service layer, unit of work, business logic
- [reconciliation.md](knowledge/backend/reconciliation.md) - Reconciliation engine, diff computation, remediation strategies
- [hooks-and-actions.md](knowledge/backend/hooks-and-actions.md) - Hook system, driver actions, setup/upgrade hooks
- [orchestration-flows.md](knowledge/backend/orchestration-flows.md) - Prefect orchestration flows, callbacks, execution patterns (the agent runs the Prefect worker that executes these flows)
- [backup-restore.md](knowledge/backend/backup-restore.md) - Backup/restore system, Velero integration, strategies
- [e2e-testing.md](knowledge/backend/e2e-testing.md) - E2E testing architecture, vcluster setup, fixture graph
- [dead-code.md](knowledge/backend/dead-code.md) - Remaining dead code and cleanup tracking

Agent (in-cluster) architecture documentation in [knowledge/agent/](knowledge/agent/):

- [overview.md](knowledge/agent/overview.md) - Agent process layout, where Prefect lives, Kubernetes resource builders, status reporter
- [operator.md](knowledge/agent/operator.md) - Kopf operator, StyrminDeployment CRD, phase-based deployment, drift reconciliation

Frontend architecture documentation in [knowledge/frontend/](knowledge/frontend/):

- [routing.md](knowledge/frontend/routing.md) - TanStack Router architecture, route tree, type registration, lazy routes
- [data-fetching.md](knowledge/frontend/data-fetching.md) - TanStack Query + codegen pipeline, fetcher, cache invalidation, polling
- [forms.md](knowledge/frontend/forms.md) - TanStack Form architecture, Zod integration, field bindings, dynamic fields
- [ui-primitives.md](knowledge/frontend/ui-primitives.md) - Base UI wrapper layer, Slot utility, data-attribute conventions

## Current Guides

- [database-migrations.md](guides/database-migrations.md) - Alembic migration workflow: creating, applying, and rolling back migrations
- [graphql-propagation-tests.md](guides/graphql-propagation-tests.md) - How to write the unit test that proves a GraphQL field is wired through every layer to the database
- [local-demo.md](guides/local-demo.md) - Local vCluster demo lifecycle
- [pod-scheduling.md](guides/pod-scheduling.md) - Pod scheduling configuration reference
- [session-retrospectives.md](guides/session-retrospectives.md) - End-of-session workflow for turning agent friction into approved context-management improvements
- [users-and-groups.md](guides/users-and-groups.md) - Operator guide to users, groups, roles, the bootstrap admin, the Settings → Access UI, lockout recovery, and v1 limitations
