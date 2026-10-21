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
- [0033-scheduling-merge-semantics.md](adr/0033-scheduling-merge-semantics.md) - Scheduling merge: Environment → Deployment → Component, affinity accumulate with per-kind `replace:true`, topology-spread keyed by `(topologyKey, whenUnsatisfiable)`; no cluster-level scheduling (a cluster config rejects it since #482)
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
- [0071-ingress-class-set-by-post-render.md](adr/0071-ingress-class-set-by-post-render.md) - With a dedicated ingress controller, a strategic merge patch removes `spec.ingressClassName` from every application Ingress after the chart renders (a JSON6902 `remove` fails on an absent field), instead of an IngressClass per controller; `ingress_class` stays in the values-template data in both modes; with no class resolved, the chart's class stays; driver templates set no class
- [0072-helm-v4-defaults-releases-keep-apply-method.md](adr/0072-helm-v4-defaults-releases-keep-apply-method.md) - helm-controller runs without `UseHelm3Defaults`, so new installs use server-side apply with forced conflicts, installs and upgrades wait with kstatus, and Helm hooks receive Styrmin's post-render patches (`combined`); upgrades and rollbacks keep `auto`, so releases installed with the gate keep client-side apply and releases installed without it keep server-side apply if the gate is turned on again; the every-resource label patch becomes a strategic merge so a resource without `metadata.labels` no longer fails the render; the operator's rules do not change
- [0073-kubernetes-objects-named-and-found-by-record-id.md](adr/0073-kubernetes-objects-named-and-found-by-record-id.md) - Every Kubernetes object that Styrmin creates for a record is named after the record's id and carries an id label; updates and deletes find it by that label or by the id-based name, never by a name a user can change; flows that act on cluster objects take the id
- [0074-bsl-keys-passed-to-flows-in-prefect-secret-block.md](adr/0074-bsl-keys-passed-to-flows-in-prefect-secret-block.md) - The server saves a backup storage location's S3 keys in the Prefect Secret block `styrmin-bsl-<id>-credentials` and passes only the id to the `sync-bsl` flows, which load the keys from the block; the value is a JSON string so Prefect API reads hide it; deleting the location deletes the block
- [0075-deployment-references-stored-by-id.md](adr/0075-deployment-references-stored-by-id.md) - A deployment reference in a pod affinity or pod anti-affinity term is stored as the named deployment's id: every write that stores a config replaces a name with the id, and refuses a term that names a deployment the environment does not have or a tombstoned deployment with `VALIDATION_ERROR` and the term's path; each reconcile resolves the id to `styrmin/deployment_id=<id>`, so a rename changes no term; an environment clone points the copied terms at its counterpart deployments and refuses a request whose copied terms name a deployment it does not copy; an environment restore writes the captured config back unchanged; amends ADR-034
- [0076-teardown-deletes-service-aliases-in-all-namespaces.md](adr/0076-teardown-deletes-service-aliases-in-all-namespaces.md) - The operator's teardown first deletes the deployment's service aliases in all namespaces, found by the `styrmin.io/deployment-id` label or, without it, by the namespace that `spec.externalName` points into; it acts only when the CR's namespace is `styrmin-<spec.deploymentId>`, and, without `spec.deletionRequested`, only while the namespace exists and is not `Terminating`, so a restore's namespace deletion deletes no alias; deletes carry the listing's `resourceVersion` and are best-effort
- [0077-alias-flow-reads-deletion-state-at-write-time.md](adr/0077-alias-flow-reads-deletion-state-at-write-time.md) - The alias flow reads each Namespace and StyrminDeployment before it writes and skips departing namespaces, reads again after it writes and deletes the aliases it wrote for a deployment whose deletion started in between, and never creates a namespace; one case can leave an alias, which the maintainer accepted
- [0078-alias-step-reads-current-services-from-server.md](adr/0078-alias-step-reads-current-services-from-server.md) - The alias step reads the other deployments' services from the server with the flow's action token, because a flow's context lists no deployment requested after it; the deployment's own services and the templates' context stay as built; a deployment changed while a peer is restored gets no aliases to it until a later change
- [0079-driver-actions-import-only-from-their-driver-directory.md](adr/0079-driver-actions-import-only-from-their-driver-directory.md) - Each action of a driver version loaded from a driver directory runs from it through Prefect's `set_working_directory` pull step, so `actions.py` imports modules only from its driver directory and the action's image; every git load, from a driver directory or the repository root, refuses a driver directory or driver file whose real path is outside the clone
- [0080-action-deployments-keyed-by-driver-directory.md](adr/0080-action-deployments-keyed-by-driver-directory.md) - The Prefect deployment of each action of a driver version loaded from a driver directory carries a `directory/<driver directory>` tag and a 12-character SHA-256 digest of the driver directory in its name, so two driver versions loaded at one commit keep separate actions; root driver versions keep their names and tags, and a lookup for one drops deployments that carry a `directory/` tag
- [0081-local-driver-actions-check-their-files-at-the-driver-path.md](adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md) - The actions of a driver version loaded from a local directory are registered under its path (`action_directory_of`) and run the `actions.py` at that path, after a pull step that checks the files there against the driver version's provenance fingerprint; a local path with `{` or `}` is refused for a driver with actions; the first `ERROR` log of a crashed action goes into its hook step's error; a declared action without a registered flow fails its hook step (in `apply_state`, or in a request check of `update_deployment_version` that changes nothing) instead of being skipped, and loading the driver again registers the missing actions; actions run in the agent pod, where an action's `image:` has no effect
- [0082-recorded-demos-reuse-e2e-page-objects.md](adr/0082-recorded-demos-reuse-e2e-page-objects.md) - The recorded demos live in `backend/tests/e2e/demos/` and act in the Styrmin UI only through `UiScenarioDriver` and the E2E page objects, with no selector for a Styrmin page; page objects take `keystroke_delay_ms` and enter text with `enter_text`, so the demos type one key at a time and the E2E suite keeps `fill()`; CI does not run the demos, E2E tests call the page-object methods they added, and the command has an owner and a schedule for recording again
- [0083-demo-waits-sped-up-after-recording.md](adr/0083-demo-waits-sped-up-after-recording.md) - Each demo is recorded as one Playwright 1.64 screencast with chapters, a cursor and a highlight; the recorder records the start and end of each wait and each cut, a pure `plan_segments` speeds each long wait up to at most 4 s, labels are PNG images that the browser renders and ffmpeg overlays, the video is H.264 MP4 at 1920×1080, and `plan.json` lets a failed encoding run again without recording again
- [0084-record-command-deletes-only-environments-it-created.md](adr/0084-record-command-deletes-only-environments-it-created.md) - The record command records the ids of the environments it creates in `$XDG_STATE_HOME/styrmin/demo-environments.json`, for each demo stack URL, and deletes only those; it asks on the terminal before it deletes another environment with a demo's name, and without a yes or a terminal it stops before any change

## Current Knowledge

- [architecture.md](knowledge/architecture.md) - High-level system architecture: server↔agent topology, declarative state, context model. Companion to the constitution.

Backend (server) architecture documentation in [knowledge/backend/](knowledge/backend/):

- [overview.md](knowledge/backend/overview.md) - Architecture overview, directory structure, request flow
- [api.md](knowledge/backend/api.md) - GraphQL API (public and internal), types, response patterns
- [data-models.md](knowledge/backend/data-models.md) - Database, domain, and context models
- [services.md](knowledge/backend/services.md) - Service layer, unit of work, business logic
- [reconciliation.md](knowledge/backend/reconciliation.md) - Reconciliation engine, diff computation, remediation strategies
- [hooks-and-actions.md](knowledge/backend/hooks-and-actions.md) - Hook system, driver actions, setup/upgrade hooks
- [orchestration-flows.md](knowledge/backend/orchestration-flows.md) - Prefect orchestration flows, callbacks, execution patterns (the server chart's task-worker runs the INTERNAL flows; the agent's Prefect worker runs the USER flows and driver actions)
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
