# Research: Ingress Class Set Only After the Chart Renders

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-15

The experiments below ran in the scratchpad with `kubectl kustomize` from kubectl v1.35.0 (Kustomize v5.7.1), the same tool the integration tests call. Flux helm-controller `v1.6.5` ([`helm/agent/templates/helm-controller/deployment.yaml`](../../helm/agent/templates/helm-controller/deployment.yaml)) applies the `postRenderers.kustomize.patches` of a HelmRelease with the Kustomize API, so the patch behavior is the same. The E2E tests confirm it on a cluster.

## D-001: Remove `spec.ingressClassName` with a strategic merge patch that sets it to `null`

**Decision**: In dedicated mode, the ingress utility adds one new patch block, `IngressClassNameRemovalPatch`, targeted at `kind: Ingress`. It is a strategic merge patch:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: any
spec:
  ingressClassName: null
```

**Rationale**:

- A JSON6902 `remove` operation fails when the field is absent. Verified: `kubectl kustomize` on an Ingress with no `spec.ingressClassName` exits with `error in remove for path: '/spec/ingressClassName': Unable to remove nonexistent key: ingressClassName: missing value`. The `simple-app` chart renders no `ingressClassName` when `className` is empty ([`templates/ingress.yaml`](../../driver/examples/simple-app/src/helm/templates/ingress.yaml)), so after the example drivers drop the class line (FR-004) a `remove` patch would fail every dedicated-mode render. The spec edge case "Chart renders no `spec.ingressClassName` in dedicated mode" requires that the render does not fail.
- A strategic merge patch that sets a field to `null` deletes the field when it is present and leaves the resource unchanged when it is absent. Verified on three Ingresses in one run: `ingressClassName: nginx` was removed, an Ingress with no class was unchanged, and an Ingress with no `metadata.annotations` was patched without error.
- With a `target` selector, Kustomize applies the strategic merge patch to every matching resource and uses the resource's own group and version. Verified: the patch above, written for `networking.k8s.io/v1`, removed the class from a `networking.k8s.io/v1beta1` Ingress in another namespace. Ingresses from subcharts are matched in the same way (A-002).
- An Ingress without `spec.ingressClassName` does not get the cluster's default IngressClass. The `DefaultIngressClass` admission plugin skips an Ingress that has the `kubernetes.io/ingress.class` annotation, whatever its value ([admission plugin, v1.35.0](https://github.com/kubernetes/kubernetes/blob/v1.35.0/plugin/pkg/admission/network/defaultingressclass/admission.go)), and Styrmin sets that annotation on every Ingress in dedicated mode. The design depends on the annotation: removing it, which the spec puts out of scope, would let the plugin set a default class on create.
- Strategic merge patches with a target are already used in production by `TemplateAnnotationPatch`, `AffinityPatch`, `RuntimeClassPatch` and `ContainerMergePatch` in [`blocks/patches.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py). Kustomize accepts strategic merge and JSON6902 patches in the same `patches` list.

**Alternatives considered**:

