# ADR-090: Styrmin Builds the Ingress of an External Service

**Status**: Accepted
**Date**: 2026-11-10
**Source**: [issue #598](https://github.com/opsmill/styrmin/issues/598);
[specs/033-service-ingress-override/](../../specs/033-service-ingress-override/) (spec, plan,
[research](../../specs/033-service-ingress-override/research.md) D-001 to D-014,
[data model](../../specs/033-service-ingress-override/data-model.md),
[contract](../../specs/033-service-ingress-override/contracts/graphql-and-manifest.md),
[end-to-end evidence](../../specs/033-service-ingress-override/e2e-evidence.md))
**Supersedes**: [ADR-071](0071-ingress-class-set-by-post-render.md) in part. The premise that every
Ingress of an application is rendered by its chart and receives its class by the post-render patch
no longer holds for a service that its driver declares `scope: external`. See
[Superseded part of ADR-071](#superseded-part-of-adr-071).
**Amends**: [ADR-005](0005-ordered-phase-deployment-sub-handlers.md) (the teardown also deletes the
Ingresses that Styrmin builds).
**Related**: [ADR-022](0022-compute-service-fqdns-at-runtime.md) (one function computes the FQDNs),
[ADR-029](0029-config-additions-via-baseconfigsection-no-migration.md) (a config addition needs no
migration), [ADR-065](0065-apply-writes-config-with-the-version.md) (`styrminctl apply` writes the
config with the version), [ADR-070](0070-replica-overrides-and-retired-parameters.md) (the replica
override that the service ingress override follows, and differs from on a driver version change),
[ADR-073](0073-kubernetes-objects-named-and-found-by-record-id.md) (see
[Relation to ADR-073](#relation-to-adr-073)). User pages:
[Service ingress overrides](../../docs/docs/concepts-and-architecture/service-ingress-overrides.md)
and [Migrate a driver whose external service renders its own Ingress](../../docs/docs/drivers/migrating-external-service-ingress.md).

## Context

A Helm chart rendered the Ingress of each service of an application, and Styrmin patched every
Ingress of the release after the chart rendered, with one ingress class and one set of annotations
([ADR-071](0071-ingress-class-set-by-post-render.md)). The patch targets `kind: Ingress` with no
name, so Styrmin could not tell which Ingress belongs to which service. The `scope` of a service
was documented as the setting that decides exposure, but no code used it
([spec](../../specs/033-service-ingress-override/spec.md), "Problem").

An operator therefore could not publish one service of a deployment differently from the others.
On 2026-11-09, on an OpsMill public sandbox deployment, the task manager of Infrahub was published
on a public address and answered a health request without a login
([issue #598](https://github.com/opsmill/styrmin/issues/598)).

Other routes were considered and rejected in
[research.md](../../specs/033-service-ingress-override/research.md) (table at the top):

- A Kustomize patch that targets one Ingress by name or label. The patch has no name today, and the
  Infrahub server Ingress carries no component label, so a label selector cannot find it.
- A change to each application chart so that it labels its Ingresses by component. Styrmin does not
  control third-party charts, and the timeline depends on their maintainers.

## Decision

### 1. Styrmin builds one Ingress for each external service, and the chart renders none for it

`IngressUtility.build_resources`
([ingress.py](../../backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py))
returns one Ingress for each service of the deployment that the driver declares `scope: external`
and `kind: http` or `kind: https`. Every deployment already has the `ingress` utility
(`DEFAULT_UTILITY_KINDS`), and the Prefect flow and the operator call the same builder, so both get
the same objects (research D-001).

- The backend is the ClusterIP Service of the service, named by its resolved name, on the declared
  port. Each rule has the path `/` with `pathType: Prefix`.
- Styrmin writes no `spec.tls` (FR-007). Whether the Tailscale operator needs one is not known
  (research D-011).
- A service of kind `tcp` or `udp` gets no Ingress, even when it is external, because an Ingress
  cannot route it. The spec records this as a clarification of the PRD, not as something the PRD
  states.
- A service that the driver declares `internal` keeps today's behavior: a chart renders its
  Ingress, and the post-render patch of ADR-071 applies to it.
- A driver version that declares a service `external` must not render an Ingress for it. A chart
  Ingress for the same service gives two Ingresses on one host. This is the breaking change in
  [Consequences](#consequences).

### 2. The Ingress is named and labeled by the driver service name

The name is `styrmin-svc-<driver service name>`. The labels are `styrmin.io/service-name` (the
driver service name), the three labels that `UtilityResourceBuilder` adds to every utility
resource (`app.kubernetes.io/managed-by`, `styrmin.io/utility-kind` and
`styrmin.io/release-reference`; research D-005, test `test_name_namespace_and_labels` and
`test_the_ownership_labels_are_added_by_the_utility_builder`), and the labels that the post-render
patch gives every object of a chart, `styrmin/environment_id` and `styrmin/deployment_id`, built from
`context.labels` (test file `test_service_ingress_labels.py`). A dedicated ingress controller starts
with `--providers.kubernetesingress.labelselector=styrmin/environment_id=<environment id>`, so it
serves an Ingress only with the first of them. The id of the `DeployedService` row
is not used, because the row is deleted and created again on a driver version change and on a
service name override ([Relation to ADR-073](#relation-to-adr-073)).

### 3. The override is stored in the deployment config, with no database column

`DeploymentConfig.services` ([config.py](../../backend/styrmin_backend/context/models/config.py))
maps a driver service name to a `ServiceConfigBlock` with `ingress_class` and `fqdn_suffix`. It
parallels `components`. A block with both fields empty is not stored, and a config without the
block dumps as before, so the stored config of a deployment without an override is unchanged
(research D-004). `git diff origin/develop --stat -- backend/styrmin_backend/db` lists no file, so no
Alembic revision ships with this change. The final check of that is a task of the specification
(T063), not part of this record.

- The key is the driver service name, because a user can change the resolved name with a service
  name override.
- `ingress_class` must be a Kubernetes object name (a DNS-1123 subdomain), and `fqdn_suffix` must
  be a DNS name. The cluster, environment and deployment settings have no such check. The override
  is the one new input, so it is the one that is checked, and the frontend repeats the checks
  (`lib/ingress-class.ts`, `lib/fqdn-suffix.ts`).
- With an override, the Ingress has the class fields and the readable host in the override suffix.
  It has none of the entry-point, external-dns, Cloudflare or allow-list annotations (FR-004).
  A deployment's `ip_whitelist` therefore does not apply to an overridden service, because the
  allow-list is a Traefik middleware (FR-005).
- With a dedicated ingress controller, an overridden Ingress gets the override class fields instead
  of the controller rule of ADR-071 decision 1 (FR-008).
- The write surfaces are the manifest (`spec.config.services`), the GraphQL input
  `DeploymentConfigInput.services` (a list of `ServiceConfigInput`, flattened to the dict, with
  `DUPLICATE_SERVICE_NAME` for a repeated name) and the UI. The update replaces the whole stored
  config, so a service that is missing from the list loses its override (research D-009).

### 4. The address rule

Every external service has the readable host `<resolved service name>-<environment name>.<suffix>`,
computed by the one function of ADR-022 (`compute_service_address` in
[fqdn.py](../../backend/styrmin_backend/context/fqdn.py)). The application address
`<app name>-<deployment id>.<suffix>` goes only to the first service that the driver declares, and
only when that service is external and has no override (research D-003).

The PRD gave the application address to "the first external service that the driver declares".
In the `infrahub` driver that is `task-manager`, while the chart Ingress of the `infrahub` service
already uses the application address as its host, so two Ingresses would claim one host. The rule
above avoids this with the order of `spec.services`, which the driver author controls. Simon
AURA--SCUSSEL confirmed it on 2026-11-10 in the session that prepared the specification (spec FR-002;
the specification says that the comment on issue #598 did not record it yet).

The override replaces the suffix of the readable host only. The application address keeps the
resolved suffix.

### 5. Styrmin refuses what it cannot build, and refuses a version change that would drop an override

[`services/service_ingress/`](../../backend/styrmin_backend/services/service_ingress/validator.py)
checks the config on `deploy`, `updateDeployment` and `updateDeploymentVersion`, which `apply`
calls, against the driver version that the deployment is bound to after the write. It runs before
any task, flow run or pod change. Every error is a `ServiceError` that names the service:

| Code | When |
|------|------|
| `UNKNOWN_SERVICE_INGRESS_OVERRIDE` | An override that is added or changed names a service that the driver version does not declare. |
| `SERVICE_INGRESS_NOT_BUILT` | An override that is added or changed names a service that is not `scope: external`, or is external with kind `tcp` or `udp` (FR-009). |
| `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED` | A driver version change removes the service, makes it internal, or makes its kind `tcp` or `udp` while an override is stored and not cleared in the same write (FR-010). |
| `DUPLICATE_SERVICE_NAME` | The `services` list of the input has the same name twice. It is raised when the list is flattened, before the validator runs. |

This differs from ADR-070 on purpose. For a replica override on a component that the target version
removes, Styrmin keeps the override as an orphan, which is harmless. An ingress override on a
service that Styrmin no longer builds an Ingress for would stop applying without notice, so Styrmin
refuses the change. A request that clears the override passes (research D-008).

### 6. The operator creates, restores and deletes the built Ingress

- `list_managed_resources` and `delete_kubernetes_resource`
  ([reconciler.py](../../backend/styrmin_backend/operator/reconciler.py)) handle `Ingress`, and so
  does `apply_kubernetes_resource`
  ([primitives.py](../../backend/styrmin_backend/agent/service/kubernetes/primitives.py)).
  Without the branch in the last one, the apply went down the custom resource path and built the
  plural `ingresss`, and the API server returned 403 (e2e-evidence, run 1).
- The periodic loops of the HelmRelease timer and of the StyrminDeployment timer reconcile
  `Ingress` with the Services and Secrets. Kopf drift handlers for `Ingress` update and delete exist
  ([utility_resources.py](../../backend/styrmin_backend/operator/handlers/utility_resources.py)).
- The drift handlers and the listing select only objects that carry `managed-by=styrmin` and the
  release reference. A chart Ingress carries neither label (comment in `utility_resources.py`), so
  Helm keeps it and the operator never lists or deletes it.
- The teardown deletes Ingresses and then Services in its second step
  ([styrmin_deployment.py](../../backend/styrmin_backend/operator/handlers/styrmin_deployment.py)).
- The cluster role of the agent already allows every verb on `ingresses`
  ([roles.yaml](../../helm/agent/templates/roles.yaml), research D-002), so no RBAC rule changed.

### 7. The service address reaches driver templates and the UI

`services.<driver service name>` in a driver template gains `ingress_class` and `overridden`, and
`human_readable_fqdn` uses the override suffix. `DeployedService` in GraphQL gains `ingressClass`,
`ingressClassOverridden` and `fqdnSuffixOverridden`, `Deployment` gains `serviceIngressOverrides`,
and `humanReadableFqdn` uses the override suffix (FR-006). A service uses the override of the
deployment that owns it, not of the deployment whose context is built
([context.py](../../backend/styrmin_backend/services/context.py)).

### 8. Three example drivers change in the same release

`infrahub` (version 5 to 6) and `infrahub-enterprise` (version 4 to 5) declare `task-manager`
`scope: external` and switch the chart's Prefect Ingress off. Their `infrahub` service stays
`internal`, and its chart Ingress keeps the application address. `generic-app` (version 1 to 2)
stops rendering its own Ingress (FR-012, FR-013).

## Relation to ADR-073

ADR-073 says that a Kubernetes object that Styrmin creates for a record is named after the record's
id, carries a label with that id, and is found by that label or by a name built only from the id,
never by a name built from a field that a user can change.

This Ingress does not follow the wording. It is an exception, for these reasons, which come from
[research.md D-005](../../specs/033-service-ingress-override/research.md) and the code:

- No record has a stable id that fits. The `DeployedService` row is deleted and created again by
  `reconcile_services_on_upgrade` on every driver version change, on every service name override
  and when a restored instance is adopted, so each time it gets a new `uuid4`. A name built from it
  would change with each of those.
- The name is built from the namespace of the deployment, `styrmin-<deployment id>`, and the driver
  service name. The driver service name is set by the driver author, is unique inside one driver
  version, and is a DNS label of at most 63 characters, so the name is a valid Ingress name.
  A user cannot change it. A service name override changes `resolved_name` only, and the unit test
  `test_name_namespace_and_labels` builds the Ingress of a service with a different resolved name
  and checks that the Ingress name and label do not change.
- Styrmin finds the object by the two labels `managed-by` and `release-reference` and compares names
  with the desired set. The `release-reference` label is `styrmin-<deployment id>` for an ordinary
  deployment. For the counterpart deployment of an environment clone it is the Helm release name of
  the source deployment ([operator.md](../knowledge/agent/operator.md#name-of-the-cr-and-the-release-reference)).
  `styrmin.io/service-name` holds a driver service name, not an id.

What the exception keeps of the purpose of ADR-073: a rename by a user changes nothing in the
cluster, and Styrmin finds the object again for its whole life. What it does not keep: a driver
version that renames or removes a service gets a new Ingress under the new name, and the operator
deletes the old one, because the old name is no longer in the desired set. ADR-073 already allows
the ClusterIP Service, which is the backend of this Ingress, to keep the name that the user asked
for. Whether the reviewers accept this reading is open, and research D-005 says the same.

## Superseded part of ADR-071

ADR-071 Context says that the ingress utility sets the class "on every Ingress", and decision 1
says that the removal patch "applies to every Ingress of the release". Its Consequences say that
driver templates do not need to set the Ingress class. These statements assume that a chart renders
every Ingress of an application. For a service that its driver declares `scope: external`, that is
no longer true: the driver renders no Ingress, and Styrmin builds it.

What this record supersedes: that assumption, for external services. The class of a built Ingress
without an override follows the same rules as the patch (no `spec.ingressClassName` and the
controller annotation with a dedicated ingress controller; both fields set to the resolved class
without one; nothing when no class resolves), through the same function,
`build_ingress_settings`, that feeds the patch. With an override, the override class replaces the
controller rule (decision 3).

What stays: decision 1 (the strategic merge patch), decision 2 and decision 3 of ADR-071 for every
Ingress that a chart renders, which are the Ingresses of internal services and the Infrahub server
Ingress. ADR-071 is marked "superseded in part" and points here.

## Consequences

- A team can publish one external service with another ingress class and FQDN suffix, with a
  manifest, the API or the UI, and the deployment's other Ingresses stay as they are. On a
  disposable vCluster, the end-to-end test changed only the `styrmin-svc-task-manager` Ingress
  (class `tailscale`, host `task-manager-test-environment.tailnet.example.ts.net`, the class
  annotation only), left the chart Ingress `styrmin-infrahub-ingress` with the same
  `resourceVersion`, and restored the first state when the override was cleared (API and UI
  variants). The refusals test saw no new task, no changed pod and the stored override still in
  place. The tests are listed in
  [e2e-evidence.md](../../specs/033-service-ingress-override/e2e-evidence.md).
- A driver that declares `scope: external` and also renders its own Ingress for that service now
  gets two Ingresses on the same host. This is a breaking change of the driver format, which the
  beta policy allows with release notes and a migration guide
  ([migration guide](../../docs/docs/drivers/migrating-external-service-ingress.md), changelog
  fragment `598.changed.md`).
  - The effect starts when a deployment runs a Styrmin release with this change, not only at a
    driver version change. A deployment of the stored `generic-app` version 1 gets a second Ingress
    at its next reconcile. Simon AURA--SCUSSEL accepted this without a guard on 2026-11-10, because
    Styrmin cannot tell whether a chart renders an Ingress without rendering the chart (research
    D-012). A downgrade to such a driver version has the same effect.
  - An apply error on an Ingress now fails the deploy flow. An ingress controller that rejects an
    Ingress with a host and path that another Ingress already has could therefore fail the deploy
    flow of a deployment that gets the second Ingress. This is plausible and not verified: no
    controller that rejects a duplicate was tested.
  - The three drivers of this repository changed in the same release, so for them the Styrmin
    upgrade and the driver version upgrade come together. The end-to-end test of `generic-app`
    version 2 found one Ingress, `styrmin-svc-app`. A run of the same test before the driver change
    (version 1, on the same Styrmin code) found two, `styrmin-app` and `styrmin-svc-app`
    (e2e-evidence). An upgrade of a running `generic-app` deployment from version 1 to 2 was not
    tested.
  - How many drivers outside this repository declare `external` and render their own Ingress is
    not known.
- A deployment's `ip_whitelist` does not apply to an overridden service.
- An override that Styrmin cannot honor fails with an error that names the service, and a driver
  version change that would drop an override fails the same way, so nothing changes in the cluster.
- Not verified:
  - Traffic through a controller of the override class. No ingress controller of class `tailscale`
    runs in the test cluster, so nothing shows that an overridden host answers through it. The
    end-to-end tests do send requests through the dedicated Traefik: the default host of
    `task-manager` answers 200 without an override and after it is cleared, the overridden host
    answers 404 through it, and the hosts of the `generic-app` Ingress answer 200.
  - Whether the Tailscale operator needs `spec.tls` or ignores the host in the rules. Not known.
  - The upgrade of a running Infrahub deployment from the chart Prefect Ingress to the built one
    (research D-013). Measured on a local vCluster with a dedicated Traefik, by upgrading
    `infrahub-enterprise` from driver version 4 to 5 and sending one request per second to the
    Prefect UI host through the controller. With the operator pass every 5 seconds (two runs), no
    request failed (0 of 112 and 0 of 118). With the default pass of 60 seconds (two runs), the host
    answered HTTP 404 for about 12 seconds (12 of 126 requests) and about 7 seconds (7 of 120). These
    are four samples on one machine, not limits: the length depends on when the operator's pass
    happens after Helm removes the chart Ingress ([e2e-evidence.md](../../specs/033-service-ingress-override/e2e-evidence.md),
    "The label defect: fix, traffic checks and the upgrade measurement repeated").
  - The first creation of the Ingress on a default install. The operator creates it through the
    HelmRelease timer, whose default interval is 60 seconds
    (`SETTINGS.operator.reconcile_interval`). In the upgrade runs at that interval, the host
    answered again 51 and 55 seconds after the upgrade started. The creation delay without an
    upgrade was not measured.
  - In both runs with the 5-second pass, the operator deleted `styrmin-svc-task-manager` a few
    seconds after it built it and built it again. The chart Ingress still served the host, so no
    request failed. The cause was not investigated.
  - Backup, restore and environment clone of an environment that has built Ingresses. Not known.
  - The CI matrix. The tests ran on one machine.

## Alternatives considered

- **Patch the chart Ingress by name or label.** Rejected: see Context.
- **Name the Ingress after the `DeployedService` id.** This was the first version of the decision.
  Rejected after reading `reconcile_services_on_upgrade`: the id is new after each run.
- **The literal PRD rule for the application address.** Rejected: two Ingresses would claim one
  host in the `infrahub` driver.
- **A new driver field that names the service of the application address.** Rejected: it changes
  the driver format, and Styrmin's own code solves the problem.
- **Drop an override on a driver version change, with a warning.** Rejected: FR-010 forbids a
  silent drop.
- **Keep the override as an orphan, as ADR-070 does for replicas.** Rejected: the override would
  stop applying without notice.
- **A guard against the second Ingress of an existing deployment.** Not built: Styrmin cannot tell
  the chart's Ingresses without rendering it (research D-012).

## Open points

Each point has its source. None blocks this decision.

- The first version of the builder gave the Ingress only the label `styrmin.io/service-name` (and
  the ownership labels). A dedicated ingress controller selects Ingresses by `styrmin/environment_id`,
  so it did not serve the Ingress, and the Prefect UI host answered HTTP 404 after an upgrade of a
  running Infrahub deployment, until the label was added. A traffic measurement found it
  ([e2e-evidence.md](../../specs/033-service-ingress-override/e2e-evidence.md), "T062"). The tests
  written before then read Kubernetes objects only, so they passed: no test sent a request through
  the controller. The builder now sets `styrmin/environment_id` and `styrmin/deployment_id`, a unit
  test reads the selector from the controller's chart values template, and the end-to-end tests send
  requests through the dedicated Traefik. No release contains the first version of the builder.
- `compute_diff` compares `spec` only (`_normalize_for_comparison` in
  [reconciler.py](../../backend/styrmin_backend/operator/reconciler.py)), so a change of a label or an
  annotation alone does not update an Ingress that already exists. A later change to the labels of
  the built Ingress needs a change of `spec`, or the operator will not write it. Read from the code, not run.

- The operator creates the built Ingress through the HelmRelease timer, not through the services
  phase. `_is_service_or_middleware` and `execute_phase_services`
  ([pipeline.py](../../backend/styrmin_backend/operator/pipeline.py)) do not include `Ingress`.
  The first creation therefore waits for a timer run, up to the reconcile interval. The decision
  not to change it was written before commit `a0885121`, with the reason that the two timers would
  rewrite the object (e2e-evidence, "First creation of the Ingress: operator pipeline"). That
  commit gave both timers one release reference, so the reason has not been checked again.
- The HelmRelease that the StyrminDeployment pipeline creates has no `styrmin.io/release-reference`
  label. Commit `a0885121` made the HelmRelease timer use `context.instance.release_reference` when
  the label is empty, because the two timers otherwise wrote the same objects with different labels
  every few seconds. The kopf drift handlers for Ingress, Service, Secret and NetworkPolicy select
  a HelmRelease by that label, so they log that they found none and do nothing. Drift correction
  therefore rests on the timers. This comes from reading the code in the evidence file; the log
  lines were not counted.
- After that commit, Services were still written about every 5 seconds in the end-to-end runs
  (23 to 37 resource versions per run) with a stable label, and the Ingress was not. The cause is
  not investigated.
- `on_helmrelease_delete` passes the empty label of the HelmRelease to `cleanup_operator_resources`,
  so after commit `a0885121` it selects none of the operator-managed NetworkPolicies, which carry
  the real reference. The teardown deletes them by the real reference, and the runs left nothing
  behind. A HelmRelease deleted alone was not tested.
- `apply_utility_resources` logged "the CRD type may not be installed yet" for every failed Ingress
  apply, which hid the 403 of the first end-to-end run. An Ingress error now fails the flow. Every
  other kind keeps the behaviour from before this change: an error is logged and skipped, whatever
  the status. The log now carries the status and the reason, and the hint that the kind may not be
  installed only for status 404. A custom resource other than an Ingress, for example a Traefik
  Middleware, that the cluster refuses with 403, 422 or 500 is therefore still skipped, and the
  deployment reports success without it. That behaviour exists before this change and is left open.
- `DeploymentResource.scale` sends `components` and, since this change, the stored `services`. It
  still clears every other stored config key (a probe showed `ip_whitelist` and `env_vars` cleared).
  That behavior exists before this change.
- The text "omitting a field leaves the persisted state untouched" is wrong for `updateDeployment`:
  a write with at least one config field replaces the whole stored config
  (`deployment.config = deployment_config` in `update_deployment`, and the functional tests
  `test_service_ingress_propagation.py` and `test_sdk_scale_keeps_service_overrides.py`). The text
  is in the description of `UpdateDeploymentInput` in `schema.graphql` and in the module docstring
  of `api/definitions/deployment/inputs.py`, and ADR-018 repeats it ("omitted/null field = do not
  touch"). The Python SDK docstring of `DeploymentResource.update` and
  [`dev/knowledge/backend/api.md`](../knowledge/backend/api.md) are corrected. The GraphQL description and
  ADR-018 are not changed here, because a schema description change needs regeneration and approval.
- The Tailscale `spec.tls` question and the optional `tls` hosts field are open
  (research D-011).
- A class-only override on the first declared service removes the application address from its
  Ingress (it follows research D-003). The owner of the feature decides whether that is wanted. The
  documentation states the effect.
- No warning is shown or returned when a deployment sets `ip_whitelist` and a service gets an
  override. The overridden Ingress has no allow-list annotation, so the allow-list is not applied to
  that service (FR-004, FR-005). The help text of the override fields and the entry in the Review
  dialog state that. A write-time warning or refusal is a candidate for a later change.
- `_service_overrides_by_deployment` in `services/context.py` reads every peer deployment with
  `uow.deployments.find` on each context generation, so the cost grows with the number of
  deployments. It was not measured.
- With `dedicated_ingress` on a cluster that has a default IngressClass, the API server may add
  `spec.ingressClassName`, and the spec comparison would then replace the Ingress on each pass.
  This is plausible and not verified.
- `list_managed_resources` returns no Ingress when the list call fails, so the operator would create
  the desired Ingresses again in each cycle and never delete a stale one. The other kinds have the
  same pattern. The Ingress drift handlers return without a log when the release-reference label is
  missing.
- `_deployment_labels` leaves out a label that has no value. A missing `styrmin/environment_id`
  would make a dedicated controller ignore the Ingress again, and nothing logs it.
- The `ingress_class` key of the `deployed_services` entries is not read by any code, and the
  `settings or build_ingress_settings(...)` fallback in the builder cannot run. Some unit tests still
  carry `importlib` indirection and "planned symbol" comments, four test files repeat a context
  fixture, and two frontend helpers (`servicesWithInvalidSuffix`, `servicesWithInvalidClass`) are twins.
- The suffix rule and the ingress class rule exist in Python and in TypeScript with no shared test
  cases. Twenty-one edge cases were compared by hand. `deployed_services` is an untyped
  `list[dict[str, Any]]`; the builder now reads it with `.get`, and a typed model is a larger change.
- Not tested: the unit test that joins `compute_service_address` and the builder; the read of an
  override back through the CLI or a manifest command; Tailscale (SC-005 needs a Tailscale operator).
  FR-005, FR-011 and FR-014 are covered by documentation only.
- The `ValueError` for a missing FQDN suffix reaches Prefect as a plain exception. The review fixes
  change its text only.
- The spec does not say what happens when the first declared service is external with kind `tcp` or
  `udp`. Today no Styrmin-built Ingress carries the application address. A unit test pins that
  behavior.
- The description of the `services` field of `DeploymentConfigInput` (shared by `UpdateDeploymentInput`)
  still lists only "removes or declares `internal`" for `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED`.
  It was not changed, because the description of `UpdateDeploymentInput` is not changed here. The
  description of `ServiceConfigInput.name` and the contract name the `tcp` and `udp` case.
