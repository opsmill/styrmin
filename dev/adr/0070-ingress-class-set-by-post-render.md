# ADR-070: Ingress Class Set by Post-Render

**Status**: Accepted
**Date**: 2026-10-15
**Source**: specs/023-ingress-class-post-render/ (spec, plan, research D-001 to D-007, contracts);
[issue #471](https://github.com/opsmill/styrmin/issues/471)
**Related**: [ADR-057](0057-post-render-component-overrides.md) (env vars applied by post-render),
[ADR-069](0069-container-command-args-by-post-render.md) (container `command` and `args` applied by
post-render), [ADR-066](0066-cluster-config-fanout.md) (the cluster config fan-out, which moves
applications onto and off a dedicated ingress controller)

## Context

Driver templates set the Ingress class in `values.j2.yml`. The three example drivers wrote
`className: "{{ instance.config.ingress_class }}"`, and the driver documentation told authors to
write the same line. The ingress utility
(`agent/service/kubernetes/resources/utilities/ingress.py`) already set the class after the chart
rendered:

- Without a dedicated ingress controller, it set `spec.ingressClassName` and the
  `kubernetes.io/ingress.class` annotation on every Ingress to the resolved `ingress_class`, with
  JSON6902 `add` operations.
- With a dedicated ingress controller, it set only the annotation, to the controller
  implementation (`traefik`). So that templates rendered an empty class,
  `ApplicationHelmReleaseBuilder.render_value_template` removed `ingress_class` from the
  `instance`, `cluster`, `environment` and `deployment` sections of the template data.

The removal protected only templates that read `ingress_class`. A class that the chart set by
default, or that a template wrote as a fixed value, still reached the Ingress with a dedicated
ingress controller:

- Kubernetes rejects a new Ingress whose `kubernetes.io/ingress.class` annotation differs from its
  `spec.ingressClassName`, so a chart that rendered `nginx` gave an Ingress that could not be
  created.
- When `spec.ingressClassName` is set, Traefik ignores the annotation and serves the Ingress only
  when it has read an IngressClass of that name. The dedicated ingress controller reads no
  IngressClass (`providers.kubernetesIngress.disableIngressClassLookup: true` in
  `services/ingress_controller/templates/chart_values.j2.yaml`), so it ignores every Ingress that
  sets `spec.ingressClassName`, and a chart that rendered `traefik` gave an Ingress that the
  controller ignored.

## Decision

### 1. With a dedicated ingress controller, Styrmin removes `spec.ingressClassName` by a strategic merge patch (research D-001)

In dedicated mode, `IngressUtility.build_app_post_rendering_patches` adds
`IngressClassNameRemovalPatch` (`agent/service/kubernetes/resources/blocks/patches.py`), targeted
at `kind: Ingress` with no name, so it applies to every Ingress of the release, Ingresses of
subcharts included. It is a strategic merge patch that sets `spec.ingressClassName` to `null`:
Kustomize deletes the field when it is present and leaves the Ingress unchanged when it is absent.
The annotation is still set to `dedicated_ingress.implementation`.

The patch is not a JSON6902 `remove` operation, because `remove` fails when the field is absent:
`kubectl kustomize` (Kustomize v5.7.1) exits with `Unable to remove nonexistent key:
ingressClassName`. The `simple-app` chart renders no `spec.ingressClassName` when its `className`
value is empty, so a `remove` would fail every render with a dedicated ingress controller once the
example drivers drop the class line.

Styrmin removes the field instead of giving each dedicated ingress controller its own IngressClass
and setting `spec.ingressClassName` to it. That change is tracked in
[#464](https://github.com/opsmill/styrmin/issues/464).

Without a dedicated ingress controller, the JSON6902 `add` patches do not change (research D-002).
`add` replaces a class that the chart rendered, and the HelmRelease of a deployment in this mode
stays byte-identical, so this change starts no Flux upgrade there.

### 2. `ingress_class` stays in the template data in both modes (research D-004)

`render_value_template` no longer removes `ingress_class` from the template data when a dedicated
ingress controller is on. After decision 1, Styrmin removes whatever class a template renders, so
the removal protected nothing, and it kept a second place that decided the class.

### 3. With no class resolved, Styrmin leaves the chart's class unchanged (research D-003)

Without a dedicated ingress controller and with an empty resolved `ingress_class`, the ingress
utility adds no class patch and no `kubernetes.io/ingress.class` annotation, as before. The class
and the annotation that the chart rendered stay. `_apply_cluster_defaults` (`services/clusters.py`)
sets `traefik` when the cluster config has no `ingress_class` key, so the resolved value is empty
only when the cluster was created with `ingress_class: null` and no environment or deployment sets
a class, or when the deepest of the three levels that sets `ingress_class` sets an empty string.
`_resolve_instance_config` (`context/resolvers.py`) skips only `null` values, so an environment
that sets `""` and a deployment that sets `nginx` resolve to `nginx`.

## Consequences

- Driver templates do not need to set the Ingress class. The `simple-app`, `semaphore`, `slurpit`
  and `generic-app` example drivers dropped the class line and kept their `spec.version`;
  reloading one creates a new driver version with a new provenance fingerprint.
- A chart that sets its own class, by default or with a fixed value, deploys with a dedicated
  ingress controller: its Ingresses have no `spec.ingressClassName` and the annotation `traefik`.
- A driver version whose template still sets the class keeps deploying in both modes. Styrmin
  overwrites the class without a dedicated ingress controller and removes it with one. The
  integration test `backend/tests/integration/test_ingress_class_post_render.py` checks that such a
  template gives the same Ingress as a template without the class line.
- Templates that read `ingress_class` get the resolved value with a dedicated ingress controller,
  where they got an empty value before. Whether a driver outside this repository reads the key for
  something other than the Ingress class is not known (spec A-001).
- The design depends on the `kubernetes.io/ingress.class` annotation. The `DefaultIngressClass`
  admission plugin skips an Ingress that has the annotation, so an Ingress without
  `spec.ingressClassName` does not get the cluster's default IngressClass. Removing the
  annotation, which Kubernetes has deprecated, would let the plugin set the default class when the
  Ingress is created.
- Every application HelmRelease with a dedicated ingress controller gets one more patch, so Flux
  upgrades each release on its next render. The Ingress changes only when the chart sets its own
  class.

## Alternatives Considered

- A JSON6902 `remove` operation. Rejected: it fails on an Ingress that has no
  `spec.ingressClassName`.
- A JSON6902 `add` of a placeholder value, followed by a `remove`. This works, but writes a value
  only to delete it. Rejected because the strategic merge patch states the removal directly.
- `SpecPatch` with a `None` value. Rejected: `SpecPatch` renders JSON6902 `add` operations, which
  would set the string `None`.
- Making Kustomize accept a `remove` of a missing field (`AllowMissingPathOnRemove` of the JSON
  Patch library). Rejected: it needs a Kustomize API change and a Flux helm-controller release.
- One strategic merge patch that sets both the class and the annotation in both modes. Rejected:
  it changes the HelmRelease of every deployment without a dedicated ingress controller, with no
  change in the Ingress.
- Keeping the removal of `ingress_class` from the template data as extra protection. Rejected: it
  hides the value from templates and keeps two places that decide the class.
- Removing the chart's class also when no class is resolved. Rejected: the Ingress would have no
  class at all.

## Out of Scope

The spec leaves these out; no decision was taken on them:

- an IngressClass for each dedicated ingress controller, and controllers other than Traefik
  ([#464](https://github.com/opsmill/styrmin/issues/464));
- the Kubernetes Gateway API ([#465](https://github.com/opsmill/styrmin/issues/465));
- a warning or a load error for a template that still sets the class;
- removing the `kubernetes.io/ingress.class` annotation;
- the Ingress of the Styrmin server in the Styrmin Helm chart.
