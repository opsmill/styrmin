# End-to-end evidence: service ingress override (#598)

Task T033 (Constitution V). Test: T025, `backend/tests/e2e/test_service_ingress_override.py`.

## Result

- API variant: passed (run 4 below, on commit `55c002b32038b33ce330fffd283fce083a6b08c4`).
- UI variant: not run, deferred to T048. The UI driver rejects `config["services"]` until T042 adds the steps, so `[ui-chromium]` cannot pass yet.

## Final passing run (run 4)

- Node id: `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_moves_only_the_overridden_service[api-chromium]`
- Commit: `55c002b32038b33ce330fffd283fce083a6b08c4` (working tree clean when the run started).
- Started: 2026-11-10T11:43:15Z. Ended: about 2026-11-10T11:48:02Z (vCluster deleted).
- Command, from the repository root:

  ```bash
  sleep 86400 | PYTHONPATH=<scratchpad>/plugins INGRESS_DUMP=<scratchpad>/ingress-dump.txt \
    uv run pytest -p ingress_dump backend/tests/e2e/test_service_ingress_override.py \
    -k api-chromium -v -s --pdb 2>&1 | tee <scratchpad>/pdb.log
  ```

  Two differences from the command in AGENTS.md:
  - `sleep 86400` replaces `sleep infinity`. On macOS, `sleep infinity` exits at once with a usage error, so pdb reads end-of-file and quits. Runs 1 and 2 lost their cluster for that reason.
  - `-p ingress_dump` loads a throwaway plugin kept outside the repository. After each of the three reads of the Ingress objects in the test, it runs `kubectl get ingress -o wide` and `-o yaml` against the vCluster and appends the output to a file. It does not change any assertion.
- vCluster: `pytest-7b21d3fe-8ce3-40eb-9437-c5903a7a0c09`.
- Kubeconfig: `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1415/vcluster0/kubeconfig` (also reachable as `pytest-current`; the vCluster is deleted at the end of the session).
- Deployment namespace: `styrmin-43180613-bb1e-41b9-bd86-1ad084619854`.
- Verbatim pytest output (ANSI colors removed; `-s` interleaves the vCluster log into the result line):

  ```text
  backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_moves_only_the_overridden_service[api-chromium] 12:43:18 warn There is a newer version of vcluster: v0.37.7. Run `vcluster upgrade` to upgrade to the newest version.
  ...
  PASSED12:47:55 info Removing vCluster container vcluster.cp.pytest-7b21d3fe-8ce3-40eb-9437-c5903a7a0c09...
  =========== 1 passed, 1 deselected, 4 warnings in 285.07s (0:04:45) ============
  ```

  The times in these lines are local time (UTC+1), so 12:43:18 is 11:43:18Z.

## Ingress objects on the vCluster of run 4

Copied from the output of `kubectl get ingress -n styrmin-43180613-bb1e-41b9-bd86-1ad084619854`. The vCluster has a dedicated ingress controller (Traefik), and `external_dns_endpoints_type` is `NodeExternalIP`.

### Before: no override

```text
NAME                       CLASS    HOSTS                                                                                                                   ADDRESS   PORTS   AGE
styrmin-infrahub-ingress   <none>   infrahub-enterprise-43180613-bb1e-41b9-bd86-1ad084619854.styrmin.com,infrahub-enterprise-test-environment.styrmin.com             80      76s
styrmin-svc-task-manager   <none>   task-manager-test-environment.styrmin.com                                                                                         80      73s
```

`styrmin-svc-task-manager`, built by Styrmin (the line breaks inside the `kopf.zalando.org/last-handled-configuration` value are cut here):

```yaml
metadata:
  annotations:
    external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"
    external-dns.alpha.kubernetes.io/endpoints-type: NodeExternalIP
    external-dns.alpha.kubernetes.io/hostname: styrmin-43180613-bb1e-41b9-bd86-1ad084619854-infrahub-enterprise.styrmin.com
    kopf.zalando.org/last-handled-configuration: '{"spec":{...},"metadata":{...}}'
    kubernetes.io/ingress.class: traefik
    traefik.ingress.kubernetes.io/router.entrypoints: web,websecure
  finalizers:
  - styrmin.io/kopf-finalizer
  labels:
    app.kubernetes.io/managed-by: styrmin
    styrmin.io/release-reference: ""
    styrmin.io/service-name: task-manager
    styrmin.io/utility-kind: ingress
  name: styrmin-svc-task-manager
  resourceVersion: "1733"
spec:
  rules:
  - host: task-manager-test-environment.styrmin.com
    http:
      paths:
      - backend:
          service:
            name: task-manager
            port:
              number: 4200
        path: /
        pathType: Prefix
```

