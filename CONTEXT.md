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
The anonymous, opt-out signal that **Styrmin** sends to OpsMill. It has two sources, each with its own settings and its own **install ID**. (1) The **CLI**'s per-command event: a single best-effort HTTPS POST of a scrubbed event (resolved command route, canonical option _names_, outcome + error category, coarse environment facts) that the **CLI** fire-and-forgets after each _eligible_ invocation. On by default on interactive workstations, silent in CI / non-interactive contexts; capped at ≤ 200 ms added latency and failure-isolated (never alters output, exit code, or speed). Scrub-by-construction: never carries names, values, paths, tokens, or addresses. Opt out with `styrminctl telemetry disable`, `STYRMIN_TELEMETRY=0`, or `DO_NOT_TRACK=1`. State `{install_id, enabled}` persists next to the token store. See [ADR-047](dev/adr/0047-styrminctl-anonymous-fire-and-forget-telemetry.md). (2) The **server**'s daily report: one POST a day at 02:43 UTC from the INTERNAL **flow** `send_telemetry_report`, which runs in the task worker (the Prefect worker of `styrmin-work-pool`), in the same envelope as the CLI event with `kind: "styrmin"`. It carries the **install ID**, the Styrmin, Python and operating system versions, the number of **clusters**, **environments** and **deployments** that are not **tombstoned**, and one entry per loaded **application driver version** (driver name as written, version, source type, number of deployments that use it). On by default; a run that starts more than one hour late sends nothing, and each run logs one INFO line that says whether the report was sent, so a send failure is never a warning. Turned off by the Helm value `styrmin.telemetry.enabled: false`, `STYRMIN_TELEMETRY_ENABLED=false`, `DO_NOT_TRACK=1` or `STYRMIN_TELEMETRY=0`, which must reach both the **server** and the task worker. `styrmin telemetry show` in the server pod prints the report data without sending it. See [ADR-061](dev/adr/0061-server-anonymous-daily-telemetry.md).
_Avoid_: "analytics", "tracking", "metrics" (reserved for backend/observability signal).

**Install ID**:
A random UUID that lets OpsMill count distinct installs in **telemetry** without identifying them. The **CLI** and the **server** each have their own, and the two are not linked. The CLI's is created the first time the CLI reads it, stored next to the token store, and kept when telemetry is disabled. The server's is created the first time the **server** starts with a **database**, whether telemetry is on or off, and stored in the single-row `installation` table, so there is one per database: a database dump restored into another install reports the same install ID, and a database rebuilt from scratch reports a new one.
_Avoid_: "instance ID" (an **instance** is the realised state of a **deployment**), "customer ID" (it identifies no customer).

**SDK / styrmin-sdk**:
The async Python client SDK that wraps GraphQL operations as typed Pydantic models. Used by **CLI**, **E2E tests**, and external callers. Types are generated from `schema.graphql` via ariadne-codegen.
_Avoid_: "python client", "API client".

**Frontend**:
The React 19 + Vite SPA that consumes the GraphQL API. Single-page application; not server-rendered.
_Avoid_: "UI" (ambiguous with the rendered surface a user sees), "web app".

### Infrastructure entities

**Cluster**:
A Kubernetes cluster registered in Styrmin and represented by a `Cluster` database row. Carries a **config** dict and a computed **capabilities** dict. The config is set by `createCluster` and replaced in full by `updateCluster`, which recomputes the capabilities and starts a **config fan-out**. One **agent** runs per **cluster**. Currently exactly one **cluster** is supported at a time — see [002-single-cluster-limit].
_Avoid_: "k8s cluster" (redundant), "target cluster" (used only when contrasting source/target in code that involves multiple clusters).

**Environment**:
A logical deployment target bound to exactly one **cluster**. Carries its own **config** and **capabilities** dicts, which override the **cluster**'s values when they overlap. Name is unique per cluster, not globally.
_Avoid_: "env" (in prose; the abbreviation is fine in code), "deployment environment", "namespace" (Kubernetes-specific).

**Config fan-out**:
The redeploys that Styrmin starts after an **environment**'s **config** is updated: one redeploy for each non-tombstoned, non-internal **deployment** whose active **instance** is not yet at the new config. Deployments already at the new config are skipped, and a failed redeploy does not stop the others. See [ADR-012](dev/adr/0012-environment-config-fanout.md). The redeploys are ordered around the environment's **dedicated ingress controller**, an internal **deployment**: the fan-out creates the controller or redeploys it with the new values, a non-internal deployment moves onto the controller only once the controller is `RUNNING` with the new values, the **status reporter** redeploys the non-internal deployments that waited when the controller reaches `RUNNING`, and the controller is removed only after every non-internal deployment has moved off it. `DELETING` deployments are skipped. After a **cluster**'s config is updated, the cluster config fan-out does the same in every environment of the cluster, with one difference: each deployment is compared on its resolved config (the cluster config, then the environment config, then the deployment config, where the deepest value wins) against the resolved config of its active instance, so a deployment in an environment that sets the changed value itself is not redeployed. A failure in one environment does not stop the others. See [ADR-066](dev/adr/0066-cluster-config-fanout.md).
_Avoid_: "cascade", "propagation" (a propagation test is a different thing).

