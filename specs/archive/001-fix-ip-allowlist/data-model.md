# Phase 1 Data Model: Activate Per-Deployment IP Allowlist Enforcement

**Branch**: `001-fix-ip-allowlist`
**Date**: 2026-04-28

This change introduces no new persistent entities, no GraphQL types, no SDK models, and no database tables. The "data model" relevant to this feature is the **shape of Kubernetes resources** rendered per deployment by `IngressUtility`, and the existing config field `ip_whitelist` that drives them.

---

## Existing config field (read by this feature)

| Field | Location | Type | Default | Notes |
|-------|----------|------|---------|-------|
| `ip_whitelist` | `EnvironmentConfig` (`backend/styrmin_backend/context/models/config.py:373`) | `list[str] \| None` | `None` | List of CIDR strings; merged into `ResolvedConfig` via `DeploymentConfig`. Read by both the Jinja template (`{{ context.instance.config.ip_whitelist }}`) and the new annotation builder. |
| `dedicated_ingress` | `EnvironmentConfig` | `DedicatedIngressConfig \| None` | `None` | Independent of this feature; controls separate annotations. Documented here only because `IngressUtility.build_app_post_rendering_patches` already inspects it on adjacent code paths. |
| `deployment_id` | `InstanceContext` (`context/models/contexts.py:91`) | `UUID` | required | Used (via `get_kubernetes_reference()`) to derive the namespace prefix that names the `acl` Middleware. |

**No fields are added, removed, or renamed.** The change is read-only with respect to the config schema.

---

## Kubernetes resources rendered per deployment

For each deployment that has `IngressUtility` in its utility set, the agent renders resources into the deployment's namespace `styrmin-<deployment_id>`. The two resources affected by this feature:

### A. Traefik `IPAllowList` Middleware (named `acl`)

| Property | Value | Source |
|----------|-------|--------|
| `apiVersion` | `traefik.io/v1alpha1` | `ingress.py:131` |
| `kind` | `Middleware` | `ingress.py:132` |
| `metadata.name` | `acl` (bare; deployment namespace already disambiguates) | Jinja template, line 3 |
| `metadata.namespace` | `styrmin-<deployment_id>` | passed by `build_resources(namespace=...)` |
| `spec.ipAllowList.sourceRange` | value of `context.instance.config.ip_whitelist` | Jinja template, line 6 |
| `spec.ipAllowList.ipStrategy.depth` | `1` (unchanged) | Jinja template, line 8 |

**New rule**: this resource is rendered ONLY when `context.instance.config.ip_whitelist` is non-empty. When `ip_whitelist` is `None` or `[]`, the entire entry is skipped via a Jinja `{% if %}` guard. All other resources in the same template (the `auth` Middleware, secrets, network policies) are unaffected.

### B. Application Ingress annotation

| Annotation key | Value | Presence |
|----------------|-------|----------|
| `traefik.ingress.kubernetes.io/router.entrypoints` | `web,websecure` | always (when `IngressUtility` enabled) |
| `external-dns.alpha.kubernetes.io/hostname` | `<release_reference>-<app_name>.<fqdn_suffix>` | always |
| `external-dns.alpha.kubernetes.io/cloudflare-proxied` | `true` | always |
| `kubernetes.io/ingress.class` | `<dedicated_ingress.implementation>` or `<ingress_class>` | when one of those is set |
| **`traefik.ingress.kubernetes.io/router.middlewares`** | **`styrmin-<deployment_id>-acl@kubernetescrd`** | **NEW: only when `ip_whitelist` is non-empty** |

The new annotation key is added to the same `annotations` dict that already governs the others; it does not introduce a new patch type.

---

## State transitions

There are no entity state transitions. The feature is a render-time decision: for a given `(context, release_reference)`, the same gating logic produces the same resource set on every reconcile. This satisfies Constitution Principle I (Declarative State Reconciliation) and ensures idempotence.

When the operator changes `ip_whitelist` (set → updated → unset), the next reconcile run produces the new resource set: the Middleware is created/updated/deleted, and the annotation is added/updated/removed in lockstep. Traefik picks up Middleware changes without application restart, satisfying SC-005.
