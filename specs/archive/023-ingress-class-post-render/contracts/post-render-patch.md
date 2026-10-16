# Contract: Ingress Class Post-Render Patches

**Feature**: [../spec.md](../spec.md) | **Data model**: [../data-model.md](../data-model.md)

The contract between the ingress utility (`IngressUtility.build_app_post_rendering_patches`) and the HelmRelease that the agent writes. The patches go into `spec.postRenderers[].kustomize.patches` of the application's HelmRelease, and Flux helm-controller applies them to the manifests that the chart rendered.

## Dedicated ingress controller on

Input: `instance.config.dedicated_ingress` is set, `implementation: traefik`.

```yaml
- target:
    kind: Ingress
  patch: |
    apiVersion: networking.k8s.io/v1
    kind: Ingress
    metadata:
      name: any
    spec:
      ingressClassName: null
- target:
    kind: Ingress
  patch: |
    - op: add
      path: /metadata/annotations/traefik.ingress.kubernetes.io~1router.entrypoints
      value: web,websecure
    # ... the other annotations, unchanged ...
    - op: add
      path: /metadata/annotations/kubernetes.io~1ingress.class
      value: traefik
```

Guarantees:

- Every Ingress in the release has no `spec.ingressClassName`, whether the chart rendered none, `traefik`, `nginx` or any other value.
- The render does not fail when an Ingress has no `spec.ingressClassName` or no `metadata.annotations`.
- No `SpecPatch` for `ingressClassName` is emitted.

## Dedicated ingress controller off, class resolved

Input: `instance.config.dedicated_ingress` is `None`, `instance.config.ingress_class` is `nginx`. Unchanged from today.

```yaml
- target:
    kind: Ingress
  patch: |
    - op: add
      path: /spec/ingressClassName
      value: nginx
- target:
    kind: Ingress
  patch: |
    # ... the other annotations, unchanged ...
    - op: add
      path: /metadata/annotations/kubernetes.io~1ingress.class
      value: nginx
```

Guarantees:

- Every Ingress in the release has `spec.ingressClassName: nginx` and `kubernetes.io/ingress.class: nginx`, whatever class the chart rendered.
- The rendered HelmRelease is the same as before this change.

## Dedicated ingress controller off, no class resolved

Input: `instance.config.dedicated_ingress` is `None`, `instance.config.ingress_class` is `None` or empty. Unchanged from today.

- No `ingressClassName` patch, no removal patch, and no `kubernetes.io/ingress.class` entry in the annotation patch.
- Every Ingress keeps the class and the annotation that the chart rendered.

## Errors

No new error type or error code. A patch that Kustomize cannot apply fails the HelmRelease reconcile as today.