`styrmin-infrahub-ingress`, rendered by the Helm chart (annotations `external-dns.alpha.kubernetes.io/hostname`, `kubernetes.io/ingress.class: traefik`, `traefik.ingress.kubernetes.io/router.entrypoints` and `external-dns.alpha.kubernetes.io/endpoints-type` are the ones that the post-render patch sets):

```yaml
metadata:
  annotations:
    external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"
    external-dns.alpha.kubernetes.io/endpoints-type: NodeExternalIP
    external-dns.alpha.kubernetes.io/hostname: styrmin-43180613-bb1e-41b9-bd86-1ad084619854-infrahub-enterprise.styrmin.com
    kubernetes.io/ingress.class: traefik
    meta.helm.sh/release-name: styrmin-43180613-bb1e-41b9-bd86-1ad084619854
    traefik.ingress.kubernetes.io/router.entrypoints: web,websecure
  name: styrmin-infrahub-ingress
  resourceVersion: "1579"
  uid: b947777e-2c17-4177-b3c4-08a20b2e36d6
spec:
  rules:
  - host: infrahub-enterprise-43180613-bb1e-41b9-bd86-1ad084619854.styrmin.com
  - host: infrahub-enterprise-test-environment.styrmin.com
    # both route / to service styrmin-infrahub-infrahub-server, port 8000
```

### After: override on `task-manager` (class `tailscale`, suffix `tailnet.example.ts.net`)

```text
NAME                       CLASS       HOSTS                                                                                                                   ADDRESS   PORTS   AGE
styrmin-infrahub-ingress   <none>      infrahub-enterprise-43180613-bb1e-41b9-bd86-1ad084619854.styrmin.com,infrahub-enterprise-test-environment.styrmin.com             80      103s
styrmin-svc-task-manager   tailscale   task-manager-test-environment.tailnet.example.ts.net                                                                              80      100s
```

```yaml
metadata:
  annotations:
    kopf.zalando.org/last-handled-configuration: '{"spec":{"ingressClassName":"tailscale",...}}'
    kubernetes.io/ingress.class: tailscale
  generation: 4
  name: styrmin-svc-task-manager
  resourceVersion: "2520"
  uid: d13d24b5-46cf-4f7d-99aa-33b767d91350   # same object as before: updated, not recreated
spec:
  ingressClassName: tailscale
  rules:
  - host: task-manager-test-environment.tailnet.example.ts.net
    http:
      paths:
      - backend:
          service:
            name: task-manager
            port:
              number: 4200
        path: /
        pathType: Prefix
```

The Ingress has only the class annotation: the entry-point, external-dns and Cloudflare annotations are gone, as FR-004 requires. `styrmin-infrahub-ingress` still has `resourceVersion: "1579"` and the same annotations, so Kubernetes did not write it between the two reads.

### After: override cleared

```text
NAME                       CLASS    HOSTS                                                                                                                   ADDRESS   PORTS   AGE
styrmin-infrahub-ingress   <none>   infrahub-enterprise-43180613-bb1e-41b9-bd86-1ad084619854.styrmin.com,infrahub-enterprise-test-environment.styrmin.com             80      2m11s
styrmin-svc-task-manager   <none>   task-manager-test-environment.styrmin.com                                                                                         80      2m8s
```

## Earlier runs on the way to the pass

All on the API variant, same node id.

1. Run 1 (started 2026-11-10T11:18:58Z, tree at `ad1e5673`): failed. `_split` found only `styrmin-infrahub-ingress`; `styrmin-svc-task-manager` was never created.
   - Found: the operator log shows `ingresss.networking.k8s.io is forbidden ... cannot create resource "ingresss"` (403), repeated on every reconcile. `apply_kubernetes_resource` had no branch for `Ingress`, so it went down the custom resource path and built the plural `ingresss`. The Prefect path (`apply_utility_resources`) logs and swallows the `ApiException` of a resource with a group in its `apiVersion`, so it hid the error.
   - Changed: `primitives.py` creates the Ingress with the networking API and replaces it on 409. New tests in `backend/tests/unit/agent/test_apply_ingress.py` failed before the change and pass after.
   - Also: pdb quit at once because of the macOS `sleep infinity` problem above, so the vCluster was gone before I could use `kubectl`. The diagnosis comes from the cluster log that the fixtures dump at teardown (`pdb-iter1.log` in the scratchpad).
