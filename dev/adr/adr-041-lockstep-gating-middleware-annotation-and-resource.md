# ADR-041: Lockstep gating of Traefik middleware annotation and middleware resource

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-fix-ip-allowlist/research.md (D2)

## Context

The per-deployment IP allowlist works via two coordinated artifacts on the Traefik ingress path:

1. A `Middleware` resource (the `acl` Middleware) rendered by the ingress-controller chart values template. Its `sourceRange` is the operator's `ip_whitelist`.
2. A `traefik.ingress.kubernetes.io/router.middlewares` annotation on the application Ingress, pointing at the `Middleware` by namespace-qualified name.

The annotation is **a reference**. If the annotation is rendered without the corresponding `Middleware` resource existing, Traefik (correctly) refuses to admit traffic — the ingress becomes broken in a confusing way. The reverse — emit the Middleware but not the annotation — silently disables enforcement and lulls operators into thinking the allowlist is in force.

The original bug producing this spec was exactly this class of failure: the annotation pointed at a Middleware that wasn't being rendered. Beyond the immediate fix, this established a general discipline.

## Decision

When a rendered artifact (annotation, label, JSON path) **references another artifact by name**, both the reference and its referent MUST be gated on the same condition. If either is conditional on operator config, the other follows the same conditional.

For the `ip_whitelist` case, the condition is `context.instance.config.ip_whitelist` being truthy (non-`None` and non-empty list). Python truthiness over `list[str] | None` covers both the unset and the explicitly-empty cases with one check. The gate appears in **both** render paths:

- The Jinja template `ingress-controller-chart-values.j2.yaml` wraps the `acl` Middleware entry in `{% if context.instance.config.ip_whitelist %}…{% endif %}`.
- `IngressUtility.build_app_post_rendering_patches` adds the `traefik.ingress.kubernetes.io/router.middlewares` annotation only when the same truthy check holds.

## Consequences

- A non-existent `Middleware` reference can no longer slip into a deployed Ingress through code-review oversight — the gating discipline catches the asymmetry.
- The "no filtering" path is genuinely no-filtering: neither the annotation nor the Middleware is materialised, so there is no dangling reference and no resource that exists "just in case".
- The pattern composes for future referencing artifacts (e.g., other Traefik plugin annotations pointing at platform-managed resources, label selectors targeting platform-managed labels): wherever a rendered name references a rendered object, both gates live in lockstep.
- The cost: every conditional reference requires two coordinated changes. This is rarely a real burden — the conditions are usually a single config attribute — but reviewers should explicitly check both sides when a new conditional reference lands.

## Alternatives Considered

- **Always render the Middleware with a default allow-all `sourceRange`**: rejected. Changes the operator's intent (they didn't opt into filtering), creates spurious cluster-side resources that have to be reasoned about by operators reading manifests, and the e2e suite would lose its "no-filtering" path entirely.
- **Validate at config-submission time and reject deployments with an enabled ingress utility but no `ip_whitelist`**: rejected. Turns an optional field into a required one, breaks existing deployments, and adds a GraphQL/validation surface for a problem that's structurally fixable in the render layer.
- **Gate only the annotation, always render the Middleware**: rejected. Same problems as "always render with default allow-all" — material exists that the operator didn't ask for.
- **Gate only the Middleware, leave the annotation always rendered**: rejected — this is the exact failure mode that motivated the spec.
