# Contract: Application Ingress ↔ `acl` Middleware Wiring

**Branch**: `001-fix-ip-allowlist`
**Date**: 2026-04-28

This feature introduces no GraphQL or REST contract changes. The relevant contract is between Styrmin's resource builder (producer) and the Traefik ingress controller (consumer), expressed as the annotation that must appear on the Ingress for IP allowlist enforcement to take effect. This document fixes that contract so the builder and the consumer agree on key, value, and presence rules.

---

## Annotation contract

| Aspect | Specification |
|--------|---------------|
| **Annotation key** | `traefik.ingress.kubernetes.io/router.middlewares` |
| **Annotation value** | `<namespace>-acl@kubernetescrd` where `<namespace>` is `f"styrmin-{deployment_id}"` (the deployment's own namespace) |
| **Resource scope** | Application Ingress object emitted by Styrmin's `IngressUtility` |
| **Producer** | `IngressUtility.build_app_post_rendering_patches` (`backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py`) |
| **Consumer** | Traefik ingress controller (resolves `<namespace>-<name>@kubernetescrd` to a Traefik `Middleware` CRD in the deployment's namespace) |

### Format details

- `@kubernetescrd` is Traefik's provider suffix indicating the Middleware is a Kubernetes CRD (as opposed to one defined in static config). It is part of Traefik's documented annotation grammar; no escaping or alternative form.
- The namespace prefix and the Middleware name are joined by a single hyphen: `<namespace>-<name>@kubernetescrd`. The Middleware's bare name (`acl`) is intentional — see `ingress.py:90-93` for the rationale (per-namespace deployment makes prefixing internal references unsafe).

### Example values

For a deployment with `deployment_id = 6f3309e3-b087-4bf1-9686-0f680e1099c2`:

- Namespace: `styrmin-6f3309e3-b087-4bf1-9686-0f680e1099c2`
- Annotation value: `styrmin-6f3309e3-b087-4bf1-9686-0f680e1099c2-acl@kubernetescrd`

---

## Presence rules

The annotation MUST be present on the Ingress in **exactly one** of the following situations:

| `IngressUtility` enabled? | `ip_whitelist` value | Annotation rendered? | Middleware rendered? |
|---------------------------|----------------------|----------------------|----------------------|
| No | (any) | NO | NO |
| Yes | `None` (unset) | NO | NO |
| Yes | `[]` (empty list) | NO | NO |
| Yes | `["0.0.0.0/0"]` (allow-all) | YES | YES (admits everything) |
| Yes | `["10.0.0.0/8", "192.168.1.0/24"]` (multi-CIDR) | YES | YES (admits union) |
| Yes | `["203.0.113.5/32"]` (narrow) | YES | YES (admits one) |

**Invariant**: the annotation MUST appear if and only if the `acl` Middleware is rendered. There is no valid configuration in which one exists without the other.

---

## Negative tests (what the producer must NOT do)

- MUST NOT emit the annotation with a `release_reference`-prefixed namespace. `release_reference` is the Helm release name; the Middleware lives in the namespace, not in any release-derived namespace. (This was the latent bug in the originally-commented code.)
- MUST NOT emit the annotation when the Middleware is not also rendered. Doing so produces a dangling reference and Traefik logs/refuses to apply the route.
- MUST NOT render the Middleware with `sourceRange: None` or `sourceRange: []`. Traefik's IPAllowList CRD validation rejects empty `sourceRange`. The Jinja `{% if %}` guard prevents this case from reaching Traefik.

---

## Consumer assumptions (Traefik behavior, unchanged by this feature)

The following are existing Traefik behaviors that the spec relies on but does not modify:

- Traefik resolves `<namespace>-<name>@kubernetescrd` against `Middleware` CRDs in the cluster.
- Traefik applies the Middleware to all routes derived from Ingresses carrying the annotation.
- For `IPAllowList`, the documented response on a denied source is HTTP 403 Forbidden.
- `ipStrategy: depth: 1` (set in the existing template) makes Traefik trust the X-Forwarded-For header at depth 1; the source IP that gets allowlist-checked is the IP just before Traefik in the proxy chain.

These behaviors define the contract from the consumer side and are referenced by the e2e test (see [quickstart.md](../quickstart.md)).
