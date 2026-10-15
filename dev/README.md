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

- **specs/**: Approved designs at repo root (`../specs/`). Living during development, then extracted into `knowledge/` / `guidelines/` / `adr/` and moved to `../specs/archive/` with an `EXTRACTED.md` record.
- **guidelines/**: Prescriptive rules. How code should be written.
  - `backend/` - Python backend standards
  - `frontend/` - React/TypeScript standards
  - `cyclopts.md` - CLI authoring standards
- **knowledge/**: Descriptive reference. How the system works.
  - `backend/` - Backend (server) architecture and patterns
  - `agent/` - In-cluster agent and operator
  - `frontend/` - Frontend architecture
  - `cli/` - `styrminctl` internals
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
- [helm.md](guidelines/helm.md) - Styrmin chart rules: requests only, never resource limits
- [changelog.md](guidelines/changelog.md) - towncrier newsfragments: types, naming, and how releases assemble CHANGELOG.md
- [markdown.md](guidelines/markdown.md) - Markdown conventions and document structure

## Current ADRs

- [0001-alembic-database-migrations.md](adr/0001-alembic-database-migrations.md) - Adopt Alembic for versioned database migration management
- [0002-shared-async-event-loop-kopf-prefect.md](adr/0002-shared-async-event-loop-kopf-prefect.md) - Shared async event loop for kopf operator and Prefect agent
- [0003-leader-election-kopf-peering.md](adr/0003-leader-election-kopf-peering.md) - Priority-based leader election via kopf peering
- [0004-embed-context-in-deployment-crd.md](adr/0004-embed-context-in-deployment-crd.md) - Embed GlobalContext in StyrminDeployment CRD for autonomous reconciliation
- [0005-ordered-phase-deployment-sub-handlers.md](adr/0005-ordered-phase-deployment-sub-handlers.md) - Ordered phase-based deployment via kopf sub-handlers
- [0006-prefect-crd-intent-declaration.md](adr/0006-prefect-crd-intent-declaration.md) - Prefect flows declare intent via CRD instead of direct resource management
- [0007-pod-status-records-observed-state-not-declared-state.md](adr/0007-pod-status-records-observed-state-not-declared-state.md) - Pod-status records observed runtime state, not declared component intent
- [0008-deployment-soft-delete-tombstoning.md](adr/0008-deployment-soft-delete-tombstoning.md) - Soft-delete tombstoning with the agent status reporter as the sole writer of `Deployment.deleted_at`
- [0009-forensic-cr-retention-janitor.md](adr/0009-forensic-cr-retention-janitor.md) - Forensic-retention CR janitor: TTL-gated reaping of `phase: Deleted` CRs, never reaps `Deleting`-stuck ones
- [0010-tombstone-visibility-conflation.md](adr/0010-tombstone-visibility-conflation.md) - Tombstoned-record visibility: `NOT_FOUND` conflation on writes + opt-in `includeDeleted` filter on reads
- [0011-scoped-tombstone-aware-name-uniqueness.md](adr/0011-scoped-tombstone-aware-name-uniqueness.md) - Per-environment, tombstone-aware deployment name uniqueness via partial unique index
- [0012-environment-config-fanout.md](adr/0012-environment-config-fanout.md) - Environment-config update — typed `UpdateEnvironmentInput`, per-deployment fanout, clean replace
- [0013-driver-env-var-consumption.md](adr/0013-driver-env-var-consumption.md) - Deployment env vars: free-form `dict[str, str]`, three-scope deepest-wins, consumed driver-side via the values template (no platform post-render injection); superseded in part by ADR-057
- [0014-schema-walking-input-propagation-tests.md](adr/0014-schema-walking-input-propagation-tests.md) - Schema-walking propagation tests for Strawberry input completeness against Pydantic config models
- [0015-frontend-value-transform-boundary.md](adr/0015-frontend-value-transform-boundary.md) - Frontend value-transform layer at the GraphQL submit boundary for full-replacement inputs
- [0016-authentication-and-sessions.md](adr/0016-authentication-and-sessions.md) - Opaque server-side session tokens with dual transport (HttpOnly cookie + bearer header), 30-day absolute / 7-day idle lifetime, argon2id passwords
- [0017-authorization-model.md](adr/0017-authorization-model.md) - Three-tier role-based authorization (`READ_ONLY` / `READ_WRITE` / `ADMIN`) with default-deny `RequiresAuthentication` extension and per-resolver `RequiresRole`
- [0018-typed-update-deployment-input.md](adr/0018-typed-update-deployment-input.md) - Typed `UpdateDeploymentInput` — list-shaped named-dict fields with typed duplicate detection, `parameters`-merge asymmetry, shared leaf inputs under `config/inputs.py`
- [0019-crd-phase-and-task-callback-coexist.md](adr/0019-crd-phase-and-task-callback-coexist.md) - CRD phase reports and Prefect task callbacks both write `Deployment.status` via last-write-wins; CRD phase → status mapping
- [0020-separate-crd-status-reporting-mutation.md](adr/0020-separate-crd-status-reporting-mutation.md) - Dedicated `reportCrdStatuses` mutation alongside `reportPodStatuses` to keep observed-state channels orthogonal
- [0021-deployment-crd-status-snapshot-table.md](adr/0021-deployment-crd-status-snapshot-table.md) - One-to-one `DeploymentCrdStatus` snapshot table with JSON conditions/managed-resource counts, mirroring the PodStatus observed-state pattern
- [0022-compute-service-fqdns-at-runtime.md](adr/0022-compute-service-fqdns-at-runtime.md) - Compute service FQDNs at runtime instead of persisting; both UI resolver and driver-context call sites stay live against the resolved config hierarchy
- [0023-dedicated-mutation-per-observed-state-channel.md](adr/0023-dedicated-mutation-per-observed-state-channel.md) - Each observed-state channel gets its own `report<X>Statuses` GraphQL mutation rather than overloading `callback()` or bundling channels
- [0024-two-pronged-stale-data-cleanup.md](adr/0024-two-pronged-stale-data-cleanup.md) - Observed-state tables cleaned via server-side stale-set diff per cycle + FK cascade on deployment delete; agent only sends "active set"
- [0025-capabilities-as-extensible-json-column.md](adr/0025-capabilities-as-extensible-json-column.md) - Cluster/Environment `capabilities` persisted as JSON column with extensible nested-dict schema `{category: {sub: details}}`, exposed as `JSON` GraphQL scalar
- [0026-capabilities-recalculation-in-service-layer.md](adr/0026-capabilities-recalculation-in-service-layer.md) - Capabilities recalculated synchronously in service-layer mutations within the same `UnitOfWork`; no triggers, no background tasks, no event bus
- [0027-environment-capabilities-computed-independently.md](adr/0027-environment-capabilities-computed-independently.md) - Environment capabilities computed directly from environment's own config + relationships, not by copying/filtering cluster capabilities
- [0028-deployment-history-derived-from-existing-data.md](adr/0028-deployment-history-derived-from-existing-data.md) - `deploymentTimeline` query derives version + context diff at read time from existing `Task` and `ApplicationInstance.context` rows — no schema additions
- [0029-config-additions-via-baseconfigsection-no-migration.md](adr/0029-config-additions-via-baseconfigsection-no-migration.md) - Default pattern for operator-tunable config knobs: add to `BaseConfigSection`, no DB migration, no GraphQL schema change — rides existing JSON columns and `config: JSON` mutations
- [0030-lockstep-gating-middleware-annotation-and-resource.md](adr/0030-lockstep-gating-middleware-annotation-and-resource.md) - Rendered name-references (e.g., Traefik `router.middlewares` annotation → `Middleware` resource) gated on the same condition as their referent; both render or neither does
- [0031-dual-identifier-resolution-service-layer.md](adr/0031-dual-identifier-resolution-service-layer.md) - GraphQL operations accept `<resource>Id` / `<resource>Name` optional pair; service-layer `resolve_<resource>` helpers validate mutual exclusivity and own the name → entity lookup (`AmbiguousIdentifierError`)
- [0032-resourcespec-first-class-plus-extended-map.md](adr/0032-resourcespec-first-class-plus-extended-map.md) - `ResourceSpec` types CPU/memory/ephemeral-storage as first-class fields plus an `extended: dict[str, str]` map (hugepages, GPUs, vendor resources) with quantity validation only
- [0033-scheduling-merge-semantics.md](adr/0033-scheduling-merge-semantics.md) - Scheduling merge: Environment → Deployment → Component, affinity accumulate with per-kind `replace:true`, topology-spread keyed by `(topologyKey, whenUnsatisfiable)`; no cluster-level scheduling
- [0034-affinity-by-deployment-reference-via-label.md](adr/0034-affinity-by-deployment-reference-via-label.md) - Affinity-by-deployment-reference expands to a `labelSelector` against the `styrmin/deployment_id` pod label, stamped by `TemplateLabelPatch` on every platform-managed pod template
- [0035-post-render-injection-toggles-and-kind-list.md](adr/0035-post-render-injection-toggles-and-kind-list.md) - Post-render injection: six per-feature `inject.*` booleans at deployment/component scope (no environment scope), patches target a static six-kind list (`Deployment`, `StatefulSet`, `DaemonSet`, `Job`, `CronJob`, `ReplicaSet`)
- [0036-scheduling-provenance-map.md](adr/0036-scheduling-provenance-map.md) - Resolved scheduling carries a parallel `provenance: dict[str, "environment" | "deployment" | "component"]` map keyed by dotted paths so operators can see which level contributed each value
- [0037-sdk-typed-bindings-outer-wrapper-and-facade.md](adr/0037-sdk-typed-bindings-outer-wrapper-and-facade.md) - SDK keeps `Transport.execute()` + `load_query()`, swaps hand-written models for ariadne-codegen outer-wrapper validation, re-exports canonical names from `models/__init__.py` as a facade
- [0038-scenario-driver-protocol-and-parametrized-fixture.md](adr/0038-scenario-driver-protocol-and-parametrized-fixture.md) - E2E `ScenarioDriver` Protocol with API/UI implementations + parametrized fixture; one scenario body produces `[api-chromium]` and `[ui-chromium]` variants; `-k` is the single selection axis
- [0039-single-cluster-platform-scope.md](adr/0039-single-cluster-platform-scope.md) - Platform is single-cluster — enforced at service layer (`ClusterLimitReachedError`), no DB constraint, default name `"default"`; multi-cluster is a future architectural project
- [0040-cosign-keyless-image-signing.md](adr/0040-cosign-keyless-image-signing.md) - Container images signed with cosign keyless via GitHub Actions OIDC; sign by digest, not tag; one signature on the multi-arch manifest list covers all architectures
- [0041-release-workflow-orchestration.md](adr/0041-release-workflow-orchestration.md) - Release pipeline split into `release.yml` orchestrator + reusable child workflows (`docker-publish.yml`, `publish-helm-chart.yml`); static concurrency group with `cancel-in-progress: false` so an in-flight release is never killed mid-write
- [0042-multiarch-via-native-runner-matrix.md](adr/0042-multiarch-via-native-runner-matrix.md) - Multi-arch Docker built on native runners (`ubuntu-24.04` + `ubuntu-24.04-arm64`) via a matrix + `imagetools` manifest merge, not QEMU emulation; per-arch pushes by digest only, manifest signed as one
- [0043-docs-site-and-documentation-lifecycle.md](adr/0043-docs-site-and-documentation-lifecycle.md) - User-facing docs live in Docusaurus at `docs/`; `dev/knowledge/`, `dev/guides/`, `dev/adr/` stay contributor-internal; promotion from `dev/` to `docs/` is a deliberate authoring step, not automatic extraction
- [0044-e2e-matrix-sharding.md](adr/0044-e2e-matrix-sharding.md) - E2E parallelism via CI matrix shards (one vCluster per shard, bare-name shard markers enforced at collection), not pytest-xdist
- [0045-container-override-no-layering-and-omit-marker.md](adr/0045-container-override-no-layering-and-omit-marker.md) - Component-scope `command`/`args`: no layering, empty-list marker with a chart `{{- with }}` guard (the omit-marker broke clearing under merge-patch), per-field typed errors; merge-patch apply narrowed by ADR-057; §2 and §5 superseded by ADR-069
- [0046-tombstone-cleanup-of-deployed-services.md](adr/0046-tombstone-cleanup-of-deployed-services.md) - Delete `DeployedService` rows when a deployment is tombstoned so a redeploy does not collide on service name
- [0047-styrminctl-anonymous-fire-and-forget-telemetry.md](adr/0047-styrminctl-anonymous-fire-and-forget-telemetry.md) - Anonymous opt-out CLI telemetry: closed key set scrubbed by construction, daemon-thread dispatch with a hard 200 ms cap, default-on but silent with CI/non-TTY exclusion
- [0048-declarative-apply-client-side-orchestration.md](adr/0048-declarative-apply-client-side-orchestration.md) - Declarative apply is orchestrated client-side in the SDK over the existing `deploy`/`updateDeployment`/`updateDeploymentVersion` mutations; config before version, one re-lookup on a duplicate-name race
- [0049-styrmin-v1-manifest-contract.md](adr/0049-styrmin-v1-manifest-contract.md) - The `styrmin/v1` manifest: strict `extra="forbid"` parsing, full replacement of `config`/`parameters`, flag > env > manifest precedence, `cluster` as a disambiguation hint, deliberately not kubectl-compatible
- [0050-composite-natural-key-deployment-lookup.md](adr/0050-composite-natural-key-deployment-lookup.md) - `deployment(name, environmentId)` composite natural-key shape with a runtime argument-group guard; the bounded carve-out from ADR-031's `<resource>Id`/`<resource>Name` pattern
- [0051-styrminctl-credential-resolution-and-token-store.md](adr/0051-styrminctl-credential-resolution-and-token-store.md) - CLI credential ladder (env > auto-login > file > none) resolved at one chokepoint, plus the versioned, canonical-URL-keyed, atomically-written token store
- [0052-client-side-config-diff-impact-and-conflict-detection.md](adr/0052-client-side-config-diff-impact-and-conflict-detection.md) - Deployment config drawer: hand-rolled stable-key structural diff, declarative impact rule table behind a swappable interface, client-side fingerprint conflict detection with reload-keeping-edits
- [0053-driver-version-provenance-fingerprint.md](adr/0053-driver-version-provenance-fingerprint.md) - Driver-version identity widens to include a provenance fingerprint (`content_hash` for local, `source_commit_sha` for git); no load ever deletes a row; labels always render `<version>@<short7>`
- [0054-backend-authoritative-noop-detection.md](adr/0054-backend-authoritative-noop-detection.md) - No-op detection runs in the service layer before any write and is signalled by returning `null` from the already-nullable `Task` field; reverts the SDK-side stopgap
- [0055-environment-backup-parent-records.md](adr/0055-environment-backup-parent-records.md) - Environment backup/restore as parent records grouping constituents via nullable child FKs, with status derived on every read and never stored; the justified deviation from ADR-012's umbrella rejection, plus the restore ordering that excludes restored deployments from the config fan-out
- [0056-environment-clone-record-and-cross-target-restore.md](adr/0056-environment-clone-record-and-cross-target-restore.md) - Environment clone as a first-class `EnvironmentClone` record with derived status, built from a fresh environment backup and a cross-target restore (Velero `namespaceMapping`) into counterpart deployments that keep the source's Helm release name; a waiting INTERNAL flow; `IN_USE` delete guard limited to the capture window
- [0057-post-render-component-overrides.md](adr/0057-post-render-component-overrides.md) - Drivers declare a component container per component; env vars merge into it by a strategic-merge post-render patch (chart entries survive), `component_env_vars` retired, Styrmin-managed HelmRelease `spec` keys replaced on update; wrong-name failure narrowed by ADR-058
- [0058-image-overrides-and-component-container-guard.md](adr/0058-image-overrides-and-component-container-guard.md) - Per-component image overrides (`{{ app.version }}` substitution, hand-written reference grammar) applied to the component container by post-render; one JSON6902 guard for env vars and images fails a misnamed container with `COMPONENT_CONTAINER_NOT_FOUND` instead of adding one; upgrade re-validation; `get_component_images` returns the component container's image first; extended to `command`/`args` by ADR-069
- [0059-driver-action-api-tokens.md](adr/0059-driver-action-api-tokens.md) - Driver actions call the API as the built-in `styrmin-actions` user (`READ_WRITE`, no password) with a session that `apply_state` creates per reconcile, passes down in `STYRMIN_TOKEN` through Prefect job variables, and deletes when the reconcile ends; no allow-list or schema change
- [0060-steps-and-derived-task-result.md](adr/0060-steps-and-derived-task-result.md) - Steps of tasks, backups and restores are written only through the step recorder, by server code and INTERNAL flows directly, by USER flows and actions through `recordStep` (`styrmin-actions` only), and by operator reports linked through `status.instanceId`; the task result is derived from the task's family on every read; the operator judges the HelmRelease on its current generation; `run_job`, backups and restores get action tokens
- [0061-server-anonymous-daily-telemetry.md](adr/0061-server-anonymous-daily-telemetry.md) - The server side sends one anonymous report a day from an INTERNAL cron flow in the task worker, in the `styrminctl` envelope with `kind: "styrmin"`; driver names are sent as written; the install ID is stored in the single-row `installation` table; runs that start more than one hour late send nothing; `STYRMIN_WORKFLOW_ENABLE` does not stop it
- [0062-backup-history-derived-through-instances.md](adr/0062-backup-history-derived-through-instances.md) - A deployment's backup history is every backup of any of its instances, read by joining `Backup` to `ApplicationInstance`; `backups` takes exactly one of `deploymentId` or `instanceId`; no `Backup.deployment_id` column
- [0063-restore-of-earlier-instance-backup.md](adr/0063-restore-of-earlier-instance-backup.md) - Restoring a backup of an earlier instance puts that instance's resources back and keeps the active instance; the Backups tab warns, `restore --last` asks for confirmation (`--yes`) and skips expired backups; the server refuses a restore into a deleted deployment
- [0064-styrmindeployment-write-order-by-instance-sequence.md](adr/0064-styrmindeployment-write-order-by-instance-sequence.md) - Each instance gets a per-deployment `sequence` from `deployment.last_instance_sequence`, incremented under the deployment row lock when the repository saves it; the StyrminDeployment records it in `styrmin.io/instance-sequence`, and a flow leaves a StyrminDeployment that holds a higher sequence unchanged
- [0065-apply-writes-config-with-the-version.md](adr/0065-apply-writes-config-with-the-version.md) - `updateDeploymentVersion` takes an optional `input` validated against the target driver and application versions and written with the version in one task; `styrminctl apply` sends one such call per existing deployment; upgrade task only on a version or binding change; services recreated only when they change
- [0066-cluster-config-fanout.md](adr/0066-cluster-config-fanout.md) - The cluster config fan-out redeploys each deployment whose resolved config differs from its active instance's (not ADR-012's comparison of one config level); applications move onto a dedicated ingress controller only once it is `RUNNING`, continued by the status reporter, and the controller is removed once no application depends on it (which also applies after an environment update); typed `UpdateClusterInput` while `createCluster` keeps JSON; `updateCluster` returns the redeployed, waiting and failed deployments and has a `dryRun`; each environment commits on its own, and a nested `async with uow` that fails inside a savepoint rolls back only that savepoint (`uow.commit()` inside a savepoint raises); the SDK refuses unknown config keys
- [0067-driver-logos-loaded-by-the-viewer-browser.md](adr/0067-driver-logos-loaded-by-the-viewer-browser.md) - A driver logo is an `https` URL stored per driver version and loaded by each viewer's browser through `<img>` with no referrer; Styrmin never fetches or proxies it; `STYRMIN_DRIVER_SHOW_LOGOS=false` makes the API return no icon
- [0068-invalid-driver-info-dropped-with-load-warning.md](adr/0068-invalid-driver-info-dropped-with-load-warning.md) - An invalid `spec.info` icon or link is dropped and the load returns a warning in `loadWarnings` instead of failing; replaces research R3 of spec 020
- [0069-container-command-args-by-post-render.md](adr/0069-container-command-args-by-post-render.md) - Container `command`/`args` overrides are applied by the post-render merge patch (renamed `ContainerMergePatch`) and guard to the component container; one `override_applies` rule for the patch builder, action primitives and `isApplicable`; `component_command`/`component_args` retired with `RETIRED_TEMPLATE_FILTER`; `COMPONENT_CONTAINER_NOT_DECLARED` extended to `command`/`args`; `spec.container_overrides` removed from the driver format, database and API; supersedes ADR-045 §2 and §5
- [0070-replica-overrides-and-retired-parameters.md](adr/0070-replica-overrides-and-retired-parameters.md) - Per-component replica overrides stored in `ComponentConfigBlock.replicas` and applied by one post-render `spec.replicas` patch per kind per component, which also carries the stopped state (replaces the component state patch of ADR-057 §2); order of precedence override, then driver default (`replicas`, or 1 for `singleton: true`), then the chart's count; `UNKNOWN_COMPONENT_REPLICA_OVERRIDE` and `SINGLETON_REPLICA_OVERRIDE` against the driver version bound after the write; on a driver version change a parameter the target no longer declares is dropped at its current default (same type) and otherwise rejected with `RETIRED_PARAMETER_VALUE`
- [0070-ingress-class-set-by-post-render.md](adr/0070-ingress-class-set-by-post-render.md) - With a dedicated ingress controller, a strategic merge patch removes `spec.ingressClassName` from every application Ingress after the chart renders (a JSON6902 `remove` fails on an absent field), instead of an IngressClass per controller; `ingress_class` stays in the values-template data in both modes; with no class resolved, the chart's class stays; driver templates set no class

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
- [backup-restore.md](knowledge/backend/backup-restore.md) - Backup/restore system, Velero integration, strategies, retention TTL, environment-level backup and restore, environment clone and the cross-target restore
- [deployment-env-vars.md](knowledge/backend/deployment-env-vars.md) - Deployment env vars: when to use them, three-scope precedence, post-render injection into the component container
- [e2e-testing.md](knowledge/backend/e2e-testing.md) - E2E testing architecture, vCluster fixture graph, markers, debugging workflow
- [dead-code.md](knowledge/backend/dead-code.md) - Remaining dead code and cleanup tracking

Agent (in-cluster) architecture documentation in [knowledge/agent/](knowledge/agent/):

- [overview.md](knowledge/agent/overview.md) - Agent process layout, where Prefect lives, Kubernetes resource builders, status reporter
- [operator.md](knowledge/agent/operator.md) - Kopf operator, StyrminDeployment CRD, phase-based deployment, drift reconciliation

Frontend architecture documentation in [knowledge/frontend/](knowledge/frontend/):

- [routing.md](knowledge/frontend/routing.md) - TanStack Router architecture, route tree, type registration, lazy routes
- [data-fetching.md](knowledge/frontend/data-fetching.md) - TanStack Query + codegen pipeline, fetcher, cache invalidation, polling
- [forms.md](knowledge/frontend/forms.md) - TanStack Form architecture, Zod integration, field bindings, dynamic fields
- [ui-primitives.md](knowledge/frontend/ui-primitives.md) - Base UI wrapper layer, Slot utility, data-attribute conventions
- [deployment-configuration.md](knowledge/frontend/deployment-configuration.md) - Configuration tab and edit drawer: draft lifecycle, diff → impact → apply, inheritance state, conflict detection
- [deployment-timeline.md](knowledge/frontend/deployment-timeline.md) - History timeline and backup/restore rows: task result badges, step rows, output loaded on request, entry expansion and task links, E2E data attributes
- [environment-backups.md](knowledge/frontend/environment-backups.md) - Backups and Clones tabs of the environment detail page: roles, polling, invalidated queries, the discard label
- [driver-pages.md](knowledge/frontend/driver-pages.md) - Driver list and detail pages: `DriverLogo` states, where the logo, description and links appear, load warnings

CLI (`styrminctl`) internals in [knowledge/cli/](knowledge/cli/):

- [overview.md](knowledge/cli/overview.md) - Invocation pipeline, credential chokepoint, token store, error boundary, telemetry wrapper

## Current Guides

- [database-migrations.md](guides/database-migrations.md) - Alembic migration workflow: creating, applying, and rolling back migrations
- [graphql-propagation-tests.md](guides/graphql-propagation-tests.md) - How to write the unit test that proves a GraphQL field is wired through every layer to the database
- [pre-commit-hooks.md](guides/pre-commit-hooks.md) - Installing the `prek` hooks, what each one runs, and the bypass policy
- [bug-pipeline.md](guides/bug-pipeline.md) - End-to-end bug workflow: analyse, reproduce, fix, verify
- [local-demo.md](guides/local-demo.md) - Local vCluster demo lifecycle
- [driver-iteration.md](guides/driver-iteration.md) - The no-bump loop: editing a driver and reloading without changing its version string
- [driver-env-var-consumption.md](guides/driver-env-var-consumption.md) - How a driver declares the component container that receives user env vars by post-render patch
- [pod-scheduling.md](guides/pod-scheduling.md) - Pod scheduling configuration reference
- [ingress-ipv6-dual-stack-validation.md](guides/ingress-ipv6-dual-stack-validation.md) - Validating ingress and NodePort behaviour on dual-stack clusters
- [e2e-parallelism.md](guides/e2e-parallelism.md) - The five-shard CI matrix scheme and how shard markers route tests
- [e2e-deployment-sharing.md](guides/e2e-deployment-sharing.md) - Decision tree for reusing an existing E2E deployment instead of booting a new one
- [session-retrospectives.md](guides/session-retrospectives.md) - End-of-session workflow for turning agent friction into approved context-management improvements
- [users-and-groups.md](guides/users-and-groups.md) - Operator guide to users, groups, roles, the bootstrap admin, the Settings → Access UI, lockout recovery, and v1 limitations