**Dedicated ingress controller**:
The internal **deployment** of the built-in **application driver** `styrmin-ingress-controller` (a Traefik chart) that serves the ingress of one **environment**. An environment has at most one that is not **tombstoned**. It is on when the environment's effective `dedicated_ingress` (the environment config's value, else the cluster config's) is set to any object, including `{}`; an absent or null value turns it off. While the value is on and no controller exists, deploying an application, changing its config or changing its version creates one, and so do the environment and cluster **config fan-outs** when the environment has applications. In the same case, a controller that is `FAILED` or `DELETING` makes those three operations fail. Its deletion is requested once no application is left in the environment, or once the value is off and every application has been redeployed without it. While it is on, Styrmin removes `spec.ingressClassName` from every Ingress of the environment's applications after the chart renders and sets the `kubernetes.io/ingress.class` annotation to the controller implementation; while it is off, Styrmin sets both to the resolved `ingress_class`, or changes neither when no `ingress_class` is resolved, so the chart's class stays. Driver templates do not need to set the class. See [ADR-066](dev/adr/0066-cluster-config-fanout.md) and [ADR-071](dev/adr/0071-ingress-class-set-by-post-render.md).
_Avoid_: "ingress utility" (the **utility** is the resource template, not the deployment), "shared ingress" (the cluster's `ingress_class`, used when the controller is off), "Traefik" alone.

**Backup storage location** (BSL):
An S3-compatible object store registered as a destination for **Velero** backups. Assigned to an **environment**; all deployments in that environment back up there.
_Avoid_: "bucket" (implementation detail), "backup destination".

**Backup retention TTL** (`backup_ttl`):
How long **Velero** keeps a backup before garbage-collecting it, as a strictly positive Go duration in `h`/`m`/`s` units (e.g. `"2160h"`). An optional `backup_ttl` on the **cluster**, **environment**, or **deployment** **config**, resolved deepest-wins at backup time — deployment → environment → cluster → the built-in `720h` — with the applied value and its source scope recorded on the backup record. Applies only to backups created afterwards; an already-created Velero backup keeps the expiration fixed at its creation. Distinct from `BackupSchedule.retention_count`, which caps _how many_ backups a schedule keeps rather than how long each one lives (and is currently unenforced — scheduled backups do not execute yet). See [016-backup-retention-ttl] and [issue #305](https://github.com/opsmill/styrmin/issues/305).
_Avoid_: "retention policy" unqualified (ambiguous with `retention_count`), "backup expiry" (that is the resulting timestamp, `Backup.expiresAt`), bare "TTL" (overloaded with the Velero polling timeout).

**Backup history**:
Every backup taken of any **instance** of one **deployment**, newest first. Not stored: it is found through the deployment's instances (`Backup.instance_id` → `ApplicationInstance.deployment_id`), so no backup row changes. Listed by `backups(deploymentId:)`, the deployment's Backups tab and `styrminctl backups list <deployment>`; the history of an internal deployment is empty. `styrminctl backups restore --last` chooses the newest completed backup from it that has not expired, and asks for confirmation (or `--yes`) when that backup was taken of an earlier instance. Each backup in it shows the **application version** of the instance it was taken of. It survives the operations that give a deployment a new **active instance** (an upgrade, a config edit, an **environment** config change and a **cluster** config change) and the deletion of the deployment (a **tombstoned deployment** keeps its history, but a restore into it is refused). A new deployment that reuses a tombstoned deployment's name starts with an empty history, because the history is listed by deployment id. See [issue #304](https://github.com/opsmill/styrmin/issues/304).
_Avoid_: "instance backups" when the deployment-wide list is meant (that is the `backups(instanceId:)` list of one **instance**).

**Environment backup**:
A coordinated, near-consistent snapshot of an **environment**: its **config** as of backup time, the declared state of every eligible **deployment** (non-tombstoned, non-internal, with an active **application instance**), and one **constituent backup** per eligible instance — grouped under a single `EnvironmentBackup` record. Its status (`PENDING` / `IN_PROGRESS` / `COMPLETED` / `PARTIAL` / `FAILED`) is **derived from its constituents on every read and never stored**, so it cannot contradict them. Deleting it cascade-deletes its constituent backups and their restores, and is legal whatever the snapshot's own status (the escape hatch for a snapshot pinned in progress), with one exception: while an **environment clone** that has not finished is still capturing into the snapshot, the deletion is refused with `IN_USE`. That refusal stops once the capture is 7200 seconds old (`CAPTURE_IN_FLIGHT_GUARD_SECONDS`, the time the clone flow waits for its capture), so a capture that never finishes can still be deleted. See [issue #7](https://github.com/opsmill/styrmin/issues/7) and [ADR-055](dev/adr/0055-environment-backup-parent-records.md).
_Avoid_: "env snapshot", "full backup" (ambiguous with a per-instance backup), "environment export".

**Environment restore**:
The coordinated operation that reapplies an **environment backup**'s captured **config** and restores every usable **constituent backup** into its still-existing **deployment**, in place — restoring what's usable and reporting what isn't (every non-restored constituent is attributed with a deployment name and a free-text reason); it never creates or deletes application deployments. The reapplied config reaches the other deployments and the **dedicated ingress controller** through the same fan-out as `updateEnvironment`, so the controller can be created, redeployed or removed ([issue #467](https://github.com/opsmill/styrmin/issues/467)). Tracked by an `EnvironmentRestore` record whose status is derived the same way. Requires the `ADMIN` role, unlike creating or deleting an **environment backup** — it rewrites `Environment.config`, the same privilege `updateEnvironment` needs.
_Avoid_: "environment rollback" (implies topology reversion), "environment recovery" (broader DR concept).

**Environment clone**:
A first-class `EnvironmentClone` record of one operation that copies a live **environment** into a **new** environment on the same **cluster**, built entirely from a fresh **environment backup** of the source — never by re-reading the live source. Each included source **deployment** gets a **counterpart deployment** in the new environment, pinned to the captured **application driver version**, into which the source's **constituent backup** is restored (a **cross-target restore**). Carries the requested target name, the deployment selection, the config override, one attribution entry per source deployment (cloned / skipped + reason / failed + reason; an internal or **tombstoned** deployment gets an entry only when the selection names it), and a flat list of operation-level events; its status (`PENDING` / `IN_PROGRESS` / `COMPLETED` / `PARTIAL` / `FAILED`) is **derived on every read and never stored**. The name is deliberately **not** unique — discarding a clone (by deleting the environment it created) must not burn the name. Copied **affinity terms** name the counterpart deployments: the clone chooses each counterpart's id before it creates the new environment, and points every copied **deployment reference**, in the new environment's config and in each counterpart's config, at the counterpart of the deployment it named. `cloneEnvironment` refuses, with `VALIDATION_ERROR` and before it creates any record or backup, a request whose copied terms name a deployment that the clone does not copy; the error lists each such deployment and the paths of the terms that name it. When the captured data of a named deployment cannot be used, or its creation fails during the clone, the counterparts whose terms name it fail too. When the new environment's config names it, the clone fails: when its captured data cannot be used, the clone creates no environment, and after a failed creation it creates no further counterpart. Requires the `ADMIN` role to create; reads are ungated. See [issue #6](https://github.com/opsmill/styrmin/issues/6), [ADR-056](dev/adr/0056-environment-clone-record-and-cross-target-restore.md) and [ADR-075](dev/adr/0075-deployment-references-stored-by-id.md).
_Avoid_: "environment copy", "environment fork", "duplicate environment", "environment snapshot" (that is an **environment backup**), "clone" alone when the reader could hear `git clone`.

**Counterpart deployment**:
The **deployment** an **environment clone** creates in the new environment for one included source **deployment**. Bound to the captured **application driver version**, created in the `RESTORING` **deployment state** with its initial **reconciliation** deferred, and it adopts the _source's_ Helm release name while keeping its own **StyrminDeployment** CRD identity — so `helm list` in a counterpart's namespace shows a release named after the source deployment. Otherwise an ordinary deployment once its restore lands.
_Avoid_: "clone deployment" (ambiguous — the clone is the operation), "target deployment" (used only when contrasting source/target inside restore code), "copy", "mirror".

**Cross-target restore**:
A restore of a **constituent backup** taken of one **deployment** into a different deployment, the **counterpart deployment** of an **environment clone**, in that deployment's own namespace. It goes through the same `create_restore` service and restore workflow as an in-place restore. Velero's `namespaceMapping` writes the source namespace's objects into the counterpart's namespace, and the restore leaves out the **HelmRelease** and the **service aliases**. The **operator** then points the restored Helm release storage at the counterpart, applies the counterpart's **StyrminDeployment**, and deletes the restored copy of the source's StyrminDeployment without tearing down the resources it names. After that recovery, the restore writes the service aliases between the counterpart and the other deployments of the new environment ([#530](https://github.com/opsmill/styrmin/issues/530)). The `Restore` row's `target_instance_id` is the counterpart's **active instance**. See [ADR-056](dev/adr/0056-environment-clone-record-and-cross-target-restore.md).
_Avoid_: "clone restore", "restore into another environment" (it restores into one deployment), "migration".

**In-place restore**:
A restore of a backup into the **deployment** that the backup was taken of, from any of its **instances** (see **Backup history**), in that deployment's own namespace `styrmin-<deployment id>`. Started from the deployment's Backups tab, by `createRestore`, by `styrminctl backups restore`, or as a **constituent restore** of an **environment restore**. The caller names only the backup: Styrmin derives the namespace from the backup's deployment and records that deployment's **active instance** as the `Restore` row's `target_instance_id`, or no instance when the deployment has none. The restore puts back the **StyrminDeployment** and the **HelmRelease** that the backup holds, and does not change the deployment's active instance ([ADR-063](dev/adr/0063-restore-of-earlier-instance-backup.md)). The restore workflow fails a restore whose namespace is not `styrmin-<deployment id>` before it changes anything in the cluster. See [issue #532](https://github.com/opsmill/styrmin/issues/532).
_Avoid_: "same-namespace restore" (the namespace is not a choice), "rollback" (a restore does not change the active instance).

**Constituent backup / constituent restore**:
An ordinary per-instance `Backup` (or per-deployment `Restore`) row that belongs to an **environment backup** (or **environment restore**), linked by the nullable FK `Backup.environment_backup_id` / `Restore.environment_restore_id`. Constituents keep their existing semantics entirely — individually listable, deletable, and expiring under the **backup retention TTL**. A null FK is a standalone backup or restore.
_Avoid_: "child backup", "sub-backup", "member backup", "partial backup" (that describes an outcome, not membership).

### Application drivers

**Application driver**:
A versioned, self-contained deployment specification that defines how an application is deployed (Helm chart reference, component definitions, services, parameters, action declarations). Identified by a unique `name`. Per Constitution §II, all deployment behavior flows from the driver — no ad-hoc deployment logic outside drivers.
_Avoid_: "driver" alone when first introducing the term, "application spec", "deployment template".

**Application driver version** (driver version):
A specific version of an **application driver**, sourced from a **driver directory** in a git repository or on the server. Owns its own `helm_chart` reference, `component_configs`, `parameters`, `services`, and `actions`. Selected per **deployment**.
_Avoid_: "version" alone (ambiguous with **application version**), "driver release".

**Driver directory**:
The folder that holds an **application driver**'s **driver specification file**, `values.j2.yml` and `actions.py`. For a load from a local directory, it is the path given on the server. For a load from git, it is the repository root or a folder of the repository, given as a path relative to the root. Stored on the **application driver version** as `source_path`, which is null when it is the repository root, and returned by the GraphQL field `driverDirectory` for a git load (null for the repository root and for a local load). The **actions** of a driver version loaded from git or from a local directory run from it, as processes in the **agent** pod, and can import only modules inside it, apart from the packages installed in the image that the **agent** runs; a git load refuses a driver directory that is a symlink to a path outside the repository, and a driver specification file, `values.j2.yml` or `actions.py` that is a symlink to a path outside the driver directory. See [issue #517](https://github.com/opsmill/styrmin/issues/517), [ADR-079](dev/adr/0079-driver-actions-import-only-from-their-driver-directory.md) and [ADR-081](dev/adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md).
_Avoid_: "subfolder", "subpath", "driver root".

**Driver specification file**:
The `driver.styrmin.yml` file at the root of a **driver directory**. Single source of truth for driver metadata, supported application versions, Helm chart, components, parameters, services, and action declarations.
_Avoid_: "driver yaml", "driver manifest".

**Driver logo**:
The image URL that a driver author sets in `spec.info.icon` of the **driver specification file**. It must be an absolute `https` URL without a username or password; for any other value the load succeeds, leaves the logo out and returns a **load warning**. Stored as text on each **application driver version** (`ApplicationDriverVersion.icon`), so two versions of the same driver can have different logos. The driver list and driver detail pages show it on a white tile next to the driver name. Styrmin never fetches the image: the browser of each person who views the page loads it from the URL. The server setting `STYRMIN_DRIVER_SHOW_LOGOS=false` (Helm value `styrmin.driver.showLogos`) makes the API return no logo, which stops these requests. Until the image has loaded, and when a driver version has no logo or the browser cannot load it, the pages show the generic package icon in the same position. See [issue #272](https://github.com/opsmill/styrmin/issues/272).
_Avoid_: "driver icon file", "driver avatar".

**Load warning**:
A message that a driver load returns for a `spec.info.icon` or `spec.info.links` value that it left out of the **application driver version**, naming the field and the reason. The load still succeeds. Returned in `loadWarnings` of the load mutations and printed by `styrminctl drivers load-version` and `load-local-version`; never stored, so loading the same file again returns it again.
_Avoid_: "load error" (the load did not fail), "validation warning".

**Provenance fingerprint** (driver-version fingerprint):
The content-addressable identifier carried by each **application driver version** that makes the row's identity stable across reloads with the same `version` string. Stored as two columns on `ApplicationDriverVersion` — `content_hash` (SHA-256 hex of the canonical local driver bytes) for `source_type = "local"`, and `source_commit_sha` (resolved git commit SHA) for `source_type = "git"`. Exactly one is non-null per row; the discriminator is `source_type`. For git, the commit covers the whole repository, so a commit that changes only files outside the **driver directory** also gives a reload a new fingerprint. Surfaced in the UI/CLI as `<version>@<short-fingerprint>` (first 7 chars). For a local **driver version**, it is also checked when an **action** runs, before the action's code is imported: the files at the driver version's path must still have the stored `content_hash` ([ADR-081](dev/adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md)). See [issue #262](https://github.com/opsmill/styrmin/issues/262).
_Avoid_: "driver hash" alone (ambiguous across source types), "version hash" (conflates with **driver version**), "build id".

**Application version**:
The user-facing version of the deployed application (e.g. `infrahub` `1.6.0`), distinct from the **driver version** that knows how to deploy it. A **driver version** declares a semver specifier (`application_supported_versions`) describing which **application versions** it can deploy. The version a person types is stored unchanged (`1.12.0-beta.1` stays `1.12.0-beta.1`), and a **prerelease** may be requested.
_Avoid_: "app version" (in code is fine, in prose write it out), conflating with **driver version**.

**Prerelease** (application version):
An **application version** that PEP 440 treats as a prerelease: a beta (`1.12.0b0`), a release candidate (`1.12.0rc1`) or a development build (`1.12.0.dev1`). A **driver version**'s `application_supported_versions` range accepts a prerelease when its numbers fit the range, so `>=1.5,<2.0` accepts `1.12.0b0`. PEP 440 orders a prerelease below its final release, so `>=1.12.0,<1.13` refuses `1.12.0b0`, and `>=1.12.0b0,<1.13` accepts it. A range accepts every prerelease whose numbers fit it. Only a `==` or `!=` clause, or bounds that put the prerelease's numbers outside the range, refuse one: `==1.12.0` refuses `1.12.0b0`, and `<2.0,!=1.12.*` refuses `1.12.0b1`. When a request for an unsupported version is refused, the error lists the supported ranges. See [issue #591](https://github.com/opsmill/styrmin/issues/591).
_Avoid_: "beta" as the general term, since a beta is one kind of prerelease.

**Latest-wins driver-version resolution**:
The deterministic rule that picks which **application driver version** a **deployment** binds to when several support the requested **application version**: highest parseable `version` string first (unparseable strings rank below all parseable ones), ties broken by `created_on` descending (most recently loaded), final tie-break on row id. Applies on initial deploy and on every upgrade — an upgrade always re-resolves the binding unless the caller pins one explicitly via `driverVersionId` (the **driver-version pin**, valid only within the deployment's own driver). Implemented by `_driver_version_sort_key` / `_resolve_latest_matching_version` in `backend/styrmin_backend/services/deployment.py`.
_Avoid_: "newest version" (ambiguous between the two orderings), "first match" (the pre-rule behavior), "default driver version" (conflates with `default_version`).

**Component**:
A logical sub-part of an application (e.g. `server`, `task-worker`) declared by the **application driver** and identified by a Kubernetes label selector (`styrmin/component`). A **deployment** can enable/disable and configure components individually. Lifecycle controls (start/stop, restart) act on the **component** as a unit. Its replica count comes from a **replica override**, the driver default or the chart's count, in that order.
_Avoid_: "service" (that is its own concept), "pod" (a **component** is observed via one or more **pods**), "module".

**Singleton component**:
A **component** that the **driver version** marks `singleton: true`. Its replica count is fixed at 1: Styrmin patches the count to 1 even when the driver declares no default. Styrmin rejects a **replica override** greater than 1 when a user writes the deployment and before a **driver version** change, and rejects a **driver specification file** that combines `singleton: true` with `replicas` greater than 1. The flag limits the replica count, not how many pods run at once during a rolling update.
_Avoid_: "single-replica component", "stateful component".

**Service** (deployed service):
A network-addressable endpoint declared by the **application driver** under `spec.services` (kind, scope, port, owning component) and materialised as a `DeployedService` row plus a Kubernetes Service object. The other **deployments** of the **environment** can connect to it on its port: Styrmin writes one NetworkPolicy per owning component, `allow-environment-to-<component>` ([#557](https://github.com/opsmill/styrmin/issues/557)). A component that owns no service is reachable from its own deployment's namespace only.
_Avoid_: "endpoint" (HTTP-specific), "port" (one attribute of a service), conflating with Kubernetes-`Service` when ambiguity matters — qualify as "K8s Service" if needed.

**Service alias**:
An `ExternalName` Kubernetes Service that lets a pod reach a **service** of another **deployment** of the same **environment** by the service's short name. Styrmin creates one alias for each service in the namespace of every other deployment of the environment, named after the service's resolved name and pointing to the service in its owner's namespace. Labelled `styrmin.io/service-alias=true` and `styrmin.io/deployment-id=<owner id>`. The create, update and upgrade flows create aliases and delete those whose name the owner no longer uses ([#491](https://github.com/opsmill/styrmin/issues/491)). The flows read the environment's current services from the server before they write aliases, because a flow's context lists no deployment requested after it. The **operator**'s teardown deletes the owner's aliases when the owner is deleted through Styrmin, best-effort ([#503](https://github.com/opsmill/styrmin/issues/503)). A namespace deletion without a deletion request, as a restore or `kubectl delete namespace` makes, deletes no alias. An **environment clone** writes the aliases of the new environment and never restores the source's aliases ([#530](https://github.com/opsmill/styrmin/issues/530)).
_Avoid_: "DNS alias", "ExternalName service", "cross-namespace service".

**Parameter**:
A user-configurable input declared by the **application driver** (`name`, `label`, `kind`, `default`). Surfaced through the GraphQL API and **frontend** forms; flows through to **context** as part of the **deployment**'s config. On a **driver version** change, Styrmin drops a stored or submitted value for a parameter that the target version no longer declares when the value equals the parameter's default in the current version, with the same type; otherwise Styrmin rejects the change (`RETIRED_PARAMETER_VALUE`) and names the parameter and its value ([ADR-070](dev/adr/0070-replica-overrides-and-retired-parameters.md)).
_Avoid_: "field" (UI term), "option", "setting", conflating with **prompt argument** in driver action templates.

**Action**:
A Python function declared by the **application driver** under `spec.actions` and implemented in the driver's `actions.py`. Runs inside a **Prefect** flow as part of the `setup` or `upgrade` **hook** at the `pre`, `core`, or `post` **mode**. The **agent** runs each action as a process in the agent pod. The actions of a **driver version** loaded from a local directory run in the agent pod from the driver version's path, after a check that the files there have its **provenance fingerprint**. A declared action without a registered flow fails its hook **step** instead of being skipped; loading the driver again registers it ([ADR-081](dev/adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md)).
_Avoid_: "task" (that is the database tracking record), "step" (running all actions of one **mode** is one **step**; the action itself is not), "function", "hook" (a **hook** is the lifecycle slot, an **action** is the work that runs in it).

**Hook**:
A lifecycle slot at which **actions** run. Currently two: `setup` (during create) and `upgrade` (during upgrade). Each **hook** is composed of three **modes**.
_Avoid_: "lifecycle event", "phase" (that is the operator's term), "stage", "Helm hook" (a chart resource annotated `helm.sh/hook` is a **Helm hook**, not a **hook**).

**Helm hook**:
A resource of an **application driver**'s Helm chart annotated `helm.sh/hook`, which Helm creates at a set point of an install, upgrade, rollback, uninstall or test, for example a pre-upgrade `Job`. helm-controller runs with Helm v4 defaults (`postRenderStrategy: combined`), so a Helm hook receives Styrmin's post-render patches as the chart's other resources do: Styrmin's labels always, the scheduling settings when it is a `Job`, `CronJob`, `Deployment`, `StatefulSet`, `DaemonSet` or `ReplicaSet` that carries a **component**'s identifier label (any of those kinds when the driver declares no components), and the **component container** patches and the replica count only when it is a `Deployment` or `StatefulSet` that matches a **component** ([ADR-072](dev/adr/0072-helm-v4-defaults-releases-keep-apply-method.md)). Distinct from a Styrmin **hook**, which is a lifecycle slot for **actions**.
_Avoid_: "hook" alone, "chart hook", "hook job" (a Helm hook can be any kind).

**Mode**:
The execution phase within a **hook**: `pre`, `core`, or `post`. Ordering inside a **mode** is unspecified; ordering across **modes** is strict.
_Avoid_: "phase" (reserved for operator phases), "stage", "step" (one run of a mode is one **step**; the mode itself is not).

**Action token**:
A session token for the built-in `styrmin-actions` user (role `READ_WRITE`, no password, and no one can log in as it) that an INTERNAL **flow** creates for the work it hands to a USER flow, which the **agent** runs as a process in the agent pod, and deletes when that work ends: `apply_state` once per **reconciliation**, `run_job` once per `run_job` **task**, and the backup and restore workflows once per backup or restore. It reaches that flow in the `STYRMIN_TOKEN` environment variable, next to the step parent (`STYRMIN_TASK_ID`, `STYRMIN_BACKUP_ID` or `STYRMIN_RESTORE_ID`); the remediation flow passes it on to every **action**, with the hook **step** in `STYRMIN_STEP_ID`. The action primitives send it as a bearer token, and flows and actions use it to record **steps** through `recordStep` and to link the **tasks** that actions start to their hook **step** through `startedByStepId`; the server accepts both from no other user. See [ADR-059](dev/adr/0059-driver-action-api-tokens.md) and [ADR-060](dev/adr/0060-steps-and-derived-task-result.md).
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
The enum value on `Deployment.status`: `PENDING`, `DEPLOYING`, `RUNNING`, `RESTORING`, `FAILED`, `DELETING`, `DELETED`. Sole source of truth for the column is the **status reporter** mapping the **operator**'s `displayState`. A `Running` report sets `RUNNING` only once the task that rolls out the reported instance, and the task whose hook step started it, have finished. The column does not change during a restore: from `createRestore` until the restore workflow records the result, the column stays `RESTORING` whatever the reports say. If that workflow cannot be dispatched, the restore and the deployment are marked `FAILED` at once.
_Avoid_: "deployment status" (use this for the _record_ `DeploymentStatus`, not the state value), "phase" (that is the operator's `.status.phase`).

**Declarative deployment manifest**:
A YAML document with `apiVersion: styrmin/v1` and `kind: Deployment` that describes the desired state of one **deployment** (`metadata.name`, `spec.driver`, `spec.version`, `spec.environment`, optional `spec.cluster`, `spec.config`, `spec.parameters`). The input format for **declarative apply**. A single file may contain multiple manifests separated by `---`. `config` and `parameters` are fully replaced on update, not deep-merged. Full schema in `specs/archive/009-deployments-apply/contracts/manifest-schema.md`; the format's design decisions are recorded in [ADR-049](dev/adr/0049-styrmin-v1-manifest-contract.md).
_Avoid_: "deployment spec" (overloaded — `Deployment.spec` also refers to the cluster-side CR), "k8s manifest" (these are not Kubernetes objects), "yaml file".

**Declarative apply**:
The upsert operation exposed as `styrminctl deployments apply -f <path>` and the SDK's `DeploymentResource.apply_files(...)`. Resolves each **declarative deployment manifest** by `(name, environment)` identity, then creates if absent or updates if present (driver-disagreement fails with `DriverMismatchError`; driver changes require explicit delete-and-recreate). Continue-on-error within a batch; exits non-zero if any manifest failed. With `--wait`, blocks until each successfully submitted deployment reaches a terminal **reconciliation** state. Not a delete operation — manifests missing from a directory are not pruned.
_Avoid_: "kubectl apply" (intentionally similar UX but not the same semantics — no pruning, no server-side merge), "deploy" (overloaded with the existing `deploy()` mutation, which is create-only).

### Instances — current (realised) state

**Instance** (`ApplicationInstance`):
A frozen snapshot of what was actually deployed at a point in time, generated from a **deployment** at **reconciliation** time. Carries a serialised `GlobalContext` in its `context` field. A **deployment** owns at most one **active instance** at a time. Each instance carries an **instance sequence**. Its name is a generated two-word name, such as `hairy-toad`, that no other instance of any deployment has: Styrmin generates ten names and keeps the first one that no stored instance has ([#499](https://github.com/opsmill/styrmin/issues/499)).
_Avoid_: "application instance" in prose (fine in code), "release", "rollout", "version".

**Instance sequence**:
The position of an **instance** among the instances of its **deployment**: 1 for the first, then one more for each new instance (`ApplicationInstance.sequence`). The repository assigns it when it saves a new **active instance**, by incrementing `Deployment.last_instance_sequence` under the deployment row lock, so the instance committed last holds the highest sequence. Recorded on the **StyrminDeployment** in the `styrmin.io/instance-sequence` annotation, and a **flow** leaves a StyrminDeployment that holds a higher sequence than its own instance unchanged ([#386](https://github.com/opsmill/styrmin/issues/386)).
_Avoid_: "revision" (Helm's term for a release version), "generation" (Kubernetes' `metadata.generation`), "instance number".

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
The mechanism by which a **deployment**'s **component** config (`DeploymentConfig.components[<name>]`) overrides the **driver version**'s default `ComponentConfig`. First-class to the deployment-config feature. Component-scope env vars, **image overrides** and **container overrides** reach pods by a post-render patch into the **component container**, not through the values template ([ADR-057](dev/adr/0057-post-render-component-overrides.md), [ADR-058](dev/adr/0058-image-overrides-and-component-container-guard.md), [ADR-069](dev/adr/0069-container-command-args-by-post-render.md)). A **replica override** patches the workload, not the **component container**, and needs no component container.
_Avoid_: "component patch", "component customisation".

**Component container**:
The single container in a **component**'s pod template that the **application driver** declares (`components.<name>.container` in the **driver specification file**) as the target of per-component post-render overrides — env vars, **image overrides** and **container overrides** (`command`, `args`). Optional: a component without one accepts no component-scope env vars, **image override** or **container override** (`COMPONENT_CONTAINER_NOT_DECLARED`) and is skipped by deployment- and environment-scope env vars; values stored there are kept and read back with `isApplicable: false`. Only `Deployment` and `StatefulSet` workloads are patched. A declared name missing from the rendered workload fails the reconcile with `COMPONENT_CONTAINER_NOT_FOUND` whichever override targets it, `command` or `args` alone included; Styrmin never adds a container. See [ADR-057](dev/adr/0057-post-render-component-overrides.md), [ADR-058](dev/adr/0058-image-overrides-and-component-container-guard.md) and [ADR-069](dev/adr/0069-container-command-args-by-post-render.md).
_Avoid_: "main container", "app container", "primary container", "target container".

**Container override**:
The per-**component** `command` (container entrypoint) and/or `args` slot a user may set on a single **deployment**, scoped to that component only — no environment/deployment-wide scope, no layering (014-component-container-overrides). Two independent, optional, nullable lists; a set list replaces the whole `command` or `args` list of the **component container**, and an unset slot keeps the value the chart renders. An empty list is rejected. Stored on `DeploymentConfig.components[<name>]` and applied by a post-render patch to the **component container** (`Deployment` and `StatefulSet` only), together with env vars and the **image override** ([ADR-069](dev/adr/0069-container-command-args-by-post-render.md)). Needs a **component container**: adding or changing a value on a component without one is rejected (`COMPONENT_CONTAINER_NOT_DECLARED`, `override: "command"` or `"args"`), and a value stored there or on an orphaned component is kept but not applied (`ComponentContainerOverrides.isApplicable: false`). The `component_command` / `component_args` template filters are retired (`RETIRED_TEMPLATE_FILTER`), and `spec.container_overrides` is removed from the **driver specification file**.
_Avoid_: "command override" / "args override" alone (they are the two slots **of** a container override), "entrypoint patch", "container customisation". Distinct from **component overrides** (the broader config-override mechanism) and from env vars (which **do** layer across scopes).

**Image override**:
The per-**component** image reference a user may set on a single **deployment**, applied by a post-render patch to the **component container** (`Deployment` and `StatefulSet` only). A full reference with an explicit tag or digest; a `{{ app.version }}` token resolves to the deployment's **application version** at render time (plain substitution, not Jinja), and a literal tag or digest pins the image across **application version** upgrades. Component scope only, no layering. Stored on `DeploymentConfig.components[<name>]`. Rejected on write and before an **application version** change when invalid (`INVALID_IMAGE_REFERENCE`); kept but never applied on a component without a **component container** or on an orphaned component. See [ADR-058](dev/adr/0058-image-overrides-and-component-container-guard.md) and [issue #20](https://github.com/opsmill/styrmin/issues/20).
_Avoid_: "custom image", "image patch", "tag override". Distinct from a registry mirror (release-wide rewrite of every image, a separate issue).

**Replica override**:
The replica count a user sets on one **component** of a single **deployment** (`DeploymentConfig.components[<name>].replicas`), an integer from 1 to the server setting `STYRMIN_MAX_REPLICA_COUNT` (default 20) when a user sets it; a stored value up to 2147483647 stays valid. Styrmin applies it with a post-render patch to `spec.replicas` of every `Deployment` and `StatefulSet` that matches the component's label selector; it needs no **component container**. Order of precedence: the replica override, then the driver default (`components.<name>.replicas` in the **driver specification file**), then the count the chart renders, which Styrmin does not patch. A stopped component stays at 0 pods and keeps its override. An override on a component that the bound **driver version** no longer declares is kept and not applied. Component scope only, no layering. See [ADR-070](dev/adr/0070-replica-overrides-and-retired-parameters.md) and [issue #202](https://github.com/opsmill/styrmin/issues/202).
_Avoid_: "scale override", "replica parameter", "replicas setting".

**Affinity term**:
One entry in the `required` or `preferred` list of the `pod_affinity`, `pod_anti_affinity` or `node_affinity` block of a `scheduling` config (`AffinityTerm`; a `preferred` entry adds a `weight`). A node affinity term selects nodes by a `label_selector`. A pod affinity or pod anti-affinity term selects the pods that a **component**'s pods are placed near or away from, by a `label_selector` or by a **deployment reference**. Operators write terms in an **environment**'s config and a **deployment**'s config; a component's terms come from the component definitions of the **driver version**, which `deploy` and `updateDeploymentVersion` copy. The levels merge as [ADR-033](dev/adr/0033-scheduling-merge-semantics.md) describes. An error about a term that names a deployment gives the term's path, such as `deployment.config.scheduling.pod_affinity.required[0]`.
_Avoid_: "affinity rule" (the wording of #492 and #508), "scheduling rule", "affinity constraint".

**Deployment reference**:
The `deployment_ref` of a pod affinity or pod anti-affinity **affinity term**. It names another **deployment** of the same **environment** and can narrow the selection to some of that deployment's **components** (`components`). A write can give `deployment_id` or `deployment_name`; Styrmin replaces a name with the id of the deployment that has that name before it saves the config, so the stored reference and the config read back give `deployment_id` only. Each **reconciliation** resolves the id to the label selector `styrmin/deployment_id=<id>`, so a rename of the named deployment changes no stored reference and restarts no pod. A write that names a deployment the environment does not have, or a **tombstoned deployment**, is refused with `VALIDATION_ERROR` and the term's path, and `createEnvironment` refuses every deployment reference, because a new environment has no deployment. After the named deployment is deleted, every later update or redeploy of the deployments that the term applies to fails with the deleted deployment's last name and `deleted: true`, until the term is written again. An **environment clone** points the copied references at the **counterpart deployments**; an **environment restore** writes the captured config back as captured. A term from a driver version can give only a name, which is looked up each time the driver version's definitions are copied. See [ADR-075](dev/adr/0075-deployment-references-stored-by-id.md) and [`dev/guides/pod-scheduling.md`](dev/guides/pod-scheduling.md#affinity-by-deployment-reference).
_Avoid_: "deployment ref" in prose (fine in code), "affinity target", "deployment link".

### Recorded intent and kubernetes

**Recorded intent**:
The flow of direction from **server** to **agent**: GraphQL → service → **Task** → **Prefect** flow → **StyrminDeployment** CRD → **operator** → Kubernetes. The **server** never calls the **agent** directly.
_Avoid_: "command", "RPC", "push" (the agent pulls).

**StyrminDeployment** (CRD):
Styrmin's primary Custom Resource Definition. Carries the embedded **GlobalContext** in `spec` and is the **operator**'s single source of truth about what should be running. Watched by the **kopf operator**. Its `status.instanceId` names the **instance** whose `spec.instanceId` the operator's create, update or resume handler last acted on (written also when the handler fails), so it changes only once the operator has picked up a new spec; `spec.instanceId` is the instance of the last **flow** that wrote the StyrminDeployment, which is the instance with the highest **instance sequence** among the flows that have run. The `styrmin.io/instance-sequence` annotation holds that sequence; Styrmin manages it and users must not edit it. `status.rolloutStartedAt` is when the current rollout started, and the readiness timeout counts from it.
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
The workflow engine. Hosts a **Prefect server** (UI on port 4200) and **Prefect workers**. The internal flows, such as `apply_state`, `run_job` and the backup and restore flows, run on the work pool `styrmin-work-pool`, which the `task-worker` of the server chart polls. The flows that act on the cluster, such as `create_instance_crd`, and the driver **actions** run on the work pool `user-work-pool`, which the **agent**'s **Prefect worker** polls.
_Avoid_: "celery" (we are not Celery), "queue".

**PrefectManager**:
The service in the **server** that wraps the Prefect SDK — submits flows, manages work pools, registers user actions.
_Avoid_: "prefect client", "workflow manager".

**Flow / Prefect flow**:
A unit of orchestration submitted to Prefect (`CREATE_INSTANCE`, `UPDATE_INSTANCE`, `UPGRADE_INSTANCE`, `DEPLOYMENT`, …). Each **task** record tracks the lifecycle of one **flow run**.
_Avoid_: "job", "workflow" alone when it could be misread, "pipeline".

**Task** (database record):
A `Task` row tracking one asynchronous operation: `status`, `type`, optional `message`, optional `prefect_flow_run_id`, the optional **instance** it rolls out (`instance_id`), and the optional hook **step** that started it (`started_by_step_id`). A **reconciliation** stores the type of the operation its caller starts (`create_instance`, `update_instance`, `upgrade_instance`, `stop_components`, `start_components`); rows from before [issue #2](https://github.com/opsmill/styrmin/issues/2) keep `noop`. `Task.status` follows only the Prefect flow run; a `delete_deployment` task runs no flow and is created with the status `success`. Users view the **task result**. Distinct from Prefect's in-process `task` primitive.
_Avoid_: when referring to Prefect's primitive, qualify as "Prefect task" — never let "task" alone refer to it.

**Step**:
One unit of work inside a **task**, a backup or a restore, recorded so users can view it: name, status (`pending`, `running`, `succeeded`, `failed`, `superseded`), start time, end time, attempt count, the error of each failed attempt, and the end of the command output when a command fails. One run of a **hook**'s **mode** is one step (e.g. "Run the upgrade pre-hook"); each **operator** phase is one step (e.g. "Install or upgrade the HelmRelease"); a restore has up to three steps, and the restore of an **environment clone** up to four, because a failed step ends the restore before the next step starts, and a backup has one step per **component**. A step is `superseded` when a later **task** of the same **deployment** interrupted the operator phase it waited for. Created and changed only by the step recorder (`services/steps/recorder.py`), which server code and INTERNAL **flows** call directly, USER flows and **actions** reach through `recordStep` with the **action token**, and the **status reporter**'s reports reach through the operator phase history. Ordered by start time, pending steps last. See [issue #2](https://github.com/opsmill/styrmin/issues/2) and [ADR-060](dev/adr/0060-steps-and-derived-task-result.md).
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
- A **counterpart deployment** receives its data through a **cross-target restore** of the source deployment's **constituent backup**.
- An **affinity term** can name another **deployment** of the same **environment** through a **deployment reference**, which stores that deployment's id.
- An **environment** has at most one **dedicated ingress controller** that is not **tombstoned**; it is an internal **deployment** of that environment.
- The **server** never calls the **agent** directly — direction flows through **recorded intent**.
- An idempotent system: a converged **deployment** produces no diff, no plan, no **flow** — by construction.

## Flagged ambiguities

- **"Driver"** alone — qualify as **application driver** on first use in any document. Bare "driver" is fine after that in the same document.
- **"Version"** — could mean **driver version** or **application version**. Always qualify.
- **"Service"** — could mean **Styrmin service** (driver-declared, → `DeployedService`), the backend **service layer**, or Kubernetes' built-in `Service` object. Qualify when ambiguous.
- **"Task"** — `Task` database row tracking an async operation, **not** Prefect's in-process `task` primitive. When referring to Prefect's primitive, write "Prefect task".
- **"Hook"** vs **"mode"** — **hooks** (`setup`, `upgrade`) are lifecycle slots; **modes** (`pre`, `core`, `post`) divide a hook. Do not interchange.
- **"Hook"** vs **"Helm hook"** — a **hook** is Styrmin's lifecycle slot for **actions**; a **Helm hook** is a chart resource annotated `helm.sh/hook`. Write "Helm hook" for the chart resource.
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
