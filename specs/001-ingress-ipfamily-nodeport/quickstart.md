# Quickstart — IP Family & Fixed NodePort Knobs

Operator-facing how-to for the three new fields on `dedicated_ingress.service`. All three are optional; omitting them preserves today's behavior exactly.

## Scenario A — Fixed NodePort for a Cloudflare origin

Goal: give Cloudflare (or any external load balancer) a stable NodePort that survives cluster restarts and Service recreations.

Set on the **environment** config (or cluster config, if the whole cluster shares it):

```yaml
dedicated_ingress:
  service:
    type: NodePort
    node_port: 30443     # any value in 1..65535; in practice 30000..32767 to fit the cluster's NodePort range
```

After redeploy, both Traefik entrypoints (`web` and `websecure`) bind to NodePort `30443` on every node. Point Cloudflare's origin at `<node-ip>:30443` and leave it.

Verify (single-family cluster works):

```bash
kubectl get svc -n <ingress-controller-ns> styrmin-traefik -o jsonpath='{.spec.ports[*].nodePort}'
# → "30443 30443" (one for web, one for websecure)
```

## Scenario B — Pin the Service to IPv6 on a dual-stack cluster

Goal: a Service that publishes only an IPv6 address on a cluster that has both IPv4 and IPv6 nodes (so DNS gets a stable AAAA record and Cloudflare's origin lookup hits v6).

Set on the **environment** config:

```yaml
dedicated_ingress:
  service:
    type: NodePort         # or LoadBalancer, depending on topology
    ip_families: ["IPv6"]
    ip_family_policy: SingleStack
```

For full dual-stack (advertise both A and AAAA), use:

```yaml
dedicated_ingress:
  service:
    ip_families: ["IPv4", "IPv6"]
    ip_family_policy: RequireDualStack    # only on clusters that have BOTH families configured
```

If you want dual-stack with single-family fallback, use `PreferDualStack` instead of `RequireDualStack`.

Verify on a dual-stack cluster:

```bash
kubectl get svc -n <ingress-controller-ns> styrmin-traefik -o jsonpath='{.spec.ipFamilies}{"\n"}{.spec.ipFamilyPolicy}'
# → ["IPv6"]
#   SingleStack
```

> **Manual validation runbook**: until automated dual-stack E2E coverage lands, the full IPv6 verification flow (cluster topology pre-flight, DNS AAAA lookup, end-to-end v6 client request) lives in `dev/guides/ingress-ipv6-dual-stack-validation.md`. Operators landing the Cloudflare/Infrahub recipe should run that runbook on the target cluster.

## Combined (the Cloudflare/Infrahub recipe)

```yaml
dedicated_ingress:
  service:
    type: NodePort
    node_port: 30443
    ip_families: ["IPv6"]
    ip_family_policy: SingleStack
```

This is the recipe the spec was written to enable: stable NodePort for the Cloudflare origin **and** Service pinned to IPv6 on a dual-stack cluster.

## Validation errors (config load)

You will see a `ValidationError` immediately at config load — before any cluster API call — for any of these:

| Bad config | Error |
|------------|-------|
| `ip_families: []` | `ip_families must not be empty when set; remove the field to use the cluster default.` |
| `ip_families: ["IPv6", "IPv6"]` | `ip_families must not contain duplicates; got ['IPv6', 'IPv6'].` |
| `ip_families: ["foo"]` | Pydantic Literal mismatch — `Input should be 'IPv4' or 'IPv6'`. |
| `ip_family_policy: "Whatever"` | Pydantic Literal mismatch — `Input should be 'SingleStack', 'PreferDualStack' or 'RequireDualStack'`. |
| `node_port: 0` or `65536` or `-1` | Pydantic range error — `Input should be greater than or equal to 1 / less than or equal to 65535`. |
| `type: "LoadBalancer"` + `node_port: 30443` | `node_port is only valid when type == 'NodePort'; got type='LoadBalancer' with node_port=30443.` |

## Backward compatibility

If you don't set any of the three new fields, the rendered Helm values are byte-identical to today's output, the existing snapshot tests pass without modification, and your existing deployments redeploy with no behavioral change.
