# Research: Service ingress override

**Feature**: [spec.md](spec.md) | **Date**: 2026-11-10

Every statement below was read in the repository at commit `5abe5647` (Styrmin 0.1.58) unless it is marked "not verified".

## Constrained third-party dependencies (planning directive)

The gap: Helm charts render the Ingresses of a deployment, and Styrmin cannot tell which Ingress belongs to which service. The dependencies involved are the application Helm charts, Kustomize (the post-render patches) and, for the override class, the Tailscale operator.

| Route | Result |
|---|---|
| Extension mechanism of Kustomize: patch a single Ingress by name or label selector | Rejected. The patch for `kind: Ingress` has no name today ([ingress.py](../../backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py)). A name or label target needs knowledge of each chart. The issue's local reproduction shows that the Infrahub server Ingress carries no component label, so a label selector cannot find it ([#598](https://github.com/opsmill/styrmin/issues/598)). |
| Extension mechanism of the charts: chart values that switch an Ingress off | Used where it exists. The `infrahub` chart exposes `prefect-server.ingress.enabled` ([values.j2.yml](../../driver/examples/infrahub/values.j2.yml) line 66-71), so the new driver version turns it off (FR-013). |
| Upstream contribution: ask each chart to label its Ingresses by component | Rejected for this release. Styrmin does not control the charts of third-party applications, and the timeline depends on their maintainers. |
| Styrmin builds the Ingress itself from the driver's `services` block | Chosen. It follows the direction agreed in the review of [#598](https://github.com/opsmill/styrmin/issues/598), and it needs no change to any chart except to switch its own Ingress off. |
| Tailscale operator: does it need `spec.tls`, does it ignore the rule host | Not known. The Tailscale documentation does not say. Nothing in Styrmin can fill this gap. FR-007 writes no `spec.tls`, and a test on a real operator settles it (see D-011). |

## D-001: Where the Ingress is built

- **Decision**: `IngressUtility.build_resources` returns the Ingress objects, next to the Middleware, Secret and NetworkPolicy objects it already returns.
- **Evidence**: `DEFAULT_UTILITY_KINDS = [UtilityKind.INGRESS]` ([utilities.py](../../backend/styrmin_backend/services/utilities/utilities.py) line 9), so every deployment already has the `ingress` utility. `UtilityResourceBuilder.build` adds the `managed-by`, `utility-kind` and `release-reference` labels to every resource it returns ([builders/utility.py](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/utility.py)). The Prefect flow `_apply_utility` and the operator function `build_desired_resources` both call the same builder, so both paths get the same objects.
- **Alternatives rejected**:
  - A new utility kind (for example `service-ingress`): needs a new `UtilityKind`, a factory entry and an auto-add in `generate_context_from_deployment`, with no gain, because the `ingress` utility is always present.
  - Put the logic in `ServiceDiscoveryUtility`: it builds ClusterIP Services only when a deployment has services, and it is the wrong owner for Ingress annotations and classes.
- **Consequence**: the existing patch builder `build_app_post_rendering_patches` stays as it is for chart Ingresses (ADR-071), and it must not touch a Styrmin-built Ingress, because that one is not in the Helm release. The patch applies only to objects that the chart renders, so there is nothing to exclude. This is verified by FR-004 and SC-002 tests.

## D-002: Operator and Prefect handling of the new kind

