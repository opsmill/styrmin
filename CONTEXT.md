# Styrmin

A deployment orchestration platform that manages application deployments on Kubernetes clusters through versioned, declarative **Application Drivers** and a desired-vs-current reconciliation loop.

This file is the project glossary. It defines the canonical name for each domain concept and the synonyms to avoid. Use these terms verbatim in code, GraphQL schema, specs, ADRs, commit messages, PR descriptions, and conversation. When a concept is missing or drifts from how the code actually uses it, update this file in the same change.

For prescriptive principles see [`dev/constitution.md`](dev/constitution.md). For the descriptive system overview see [`dev/knowledge/architecture.md`](dev/knowledge/architecture.md). For decisions see [`dev/adr/`](dev/adr/).

## Language

### Top-level processes

**Styrmin**:
The deployment orchestration platform as a whole — the **server**, the **agent**, the **CLI**, the **SDK**, the **frontend**, and the **driver** ecosystem taken together.
_Avoid_: "the system", "the platform" (used only when context already pins it to Styrmin), "Styrmin MVP".

**Server**:
The FastAPI + GraphQL backend process. Owns the **database**, exposes the public GraphQL API, holds the **SDK** contract, and submits **Prefect** flows. Never calls the **agent** directly — direction flows through **recorded intent**.
_Avoid_: "backend" (use only for the `backend/` directory or the language layer), "API", "controller".

**Agent**:
The single container that runs a **Prefect** worker, a **kopf** operator, and a **status reporter** in one shared async event loop. Reconciles **recorded intent** into Kubernetes resources inside one target cluster. There is one **agent** per **cluster**.
_Avoid_: "worker" (overloaded with **Prefect worker**), "operator" (that is one of its sub-functions), "K8s agent" (legacy README phrasing), "controller".

**CLI / styrminctl**:
The Cyclopts-based command-line client (`styrminctl`). A thin client over the GraphQL API — never talks to the **database** or the **agent** directly. Its one outbound call to a destination _other_ than the GraphQL API is the anonymous, opt-out **telemetry** POST (see below) — the CLI's first non-GraphQL network egress.
_Avoid_: "the CLI tool", "styrmin command" (ambiguous with the `styrmin` developer command for schema export).

**Telemetry**:
The anonymous, opt-out usage signal the **CLI** fire-and-forgets after each _eligible_ invocation — a single best-effort HTTPS POST of a scrubbed event (resolved command route, canonical option _names_, outcome + error category, coarse environment facts) to a fixed endpoint. On by default on interactive workstations, silent in CI / non-interactive contexts; capped at ≤ 200 ms added latency and failure-isolated (never alters output, exit code, or speed). Scrub-by-construction: never carries names, values, paths, tokens, or addresses. Opt out with `styrminctl telemetry disable`, `STYRMIN_TELEMETRY=0`, or `DO_NOT_TRACK=1`. State `{install_id, enabled}` persists next to the token store.
_Avoid_: "analytics", "tracking", "metrics" (reserved for backend/observability signal).

**SDK / styrmin-sdk**:
The async Python client SDK that wraps GraphQL operations as typed Pydantic models. Used by **CLI**, **E2E tests**, and external callers. Types are generated from `schema.graphql` via ariadne-codegen.
_Avoid_: "python client", "API client".

**Frontend**:
The React 19 + Vite SPA that consumes the GraphQL API. Single-page application; not server-rendered.
_Avoid_: "UI" (ambiguous with the rendered surface a user sees), "web app".

### Infrastructure entities

**Cluster**:
A Kubernetes cluster registered in Styrmin and represented by a `Cluster` database row. Carries a **config** dict and a computed **capabilities** dict. One **agent** runs per **cluster**. Currently exactly one **cluster** is supported at a time — see [002-single-cluster-limit].
_Avoid_: "k8s cluster" (redundant), "target cluster" (used only when contrasting source/target in code that involves multiple clusters).

**Environment**:
A logical deployment target bound to exactly one **cluster**. Carries its own **config** and **capabilities** dicts, which override the **cluster**'s values when they overlap. Name is unique per cluster, not globally.
_Avoid_: "env" (in prose; the abbreviation is fine in code), "deployment environment", "namespace" (Kubernetes-specific).

**Backup storage location** (BSL):
An S3-compatible object store registered as a destination for **Velero** backups. Assigned to an **environment**; all deployments in that environment back up there.
_Avoid_: "bucket" (implementation detail), "backup destination".

