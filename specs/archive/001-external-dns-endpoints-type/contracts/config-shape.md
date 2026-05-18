# Contract: Config-shape and Rendered-Annotation

This feature adds **no new GraphQL operations** and **no new SDK methods**. The field rides through the existing `JSON | None` config payloads accepted by the `create_cluster`, `create_environment`, `create_deployment`, and `update_*` mutations, and through the existing `JSON` storage columns.

The "contract" this feature establishes is therefore narrower:

1. The shape of the JSON config payload that an operator may now send.
2. The shape of the Kubernetes Ingress annotation that Styrmin will emit.
3. The shape of the validation error returned for an invalid value.

---

## 1. Operator-Facing Config Payload

### 1a. Cluster-layer opt-in (typical IPv6/Cloudflare topology)

```json
{
  "fqdn_suffix": "infrahub.cloud.example.com",
  "ingress_class": "traefik",
  "dedicated_ingress": {
    "implementation": "traefik",
    "type": "ingress",
    "service": { "type": "LoadBalancer" }
  },
  "external_dns_endpoints_type": "NodeExternalIP"
}
```

### 1b. Deployment-layer override of cluster default

```json
{
  "external_dns_endpoints_type": "ClusterIP"
}
```

(applied to a single deployment that needs to opt out of the cluster-wide `NodeExternalIP` policy)

### 1c. Field absent (default — pre-feature behaviour)

```json
{
  "fqdn_suffix": "test.styrmin.com",
  "ingress_class": "traefik"
}
```

The renderer emits no `endpoints-type` annotation.

### 1d. Explicit null (equivalent to absent)

```json
{
  "external_dns_endpoints_type": null
}
```

Treated identically to "field absent" — Pydantic deserialises as `None`, renderer emits nothing.

---

## 2. Rendered Ingress Annotation

When the resolved config has `external_dns_endpoints_type` set to `"NodeExternalIP"` (or `"ClusterIP"`), the Ingress emitted by `IngressUtility.build_app_post_rendering_patches` carries the new annotation **alongside** the existing two `external-dns.alpha.kubernetes.io/*` annotations:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: web,websecure
    external-dns.alpha.kubernetes.io/hostname: <release-ref>-<app>.<fqdn_suffix>
    external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"
    external-dns.alpha.kubernetes.io/endpoints-type: NodeExternalIP   # ← NEW
    kubernetes.io/ingress.class: traefik   # only when dedicated_ingress or ingress_class is set
```

When the resolved config leaves the field unset, the rendered Ingress is **byte-identical** to the pre-feature output: no `endpoints-type` annotation key is present in the dict.

---

## 3. Validation Error Shape (invalid input)

Sending a payload with `external_dns_endpoints_type` set to anything other than `"NodeExternalIP"`, `"ClusterIP"`, `null`, or absent triggers a Pydantic `ValidationError` at config-parse time, surfaced through the existing GraphQL error path that already handles `external_url_scheme` violations.

**Example invalid payload**:

```json
{ "external_dns_endpoints_type": "PodIP" }
```

**Resulting Pydantic error message** (the verbatim format depends on Pydantic version; the contract is on the *content*):

```text
1 validation error for ClusterConfig
external_dns_endpoints_type
  Input should be 'NodeExternalIP' or 'ClusterIP'
  [type=literal_error, input_value='PodIP', input_type=str]
```

**Contract guarantees**:

- The error names the offending field (`external_dns_endpoints_type`).
- The error lists the accepted values (`'NodeExternalIP'`, `'ClusterIP'`).
- The error fires before any Kubernetes resource is rendered or applied (FR-005, SC-003).
- An unknown-key typo (e.g. `external_dns_endpoint_type` — missing `s`) triggers the existing `extra="forbid"` rejection rather than being silently dropped.

---

## What Is NOT a Contract Change

- **GraphQL schema (`schema.graphql`)**: no change. No regeneration of `python_sdk/src/styrmin_sdk/graphql/_generated/`.
- **Database schema**: no change. No new column, no new migration in `backend/styrmin_backend/db/migrations/versions/`.
- **SDK Python types**: no change.
- **Frontend types** (`frontend/src/sdk/...`): no change.
- **Driver specifications** (`driver/`): no change. Drivers do not consume `external_dns_endpoints_type`; only the rendering-time `IngressUtility` does.
- **Existing rendered annotations** for deployments that don't set the field: no change. Snapshot-style tests (`test_includes_external_dns_hostname`, `test_includes_cloudflare_proxied`) continue to pass without modification.