- **Decision**: add `Ingress` to the kinds that the operator lists, deletes and reconciles.
- **Evidence**: `list_managed_resources` lists only NetworkPolicy, Service and Secret; `delete_kubernetes_resource` deletes only those and CRDs ([reconciler.py](../../backend/styrmin_backend/operator/reconciler.py) lines 150-190 and 277-360). The periodic reconcile loops iterate over `("Service", "Secret")` and `("NetworkPolicy", "Secret", "Service")` ([helmrelease.py](../../backend/styrmin_backend/operator/handlers/helmrelease.py) line 342, [styrmin_deployment.py](../../backend/styrmin_backend/operator/handlers/styrmin_deployment.py) lines 991 and 1162). Kopf drift handlers exist per kind in [utility_resources.py](../../backend/styrmin_backend/operator/handlers/utility_resources.py) (NetworkPolicy, Service, Secret, Middleware).
- **Why it is needed**: without it, an Ingress that Styrmin stops building (an override moved a service to internal, or a driver version made it internal) is never deleted, and a deleted or edited Ingress is never restored. FR-001 requires create, update and delete with the deployment.
- **RBAC**: the agent chart grants `*` on `ingresses` in `networking.k8s.io` ([roles.yaml](../../helm/agent/templates/roles.yaml) line 202-209). Whether this role is the one the operator runs under is not verified; a task checks it.
- **Deletion with the deployment**: not verified. The namespace of a deployment is named `styrmin-<deployment id>` (ADR-073), which suggests that deleting the namespace removes the Ingress. A task confirms it with the end-to-end test of FR-001.
- **Alternatives rejected**: leave the Ingress to the Prefect apply flow alone. Rejected because the flow only applies what is desired, and the operator is what restores drift and removes stale objects for the other kinds.

## D-003: Which service gets the application address (changes FR-002)

- **Problem**: FR-002 of the PRD gives the application address (`<app name>-<deployment id>.<suffix>`) to "the first external service that the driver declares". In the `infrahub` driver the first external service is `task-manager`, because the `infrahub` service stays `internal` (FR-013). But the chart's Infrahub server Ingress already uses the application address: `hostname: "{{ services.infrahub.primary_fqdn }}"` ([values.j2.yml](../../driver/examples/infrahub/values.j2.yml) line 10; the same in `infrahub-enterprise`). `compute_primary_fqdn` takes no service, so the value is the same for every service ([fqdn.py](../../backend/styrmin_backend/context/fqdn.py)). The literal rule would give two Ingresses one host, the server's chart Ingress and the new `task-manager` Ingress. That breaks FR-013 ("the server Ingress is identical before and after") and SC-005 ("the Infrahub address still answers").
- **Decision**: the application address goes to the first service that the driver declares, and only when that service is `external`. For `generic-app` the first service is `app`, so it keeps both addresses. For `infrahub` the first service is `infrahub` (internal), so no Styrmin-built Ingress carries the application address, and the chart keeps it.
- **Why this rule**: it keeps the reason of FR-002 (no two Ingresses claim one host) and needs only the order of `spec.services`, which the driver already controls. It is a change in Styrmin's own code and needs no change to the driver format.
- **Alternatives rejected**:
  - The literal PRD rule. Rejected for the collision above.
  - A new driver field that names the service of the application address. Rejected: it changes the driver format, and a change in Styrmin's own code solves the problem (design preference for Styrmin).
  - Drop the application address from Styrmin-built Ingresses. Rejected: the `generic-app` Ingress carries it today ([values.j2.yml](../../driver/examples/generic-app/values.j2.yml) line 83-96), and the move to a Styrmin-built Ingress must keep that address.
