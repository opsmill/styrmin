# Quickstart — external-dns endpoints-type

This walks an operator through using the new field, and an implementer through verifying it.

## Operator Walkthrough

### Goal

Make external-dns publish your workload **node's** external IPv6 (not the Service `ClusterIP`) as the AAAA record for each application hostname Styrmin manages.

### Prerequisites

- A Styrmin-managed cluster running on the dedicated-Traefik ingress path.
- external-dns installed in the cluster and configured to source records from Ingress objects (operator responsibility — out of scope for Styrmin; tracked in a sibling issue).
- Workload nodes with reachable external IPv6 addresses surfaced in their `Node.status.addresses` list.

### Step 1 — Set the field at the cluster layer

Edit the cluster config (via your usual GraphQL/SDK/Terraform path; here is the JSON shape):

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

### Step 2 — Reconcile

Trigger a reconcile of an existing deployment in that cluster (or wait for the next reconcile tick). No deployment-config change is required; the cluster-layer value inherits down through the Cluster → Environment → Deployment merge.

### Step 3 — Verify the rendered Ingress

```bash
kubectl -n styrmin-<deployment-id> get ingress -o yaml
```

You should see the new annotation alongside the existing two:

```yaml
metadata:
  annotations:
    external-dns.alpha.kubernetes.io/hostname: <release-ref>-<app>.infrahub.cloud.example.com
    external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"
    external-dns.alpha.kubernetes.io/endpoints-type: NodeExternalIP   # ← the new annotation
```

### Step 4 — Verify the AAAA record

After external-dns runs its next sync (typical 1-minute interval), inspect the AAAA record:

```bash
dig AAAA <release-ref>-<app>.infrahub.cloud.example.com
```

The address returned should be the node's external IPv6 — not the Service `ClusterIP`.

### Per-deployment override (optional)

Need a single deployment to opt **out** of the cluster-wide `NodeExternalIP` policy? Set `"external_dns_endpoints_type": "ClusterIP"` on that deployment's config. Deployment beats Cluster, mirroring the precedence already in use for `fqdn_suffix` / `ingress_class`.

### Rolling back

Remove the field entirely (or set it to `null`). The renderer reverts to emitting no `endpoints-type` annotation, and external-dns falls back to its default behaviour. No data migration, no manifest hand-patching.

---

## Implementer Walkthrough — Verifying the Change

### Unit tests (fast)

```bash
uv run pytest backend/tests/unit/agent/test_utility_resources.py::TestIngressUtilityPostRenderingPatches -v
```

Expected: the existing four tests pass, and the three new tests pass:

- `test_includes_endpoints_type_when_node_external_ip`
- `test_includes_endpoints_type_when_cluster_ip`
- `test_omits_endpoints_type_when_unset`

### Pydantic validation (manual smoke)

```bash
uv run python -c "
from styrmin_backend.context.models.config import ClusterConfig
ClusterConfig(external_dns_endpoints_type='PodIP')
"
```

Expected: `pydantic.ValidationError` naming the field and listing accepted values.

```bash
uv run python -c "
from styrmin_backend.context.models.config import ClusterConfig
print(ClusterConfig(external_dns_endpoints_type='NodeExternalIP'))
print(ClusterConfig(external_dns_endpoints_type=None))
print(ClusterConfig())
"
```

Expected: all three succeed, the last two have `external_dns_endpoints_type=None`.

### E2E test (vcluster)

```bash
sleep infinity | uv run pytest backend/tests/e2e/test_ingress_controller.py::test_deploy_with_dedicated_ingress -v -s --pdb 2>&1 | tee /tmp/pdb.log
```

(`sleep infinity |` keeps pdb's stdin open per AGENTS.md; use Ctrl-D / `pkill -f pytest` to terminate.)

Expected: the test passes. The new assertion (within the existing `for ing in ingresses:` loop) checks:

```python
assert annotations.get("external-dns.alpha.kubernetes.io/endpoints-type") == "NodeExternalIP"
```

This passes because the session cluster fixture in `backend/tests/e2e/conftest.py` (line ~665) was updated to include `"external_dns_endpoints_type": "NodeExternalIP"` in the cluster config dict, exercising the inheritance path through Cluster → Environment → Deployment → ResolvedConfig and out to the rendered Ingress annotations.

### Format and lint (required before commit)

```bash
uv run invoke format lint
```

Both must pass cleanly. No GraphQL or SDK regeneration is needed (no schema or operation changes).