- **JSON6902 `remove`**: rejected; fails on an absent field (verified above).
- **JSON6902 `add` of a placeholder value, then `remove`**: works (verified), because `add` creates or replaces the member and `remove` then always finds it. Rejected because it writes a value only to delete it, which a reader has to decode, while the strategic merge patch states the intent directly.
- **Extending the existing `SpecPatch` with a `None` value**: `SpecPatch` renders JSON6902 `add` operations. JSON6902 has no "remove if present" operation, so a `None` value cannot express removal there; it would render `value: None`, which sets the string `None`.
- **Dependency extension (evaluated per the research directive)**: the Flux `postRenderers.kustomize.patches` list is the extension point that Flux provides for changing a rendered release, and Styrmin already uses it. Kustomize's strategic merge patch supports field deletion with `null`, so no new mechanism is needed.
- **Upstream contribution (evaluated per the research directive)**: the JSON Patch library that Kustomize uses (`evanphx/json-patch` v5) has an `ApplyOptions.AllowMissingPathOnRemove` option, but Kustomize does not expose it in its patch configuration. Exposing it would need a Kustomize API change and a Flux helm-controller release that picks it up. Rejected: the strategic merge patch already gives the needed behavior with the versions in use today.
- **Giving the dedicated ingress controller its own IngressClass and setting `spec.ingressClassName` to it**: out of scope ([#464](https://github.com/opsmill/styrmin/issues/464)); the PRD decides to remove the field instead.

## D-002: Without a dedicated ingress controller, keep the existing JSON6902 `add` patches

**Decision**: The patches for the non-dedicated mode do not change. With a resolved `ingress_class`, the ingress utility keeps emitting `SpecPatch(specs={"ingressClassName": <class>})` and the `kubernetes.io/ingress.class` entry in the `AnnotationPatch`.

**Rationale**:

- JSON6902 `add` on an existing object member replaces its value (RFC 6902, section 4.1), so a class that the chart rendered is overwritten (FR-001). Verified: Kustomize's `add` to `/metadata/annotations/kubernetes.io~1ingress.class` also works on an Ingress with no `metadata.annotations`.
- The PRD states that nothing changes in this mode. Keeping the patches as they are means the rendered HelmRelease for existing deployments in this mode is byte-identical, so the change triggers no Flux upgrade in this mode.

**Alternatives considered**: one strategic merge patch that sets both the class and the annotation in both modes. Rejected: it changes the rendered HelmRelease of every deployment in non-dedicated mode, with no change in the resulting Ingress.

## D-003: With no class resolved, emit no class patch

**Decision**: Without a dedicated ingress controller and with `ingress_class` unset (`None` or empty), the ingress utility emits no `spec.ingressClassName` patch and no `kubernetes.io/ingress.class` annotation, as today. The chart's class stays unchanged (FR-006).

**Rationale**: This is today's behavior ([`utilities/ingress.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py)), and the PRD records it as a decision for the new ADR. The case can happen only when the cluster config sets `ingress_class: null` explicitly, because `_apply_cluster_defaults` fills in `traefik` only when the key is absent ([`services/clusters.py`](../../backend/styrmin_backend/services/clusters.py)).

**Alternatives considered**: removing the chart's class in this case too. Rejected: no class would be left, and the PRD keeps the chart's class.

## D-004: Stop removing `ingress_class` from the template data

**Decision**: Delete the block in `ApplicationHelmReleaseBuilder.render_value_template` that pops `ingress_class` from the `instance`, `cluster`, `environment` and `deployment` config sections when `dedicated_ingress` is set ([`builders/application.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py)). Update the docstring to state that `ingress_class` is template data in both modes and that Styrmin sets or removes the Ingress class after the chart renders.

**Rationale**: FR-003 and user story 4 of the PRD. After D-001, the removal protects nothing: whatever class the template renders, Styrmin removes it after the chart renders.

**Effect on a driver version that still sets the class (FR-005)**: in dedicated mode its template now renders `className: <resolved ingress_class>` instead of an empty class. The chart renders `spec.ingressClassName`, and D-001 removes it. The resulting Ingress is the same as today's. The integration test checks this case (D-006).

**Alternatives considered**: keeping the removal as extra protection. Rejected: it hides the resolved value from templates that may need it and keeps two places that decide the class, which is the problem in [#471](https://github.com/opsmill/styrmin/issues/471).

## D-005: Example drivers drop the class line and keep `spec.version`

**Decision**: Remove `className: "{{ instance.config.ingress_class }}"` from [`simple-app/values.j2.yml`](../../driver/examples/simple-app/values.j2.yml), [`semaphore/values.j2.yml`](../../driver/examples/semaphore/values.j2.yml) and [`slurpit/values.j2.yml`](../../driver/examples/slurpit/values.j2.yml). Do not change `spec.version` in their `driver.styrmin.yml`.

**Rationale**: FR-007 and A-003. A reload of a changed values template creates a new driver version row with a new provenance fingerprint under the same `spec.version` ([Loading drivers](../../docs/docs/drivers/loading-drivers.md), "Reloading a local driver while you iterate"). The `simple-app` chart's default `ingress.className` is empty ([`values.yaml`](../../driver/examples/simple-app/src/helm/values.yaml)). The default class of the `semaphore` and `slurpit` charts was not checked; with D-001 and D-002 their Ingress gets the right class whatever the default is.

## D-006: Tests: unit, one new integration test, two existing E2E tests

**Decision**:

- **Unit, ingress utility** ([`backend/tests/unit/agent/test_utility_resources.py`](../../backend/tests/unit/agent/test_utility_resources.py), class `TestDedicatedIngressPatching`):
  - dedicated mode emits one `IngressClassNameRemovalPatch` targeted at `kind: Ingress`, no `SpecPatch`, and the annotation set to the implementation (replaces `test_dedicated_ingress_does_not_set_ingress_class_name`);
  - non-dedicated mode with a resolved class emits the `SpecPatch` and the annotation, and no removal patch;
  - no class resolved emits neither the class patch, the annotation entry nor the removal patch.
- **Unit, patch block**: a test of `IngressClassNameRemovalPatch.render_value` in the same file, which parses the YAML and checks `apiVersion`, `kind`, `metadata.name` and `spec == {"ingressClassName": None}`. The class also gets a docstring example like the other patch blocks, but the test suite does not run doctests, so the unit test is the check.
- **Unit, values template renderer** (new file `backend/tests/unit/agent/test_render_value_template_ingress_class.py`, next to `test_render_value_template_env_vars.py`): in dedicated mode, a template that reads `instance.config.ingress_class`, `cluster.config.ingress_class`, `environment.config.ingress_class` and `deployment.config.ingress_class` gets the resolved values (FR-003).
- **Integration** (new file `backend/tests/integration/test_ingress_class_post_render.py`, after [`test_container_override_migration_parity.py`](../../backend/tests/integration/test_container_override_migration_parity.py)): renders the `simple-app` chart with `helm template` with `ingress.className` set to `""`, `traefik` and `nginx`, applies the ingress utility patches with `kubectl kustomize` in both modes, and checks every Ingress:
  - dedicated mode: no `spec.ingressClassName`, annotation `traefik` (FR-002, FR-005, SC-003);
  - non-dedicated mode with `ingress_class: traefik`: `spec.ingressClassName: traefik` and annotation `traefik` (FR-001);
  - non-dedicated mode with no class resolved: the chart's class is unchanged (FR-006).
  It also renders the migrated `simple-app/values.j2.yml` through `render_value_template` in both modes and checks that the result matches the case `className: ""` (FR-004, SC-002). The test is skipped when `helm` or `kubectl` is not on `PATH`, like the prior art.
- **E2E**: no new test (approved in the idea review of #471). Run locally, with the evidence that Constitution §V requires:
  - [`test_cluster_update_redeploys_and_moves_dedicated_ingress`](../../backend/tests/e2e/test_cluster_update.py) (`api_only`, `shard_compute`): expects `spec.ingressClassName: nginx` and the matching annotation without a dedicated ingress controller.
  - [`test_traffic_routes_through_dedicated_ingress`](../../backend/tests/e2e/test_ingress_controller.py) (`shard_compute`, runs as `api-chromium` and `ui-chromium` in CI): the application responds through the dedicated ingress controller. Running the `api-chromium` variant locally is enough, because the change is in the agent and the driver template, not in the UI.

- **E2E fixture drivers kept as they are**: `late-container` and `failing-actions` under `backend/tests/e2e/fixtures/drivers/` keep their class line. The main E2E cluster has a dedicated ingress controller, so the CI tests that deploy them render a template that still sets the class in dedicated mode (FR-005). No task changes them.

**Rationale**: the spec's Testing Approach. A good test checks the Ingress that the cluster receives, so the integration test runs the real `helm template` and `kubectl kustomize` instead of comparing patch objects.

**Alternatives considered**: a new E2E test that deploys a driver whose chart sets its own class. Rejected in the idea review of #471: the integration test checks the same Ingress shape that the second E2E test reaches over HTTP.

## D-007: Documentation and ADR-070

**Decision**: In the same change:

- [`CONTEXT.md`](../../CONTEXT.md), entry "Dedicated ingress controller": add the sentence from the spec's Documentation Changes.
- [`dev/knowledge/backend/data-models.md`](../../dev/knowledge/backend/data-models.md), section `DedicatedIngressConfig`: replace "removes `ingress_class` from the values-template context" with the post-render behavior of both modes.
- [`docs/docs/drivers/creating-a-driver.md`](../../docs/docs/drivers/creating-a-driver.md) and [`docs/docs/drivers/context.md`](../../docs/docs/drivers/context.md): drop the `className` line from the examples and add a "No Ingress class" bullet to the patterns lists, next to "No env var wiring".
- [`docs/docs/concepts-and-architecture/ingress-and-networking.md`](../../docs/docs/concepts-and-architecture/ingress-and-networking.md), section "Dedicated ingress controller or shared ingress class": state the class each mode gives an application's Ingress.
- `dev/adr/0070-ingress-class-set-by-post-render.md` (MADR, next free number after ADR-069): the three decisions from the PRD (D-001, D-004, D-003 here), with ADR-057 and ADR-069 as related records. Consequences include the dependency on the `kubernetes.io/ingress.class` annotation in dedicated mode (D-001, `DefaultIngressClass` admission plugin).
- `changelog/471.changed.md`, created with `uv run towncrier create`. It says three things to driver authors: driver templates no longer need to set the Ingress class, because Styrmin sets it, or removes it with a dedicated ingress controller, after the chart renders; with a dedicated ingress controller, Styrmin now removes a class that the chart sets on its own, so such a chart deploys there; and templates now read the resolved `ingress_class` with a dedicated ingress controller too, where it was empty before.

**Rationale**: Constitution §VII and the PRD's documentation list. `docs/docs/installation/vcluster-local.md` sets `className: traefik` for the Styrmin server's own Ingress in the Styrmin Helm chart, which is out of scope, so it does not change. [`driver/DRIVERS.md`](../../driver/DRIVERS.md) lists `ingress_class` as context data, which stays true (D-004).