**Backup retention TTL** (`backup_ttl`):
How long **Velero** keeps a backup before garbage-collecting it, as a strictly positive Go duration in `h`/`m`/`s` units (e.g. `"2160h"`). An optional `backup_ttl` on the **cluster**, **environment**, or **deployment** **config**, resolved deepest-wins at backup time — deployment → environment → cluster → the built-in `720h` — with the applied value and its source scope recorded on the backup record. Applies only to backups created afterwards; an already-created Velero backup keeps the expiration fixed at its creation. Distinct from `BackupSchedule.retention_count`, which caps _how many_ backups a schedule keeps rather than how long each one lives (and is currently unenforced — scheduled backups do not execute yet). See [016-backup-retention-ttl] and [issue #305](https://github.com/opsmill/styrmin/issues/305).
_Avoid_: "retention policy" unqualified (ambiguous with `retention_count`), "backup expiry" (that is the resulting timestamp, `Backup.expiresAt`), bare "TTL" (overloaded with the Velero polling timeout).

**Environment backup**:
A coordinated, near-consistent snapshot of an **environment**: its **config** as of backup time, the declared state of every eligible **deployment** (non-tombstoned, non-internal, with an active **application instance**), and one **constituent backup** per eligible instance — grouped under a single `EnvironmentBackup` record. Its status (`PENDING` / `IN_PROGRESS` / `COMPLETED` / `PARTIAL` / `FAILED`) is **derived from its constituents on every read and never stored**, so it cannot contradict them. Deleting it cascade-deletes its constituent backups and their restores, and is legal regardless of status (the escape hatch for a snapshot pinned in progress). See [issue #7](https://github.com/opsmill/styrmin/issues/7) and [ADR-055](dev/adr/0055-environment-backup-parent-records.md).
_Avoid_: "env snapshot", "full backup" (ambiguous with a per-instance backup), "environment export".

**Environment restore**:
The coordinated operation that reapplies an **environment backup**'s captured **config** and restores every usable **constituent backup** into its still-existing **deployment**, in place — restoring what's usable and reporting what isn't (every non-restored constituent is attributed with a deployment name and a free-text reason); it never creates or deletes deployments. Tracked by an `EnvironmentRestore` record whose status is derived the same way. Requires the `ADMIN` role, unlike creating or deleting an **environment backup** — it rewrites `Environment.config`, the same privilege `updateEnvironment` needs.
_Avoid_: "environment rollback" (implies topology reversion), "environment recovery" (broader DR concept).

**Environment clone**:
A first-class `EnvironmentClone` record of one operation that copies a live **environment** into a **new** environment on the same **cluster**, built entirely from a fresh **environment backup** of the source — never by re-reading the live source. Each included source **deployment** gets a **counterpart deployment** in the new environment, pinned to the captured **application driver version**, into which the source's **constituent backup** is restored (a _cross-target restore_). Carries the requested target name, the deployment selection, the config override, one attribution entry per source deployment (cloned / skipped + reason / failed + reason), and a flat list of operation-level events; its status (`PENDING` / `IN_PROGRESS` / `COMPLETED` / `PARTIAL` / `FAILED`) is **derived on every read and never stored**. The name is deliberately **not** unique — discarding a clone (by deleting the environment it created) must not burn the name. Requires the `ADMIN` role to create; reads are ungated. See [issue #6](https://github.com/opsmill/styrmin/issues/6) and [ADR-056](dev/adr/0056-environment-clone-record-and-cross-target-restore.md).
_Avoid_: "environment copy", "environment fork", "duplicate environment", "environment snapshot" (that is an **environment backup**), "clone" alone when the reader could hear `git clone`.

**Counterpart deployment**:
The **deployment** an **environment clone** creates in the new environment for one included source **deployment**. Bound to the captured **application driver version**, created in the `RESTORING` **deployment state** with its initial **reconciliation** deferred, and it adopts the _source's_ Helm release name while keeping its own **StyrminDeployment** CRD identity — so `helm list` in a counterpart's namespace shows a release named after the source deployment. Otherwise an ordinary deployment once its restore lands.
_Avoid_: "clone deployment" (ambiguous — the clone is the operation), "target deployment" (used only when contrasting source/target inside restore code), "copy", "mirror".

**Constituent backup / constituent restore**:
An ordinary per-instance `Backup` (or per-deployment `Restore`) row that belongs to an **environment backup** (or **environment restore**), linked by the nullable FK `Backup.environment_backup_id` / `Restore.environment_restore_id`. Constituents keep their existing semantics entirely — individually listable, deletable, and expiring under the **backup retention TTL**. A null FK is a standalone backup or restore.
_Avoid_: "child backup", "sub-backup", "member backup", "partial backup" (that describes an outcome, not membership).

### Application drivers

**Application driver**:
A versioned, self-contained deployment specification that defines how an application is deployed (Helm chart reference, component definitions, services, parameters, action declarations). Identified by a unique `name`. Per Constitution §II, all deployment behavior flows from the driver — no ad-hoc deployment logic outside drivers.
_Avoid_: "driver" alone when first introducing the term, "application spec", "deployment template".

**Application driver version** (driver version):
A specific version of an **application driver**, sourced from a git repository or a local directory. Owns its own `helm_chart` reference, `component_configs`, `parameters`, `services`, and `actions`. Selected per **deployment**.
_Avoid_: "version" alone (ambiguous with **application version**), "driver release".

**Driver specification file**:
The `driver.styrmin.yml` file at the root of a driver directory. Single source of truth for driver metadata, supported application versions, Helm chart, components, parameters, services, and action declarations.
_Avoid_: "driver yaml", "driver manifest".

**Provenance fingerprint** (driver-version fingerprint):
The content-addressable identifier carried by each **application driver version** that makes the row's identity stable across reloads with the same `version` string. Stored as two columns on `ApplicationDriverVersion` — `content_hash` (SHA-256 hex of the canonical local driver bytes) for `source_type = "local"`, and `source_commit_sha` (resolved git commit SHA) for `source_type = "git"`. Exactly one is non-null per row; the discriminator is `source_type`. Surfaced in the UI/CLI as `<version>@<short-fingerprint>` (first 7 chars). See [issue #262](https://github.com/opsmill/styrmin/issues/262).
_Avoid_: "driver hash" alone (ambiguous across source types), "version hash" (conflates with **driver version**), "build id".

**Application version**:
The user-facing version of the deployed application (e.g. `infrahub` `1.6.0`), distinct from the **driver version** that knows how to deploy it. A **driver version** declares a semver specifier (`application_supported_versions`) describing which **application versions** it can deploy.
_Avoid_: "app version" (in code is fine, in prose write it out), conflating with **driver version**.

**Latest-wins driver-version resolution**:
The deterministic rule that picks which **application driver version** a **deployment** binds to when several support the requested **application version**: highest parseable `version` string first (unparseable strings rank below all parseable ones), ties broken by `created_on` descending (most recently loaded), final tie-break on row id. Applies on initial deploy and on every upgrade — an upgrade always re-resolves the binding unless the caller pins one explicitly via `driverVersionId` (the **driver-version pin**, valid only within the deployment's own driver). Implemented by `_driver_version_sort_key` / `_resolve_latest_matching_version` in `backend/styrmin_backend/services/deployment.py`.
_Avoid_: "newest version" (ambiguous between the two orderings), "first match" (the pre-rule behavior), "default driver version" (conflates with `default_version`).

**Component**:
A logical sub-part of an application (e.g. `server`, `task-worker`) declared by the **application driver** and identified by a Kubernetes label selector (`styrmin/component`). A **deployment** can enable/disable and configure components individually. Lifecycle controls (start/stop, restart, scaling) act on the **component** as a unit.
_Avoid_: "service" (that is its own concept), "pod" (a **component** is observed via one or more **pods**), "module".

**Service** (deployed service):
A network-addressable endpoint declared by the **application driver** under `spec.services` (kind, scope, port, owning component) and materialised as a `DeployedService` row plus a Kubernetes Service object.
_Avoid_: "endpoint" (HTTP-specific), "port" (one attribute of a service), conflating with Kubernetes-`Service` when ambiguity matters — qualify as "K8s Service" if needed.

**Parameter**:
A user-configurable input declared by the **application driver** (`name`, `label`, `kind`, `default`). Surfaced through the GraphQL API and **frontend** forms; flows through to **context** as part of the **deployment**'s config.
_Avoid_: "field" (UI term), "option", "setting", conflating with **prompt argument** in driver action templates.

**Action**:
A Python function declared by the **application driver** under `spec.actions` and implemented in the driver's `actions.py`. Runs inside a **Prefect** flow as part of the `setup` or `upgrade` **hook** at the `pre`, `core`, or `post` **mode**.
_Avoid_: "task" (that is the database tracking record), "step" (running all actions of one **mode** is one **step**; the action itself is not), "function", "hook" (a **hook** is the lifecycle slot, an **action** is the work that runs in it).

**Hook**:
A lifecycle slot at which **actions** run. Currently two: `setup` (during create) and `upgrade` (during upgrade). Each **hook** is composed of three **modes**.
_Avoid_: "lifecycle event", "phase" (that is the operator's term), "stage".

**Mode**:
The execution phase within a **hook**: `pre`, `core`, or `post`. Ordering inside a **mode** is unspecified; ordering across **modes** is strict.
_Avoid_: "phase" (reserved for operator phases), "stage", "step" (one run of a mode is one **step**; the mode itself is not).

**Action token**:
A session token for the built-in `styrmin-actions` user (role `READ_WRITE`, no password, and no one can log in as it) that an INTERNAL **flow** creates for the work it hands to a Kubernetes Job and deletes when that work ends: `apply_state` once per **reconciliation**, `run_job` once per `run_job` **task**, and the backup and restore workflows once per backup or restore. It reaches the Job in the `STYRMIN_TOKEN` environment variable, next to the step parent (`STYRMIN_TASK_ID`, `STYRMIN_BACKUP_ID` or `STYRMIN_RESTORE_ID`); the remediation flow passes it on to every **action**, with the hook **step** in `STYRMIN_STEP_ID`. The action primitives send it as a bearer token, and flows and actions use it to record **steps** through `recordStep`, which accepts no other user. See [ADR-059](dev/adr/0059-driver-action-api-tokens.md) and [ADR-060](dev/adr/0060-steps-and-derived-task-result.md).
_Avoid_: "service token", "agent token" (the agent status reporter does not use it), "API key".

**Utility**:
A cluster-level resource (e.g. ingress controller, service discovery) managed by the same builders that produce application resources. Defined by a `Utility` row with a Jinja2 `resource_template`. Internal deployments are marked `internal: true` on the `Deployment` row.
_Avoid_: "system service", "platform service", "infra resource".

### Deployments — declared (desired) state

**Deployment**:
A long-lived database record (`Deployment`) carrying the **desired state**: which **application driver version**, which **application version**, which **environment**, and the user's **config** and **parameters**. Editing a deployment expresses a new intent and triggers **reconciliation**. Identified by `(environment_id, name)` among non-tombstoned rows. See [ADR-004](dev/adr/0004-embed-context-in-deployment-crd.md).
_Avoid_: "deploy" (verb form is fine), "release" (Helm-specific), "application", "stack".

**Tombstone / tombstoned deployment**:
A `Deployment` row whose cluster-side workload has been torn down by the **operator** but whose record is retained for timeline, backups, and audit (`deleted_at IS NOT NULL`, `status = DELETED`). The name becomes available for reuse in the same **environment**. See [ADR-008](dev/adr/0008-deployment-soft-delete-tombstoning.md) and [ADR-011](dev/adr/0011-scoped-tombstone-aware-name-uniqueness.md).
_Avoid_: "soft-deleted row" (correct mechanism, wrong vocabulary in user-facing text), "archived deployment", "removed deployment".

**Deployment state**:
The enum value on `Deployment.status`: `PENDING`, `DEPLOYING`, `RUNNING`, `RESTORING`, `FAILED`, `DELETING`, `DELETED`. Sole source of truth for the column is the **status reporter** mapping the **operator**'s `displayState`, except during a restore: from `createRestore` until the restore workflow records the result, the column stays `RESTORING` whatever the reports say. If that workflow cannot be dispatched, the restore and the deployment are marked `FAILED` at once.
_Avoid_: "deployment status" (use this for the _record_ `DeploymentStatus`, not the state value), "phase" (that is the operator's `.status.phase`).

**Declarative deployment manifest**:
A YAML document with `apiVersion: styrmin/v1` and `kind: Deployment` that describes the desired state of one **deployment** (`metadata.name`, `spec.driver`, `spec.version`, `spec.environment`, optional `spec.cluster`, `spec.config`, `spec.parameters`). The input format for **declarative apply**. A single file may contain multiple manifests separated by `---`. `config` and `parameters` are fully replaced on update, not deep-merged. Full schema in `specs/archive/009-deployments-apply/contracts/manifest-schema.md`; the format's design decisions are recorded in [ADR-049](dev/adr/0049-styrmin-v1-manifest-contract.md).
_Avoid_: "deployment spec" (overloaded — `Deployment.spec` also refers to the cluster-side CR), "k8s manifest" (these are not Kubernetes objects), "yaml file".

**Declarative apply**:
The upsert operation exposed as `styrminctl deployments apply -f <path>` and the SDK's `DeploymentResource.apply_files(...)`. Resolves each **declarative deployment manifest** by `(name, environment)` identity, then creates if absent or updates if present (driver-disagreement fails with `DriverMismatchError`; driver changes require explicit delete-and-recreate). Continue-on-error within a batch; exits non-zero if any manifest failed. With `--wait`, blocks until each successfully submitted deployment reaches a terminal **reconciliation** state. Not a delete operation — manifests missing from a directory are not pruned.
_Avoid_: "kubectl apply" (intentionally similar UX but not the same semantics — no pruning, no server-side merge), "deploy" (overloaded with the existing `deploy()` mutation, which is create-only).

### Instances — current (realised) state

**Instance** (`ApplicationInstance`):
A frozen snapshot of what was actually deployed at a point in time, generated from a **deployment** at **reconciliation** time. Carries a serialised `GlobalContext` in its `context` field. A **deployment** owns at most one **active instance** at a time.
_Avoid_: "application instance" in prose (fine in code), "release", "rollout", "version".

**Active instance**:
The single **instance** currently considered live for a **deployment** — pointed to by `Deployment.active_application_instance_id`. Reconciliation compares the proposed new **instance** against the **active instance**.
_Avoid_: "current instance" (correct concept; **active** is the term we standardise on), "live instance".

### Reconciliation

**Reconciliation**:
The act of comparing the **deployment**'s newly generated **instance** (desired) against the **active instance** (current) and planning convergence work. The reconciliation loop is the implementation of Constitution §I.
_Avoid_: "sync", "diff cycle", "drift correction" (drift correction is the **operator**'s timer-driven re-check, not this).

**Generator**:
The component that builds a fresh **instance** from a **deployment** via `generate_instance_from_deployment()`. Resolves the full **GlobalContext** as part of generation.
_Avoid_: "instance builder", "factory".

**Remediator**:
The service that maps the diff between a newly generated **instance** and the **active instance** to a plan — i.e. which **Prefect** flow (`CREATE_INSTANCE`, `UPDATE_INSTANCE`, `UPGRADE_INSTANCE`, …) to run and with which parameters.
_Avoid_: "planner", "scheduler".

### Context — the bridge between deployment and instance

**GlobalContext** (context):
The hierarchical Pydantic model holding the **resolved configuration snapshot** that both the **server** (for bookkeeping) and the **agent** (for rendering and reconciliation) act on. Produced by `generate_context_from_deployment()`. Embedded in both the **instance**'s `context` field and the **StyrminDeployment** CRD spec. Frozen for the lifetime of an **instance**.
_Avoid_: "config" alone (that is the user's input dict on a row), "settings", "snapshot" (ambiguous with **observed state**).

**ClusterContext / EnvironmentContext / DeploymentContext / InstanceContext / ApplicationContext / ComponentsContext / UtilityContext**:
The fixed set of sub-contexts that compose **GlobalContext**. Each level can override the level above; `InstanceContext.config` is the final merged view drivers and templates see.
_Avoid_: inventing additional context types without an ADR.

**Component overrides**:
The mechanism by which a **deployment**'s **component** config (`DeploymentConfig.components[<name>]`) overrides the **driver version**'s default `ComponentConfig`. First-class to the deployment-config feature. Component-scope env vars and **image overrides** reach pods by a post-render patch into the **component container**, not through the values template ([ADR-057](dev/adr/0057-post-render-component-overrides.md), [ADR-058](dev/adr/0058-image-overrides-and-component-container-guard.md)); **container overrides** still flow through the values template.
_Avoid_: "component patch", "component customisation".

**Component container**:
The single container in a **component**'s pod template that the **application driver** declares (`components.<name>.container` in the **driver specification file**) as the target of per-component post-render overrides — env vars and **image overrides**. Optional: a component without one accepts no component-scope env vars or **image override** (`COMPONENT_CONTAINER_NOT_DECLARED`) and is skipped by deployment- and environment-scope env vars. Only `Deployment` and `StatefulSet` workloads are patched. A declared name missing from the rendered workload fails the reconcile with `COMPONENT_CONTAINER_NOT_FOUND` whichever override targets it; Styrmin never adds a container. See [ADR-057](dev/adr/0057-post-render-component-overrides.md) and [ADR-058](dev/adr/0058-image-overrides-and-component-container-guard.md).
_Avoid_: "main container", "app container", "primary container", "target container".

**Container override**:
The per-**component** `command` (container entrypoint) and/or `args` slot a user may set on a single **deployment**, scoped to that component only — no environment/deployment-wide scope, no layering (014-component-container-overrides). Two independent, optional, nullable lists; absence falls through to the chart/image default. Stored on `DeploymentConfig.components[<name>]`, consumed by the **driver version** through the `component_command` / `component_args` template filters. The `container` named in the driver's `spec.container_overrides` is informational and distinct from the **component container**.
_Avoid_: "command override" / "args override" alone (they are the two slots **of** a container override), "entrypoint patch", "container customisation". Distinct from **component overrides** (the broader config-override mechanism) and from env vars (which **do** layer across scopes and are injected by post-render).

**Image override**:
The per-**component** image reference a user may set on a single **deployment**, applied by a post-render patch to the **component container** (`Deployment` and `StatefulSet` only). A full reference with an explicit tag or digest; a `{{ app.version }}` token resolves to the deployment's **application version** at render time (plain substitution, not Jinja), and a literal tag or digest pins the image across **application version** upgrades. Component scope only, no layering. Stored on `DeploymentConfig.components[<name>]`. Rejected on write and before an **application version** change when invalid (`INVALID_IMAGE_REFERENCE`); kept but never applied on a component without a **component container** or on an orphaned component. See [ADR-058](dev/adr/0058-image-overrides-and-component-container-guard.md) and [issue #20](https://github.com/opsmill/styrmin/issues/20).
_Avoid_: "custom image", "image patch", "tag override". Distinct from a registry mirror (release-wide rewrite of every image, a separate issue).

### Recorded intent and kubernetes

**Recorded intent**:
The flow of direction from **server** to **agent**: GraphQL → service → **Task** → **Prefect** flow → **StyrminDeployment** CRD → **operator** → Kubernetes. The **server** never calls the **agent** directly.
_Avoid_: "command", "RPC", "push" (the agent pulls).

**StyrminDeployment** (CRD):
Styrmin's primary Custom Resource Definition. Carries the embedded **GlobalContext** in `spec` and is the **operator**'s single source of truth about what should be running. Watched by the **kopf operator**. Its `status.instanceId` names the **instance** whose `spec.instanceId` the operator's create, update or resume handler last acted on (written also when the handler fails), so it changes only once the operator has picked up a new spec; `spec.instanceId` is the instance the last **flow** wrote. `status.rolloutStartedAt` is when the current rollout started, and the readiness timeout counts from it.
_Avoid_: "deployment CRD" (ambiguous with the database `Deployment`), "the CR".

**Operator**:
The kopf-based controller running inside the **agent** that watches **StyrminDeployment** CRDs and reconciles them into Kubernetes resources. See [ADR-005](dev/adr/0005-ordered-phase-deployment-sub-handlers.md).
_Avoid_: "kopf" (that is the library), "kubernetes operator" (redundant), "the controller" (overloaded with K8s controllers).

**HelmRelease**:
The FluxCD v2 CRD declaring desired Helm chart state. Created and updated by the **operator** based on the resolved **GlobalContext**; on update Styrmin replaces each top-level spec key it writes (so stale `spec.values` keys disappear) and leaves keys it never writes, such as `spec.suspend` ([ADR-057](dev/adr/0057-post-render-component-overrides.md)).
_Avoid_: "release" alone (ambiguous), "Helm install".

**HelmChart / HelmRepository**:
Database records modelling the Helm chart referenced by an **application driver version** and its repository (OCI or HTTP). Distinct from FluxCD's `HelmRelease`.
_Avoid_: collapsing chart + repository into one term.

### Async orchestration

**Prefect**:
The workflow engine. Hosts a **Prefect server** (UI on port 4200) and **Prefect workers**. Flows submitted by the **server** run on the **agent**'s **Prefect worker**.
_Avoid_: "celery" (we are not Celery), "queue".

**PrefectManager**:
The service in the **server** that wraps the Prefect SDK — submits flows, manages work pools, registers user actions.
_Avoid_: "prefect client", "workflow manager".

**Flow / Prefect flow**:
A unit of orchestration submitted to Prefect (`CREATE_INSTANCE`, `UPDATE_INSTANCE`, `UPGRADE_INSTANCE`, `DEPLOYMENT`, …). Each **task** record tracks the lifecycle of one **flow run**.
_Avoid_: "job", "workflow" alone when it could be misread, "pipeline".

**Task** (database record):
A `Task` row tracking one asynchronous operation: `status`, `type`, optional `message`, `prefect_flow_run_id`, the **instance** it rolls out (`instance_id`), and the hook **step** that started it (`started_by_step_id`). A **reconciliation** stores the type of the operation its caller starts (`create_instance`, `update_instance`, `upgrade_instance`, `stop_components`, `start_components`); rows from before [issue #2](https://github.com/opsmill/styrmin/issues/2) keep `noop`. `Task.status` follows only the Prefect flow run; users view the **task result**. Distinct from Prefect's in-process `task` primitive.
_Avoid_: when referring to Prefect's primitive, qualify as "Prefect task" — never let "task" alone refer to it.

**Step**:
One unit of work inside a **task**, a backup or a restore, recorded so users can view it: name, status (`pending`, `running`, `succeeded`, `failed`, `superseded`), start time, end time, attempt count, the error of each failed attempt, and the end of the command output when a command fails. One run of a **hook**'s **mode** is one step (e.g. "Run the upgrade pre-hook"); each **operator** phase is one step (e.g. "Install or upgrade the HelmRelease"); a restore has three steps and a backup one step per **component**. A step is `superseded` when a later **task** of the same **deployment** interrupted the operator phase it waited for. Created and changed only by the step recorder (`services/steps/recorder.py`), which server code and INTERNAL **flows** call directly, USER flows and **actions** reach through `recordStep` with the **action token**, and the **status reporter**'s reports reach through the operator phase history. Ordered by start time, pending steps last. See [issue #2](https://github.com/opsmill/styrmin/issues/2) and [ADR-060](dev/adr/0060-steps-and-derived-task-result.md).
_Avoid_: "substep", "TaskStep" (backups and restores are not **tasks**), "stage", "phase" (reserved for the **operator**'s phases), "event" (reserved for Kubernetes Events).

**Task result**:
The result of a **task** as users view it, derived on every read and never stored. It covers the task and every task that its hook **steps** started, at any depth, and the first rule that matches wins: `RUNNING` while the `Task.status` of one of these tasks is `pending` or `running`, or a step of these tasks is running, or is not started and does not wait behind a failed step of its own task; `FAILED` when the `Task.status` of one of these tasks is `failed`, or a step of these tasks has failed; `SUPERSEDED` when a step of these tasks was superseded by a task outside them; `SUCCEEDED` otherwise. `Task.status` counts in addition to the steps, because a flow can fail, or still run, between two steps. A task without steps, such as one from before steps were recorded, counts by its `Task.status` only. Distinct from `Task.status`, which follows only the Prefect flow run and which driver actions wait on. See [issue #2](https://github.com/opsmill/styrmin/issues/2) and [ADR-060](dev/adr/0060-steps-and-derived-task-result.md).
_Avoid_: "operation result" (ambiguous with **GraphQL operation**), "outcome" (used by `styrminctl deployments apply`), "task status" (that is `Task.status`).

**Status reporter**:
The third coroutine in the **agent**'s shared event loop. Polls Kubernetes every ~5 s for pod state and **StyrminDeployment** CRD status, then posts the snapshots back via `reportPodStatuses` and `reportDeploymentStatuses` GraphQL mutations. A CRD snapshot carries the CR's `status.instanceId` (else `spec.instanceId`), and the server uses it to move the operator-phase **steps** of the task that rolled out that **instance**. Distinct from Prefect's flow-state callbacks.
_Avoid_: "status poller", "watcher" (kopf is the watcher), "reporter" alone.

### Observed state

**Observed state**:
What the **agent** actually sees in the cluster, as opposed to **declared state** (`Deployment` / `Component` config). Captured in `PodStatus` and `DeploymentStatus` rows on each poll cycle. Drift between observed and declared is expected and not an error. See [ADR-007](dev/adr/0007-pod-status-records-observed-state-not-declared-state.md).
_Avoid_: "actual state" (fine in conversation, but **observed** is what the code uses), "runtime state".

**PodStatus**:
The per-pod observed-state record (one row per `(deployment_id, pod_name)`), upserted by `reportPodStatuses`. Stale rows are pruned server-side. The agent labels pods with `styrmin/component`; the value is recorded as-is on `component_name` without server-side validation.
_Avoid_: "pod" alone (the Kubernetes object) — qualify when referring to the row.

**DeploymentStatus** (record):
The latest `StyrminDeployment` CRD `.status` snapshot per deployment (one row per deployment), upserted by `reportDeploymentStatuses`. Pass-through; not interpreted by the server. Distinct from `Deployment.status` (the **deployment state** enum), which is driven by the wire payload's `displayState`.
_Avoid_: confusing with the **deployment state** enum value.

### GraphQL boundary

**GraphQL operation**:
A query or mutation defined in a `.graphql` file. Inline GraphQL strings in Python are not allowed. SDK operations live under `python_sdk/src/styrmin_sdk/graphql/`; dev task operations under `tasks/graphql/`. Loaded via `load_query()`.
_Avoid_: "GraphQL query" (use **operation** when it could be either), inline GraphQL in Python.

**GraphQL propagation test**:
A unit test required for every new/modified GraphQL field, argument, input type, or mutation under `backend/styrmin_backend/api/schema/`. Asserts full-stack propagation through the real service and repository layers — value reaches the database for writes, database state is projected to the resolver for reads. Non-negotiable per Constitution §V. See [`dev/guides/graphql-propagation-tests.md`](dev/guides/graphql-propagation-tests.md) and [ADR-014](dev/adr/0014-schema-walking-input-propagation-tests.md).
_Avoid_: "integration test" (those are a separate tier), "schema test".

### Testing

**Unit / integration / E2E** (test tiers):
Three tiers per Constitution §V. Unit = service/repository logic. Integration = contract testing. **E2E** = real **vcluster** with FluxCD, Prefect, and supporting services — no mocks.
_Avoid_: "e2e test" lowercase mid-sentence (write "E2E"), "system test", "kind cluster" (we use **vcluster**, not kind).

**vcluster**:
The virtual Kubernetes cluster used as the E2E test target. Started per test by the E2E fixtures; kubeconfig surfaces at `/tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig`. Replaces the earlier kind-based setup.
_Avoid_: "kind cluster", "test cluster" (qualify as **vcluster** so it is unambiguous).

**Dual-entrypoint E2E**:
The default that runs every E2E test twice — `[api-chromium]` (driver = **SDK**) and `[ui-chromium]` (driver = Playwright). Mark with `@pytest.mark.api_only` when there is no UI flow, `@pytest.mark.ui_only` when there is no SDK equivalent. See `AGENTS.md` → Debugging E2E Tests.
_Avoid_: silently running both variants when only one is meaningful.

**E2E definition-of-done**:
Per Constitution §V, every new feature MUST ship an E2E test covering the user-visible flow, executed and observed to pass. Skipping requires explicit reviewer approval; the implementer cannot decide unilaterally.
_Avoid_: "we'll add E2E later", "covered by unit tests" without naming which one and getting approval.

### Shard (CI E2E shard)

A subset of E2E tests routed together to one matrix cell of the
`e2e-tests` GitHub Actions job. Each shard boots its own vcluster.
Tests opt into a shard via a bare-name `@pytest.mark.shard_<name>`
marker. See [`dev/guides/e2e-parallelism.md`](dev/guides/e2e-parallelism.md).

The five shards: `general`, `env`, `compute`, `backup`, `configuration`.

### Test pod

The set of tests that share one vcluster + styrmin install in CI —
operationally, one shard's worth of tests. Synonym for "shard
contents". Use "shard" when talking about the CI matrix cell; use
"test pod" when talking about the test grouping itself.

## Relationships

- **Styrmin** is composed of **server**, **agent**, **CLI**, **SDK**, and **frontend**.
- A **cluster** has one **agent** running inside it; a **cluster** has many **environments**; an **environment** has many **deployments**.
- A **deployment** references one **application driver version** and lives in exactly one **environment**.
- A **deployment** owns zero or more **instances** over its lifetime; at most one is the **active instance** at any time.
- **Reconciliation** generates a new **instance** from the **deployment**, the **remediator** maps the diff against the **active instance** to a plan, and the **PrefectManager** submits the resulting flow.
- A **flow** runs on the **agent**'s **Prefect worker**, resolves a **GlobalContext**, and writes a **StyrminDeployment** CRD whose `spec` embeds that context.
- The **operator** watches **StyrminDeployment** CRDs and reconciles the cluster; FluxCD then reconciles the **HelmRelease** into actual workloads.
- The **status reporter** polls the cluster and writes **PodStatus** + **DeploymentStatus** back via GraphQL — this is the only path that updates `Deployment.status` and the only path that stamps `deleted_at` on the terminal `Deleted` transition.
- A **task**, a backup or a restore has zero or more **steps**; a hook **step** can start **tasks**, and a **task result** covers the task and every task its hook steps started.
- A **GlobalContext** is composed of **ClusterContext**, **EnvironmentContext**, **DeploymentContext**, **InstanceContext**, **ApplicationContext**, **ComponentsContext**, and a list of **UtilityContext**; lower levels override higher ones.
- An **environment clone** links two **environments** — the source it captured and the one it created — and owns one **counterpart deployment** per included source **deployment**.
- The **server** never calls the **agent** directly — direction flows through **recorded intent**.
- An idempotent system: a converged **deployment** produces no diff, no plan, no **flow** — by construction.

## Flagged ambiguities

- **"Driver"** alone — qualify as **application driver** on first use in any document. Bare "driver" is fine after that in the same document.
- **"Version"** — could mean **driver version** or **application version**. Always qualify.
- **"Service"** — could mean **Styrmin service** (driver-declared, → `DeployedService`), the backend **service layer**, or Kubernetes' built-in `Service` object. Qualify when ambiguous.
- **"Task"** — `Task` database row tracking an async operation, **not** Prefect's in-process `task` primitive. When referring to Prefect's primitive, write "Prefect task".
- **"Hook"** vs **"mode"** — **hooks** (`setup`, `upgrade`) are lifecycle slots; **modes** (`pre`, `core`, `post`) divide a hook. Do not interchange.
- **"Status"** — three things: `Deployment.status` (a **deployment state** enum), `Instance.status` (an `InstanceStatus` enum), and `DeploymentStatus` (the observed-state row). Always qualify.
- **"Context"** — when speaking domain, this means **GlobalContext**. In code, "context" also appears as Python `Context` (Invoke) and Strawberry `Info.context`. Qualify if a reader could confuse them.
- **"Component"** vs **"Pod"** — a **component** is the driver-declared unit of an app (e.g. `server`). A pod is a Kubernetes runtime object. Lifecycle controls act on **components**; status observation surfaces **pods**.
- **"Operator"** — Styrmin's **operator** is the kopf controller inside the **agent**. Do not use "operator" for an on-call human or a Kubernetes operator in general; qualify if needed.
- **"Tombstoned"** vs **"deleted"** — a **tombstoned** deployment is one with `deleted_at IS NOT NULL` and `status = DELETED`. The cluster-side workload is gone, the record remains. "Deleted" without context can mislead users into thinking the row is also gone.
- **"K8s agent"** — legacy README phrasing. Use **agent** — there is only one process and it is not exclusively a K8s controller (it also runs Prefect and the status reporter).
- **"Backend"** — the `backend/` directory and the language layer. The **server** is the running process. Do not say "the backend reconciles" — say "the server reconciles".
- **"Workflow"** — fine as a colloquial label for a **flow**; use **flow** or "Prefect flow" in technical writing to keep alignment with Prefect's vocabulary.
- **"Config"** — overloaded: `Cluster.config`, `Environment.config`, `Deployment.config`, `Component.config`, plus the merged view exposed on `InstanceContext.config`. Qualify which level you mean.

## Updating this file

Treat CONTEXT.md as part of the codebase. If a change introduces a new domain concept, renames one, or shifts how an existing one behaves:

1. Update CONTEXT.md in the same change.
2. Sync `AGENTS.md` if a referenced term in its prose drifts.
3. If the change reflects a decision worth preserving (not just a renaming), file or update an ADR under `dev/adr/`.

Any contributor (or agent) can update CONTEXT.md directly — no special workflow is required. The `/grill-idea` skill happens to read this file and will extend it when grilling surfaces a missing concept, but it is one of several ways the glossary stays current, not the canonical path.
