# Feature Specification: Ingress Class Set Only After the Chart Renders

**Feature Branch**: `fac/ingress-class-post-render-tb7qv`

**Created**: 2026-10-15

**Status**: Draft

**Input**: PRD "Ingress class set only after the chart renders" — [opsmill/styrmin#471 (comment)](https://github.com/opsmill/styrmin/issues/471#issuecomment-6187650614). Seed issue: [#471](https://github.com/opsmill/styrmin/issues/471). Builds on [ADR-057](../../dev/adr/0057-post-render-component-overrides.md) (env vars applied by post-render) and [ADR-069](../../dev/adr/0069-container-command-args-by-post-render.md) (container `command` and `args` applied by post-render).

## Context

Driver authors write the Ingress class into `values.j2.yml`, under whatever key the chart reads:

- The three example drivers do this: [`simple-app`](../../driver/examples/simple-app/values.j2.yml), [`semaphore`](../../driver/examples/semaphore/values.j2.yml) and [`slurpit`](../../driver/examples/slurpit/values.j2.yml), each with `className: "{{ instance.config.ingress_class }}"`.
- The driver documentation tells authors to write the same line: [Creating a driver](../../docs/docs/drivers/creating-a-driver.md) and [Context](../../docs/docs/drivers/context.md).

Styrmin already sets the class after the chart renders, through the post-render patches of the ingress **utility** ([`utilities/ingress.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py)). Every application deployment gets the ingress utility by default ([`DEFAULT_UTILITY_KINDS`](../../backend/styrmin_backend/services/utilities/utilities.py)).

- Without a **dedicated ingress controller**, Styrmin sets `spec.ingressClassName` and the `kubernetes.io/ingress.class` annotation on every Ingress to the resolved `ingress_class`.
- With a dedicated ingress controller, Styrmin sets only the annotation, to the controller implementation (`traefik`), and does not change `spec.ingressClassName`. So that templates render an empty class, Styrmin removes `ingress_class` from the template data before it renders the values template ([`builders/application.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py), `render_value_template`).

The removal protects only templates that read `ingress_class`. A class that the chart sets by default, or that a template writes as a fixed value, still reaches the Ingress in dedicated mode, and the dedicated ingress controller cannot serve that Ingress:

- Kubernetes rejects a new Ingress whose `kubernetes.io/ingress.class` annotation differs from its `spec.ingressClassName` ([Kubernetes Ingress validation](https://github.com/kubernetes/kubernetes/blob/cbfc0564b409b82c6ec0cf76e2d15860dd13b31b/pkg/apis/networking/validation/validation.go#L309-L313)). A chart that renders `className: nginx` gets an Ingress that cannot be created.
- When `spec.ingressClassName` is set, Traefik ignores the annotation and serves the Ingress only when an IngressClass of that name exists ([Traefik v3.7.1 Ingress provider](https://github.com/traefik/traefik/blob/v3.7.1/pkg/provider/kubernetes/ingress/kubernetes.go#L540-L550)). The dedicated ingress controller creates no IngressClass and does not look IngressClasses up ([controller chart values](../../backend/styrmin_backend/services/ingress_controller/templates/chart_values.j2.yaml)). A chart that renders `className: traefik` gets an Ingress that the dedicated ingress controller ignores.

Whether a driver in use sets a class this way is not known. The default class of the `simple-app` chart is empty ([chart values](../../driver/examples/simple-app/src/helm/values.yaml)). The defaults of the other charts were not checked.

This feature makes Styrmin set or remove the Ingress class after the chart renders, in both modes:

- Without a dedicated ingress controller, nothing changes: Styrmin sets `spec.ingressClassName` and the annotation to the resolved `ingress_class`, whatever class the chart rendered.
- With a dedicated ingress controller, Styrmin removes `spec.ingressClassName` from every Ingress and sets the annotation to the controller implementation, as it sets the annotation today.
- Styrmin no longer removes `ingress_class` from the template data.
- The example drivers and the driver documentation drop the class line. A driver version that still sets the class keeps deploying, because Styrmin overwrites or removes the class after the chart renders. Deployment users get the same Ingress class as today.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A driver author removes the class line from the values template (Priority: P1)

A driver author removes the Ingress class line from `values.j2.yml`. The application's Ingress gets the same class as today, with and without a dedicated ingress controller. The driver has no chart-specific template code for a value that Styrmin owns.

**Why this priority**: This is the change the issue asks for. Every other story depends on Styrmin setting or removing the class after the chart renders in both modes, which this story proves on the drivers that ship in this repository.

**Independent Test**: Load the `simple-app` example driver without its class line, deploy it in an environment without a dedicated ingress controller and in one with a dedicated ingress controller, and read the class field and the annotation of each Ingress that the cluster receives.

**Acceptance Scenarios**:

1. **Given** an environment whose resolved `ingress_class` is `nginx`, no dedicated ingress controller, and a driver version with no class line, **When** a user deploys the application, **Then** every Ingress in the release has `spec.ingressClassName: nginx` and the annotation `kubernetes.io/ingress.class: nginx`.
2. **Given** an environment with a dedicated ingress controller and the same driver version, **When** a user deploys the application, **Then** every Ingress in the release has no `spec.ingressClassName`, has the annotation `kubernetes.io/ingress.class: traefik`, and the application responds through the dedicated ingress controller.

---

### User Story 2 - A chart that sets its own class works with a dedicated ingress controller (Priority: P2)

A driver whose chart sets its own class, by default or through a fixed value in the template, is deployed in an environment with a dedicated ingress controller. The dedicated ingress controller serves its Ingress. The driver author does not have to override the chart's default to deploy there.

**Why this priority**: Today this case fails: the Ingress is rejected when its class differs from the annotation, or ignored by the dedicated ingress controller when its class is `traefik`. It is the defect that the removal of `ingress_class` from the template data cannot fix.

**Independent Test**: Render the `simple-app` chart with `className` set to `traefik`, then to `nginx`, apply Styrmin's post-render patches for dedicated mode, and check the resulting Ingress.

**Acceptance Scenarios**:

1. **Given** an environment with a dedicated ingress controller and a driver version whose chart renders `className: nginx`, **When** a user deploys the application, **Then** the Ingress is created with no `spec.ingressClassName` and with the annotation `kubernetes.io/ingress.class: traefik`, and the deployment reaches `RUNNING`.
2. **Given** an environment with a dedicated ingress controller and a driver version whose chart renders `className: traefik`, **When** a user deploys the application, **Then** the Ingress is created with no `spec.ingressClassName` and with the annotation `kubernetes.io/ingress.class: traefik`, and the deployment reaches `RUNNING`.
3. **Given** an environment without a dedicated ingress controller whose resolved `ingress_class` is `traefik`, and a driver version whose chart renders `className: nginx`, **When** a user deploys the application, **Then** every Ingress has `spec.ingressClassName: traefik` and the annotation `kubernetes.io/ingress.class: traefik`.

---

### User Story 3 - A released driver version that still sets the class keeps deploying (Priority: P3)

A driver author has released a driver version whose template still sets the class from `instance.config.ingress_class`. Deployments of that version keep deploying, upgrading and moving between ingress modes without a move to a new driver version. The author removes the line in the next release. Deployment users get the same Ingress class after Styrmin is upgraded.

**Why this priority**: Existing deployments must not break when Styrmin is upgraded. It ranks after the first two stories because the post-render patches that those stories need already give this result; this story makes sure that nothing in the change removes it.

**Independent Test**: Render the `simple-app` chart with `className` set to the resolved `ingress_class` in both modes, apply Styrmin's post-render patches, and check that the Ingress has the same shape as the one that a driver version without the class line gets.

**Acceptance Scenarios**:

1. **Given** a deployment of a driver version whose template sets `className: "{{ instance.config.ingress_class }}"`, in an environment without a dedicated ingress controller, **When** Styrmin is upgraded and the deployment is redeployed, **Then** every Ingress keeps `spec.ingressClassName` and the annotation set to the resolved `ingress_class`.
2. **Given** the same driver version, in an environment with a dedicated ingress controller, **When** the template renders the resolved `ingress_class` (no longer removed from the template data), **Then** Styrmin removes `spec.ingressClassName` after the chart renders, the annotation is `traefik`, and the deployment reaches `RUNNING`.
3. **Given** a cluster or an environment that turns dedicated ingress on or off, **When** the config fan-out redeploys each application, **Then** each application's Ingress gets the class of its new mode, as described in User Story 1.

---

### Edge Cases

- **No `ingress_class` resolved, no dedicated ingress controller**: Styrmin leaves the class that the chart sets unchanged. This can happen only when the cluster config sets `ingress_class: null` explicitly, because Styrmin fills in `traefik` only when the key is absent ([cluster defaults](../../backend/styrmin_backend/services/clusters.py)).
- **Chart renders no `spec.ingressClassName` in dedicated mode**: the Ingress stays without `spec.ingressClassName`. Removing a field that the chart did not render must not fail the render.
- **Dedicated ingress turned on or off**: the config fan-out redeploys each application, and Styrmin sets or removes the class after the chart renders. Today, the removal of `ingress_class` from the template data gives the same result only for templates that read it.
- **Ingresses that already exist**: they do not change until their application is next redeployed. In dedicated mode, they already have no `spec.ingressClassName` unless the chart sets one.
- **Template that reads `ingress_class` for something other than the Ingress class**: in dedicated mode it now gets the resolved value instead of an empty value. In this repository, only the three example drivers read the key, and only to set the class. For drivers outside this repository, this is not known (see Assumptions).
- **Ingresses from subcharts**: they get the same class as the main chart's Ingresses, because the patches target every Ingress in the release (for example, the Prefect UI Ingress of the `infrahub` driver).
- **Reloaded example drivers**: a reloaded example driver gets a new provenance fingerprint under the same `spec.version`, because its values template changed ([Loading drivers](../../docs/docs/drivers/loading-drivers.md)).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Without a dedicated ingress controller, and with a resolved `ingress_class`, Styrmin MUST set `spec.ingressClassName` and the `kubernetes.io/ingress.class` annotation to that value on every Ingress in the release, including Ingresses from subcharts, whatever class the chart rendered. Test: a chart that renders `className: nginx`, with `ingress_class: traefik`, gives `traefik` in both places.
- **FR-002**: With a dedicated ingress controller, Styrmin MUST remove `spec.ingressClassName` from every Ingress in the release, including Ingresses from subcharts, and set the `kubernetes.io/ingress.class` annotation to the controller implementation. Test: a chart that renders `className: traefik` or `className: nginx` gives an Ingress with no `spec.ingressClassName` and the annotation `traefik`; a chart that renders no class gives the same Ingress and the render does not fail.
- **FR-003**: Templates MUST be able to read the resolved `ingress_class` in the `instance`, `cluster`, `environment` and `deployment` config sections in both modes. Styrmin MUST no longer remove `ingress_class` from the template data when a dedicated ingress controller is on. Test: a render in dedicated mode reads the value.
- **FR-004**: Driver authors MUST be able to leave every Ingress class value out of `values.j2.yml` and get the results of FR-001 and FR-002. Test: the example drivers without the class line, deployed in both modes.
- **FR-005**: A driver version whose template still sets the class MUST deploy in both modes without moving to a new driver version. Test: the `simple-app` chart rendered with `className` set, in both modes.
- **FR-006**: Without a dedicated ingress controller and with no `ingress_class` resolved, Styrmin MUST leave the class that the chart rendered unchanged, in both `spec.ingressClassName` and the annotation.
- **FR-007**: The `simple-app`, `semaphore`, `slurpit` and `generic-app` example drivers MUST drop the Ingress class line from their values template and keep their `spec.version`.
- **FR-008**: The driver documentation pages "Creating a driver" and "Context" MUST drop the `className` line from their examples and say that Styrmin sets the Ingress class. The page "Ingress and networking" MUST state which class each mode gives an application's Ingress.
- **FR-009**: The change MUST NOT change the GraphQL schema, the SDK, `styrminctl`, the frontend, the database schema, the driver format or the `ingress_class` config key, and MUST NOT add an error type or error code.

### Key Entities

No new entity. The change affects these existing ones:

- **Application driver** and **driver version**: the values templates of the three example drivers drop the class line. The driver format does not change.
- **Dedicated ingress controller**: the Ingresses of the applications it serves no longer have `spec.ingressClassName`, whatever the chart renders.
- **Cluster, environment and deployment config**: the `ingress_class` key does not change, and its resolved value reaches the template data in both modes.
- **Provenance fingerprint**: a reloaded example driver gets a new fingerprint under the same `spec.version`, because its values template changed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The four example drivers and the two driver documentation pages ("Creating a driver" and "Context") contain no Ingress class value.
- **SC-002**: For a deployment of each example driver, every Ingress has the same `spec.ingressClassName` and annotation before and after the change, with and without a dedicated ingress controller.
- **SC-003**: In an environment with a dedicated ingress controller, a driver version whose chart sets its own class, either the resolved `ingress_class` or another value such as `nginx`, reaches `RUNNING`, and its Ingress has the shape that the dedicated ingress controller serves: no `spec.ingressClassName` and the annotation `traefik`. Verified by the Ingress shape that the integration test checks, which is the shape that `test_traffic_routes_through_dedicated_ingress` reaches over HTTP (see Testing Approach, accepted gap).
- **SC-004**: No deployment has to move to a new driver version because of this change.

## Testing Approach

- What a good test checks: the class field and the annotation of the Ingress that the cluster receives, not the template data.
- Unit tests:
  - Ingress utility post-render patches: one case per mode, the case with no class resolved, and a chart class that differs from the resolved one.
  - Values template renderer: in dedicated mode, the template reads `ingress_class`.
- Integration test (new): runs `helm template` and `kubectl kustomize` on the `simple-app` chart with `className` set to `traefik`, then to `nginx`, in both modes, and checks the resulting Ingress. This covers User Story 2, User Story 3, FR-005 and SC-003. Prior art: [the container override parity test](../../backend/tests/integration/test_container_override_migration_parity.py).
- E2E: no new test. Once `simple-app` drops its class line, two existing CI tests in `shard_compute` check the new behavior, and both MUST be run locally with their passing runs recorded, because the driver they deploy changes:
  - [`test_cluster_update_redeploys_and_moves_dedicated_ingress`](../../backend/tests/e2e/test_cluster_update.py) expects `spec.ingressClassName: nginx` without a dedicated ingress controller (FR-001, FR-004, SC-002).
  - [`test_traffic_routes_through_dedicated_ingress`](../../backend/tests/e2e/test_ingress_controller.py) checks that the application responds through the dedicated ingress controller (FR-002, FR-004, SC-002).
- Skipping a new E2E test was approved during the idea review of issue #471, because the two CI tests above cover the changed path. The integration test covers the case that no E2E test deploys.
- The E2E fixture drivers `late-container` and `failing-actions` ([`backend/tests/e2e/fixtures/drivers/`](../../backend/tests/e2e/fixtures/drivers/)) keep their `className: "{{ instance.config.ingress_class }}"` line on purpose. The main E2E cluster has a dedicated ingress controller, so the CI tests that deploy them (`shard_apply`, `shard_task_steps`) render a template that still sets the class in dedicated mode (FR-005). [`test_apply_sets_env_vars_with_the_version_that_adds_their_container`](../../backend/tests/e2e/test_deployments_apply.py) checks that every Ingress that `late-container` deploys has no `spec.ingressClassName` and has the `kubernetes.io/ingress.class: traefik` annotation, so the E2E suite detects a removal that Flux does not apply. This extends an existing test and adds no E2E test node.
- Accepted gap: no HTTP request reaches an application whose template still sets the class. The integration test checks that its Ingress has the same shape as the one that the second E2E test reaches over HTTP.

## Documentation Changes

In the same change:

- `CONTEXT.md`, entry "Dedicated ingress controller": add "While it is on, Styrmin removes `spec.ingressClassName` from every Ingress of the environment's applications after the chart renders and sets the `kubernetes.io/ingress.class` annotation to the controller implementation; while it is off, Styrmin sets both to the resolved `ingress_class`. Driver templates do not set the class."
- `dev/knowledge/backend/data-models.md`, section `DedicatedIngressConfig`: replace "removes `ingress_class` from the values-template context".
- `docs/docs/drivers/creating-a-driver.md` and `docs/docs/drivers/context.md`: remove the `className` line and say that Styrmin sets the Ingress class.
- `docs/docs/concepts-and-architecture/ingress-and-networking.md`: state which class each mode gives an application's Ingress.
- The docstring of the values template renderer.
- A new ADR after ADR-057 and ADR-069, recording three decisions:
  - Styrmin removes `spec.ingressClassName` in dedicated mode, instead of giving the dedicated ingress controller its own IngressClass;
  - `ingress_class` stays in the template data in both modes;
  - with no class resolved, Styrmin leaves the chart's class unchanged.
- A towncrier changelog fragment for issue 471.

## Assumptions

- **A-001**: Drivers outside this repository read `ingress_class` only to set the Ingress class. This is not known; it does not block the change (see Open Question).
- **A-002**: Every Ingress in an application's release gets the class, including Ingresses from subcharts, such as the Prefect UI Ingress of the `infrahub` driver. The annotation patch already targets every Ingress.
- **A-003**: The three example drivers keep their `spec.version`. Reloading the changed files creates new driver versions with new provenance fingerprints.
- **A-004**: The dedicated ingress controller implementation is Traefik, the only implementation today, so the annotation in dedicated mode is `traefik`.

## Out of Scope

- An IngressClass of its own for each dedicated ingress controller, and controllers other than Traefik ([#464](https://github.com/opsmill/styrmin/issues/464)).
- The Kubernetes Gateway API ([#465](https://github.com/opsmill/styrmin/issues/465)).
- Warning about, or rejecting, a template that still sets the class when the driver is loaded.
- Removing the deprecated `kubernetes.io/ingress.class` annotation.
- The Ingress of the Styrmin server in the Styrmin Helm chart.

## Open Question

- Do drivers outside this repository read `ingress_class` for anything other than the Ingress class? This is not known and does not block the change. Resolved for planning by assumption A-001: in dedicated mode such a template now gets the resolved value instead of an empty value.

## Sources and Related Decisions

- [Issue #471](https://github.com/opsmill/styrmin/issues/471) and [the PRD comment](https://github.com/opsmill/styrmin/issues/471#issuecomment-6187650614): the problem, the current behavior and the decisions from the idea review.
- [ADR-057](../../dev/adr/0057-post-render-component-overrides.md) and [ADR-069](../../dev/adr/0069-container-command-args-by-post-render.md): earlier moves from the values template to post-render.
- [`CONTEXT.md`, entry "Dedicated ingress controller"](../../CONTEXT.md).
- [ADR-066](../../dev/adr/0066-cluster-config-fanout.md): the cluster config fan-out that moves applications between the dedicated ingress controller and the cluster's `ingress_class`.
