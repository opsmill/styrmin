# Feature Specification: Service ingress override

**Feature Branch**: `sas-598-service-ingress-spec`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "https://github.com/opsmill/styrmin/issues/598#issuecomment-6763699998" (the PRD comment on issue [#598](https://github.com/opsmill/styrmin/issues/598), "feat(ingress): all services of a deployment share one ingress class and address suffix")

## Problem

An operator who deploys an application with several services cannot publish one of them differently from the others. Styrmin applies one ingress class and one set of annotations to every Ingress of a deployment, so the administration interface of an application (the task manager of Infrahub, for example) is published in the same way as its web interface. Styrmin cannot reliably tell which Ingress belongs to which service, because Helm charts render the Ingresses and Styrmin only patches them afterwards. The `scope` of a service is documented as the setting that decides exposure, but no code uses it.

Where it was seen: on an OpsMill public sandbox deployment on 2026-11-09, the task manager was published on a public address and answered a health request without a login ([#598](https://github.com/opsmill/styrmin/issues/598)).

## Direction

Styrmin builds and manages the Ingress of every service that its driver declares `scope: external`. For such a service, the operator can set an ingress class and an FQDN suffix in the deployment's config, in a manifest, through the API or in the UI. Styrmin then serves that service at the new class and address and leaves the deployment's other Ingresses untouched. A service declared `internal` keeps the behaviour it has today. The first release moves the task manager of the `infrahub` and `infrahub-enterprise` drivers, and the `generic-app` example driver, to this model.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Publish one service with a different ingress class and suffix (Priority: P1)

An operator sets an ingress class and an FQDN suffix for the task manager of an Infrahub deployment, and only that service moves. The Infrahub server service keeps its class and address.

**Why this priority**: This is the reason for the feature. Without it, the administration interface of an application stays on the public address.

**Independent Test**: Deploy `infrahub` on the new driver version, set the override on `task-manager`, and compare the Ingresses of the deployment before and after. Only the `task-manager` Ingress differs.

**Acceptance Scenarios**:

1. **Given** a cluster with ingress class `traefik` and FQDN suffix `example.com`, and an Infrahub deployment in environment `lab` on the new driver version, whose `task-manager` service is `scope: external` and whose `infrahub` service is `scope: internal`, **When** the operator sets, for `task-manager`, the class `tailscale` and the suffix `tailnet.example.ts.net`, **Then** the Ingress that Styrmin builds for `task-manager` has class `tailscale` and the host `task-manager-lab.tailnet.example.ts.net`, the `infrahub` Ingress is identical before and after, and the service address that the driver reads is the new host.
2. **Given** a deployment with an override on `task-manager`, **When** the operator clears the override, **Then** the `task-manager` Ingress has the cluster's class and suffix again.
3. **Given** an environment with a dedicated ingress controller, **When** the operator overrides one service, **Then** the other services keep being served through the dedicated controller and the overridden service gets the override's class.

---

### User Story 2 - Deploy an external service with no override (Priority: P2)

An operator deploys a driver version that declares a service `scope: external`, and Styrmin builds its Ingress with the resolved ingress class. The driver's chart does not need an Ingress template for that service.

**Why this priority**: Every override rests on Styrmin building the Ingress. Drivers that declare `external` services (`generic-app`, the `task-manager` of `infrahub`) must keep working after the change.

**Independent Test**: Deploy `generic-app` and assert that its service has exactly one Ingress with the resolved class and the annotations that Styrmin writes today. Delete the deployment and assert that the Ingress is gone.

**Acceptance Scenarios**:

1. **Given** a driver version that declares a service `scope: external`, **When** the operator deploys it, **Then** Styrmin builds one Ingress for the service with the resolved ingress class, the annotations that Styrmin writes today, and the hosts defined in the requirements below.
2. **Given** a deployment with a Styrmin-built Ingress, **When** the operator deletes the deployment, **Then** the Ingress is deleted.
3. **Given** a driver with two external services, **When** the operator deploys it, **Then** exactly one of the Ingresses carries the application address.

---

### User Story 3 - Set, view and clear the override in the UI (Priority: P3)

An operator opens the deployment's Settings tab and sets the ingress class and the FQDN suffix of one service, without reading a manifest. The Networking summary shows what is published where.

**Why this priority**: The API and manifest paths (User Story 1) already let an operator use the feature. The UI makes it usable without them.

**Independent Test**: In the UI, open Configuration, then Service overrides, set both values for `task-manager`, save, and read the Networking summary.

**Acceptance Scenarios**:

1. **Given** a running Infrahub deployment on the new driver version, **When** the operator opens Configuration, then Service overrides, sets `tailscale` and `tailnet.example.ts.net` for `task-manager` and saves, **Then** the deployment redeploys and the Networking summary lists `task-manager` at the new host under class `tailscale`, marked as overridden.
2. **Given** the deploy form, **When** the operator creates a deployment, **Then** the same override fields are present on the form.
3. **Given** a service without an override, **When** the operator views the Networking summary, **Then** its class and host are shown and marked as inherited.

---

### User Story 4 - Refused changes name the service (Priority: P3)

An operator who sets an override that Styrmin cannot honour, or who changes a driver version in a way that would drop an override, gets an error that names the service. Nothing changes in the cluster.

**Why this priority**: These are the guards that stop an override being lost or ignored without notice.

**Independent Test**: Set an override on the `infrahub` service (internal) and assert the error. Store an override on `task-manager`, then upgrade to a driver version that makes it internal and assert the refusal.

**Acceptance Scenarios**:

1. **Given** a service declared `scope: internal`, **When** the operator sets an override on it, **Then** Styrmin rejects the request with an error that names the service and says that Styrmin does not build its Ingress.
2. **Given** a deployment with an override stored on a service, **When** the operator changes the driver version to one that removes the service or declares it `internal`, **Then** Styrmin rejects the change before any pod changes and keeps the override.

---

### Edge Cases

- A dedicated ingress controller is on for the environment: see FR-008.
- An override on an internal service such as the Infrahub server: see FR-009.
- A driver version change drops the service, makes it internal, or makes its kind `tcp` or `udp` while an override is stored: see FR-010.
- A driver declares a service `external` and still renders its own Ingress for it: see FR-014.
- No FQDN suffix is configured: building the ingress patch already fails with an error today, and a built Ingress needs the same suffix. An override that sets a suffix for one service does not remove the requirement for the other services.
- A service declared `external` with `kind: tcp` or `udp`: an Ingress cannot route it, so Styrmin builds no Ingress for it. The PRD does not say this; it is a clarification.
- Existing deployments whose stored driver version declares a service `external` and renders its own Ingress (the `generic-app` versions in use today) get a second Ingress on the same host as soon as they run a Styrmin release with this feature, before any driver version change. Styrmin cannot see whether a chart renders an Ingress without rendering the chart. The PRD word "after the upgrade" in FR-014 does not say which upgrade. Decision by Simon AURA--SCUSSEL on 2026-11-10 in the preparation session (not yet written on issue #598): accepted, with no guard. The migration guide and the changelog entry state it (FR-014). A downgrade to such a driver version has the same effect.
- Moving an existing Infrahub deployment to the new driver version replaces the chart's Prefect Ingress with Styrmin's, on the same host. The length of any interruption is not known.
- Backup and restore of an environment with Styrmin-built Ingresses: not known.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Styrmin MUST build one Ingress for every service declared `scope: external`, with the ClusterIP Service that Styrmin already creates for that service as its backend, and MUST create, update and delete it with the deployment. Test: deploy a driver with an external service; assert the Ingress, its backend, and that deleting the deployment removes it.
- **FR-002**: The Ingress MUST carry the readable host (`<service name>-<environment name>.<suffix>`) for every external service, and the application address (`<app name>-<deployment id>.<suffix>`) only for the first service that the driver declares, and only when that service is `external`. The application address is identical for all services of a deployment, so this avoids two Ingresses claiming one host. Test: a driver with two external services; assert that exactly one Ingress has the application address. A driver whose first declared service is `internal` (such as `infrahub`): assert that no Styrmin-built Ingress has the application address.
  - *Changed from the PRD, which says "the first external service that the driver declares". In the `infrahub` driver that is `task-manager`, while the chart's Ingress for the `infrahub` service already uses the application address as its host, so two Ingresses would claim it and FR-013 and SC-005 would fail. See [research.md](research.md) D-003 and [critique](critiques/critique-20261110-1000.md) finding E1. Confirmed by Simon AURA--SCUSSEL on 2026-11-10 in the session that prepared this spec (not yet written on issue #598).*
- **FR-003**: Without an override, a Styrmin-built Ingress MUST have the resolved ingress class and the annotations that Styrmin writes today on a chart Ingress: entry points, external-dns, Cloudflare, and the allow-list middleware reference when `ip_whitelist` is set. Test: compare against a chart-rendered Ingress of the same deployment.
- **FR-004**: With an override, the Ingress MUST have the override's class and the override's suffix in its hosts, and MUST NOT carry the entry-point, external-dns, Cloudflare or allow-list annotations. Test: a unit test on the generated object, and a check on the live object.
- **FR-005**: The documentation MUST state that a deployment's `ip_whitelist` does not apply to an overridden service, because the allow-list is a Traefik middleware. Test: documentation review.
- **FR-006**: Styrmin MUST expose, for every service, the effective ingress class and the generated hostname, with the override's suffix when one is set, in the driver template data and in the GraphQL data that the UI reads. Test: render the Infrahub driver with and without an override and compare the values.
- **FR-007**: Styrmin MUST NOT write `spec.tls` on a Styrmin-built Ingress in the first release. Test: no `spec.tls` on a built Ingress. See Assumptions for the Tailscale case.
- **FR-008**: In an environment with a dedicated ingress controller, a Styrmin-built Ingress without an override MUST follow the rule that chart Ingresses follow today (no `spec.ingressClassName`, the annotation set to the controller implementation), and an overridden Ingress MUST get the override's class fields instead. Test: an end-to-end test with `dedicated_ingress` set and one service overridden.
- **FR-009**: Styrmin MUST reject an override on a service that Styrmin builds no Ingress for: a service that is not declared `scope: external`, or an external service whose kind is `tcp` or `udp` (review fix F4). The typed error names the service and says that Styrmin does not build its Ingress. Test: set an override on the Infrahub server service, and on an external `tcp` service, and assert the error code.
- **FR-010**: When a driver version change removes the service, changes it from external to internal, or changes its kind to `tcp` or `udp`, while an override is stored, Styrmin MUST reject the change before any pod changes and MUST NOT drop the override silently. Test: an upgrade test, following the rule for retired parameters.
- **FR-011**: The documentation MUST correct the statements about `scope` that were not true before, MUST describe service ingress overrides, and MUST state how Styrmin chooses the hostnames of a service, so that a driver author can predict the addresses (PRD user story 13). A migration guide and a changelog entry MUST describe the breaking change in FR-014. Test: documentation review against the code.
- **FR-012**: The `generic-app` example driver MUST be updated in the same release so that it stops rendering its own Ingress, because it declares its service `external` today. Test: an end-to-end deploy of `generic-app` yields exactly one Ingress.
- **FR-013**: The first new driver version of `infrahub` and `infrahub-enterprise` MUST declare `task-manager` as `scope: external` and turn off the chart's Prefect Ingress. The `infrahub` service MUST stay `internal` and keep its chart Ingress. Test: the User Story 1 journey as an end-to-end test; the server Ingress is identical before and after.
- **FR-014**: A driver version that declares a service `scope: external` and also renders its own Ingress for it gets two Ingresses with the same host after the upgrade. This is a breaking change and MUST be documented in a migration guide, as the beta policy requires for driver-format changes. The guide and the changelog entry MUST say that the effect starts when a deployment runs a Styrmin release with this feature, and not only at a driver version change (see Edge Cases). Test: documentation review; the guide names the steps to take.
- **FR-015**: An operator MUST be able to set, view and clear a service's ingress override in a manifest's `spec.config`, through the API, and in the UI (the deployment's Settings tab and the deploy form). Clearing the override restores the resolved class and suffix. Test: each of the three paths sets, reads back and clears an override.
- **FR-016**: The UI MUST show, for each service, the effective ingress class and host, and MUST mark each value as overridden or inherited. Test: a UI test on the Networking summary with and without an override.

### Key Entities

- **Service** (existing): a service that a driver declares. Its `scope` now decides whether Styrmin builds an Ingress for it.
- **Service ingress override** (new): a setting in a deployment's config for one service, with an ingress class and an FQDN suffix. It is stored in the deployment's JSON config. It applies only to a service declared `external`.
- **Ingress class** and **FQDN suffix** (existing, resolved from the deployment, else the environment, else the cluster): the override replaces both for one service.
- **Service name override** (existing): unchanged. It is stored as the resolved name of the service, not in the deployment's config.
- **Dedicated ingress controller** (existing): an overridden Ingress wins over it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator sets, views and clears a service ingress override with one save in the UI, or one `apply` of a manifest, without editing the driver and without `kubectl`.
- **SC-002**: Overriding one service leaves the deployment's other Ingresses with zero differences.
- **SC-003**: A deployment whose driver declares no external service has zero Ingress differences after the upgrade, for every example driver other than `generic-app`.
- **SC-004**: Every request that cannot be applied (FR-009, FR-010) fails with a typed error that names the service, and never completes silently.
- **SC-005**: On a sandbox, the public address of the task manager no longer answers, the Infrahub address still answers, and a person on the tailnet reaches the task manager at its new name. The tailnet part is open until a real Tailscale operator is tested.
- **SC-006**: After the upgrade, a `generic-app` deployment has exactly one Ingress per service.

## Assumptions

- The controller that serves the override class, such as the Tailscale operator, is already installed. Styrmin does not install or check it.
- Network access for that controller's pods is arranged outside Styrmin, for example with a network policy in Terraform. This was verified for the shared Traefik on a local kind cluster, and not tested for Tailscale proxy pods.
- The URL scheme and port resolve from the deployment, else the environment, else the cluster.
- The beta policy allows a breaking change to the driver format, with release notes and a migration guide ([beta-status.md](https://github.com/opsmill/styrmin/blob/f091158b48f32911579082d9926d57786f50222d/docs/docs/beta-status.md)).
- The pre-production sandbox cluster gets the feature after a Styrmin release and a chart bump.
- No database schema change is needed, because the override lives in the deployment's existing JSON config and Styrmin builds the Ingress at reconcile time. To be confirmed in the plan.
- Whether the Tailscale operator requires a `tls` section on an Ingress, and whether it ignores the host in the rules, is not known: the Tailscale documentation does not say. The first release writes no `spec.tls` (FR-007). If a test on a real operator shows that it is required, the override gets an optional `tls` hosts field in a later change.
- How the UI gets the driver's list of services for the override fields is not decided in the PRD. The Service overrides section does not receive it today. The plan decides it.
- How many drivers outside this repository declare `scope: external` and render their own Ingress is not known. It sets the size of the breaking change in FR-014.

## Out of Scope

- Moving the Infrahub server's Ingress to a Styrmin-built Ingress. It stays rendered by the chart.
- A rule at cluster or environment level that matches services by name across drivers.
- Extra annotations on an overridden Ingress, including pointing the override at a second Traefik ([#464](https://github.com/opsmill/styrmin/issues/464)).
- The Gateway API ([#465](https://github.com/opsmill/styrmin/issues/465)).
- Changes to Styrmin's network policies ([#131](https://github.com/opsmill/styrmin/issues/131) and [#563](https://github.com/opsmill/styrmin/issues/563)).
- Overriding the URL scheme or port for one service.
- Writing `spec.tls`, until a test on a real Tailscale operator settles whether it is needed.
- `styrminctl deployments apply` accepting and ignoring unknown component keys. It becomes a separate issue. The cause is known: the generated SDK models ignore extra fields.

## Governance Gates Crossed

- GraphQL schema modification: new input and output types. Regenerate `schema.graphql`, the SDK types and the frontend types, and add a propagation test.
- Driver format behaviour change: `scope: external` gets a meaning. The beta policy requires release notes with the steps to take and a migration guide.
- Database schema or migration: ruled out, to be confirmed in the plan.
- New dependency, CI/CD workflow, authentication or authorization: ruled out.

## Related Material

- Related ADRs: ADR-071 (ingress class set by post-render), ADR-022 (FQDNs computed at runtime), ADR-070 (replica overrides and retired parameters).
- Related issues: #464, #465, #131, #563, #596.
