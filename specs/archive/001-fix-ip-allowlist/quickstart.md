# Quickstart: Verify IP Allowlist Enforcement Locally

**Branch**: `001-fix-ip-allowlist`
**Date**: 2026-04-28

This recipe walks through verifying the fix end-to-end on a local vcluster after the implementation lands. It assumes the standard dev setup (`tasks/dev.py`).

---

## Prerequisites

- Local dev cluster running. From repo root:

  ```bash
  uv run invoke dev.up
  ```

- `kubectl` pointed at the dev cluster's kubeconfig.
- `curl` and `jq` available locally.

---

## 1. Unit-level verification (fast)

Run the new unit test for `IngressUtility.build_app_post_rendering_patches`:

```bash
uv run pytest backend/tests/unit -k "test_build_app_post_rendering_patches" -v
```

Expected: passes; assertions cover

- annotation present and equals `styrmin-<deployment_id>-acl@kubernetescrd` when `ip_whitelist` is non-empty,
- annotation absent when `ip_whitelist` is `None` or `[]`,
- namespace prefix derived via `get_kubernetes_reference(deployment_id)`.

---

## 2. End-to-end verification (real cluster)

Run the extended ingress controller e2e (always with `--pdb` per AGENTS.md so a failure leaves the vcluster paused for inspection):

```bash
uv run pytest backend/tests/e2e/test_ingress_controller.py -v -s --pdb
```

The new scenario in this file:

1. Deploys a sample application via Styrmin with `ip_whitelist: ["0.0.0.0/0"]`, observes a successful HTTP 200, and records the source IP that Traefik sees (read from the application's request log or from a Traefik access log line).
2. Reconfigures the deployment to `ip_whitelist: ["<observed-source-ip>/32"]` and asserts the same client still gets HTTP 200.
3. Reconfigures the deployment to `ip_whitelist: ["192.0.2.0/24"]` (RFC 5737 TEST-NET-1, guaranteed not to match real traffic) and asserts the same client now gets HTTP 403.
4. Asserts that during step 3 the application's namespace shows a `Middleware/acl` resource with the narrow `sourceRange` AND the application's `Ingress` carries `traefik.ingress.kubernetes.io/router.middlewares: styrmin-<deployment_id>-acl@kubernetescrd`.

---

## 3. Manual probe (optional, for debugging)

While the e2e is paused at a failure (or after deploying manually), inspect the cluster directly:

```bash
# Find the deployment namespace
kubectl get ns | grep styrmin-

# Check the Middleware exists with the expected sourceRange
kubectl -n styrmin-<deployment_id> get middleware acl -o yaml | yq .spec.ipAllowList

# Check the Ingress carries the annotation
kubectl -n styrmin-<deployment_id> get ingress -o yaml | \
  yq '.items[].metadata.annotations | with_entries(select(.key | test("router.middlewares")))'

# Hit the deployment's hostname and confirm the response matches expectations
curl -sv -o /dev/null -w "%{http_code}\n" "https://<release_reference>-<app_name>.<fqdn_suffix>/"
```

Expected outputs:

- `Middleware/acl` is present iff `ip_whitelist` is non-empty.
- The `router.middlewares` annotation appears iff `Middleware/acl` is present.
- The HTTP status is `200` from an in-range source, `403` from an out-of-range source.

---

## 4. Verify no regression in adjacent fixtures

After the fixture migration, run the wider e2e suite to confirm no test was relying on the (formerly silent) `127.0.0.1` placeholder behavior:

```bash
uv run pytest backend/tests/e2e -v -s --pdb
```

Expected: all previously-passing scenarios still pass. Any failure here indicates a fixture not on the issue's update list and needs investigation before merge.

---

## Tearing down

```bash
uv run invoke dev.down
```