- **Status**: this changes the wording of FR-002. Confirmed by Simon AURA--SCUSSEL on 2026-11-10 in the preparation session (not yet written on issue #598). The critique report lists it as a Must-Address finding (E1), the spec FR-002 now carries the changed rule with a note, and the alignment check records it.
- **With an override**: a service with an override suffix gets only the readable host in the override suffix. The application address uses the resolved suffix, so it stays on the service that has no override. If the first service has an override, it carries no application address (FR-004 says the override's suffix is in its hosts, and the application address is a different address). This is stated in the data model.

## D-004: Where the override is stored and its shape

- **Decision**: a `services` block in `DeploymentConfig`, keyed by driver service name, each value a `ServiceConfigBlock` with `ingress_class: str | None` and `fqdn_suffix: str | None`. It parallels `components` (`ComponentConfigBlock`).
- **Evidence**: config additions need no migration (ADR-029, cited in [ADR-070](../../dev/adr/0070-replica-overrides-and-retired-parameters.md)); `ComponentConfigBlock` is stored in `Deployment.config` under `components.<name>`. `DeploymentConfig` has `extra="forbid"`, so a key that the model does not know is rejected, which is why the block must exist.
- **Key**: the driver service name, not the resolved name. The service name override changes the resolved name, and the PRD states that it is stored as the resolved name, not in the deployment's config. A key that a user can change would break the override on a rename.
- **Resolution**: the override replaces the resolved `ingress_class` and `fqdn_suffix` for one service. Resolution order for the other services is unchanged: deployment, else environment, else cluster. The PRD says "with the deployment, environment, cluster resolution order"; the override exists only at deployment level in this release (the cluster and environment rule is out of scope).
- **Alternatives rejected**:
  - A list of `{service, ingress_class, fqdn_suffix}` rows in the config: the stored form would need de-duplication rules; a dict keyed by service name cannot hold two rows for one service.
  - Reuse `components.<name>`: a component can serve several services, and the override belongs to a service.
- **Database**: no column, no Alembic revision. Confirmed in the plan: nothing in `db/models.py` changes (`DeployedService` already has `scope`, `driver_service_name` and `resolved_name`).

## D-005: Name of the Ingress

- **Decision**: name the Ingress after the id of the deployed service record (`styrmin-svc-<deployed service id>`), and put the id on it as the label `styrmin.io/service-id`. Find it by that label or that name when updating or deleting.
- **Evidence**: AGENTS.md and [ADR-073](../../dev/adr/0073-kubernetes-objects-named-and-found-by-record-id.md) require that a Kubernetes object that Styrmin creates for a record is named after the record's id, never after a name a user can change. The resolved name of a service can be changed by a service name override, so it cannot be the Ingress name. The ClusterIP Service built today is named `resolved_name` ([service_discovery.py](../../backend/styrmin_backend/agent/service/kubernetes/resources/utilities/service_discovery.py)); that is the existing exception and is the backend of the Ingress, not its name.
- **Not verified**: whether the id of a `DeployedService` row stays the same across a driver version change and a service rename. A task checks it first. If the row is recreated, fall back to a name built from the driver service name (set by the driver author, not by a user, and unique in the namespace of the deployment).
- **Alternatives rejected**: name after `resolved_name` (breaks ADR-073); name after the host (changes with the suffix override).

## D-006: Hosts, class and annotations of the built Ingress

- **Without an override (FR-003)**: copy the rules of `IngressUtility.build_app_post_rendering_patches` into a function that returns the same annotations: `traefik.ingress.kubernetes.io/router.entrypoints`, `external-dns.alpha.kubernetes.io/hostname` (`{release_reference}-{app name}.{fqdn_suffix}`), `external-dns.alpha.kubernetes.io/cloudflare-proxied`, the allow-list middleware when `ip_whitelist` is set, `external-dns.alpha.kubernetes.io/endpoints-type` when set, and the class (`spec.ingressClassName` plus `kubernetes.io/ingress.class`). One helper feeds both the patch and the built object, so the two cannot drift.
- **Dedicated ingress controller (FR-008)**: no `spec.ingressClassName`; the annotation `kubernetes.io/ingress.class` set to `dedicated_ingress.implementation` (ADR-071 decision 1).
- **With an override (FR-004, FR-008)**: `spec.ingressClassName` and the annotation `kubernetes.io/ingress.class` both set to the override class, and none of the entry-point, external-dns, Cloudflare or allow-list annotations. Setting both class fields is how Styrmin sets the class today without a dedicated controller; whether Tailscale reads the annotation is not verified, and a duplicate of the same value is accepted by Kubernetes.
- **Hosts**: the readable host `<resolved service name>-<environment name>.<suffix>` computed with `compute_human_readable_fqdn` (ADR-022, one shared function). The application address follows D-003.
- **TLS (FR-007)**: no `spec.tls`.
- **No suffix**: the build raises the same `ValueError` as the patch does today when no suffix resolves (spec edge case).
- **Path and backend**: one rule per host, path `/`, `pathType: Prefix`, backend the ClusterIP Service of the service on its declared port. This matches the `generic-app` Ingress today. Services of `kind: tcp` or `udp` cannot sit behind an Ingress: the plan treats them as having no Ingress even when declared external. Whether the PRD intends this is not stated; the critique lists it.

## D-007: Service address data for driver templates and GraphQL (FR-006, ADR-022)

- **Decision**: extend `context/fqdn.py` with one function that returns, for one service, its effective ingress class, suffix and hosts from (resolved config, optional override, driver service list, environment name). Both call sites use it: `generate_context_from_deployment` in [services/context.py](../../backend/styrmin_backend/services/context.py) (lines 231-260) and the GraphQL resolver for `DeployedService` ([api/definitions/service/model.py](../../backend/styrmin_backend/api/definitions/service/model.py)).
- **Evidence**: ADR-022 requires FQDNs computed at runtime at every call site through `context/fqdn.py`. `ServiceReference` has `extra="forbid"` and holds `primary_fqdn` and `human_readable_fqdn`, so it needs the new fields `ingress_class` and `overridden`. The `deployed_services` entries in the context carry no `scope` today, so a `scope` key is added; the Ingress builder reads the scope and the FQDN data from them.
- **Why the template data matters**: the `infrahub` driver reads `services['task-manager'].human_readable_fqdn` for `prefectUiApiUrl` ([values.j2.yml](../../driver/examples/infrahub/values.j2.yml) line 82). With an override the value must be the override host, or the Prefect UI would call the old address.
- **Cross-deployment note**: `services` in the context is built for every service in the environment ([context.py](../../backend/styrmin_backend/services/context.py) lines 241-258), and they all use the one `fqdn_suffix` of the current deployment. A service of another deployment must use that deployment's override. This is a bug risk in the existing code that the override makes visible; the plan lists a task and a test.

## D-008: Validation and typed errors (FR-009, FR-010)

- **Decision**: a new package `services/service_ingress/` with a validator and exceptions, mirroring `services/replicas/`. Three `ServiceError` codes:
  - `UNKNOWN_SERVICE_INGRESS_OVERRIDE`: the block names a service that the target driver version does not declare.
  - `SERVICE_INGRESS_NOT_BUILT`: the service is not `scope: external` (FR-009). The message names the service and says Styrmin does not build its Ingress.
  - `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED`: a driver version change removes the service or makes it internal while an override is stored (FR-010). Raised before any pod changes.
- **Where it runs**: next to `_validate_replica_overrides` in [services/deployment.py](../../backend/styrmin_backend/services/deployment.py) (line 367 and its three call sites at 574, 908 and 1813 in the docstrings), in the same pre-check that runs before the target driver version is applied.
- **Differs from ADR-070**: for replicas an unchanged stored override on a removed component is kept (orphaned). FR-010 asks for the opposite for ingress: refuse, because an orphaned override would be dropped without notice. The validator therefore rejects whenever a stored override targets a service that the target version removes or makes internal.
- **Alternatives rejected**: drop the override on a version change with a warning (FR-010 forbids a silent drop); keep it orphaned like replicas (the operator would not know that the service is no longer published as set).

## D-009: GraphQL, SDK, CLI and manifest surface

- **Decision**: add `ServiceConfigInput { name, ingressClass, fqdnSuffix }` and a field `services: [ServiceConfigInput!]` to `DeploymentConfigInput`, next to `components`. Add matching output fields to the deployment config type and `ingressClass`, `ingressHost`, `ingressOverridden` style fields to `DeployedService` (names in the contract). Full replacement semantics, as `components` has: omitting a service clears its override.
- **Evidence**: `ComponentConfigInput` is the pattern ([inputs.py](../../backend/styrmin_backend/api/definitions/deployment/inputs.py) lines 77-200). The SDK types are generated from `schema.graphql`, and `styrminctl deployments apply` reads `spec.config` into the SDK manifest model ([deployment_manifest.py](../../python_sdk/src/styrmin_sdk/models/deployment_manifest.py)). Not verified: whether the manifest model needs a hand-written change or is fully generated; a task reads it. The issue states the cause of "unknown component keys accepted and ignored" is generated SDK models that ignore extra fields ([#598](https://github.com/opsmill/styrmin/issues/598)). That bug is out of scope, but the new `services` block must not be silently ignored by `apply`, so a test applies a manifest with an override and reads it back.
- **Governance**: GraphQL schema change, so regenerate `schema.graphql` and the SDK and frontend types, and add a propagation test (AGENTS.md, Constitution V).

## D-010: How the UI gets the services of a driver (open question 2 of the PRD)

- **Decision**: no new backend field. The two places already have the data:
  - Configuration drawer: `ConfigEditDrawer` already computes `driverServiceNames` from `deployment.deployedServices[].driverServiceName` and passes it to `ServiceOverridesSection` ([ConfigEditDrawer.tsx](../../frontend/src/components/deployment/configuration/ConfigEditDrawer.tsx) line 136 and 275-280). `DeployedService` carries `scope`, so the same list gives each service's scope.
  - Deploy form: `ApplicationDriverVersion.services: [ServiceDefinition!]!` exists in `schema.graphql` (line 90) and `ServiceDefinition` carries `scope`.
- **Consequence**: the new section lists only `external` services, so FR-009 is also prevented in the UI. The backend still rejects the request.
- **Not verified**: whether the deploy form already queries `services` on the driver version. A task reads the form query.

## D-011: Tailscale `spec.tls` (open question 1 of the PRD)

- **Decision**: write no `spec.tls` (FR-007). Record in the migration guide and the docs that the first release was not tested against a real Tailscale operator.
- **Not known**: whether the operator needs `tls` or ignores the host. A test on a real operator settles it. Not decided in this plan, and not a blocker for the other stories. SC-005 stays open for its tailnet part.
- **Alternative**: add an optional `tls` hosts field to the override now. Rejected: the PRD puts it out of scope until the test settles the question.

## D-012: Drivers outside this repository (open question 3 of the PRD)

- **Not known**: how many drivers outside this repository declare `scope: external` and render their own Ingress. This sets the size of the breaking change in FR-014.
- **Risk found in the code (R-1)**: the old driver versions already stored in a Styrmin instance include `generic-app` versions that declare `external` and render their own Ingress. After a Styrmin release that builds an Ingress for every external service, the next reconcile of such a deployment gives it two Ingresses on the same host, without any driver version change. The PRD words FR-014 as "after the upgrade" and does not say whether it means the Styrmin upgrade or the driver version upgrade. SC-003 and SC-006 cover only the drivers in this repository. The critique lists this as a question (P1). Decision by Simon AURA--SCUSSEL on 2026-11-10 in the preparation session (not yet written on issue #598): accepted, with no guard; the migration guide and the changelog state it. A mitigation inside Styrmin's own code is not found: Styrmin cannot see whether a chart renders an Ingress for a service without rendering the chart.

## D-013: Moving an existing Infrahub deployment to the new driver version

- **Not known**: the length of any interruption when the chart's Prefect Ingress is replaced by the Styrmin-built one on the same host (spec edge case). The order of the Helm upgrade and the utility apply decides it; it is measured by the end-to-end test, not assumed.

## D-014: Documentation and ADR

- **Decision**: one new ADR (number allocated at implementation; the latest is 0088) that supersedes the part of ADR-071 that says every Ingress of a release is patched, adds the rule for the application address (D-003) and the rule for refused driver version changes (D-008). Update [creating-a-driver.md](../../docs/docs/drivers/creating-a-driver.md) lines 511-520 and [ingress-and-networking.md](../../docs/docs/concepts-and-architecture/ingress-and-networking.md) lines 323-324, add a migration guide next to `migrating-replica-parameters.md`, a page for the override, a towncrier fragment, `CONTEXT.md` terms if missing, and the driver reference.
