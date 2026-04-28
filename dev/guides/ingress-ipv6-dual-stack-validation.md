# Manual validation: dual-stack / IPv6 ingress pinning

This runbook bridges the gap until automated dual-stack E2E coverage lands
(tracked by `specs/001-ingress-ipfamily-nodeport/` follow-up). Operators
configuring `dedicated_ingress.service.ip_families` /
`dedicated_ingress.service.ip_family_policy` on a real cluster — typically
the Cloudflare/Infrahub recipe — should run these steps to confirm the
request actually pins the published Service to the desired IP family.

The rendering layer (config → Helm values → Service object) is covered by
unit tests and an automated E2E (`test_dedicated_ingress_service_overrides`).
The remaining gap is *cluster-side traffic*: that requires a dual-stack
cluster, which CI does not currently provide.

## 1. Cluster pre-flight

Confirm the target cluster actually has both IP families configured.

```bash
# Nodes report both v4 and v6 internal addresses.
kubectl get nodes -o wide

# The node spec lists both families under .status.addresses.
kubectl get --raw /api/v1/nodes | jq '.items[].status.addresses'
```

Expected: every node shows at least one `InternalIP` of each family
(`10.x.x.x` / `fd00::…` or similar). If the cluster only has IPv4,
`RequireDualStack` and `["IPv6"]`-pinned Services will fail to admit.

## 2. Apply a known-good config

Set on the **environment** config (or cluster, if the whole cluster shares
it):

```yaml
dedicated_ingress:
  service:
    type: NodePort         # or LoadBalancer — pick what your topology supports
    ip_families: ["IPv6"]
    ip_family_policy: SingleStack
```

For dual-stack publication (advertise both A and AAAA records), use:

```yaml
dedicated_ingress:
  service:
    ip_families: ["IPv4", "IPv6"]
    ip_family_policy: RequireDualStack    # only on clusters with both families
```

`PreferDualStack` is the looser variant that falls back to single-family
when the cluster cannot satisfy dual-stack admission.

Redeploy the affected environment so Styrmin re-renders the chart values
and the controller reconciles the Service.

## 3. Verification steps

### 3.1. Service object reflects the request

```bash
kubectl -n <ingress-controller-ns> get service styrmin-traefik -o yaml \
  | yq '.spec | {ipFamilies, ipFamilyPolicy, type, ports}'
```

Expect `spec.ipFamilies: [IPv6]` and `spec.ipFamilyPolicy: SingleStack`
(or your chosen pair). If the chart re-render dropped the keys, re-check
the rendered Helm values:

```bash
helm -n styrmin get values <release-name>
```

### 3.2. AAAA resolution publishes a v6 address

```bash
dig AAAA <fqdn>
```

Expect at least one `AAAA` record. (For `LoadBalancer` Services this
depends on your DNS controller publishing the LB's v6 address; for
`NodePort` it depends on the AAAA record you point at the node IPs.)

### 3.3. End-to-end v6 client request

From a v6-capable host:

```bash
curl -6 -v -H "Host: <expected-host>" "http://[<v6-address>]:<port>/health"
```

Expect a `200`. If the request hangs, inspect Traefik's logs and confirm
the listener actually bound on the v6 family.

## 4. Reporting

If any step fails, capture:

- `kubectl get service ... -o yaml`
- the rendered Helm values from `helm get values`
- the cluster's IP families (step 1)

…and file an issue against `specs/001-ingress-ipfamily-nodeport/` (the
follow-up automated dual-stack E2E will fold these checks into CI).