2. Run 2 (11:25:05Z, uncommitted fix): failed at the assertion on the annotations of the Ingress without an override.
   - Found 1: `kopf.zalando.org/last-handled-configuration`. The operator watches the Ingress that Styrmin builds, so kopf writes its bookkeeping annotation. It is not an annotation set by Styrmin's rules.
   - Found 2 (a product defect, visible in the same assertion output): `external-dns.alpha.kubernetes.io/hostname` was `-infrahub-enterprise.styrmin.com`, with no release reference. The operator's periodic reconciliation reads the release reference from a HelmRelease label that a CRD-managed HelmRelease does not have, so it passed an empty value.
   - Changed 1: `build_ingress_settings` uses `context.instance.release_reference` when the passed value is empty (test `test_the_operator_without_a_release_reference_label_gets_the_context_one` failed before and passes after).
   - Changed 2: the test leaves out `kopf.zalando.org/*` annotations in every comparison (`_annotations`), and now asserts that the host name annotation of the Ingress that Styrmin builds equals the one of the chart Ingress. The second assertion is stricter than before; the first narrows the comparison to the annotations that Styrmin sets, and says so in the test.
3. Run 3 (11:32:08Z, same fixes but uncommitted): passed, `1 passed, 1 deselected, 4 warnings in 302.93s (0:05:02)`. Not used as the evidence, because the tree was not committed.
4. Run 4: the final run above.

## First creation of the Ingress: operator pipeline

Question: does `_is_service_or_middleware` and `execute_phase_services` in `backend/styrmin_backend/operator/pipeline.py` leave out `Ingress`, so that the first creation waits for a timer?

- Observed on the real stack (log of run 2): `Created Ingress/styrmin-svc-task-manager` is written by the HelmRelease timer `kopf_helmrelease_timer`, in the same pass that creates the NetworkPolicies, Services and the Secret, about one second after the deployment is created. The services phase (`execute_phase_services`) ran later and applied only `Middleware/auth` and the two Services, as the code reads.
- So the Ingress is not created by the services phase. It is created by the periodic reconciliation, like the Services and the Secret, so the Ingress exists before the Helm release is ready. In the end-to-end run the interval is 5 seconds (`STYRMIN_OPERATOR_RECONCILE_INTERVAL` in `backend/tests/e2e/fixtures/styrmin-values.yaml`); the default is 60 seconds (`SETTINGS.operator.reconcile_interval`), so on a default install the first creation can take up to that long after the HelmRelease exists. That default delay was not measured.
- Decision: not changed. The Ingress is created in time, and adding it to the phase would create it with the release reference label of the CRD while the timer lists objects by the empty label of the HelmRelease. That would make the timer rewrite the object on each pass.

## Not verified

- Traffic. The test asserts Kubernetes objects. No Tailscale ingress controller runs in the fixtures, so nothing proves that the overridden host answers. `test_infrahub_services.py` covers the Prefect UI through the dedicated Traefik; it was not run in this chunk. I read it: it looks for the host `task-manager-test-environment.styrmin.com` and sends traffic with that `Host` header through Traefik. The Ingress that Styrmin builds has that host, path `/`, and `kubernetes.io/ingress.class: traefik`, so the assertions look unchanged, but this is by reading.
- The UI variant (deferred to T048).
- The label `styrmin.io/release-reference: ""` on the Ingress that the operator builds. It is empty because of the same missing HelmRelease label. The kopf drift handlers on utility resources read that label to find the HelmRelease. This is the existing behavior of every Styrmin-built utility resource, and was not changed.
- The message "the CRD type may not be installed yet" in `apply_utility_resources` is also logged when an Ingress fails to apply, which hid the 403 of run 1. Not changed.
- Other end-to-end tests with `AsyncIngress` (`test_ingress_controller.py`, `test_cluster_update.py`, `test_environment_update.py`, `test_deployments_apply.py`, `configuration/test_drawer_networking_edit.py`) were read for assertions on the Prefect Ingress of the chart and on Ingress counts. They use other drivers than Infrahub Enterprise, so no assertion changed; they were not run.
