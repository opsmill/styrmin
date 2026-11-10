# End-to-end evidence: service ingress override (#598)

Task T033 (Constitution V). Test: T025, `backend/tests/e2e/test_service_ingress_override.py`.

## Result

- API variant: passed (run 4 below, on commit `55c002b32038b33ce330fffd283fce083a6b08c4`).
- UI variant: passed in T048, on commit `7bcc9576441aba62b3e6f96604e46bb32cb9762f` (see the last section of this file, "T048: UI variant").

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

# End-to-end evidence: generic-app has one Ingress (T034, T037) and simple-app has no Styrmin-built Ingress (T038)

Tests (both API variant only):

- T034 and T037: `backend/tests/e2e/test_deploy_generic_app.py::test_deploy_generic_app[api-chromium]`. The test is `@pytest.mark.api_only`, so `[ui-chromium]` is skipped by design.
- T038: `backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[api-chromium]`. The assertion (SC-003) went into this existing test, which reads the session `deployed_simple_app` stack. That fixture has many active consumers (64 uses in `backend/tests/e2e`), so no stack was added. The test has no `api_only` or `ui_only` marker, so a `[ui-chromium]` variant exists. It was not run: the assertion reads Kubernetes objects through kr8s and is the same in both variants. This is a decision, not a verified result.

## Failing run before the driver change (T034 fails for the right reason)

- Started 2026-11-10T11:51:48Z (`run0.start`), tree at `7ebf1433304a98e56922f02dd884679c166644ca` plus the uncommitted test change; the driver was still version 1.
- Command: `sleep 86400 | uv run pytest backend/tests/e2e/test_deploy_generic_app.py -k api-chromium -v -s --pdb`.
- Result: failed at the new assertion:

  ```text
  AssertionError: Expected the Ingress that Styrmin builds for the app service and no chart Ingress: ['styrmin-app', 'styrmin-svc-app']
  ```

- `kubectl get ingress -A -o wide` at the pause (vCluster `pytest-270eba13-9cb8-4fd2-ba18-3d66398f4494`): two Ingresses on the same two hosts, `styrmin-app` (the chart Ingress of version 1) and `styrmin-svc-app` (built by Styrmin). This is the double Ingress of FR-012 and SC-006.
- After `pkill -f pytest` the vCluster container stayed up. I removed it with `vcluster delete pytest-270eba13-9cb8-4fd2-ba18-3d66398f4494 --driver docker`.

## Run on the final code (T037, T038)

- Run 1 (11:56:10Z, uncommitted tree, driver version 2): `2 passed in 222.55s` (vCluster `pytest-6c8f317d-3169-4778-a028-332343f804d6`). Not the evidence: the tree was not committed, and the namespace is gone before a `kubectl` read.
- Final run (run 2): commit `790198b99e3a16235a3d7f4b462b71cf4192187b`, tree clean, started 2026-11-10T12:05:25Z, ended about 2026-11-10T12:09:07Z.
- Command, from the repository root:

  ```bash
  sleep 86400 | PYTHONPATH=<scratchpad>/plugins INGRESS_DUMP=<scratchpad>/ingress-dump2.txt \
    uv run pytest -p generic_dump \
    "backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[api-chromium]" \
    "backend/tests/e2e/test_deploy_generic_app.py::test_deploy_generic_app[api-chromium]" \
    -v -s --pdb 2>&1 | tee <scratchpad>/pdb2.log
  ```

  `-p generic_dump` is a throwaway plugin outside the repository. After the test reads the Ingress objects of the generic-app namespace, it runs read-only `kubectl get ingress -o wide` and `-o yaml` and appends the output to a file. It changes no assertion. `sleep 86400` replaces `sleep infinity` for the macOS reason in the T033 section.
- vCluster: `pytest-c3d7beeb-b2c3-4e35-9497-865a0089af00`.
- Kubeconfig: `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1420/vcluster0/kubeconfig` (the vCluster is deleted at the end of the session).
- Verbatim pytest output (ANSI colors removed; `-s` interleaves the vCluster log with the result lines; the first `PASSED` line is cut off from its node id by the same interleaving):

  ```text
  backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[api-chromium] 13:05:28 warn There is a newer version of vcluster: v0.37.7. Run `vcluster upgrade` to upgrade to the newest version.
  ...
  PASSED
  backend/tests/e2e/test_deploy_generic_app.py::test_deploy_generic_app[api-chromium] PASSED13:09:07 info Removing vCluster container vcluster.cp.pytest-c3d7beeb-b2c3-4e35-9497-865a0089af00...
  ================== 2 passed, 6 warnings in 224.42s (0:03:44) ===================
  ```

  The times in these lines are local time (UTC+1).

### Ingress of the generic-app deployment, before the deletion

Output of `kubectl get ingress -n styrmin-32abb8c7-a9e1-4835-86db-279c1ce07b5c -o wide`, read at 2026-11-10T12:08:21Z:

```text
NAME              CLASS    HOSTS                                                                                                ADDRESS   PORTS   AGE
styrmin-svc-app   <none>   app-scenario-env-4a0a96d1.styrmin.com,generic-app-32abb8c7-a9e1-4835-86db-279c1ce07b5c.styrmin.com             80      12s
```

Same Ingress as YAML (the `kopf.zalando.org/last-handled-configuration` annotation is left out; it repeats the spec):

```yaml
metadata:
  annotations:
    external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"
    external-dns.alpha.kubernetes.io/endpoints-type: NodeExternalIP
    external-dns.alpha.kubernetes.io/hostname: styrmin-32abb8c7-a9e1-4835-86db-279c1ce07b5c-generic-app.styrmin.com
    kubernetes.io/ingress.class: traefik
    traefik.ingress.kubernetes.io/router.entrypoints: web,websecure
  labels:
    app.kubernetes.io/managed-by: styrmin
    styrmin.io/release-reference: ""
    styrmin.io/service-name: app
    styrmin.io/utility-kind: ingress
  name: styrmin-svc-app
spec:
  rules:
  - host: app-scenario-env-4a0a96d1.styrmin.com      # readable host
  - host: generic-app-32abb8c7-a9e1-4835-86db-279c1ce07b5c.styrmin.com   # application address
    # both route / to service app, port 8080
```

The Ingress was created about 11 seconds before the read, by the operator's HelmRelease timer (see the T033 section), so the test polls for it (`_wait_for_service_ingress`).

### What the tests assert

- T034: the namespace holds only `styrmin-svc-app`; its two hosts are the `primary_fqdn` and `human_readable_fqdn` that the deployment reports; the backend is service `app` on port 8080; the annotation keys are the five that the chart patch set on the former chart Ingress; the class is the dedicated controller's (`kubernetes.io/ingress.class: traefik`, no `spec.ingressClassName`); the host name annotation starts with the release reference; no `spec.tls`. Then `deployments.delete` and `wait_for_deployment_status(..., "deleted")`; the namespace then holds no Ingress. The assertion that the Ingress is gone passes also because the namespace is deleted with the deployment; it does not show that the operator deletes an Ingress on its own.
- T038: the namespace of `simple-app` holds exactly one Ingress, `styrmin-simple-app` (the chart Ingress), and it has no `styrmin.io/service-name` label.

### Not verified

- Traffic to the generic-app host through the Ingress. The test asserts the object, and the existing check of the application through a port-forward to the Service is unchanged.
- The `[ui-chromium]` variant of `test_deploy_simple_app` (see above).
- The T038 assertion was not run on a base commit to show that it would fail with a Styrmin-built Ingress for an internal service. The unit tests of T009 (`test_no_ingress_for_an_internal_service`) cover that case.
- The unit test of T035 was not added: `test_the_application_address_is_on_exactly_one_ingress` and `test_the_application_address_is_only_on_the_first_declared_service` in `backend/tests/unit/agent/test_ingress_utility_service_ingress.py` (T009) already assert that exactly one Ingress has the application address with two and three external services.

### Other example drivers with an external service and a chart Ingress

Checked in `driver/examples/*/driver.styrmin.yml` and `values.j2.yml`: only `generic-app` and the two Infrahub drivers (done in T031 and T032) declare a service `scope: external`. `semaphore`, `simple-app`, `db-test` and `infrahub-mcp` declare `scope: internal`. `slurpit` declares no services. `semaphore`, `simple-app` and `slurpit` render a chart Ingress and keep it (SC-003).


# T048: UI variant of the service ingress override test (#598)

Task T048 (Constitution V). Test: T025, `backend/tests/e2e/test_service_ingress_override.py`, variant `[ui-chromium]`. The Playwright MCP server was not available in this session (no such tool was listed), so no browser debugging session was needed or used; the one failure showed its cause in the pytest traceback.

## Result

- `[ui-chromium]`: passed on a clean working tree, commit `7bcc9576441aba62b3e6f96604e46bb32cb9762f`.
- `[api-chromium]`: passed again on the same commit (backend source changed in this chunk: the FQDN suffix validator).
- `cd frontend && pnpm test`: 103 files, 1198 tests passed (2026-11-10, after the commit above). `pnpm lint`: 0 errors, 35 warnings (not compared with the base commit). `pnpm exec tsc -b`: no errors.
- `uv run invoke test`: 5970 passed, 8 skipped, 1 failed: `tests/unit/services/telemetry/test_sender.py::test_send_report_returns_false_when_the_connection_is_refused` (`assert 7.82 < 2`), the failure known before this chunk.

## Failed iteration 1

- Command: the one below, on commit `933ab8b05e0005f11d6aef59663a667b8b44f5eb` (clean tree), started 2026-11-10T12:30:24Z; vCluster `pytest-acb22a15-773a-425c-97d3-ee05f80f448e`, kubeconfig `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1421/vcluster0/kubeconfig`.
- What failed: `DeployFormPage.read_service_ingress_fields` at `deploy_form.py:96` (`_select_driver`): `Locator.click: Timeout 30000ms exceeded ... waiting for locator("[data-testid=driver-version-select]")`.
- Cause: a test bug, not a UI bug. The test called `read_service_ingress_fields` without opening the deploy form, so the page was not on the deploy form and had no driver select (which page it was on was not recorded). The method selects the driver but does not navigate.
- Change: the test opens the form with `DeployFormPage.goto(environment_id=...)` before the call. The assertion (`== ["task-manager"]`) is unchanged. No assertion was weakened and no source file of the product changed.
- After `pkill -f pytest`, the vCluster container stayed up; it was removed with `vcluster delete pytest-acb22a15-773a-425c-97d3-ee05f80f448e --driver docker`.

## Run 2 (pass, tree not clean)

- Started 2026-11-10T12:36:46Z (about; local 13:36:46 in the log), vCluster `pytest-67498153-1020-4938-b838-55ecfa803a5c`, kubeconfig `.../pytest-of-Simon/pytest-1422/vcluster0/kubeconfig`.
- Passed in 310.04 s, with the test fix from iteration 1 not yet committed. It is repeated below on a clean tree.

## Final passing run of the UI variant (run 3)

- Node id: `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_moves_only_the_overridden_service[ui-chromium]`
- Commit: `7bcc9576441aba62b3e6f96604e46bb32cb9762f` (`git status --short` empty when the run started).
- Started 2026-11-10T12:42:56Z; ended about 2026-11-10T12:48:03Z (vCluster deleted).
- Command, from the repository root:

  ```bash
  sleep 86400 | uv run pytest "backend/tests/e2e/test_service_ingress_override.py" -k ui-chromium -v -s --pdb > <scratchpad>/pdb-ui-3.log 2>&1
  ```

  `sleep 86400` replaces `sleep infinity` because `sleep infinity` exits at once on macOS (see the T033 section).
- vCluster: `pytest-ac8749e7-c2d0-4f11-a3ee-50422d7b6e9f`.
- Kubeconfig: `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1423/vcluster0/kubeconfig` (the vCluster is deleted at the end of the session).
- Verbatim pytest output (ANSI colors removed; `-s` interleaves the vCluster log into the result line; times are local, UTC+1):

  ```text
  backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_moves_only_the_overridden_service[ui-chromium] 13:42:58 warn There is a newer version of vcluster: v0.37.7. Run `vcluster upgrade` to upgrade to the newest version.
  ...
  PASSED13:47:57 info Removing vCluster container vcluster.cp.pytest-ac8749e7-c2d0-4f11-a3ee-50422d7b6e9f...
  =========== 1 passed, 1 deselected, 4 warnings in 306.70s (0:05:06) ============
  ```

## Run of the API variant on the final commit

- Node id: `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_moves_only_the_overridden_service[api-chromium]`
- Commit: `7bcc9576441aba62b3e6f96604e46bb32cb9762f`, clean tree. Started 2026-11-10T12:48:35Z, ended about 2026-11-10T12:54:03Z.
- Command: the same as above with `-k api-chromium`, log `<scratchpad>/pdb-api.log`.
- vCluster: `pytest-53b79d0c-9183-47a8-be7d-bea6a7ca39fc`; kubeconfig `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1424/vcluster0/kubeconfig`.

  ```text
  PASSED13:54:03 info Removing vCluster container vcluster.cp.pytest-53b79d0c-9183-47a8-be7d-bea6a7ca39fc...
  =========== 1 passed, 1 deselected, 4 warnings in 333.56s (0:05:33) ============
  ```

## What the UI variant covers

Steps that run only in `[ui-chromium]`, all against the real UI:

- Deploy form: opens `/environments/<id>/deploy`, selects the `infrahub-enterprise` driver version, and reads the labels `Ingress class for <name>` inside the group `Service ingress overrides`. The test asserts that the list is exactly `["task-manager"]`: the form offers the fields for the external service and none for `infrahub`. The form is not submitted, so no second Infrahub stack is deployed.
- Networking summary on the Settings tab: before the override, with it, and after it is cleared, the group `task-manager` shows the class and host with the marks Inherited, Overridden and Inherited.
- Setting and clearing the override: both changes go through the Settings edit drawer (section Services: the two fields, the button `Clear ingress override for task-manager`) and Review & apply. The assertions on the Ingress objects, the reported addresses and the Prefect UI API address are the same as in the API variant.

## Not verified

- Deploy form: a deployment created with an override typed into the form is not covered. No test fills the fields and submits the form, because that needs a second Infrahub stack. Vitest covers the form (`__tests__/deploy-form/DeployFormPage.test.tsx`, 5 tests), not the end-to-end path from the form to the Ingress.
- The deploy form step checks which fields exist, not that an invalid suffix blocks Deploy (covered in Vitest only). The end-to-end test does not type an invalid suffix in the drawer.
- Traffic: the test reads objects on the vCluster; no ingress controller of class `tailscale` runs, and no request is sent to a host.
- UI visuals: selectors, labels, roles and text are checked; layout, colors and the position of the marks are not.
- The test was run on one machine (macOS, Docker); the CI matrix was not run.

## T054: refusals name the service (`api_only`)

Node id: `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_refusals_name_the_service[api-chromium]`. The test is `api_only`, so it has no `[ui-chromium]` variant.

All runs below started on commit `f3f5668d8d92d41fe06c418b27bf94a66b6f270d` with an empty `git status --short`, except the control run, which carried one temporary edit (below). Times are UTC; the log times are local (UTC+1). `<scratchpad>` is `/private/tmp/claude-503/-Users-Simon-styrmin-598-spec/2ab6e2fa-7180-493d-8211-590f003133bd/scratchpad`. The kubeconfig of each run is under `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-<N>/vcluster0/kubeconfig` and is deleted with the session.

### Passing run (first run, no failed iteration)

- Started 2026-11-10T13:21:54Z, ended about 2026-11-10T13:26:50Z.
- Command, from the repository root (`sleep 86400` replaces `sleep infinity`, which exits at once on macOS):

  ```bash
  sleep 86400 | uv run pytest "backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_refusals_name_the_service" -k api-chromium -v -s --pdb > <scratchpad>/pdb-refusals.log 2>&1
  ```

- vCluster `pytest-7bea25d3-4cfa-47cd-b896-93fdd7a86559`; kubeconfig `.../pytest-of-Simon/pytest-1432/vcluster0/kubeconfig`.
- Verbatim pytest output (ANSI colors removed; `-s` interleaves the vCluster log into the result line):

  ```text
  backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_refusals_name_the_service[api-chromium] 14:21:57 warn There is a newer version of vcluster: v0.37.7. Run `vcluster upgrade` to upgrade to the newest version.
  ...
  PASSED14:26:46 info Removing vCluster container vcluster.cp.pytest-7bea25d3-4cfa-47cd-b896-93fdd7a86559...
  =========== 1 passed, 1 deselected, 4 warnings in 296.46s (0:04:56) ============
  ```

### What the test asserts on the real stack

- Scenario 1 (FR-009): `updateDeployment` with an override on the internal service `infrahub` fails with `SERVICE_INGRESS_NOT_BUILT`; `extensions` carry `service_name` `infrahub` and `scope` `internal`; the message contains `'infrahub'` and `does not build`.
- Scenario 2 (FR-010): a second driver build in which `task-manager` is internal. `updateDeploymentVersion` to it, once without `input` and once with the `input` that `apply` sends, fails with `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED`; `extensions` carry `service_name` `task-manager`, `reason` `internal`, `current_version` and `target_version`; the message contains `'task-manager'`.
- After each refusal: the list of task ids is unchanged (no task was started), the rollout state of the namespace is unchanged (the test compares the uid and the container restart counts of every pod, and the `generation` of the `task-manager` Deployment, which changes when its pod template changes; so no pod was replaced or restarted), the bound driver version and application version are unchanged, and the stored `config` is equal to the one before, so the override is still stored.
- The `finally` block clears the override so that the shared Infrahub stack stays as the other tests expect.

### Control run: the test fails when the source is wrong

A passing run proves little if the test cannot fail. The check for the version change was disabled for one run (`if False and current_version is not None and stored.get(name) == block:` in `backend/styrmin_backend/services/service_ingress/validator.py`; the edit was reverted with `git checkout` and is not committed).

- Started 2026-11-10T13:27:29Z; vCluster `pytest-572edbe9-6b57-4b7f-831d-89f5ff5518ad`; kubeconfig `.../pytest-1433/vcluster0/kubeconfig`.
- Result: `FAILED`, at `test_service_ingress_override.py:635`:

  ```text
  E  AssertionError: OperationFailedError("Service 'task-manager' has scope 'internal' in driver infrahub-enterprise version 6 (application version 1.7.0), so Styrmin does not build its Ingress and an ingress override has no effect. ...")
  E  assert 'SERVICE_INGRESS_NOT_BUILT' == 'SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED'
  ```

  Without the check, the request is refused for the wrong reason, and the test says so. The vCluster was removed with `vcluster delete pytest-572edbe9-6b57-4b7f-831d-89f5ff5518ad --driver docker` after `pkill -f pytest`.
- Scenario 1 was not given a control run. The functional test `backend/tests/functional/graphql/test_service_ingress_validation.py` and the unit tests of the validator cover it.

## Final-commit runs of `test_service_ingress_override_moves_only_the_overridden_service`

Part A changed backend source (`context/models/config.py`), so both variants were run again on commit `f3f5668d8d92d41fe06c418b27bf94a66b6f270d` (clean tree). The command is the one of the T048 section with `-k api-chromium` or `-k ui-chromium`.

| Variant | Started (UTC) | vCluster | Kubeconfig | Result |
|---|---|---|---|---|
| `[api-chromium]`, run 1 | 2026-11-10T13:32:56Z | `pytest-2e37ef5d-e736-48d4-8efc-ab5e26b88b5f` | `.../pytest-1434/vcluster0/kubeconfig` | FAILED (below) |
| `[api-chromium]`, run 2 | 2026-11-10T13:40:15Z | `pytest-dc422148-34c6-43b7-89ed-e539eadd9e7e` | `.../pytest-1435/vcluster0/kubeconfig` | passed |
| `[ui-chromium]` | 2026-11-10T13:45:33Z | `pytest-1fedb299-5207-46cd-b7bc-9918233cd675` | `.../pytest-1436/vcluster0/kubeconfig` | passed |

Verbatim pytest output of the passing runs:

```text
PASSED14:45:18 info Removing vCluster container vcluster.cp.pytest-dc422148-34c6-43b7-89ed-e539eadd9e7e...
=========== 1 passed, 1 deselected, 4 warnings in 307.61s (0:05:07) ============
```

```text
PASSED14:50:06 info Removing vCluster container vcluster.cp.pytest-1fedb299-5207-46cd-b7bc-9918233cd675...
=========== 1 passed, 1 deselected, 4 warnings in 278.84s (0:04:38) ============
```

### Failed run 1 of `[api-chromium]`: the release-reference label of the Ingress differs after the override is cleared

- Failing line: `assert _comparable(task_manager_cleared) == _comparable(task_manager_before)` (step "clear the override"). The only difference is the label `styrmin.io/release-reference` of the Ingress `styrmin-svc-task-manager`: `'styrmin-57254668-cd66-4b0a-a759-f93e9179ec09'` before and `''` after clearing. The label was still `''` when the vCluster was inspected about four minutes later (`kubectl get ingress -A`, saved in `<scratchpad>/ingress-after-fail.yaml`); the Ingress `resourceVersion` kept changing about every 6 seconds while its `generation` stayed 7.
- Not caused by this chunk: the commits since the last green run of this test (`7bcc9576`) change no operator, Ingress builder or label code (`git diff --stat 7bcc9576 HEAD -- backend/styrmin_backend` lists `inputs.py`, `config.py`, `deployment.py` and the new `service_ingress/` files only). The same node passed on run 2 and on the earlier runs of this evidence file.
- Cause: not proven. Observed in the source: the Ingress label comes from the `release_reference` passed to the builder (`builders/utility.py:39`). The StyrminDeployment timer passes the CRD's `releaseReference` (`operator/handlers/styrmin_deployment.py`, around line 990), and the HelmRelease timer passes the value of a HelmRelease label that a CRD-managed HelmRelease does not have, so it passes `''` (`operator/handlers/helmrelease.py:171,280`; the comment at `utilities/ingress.py:85` says so). The hypothesis is that, depending on which reconciler wrote last, the label is the real reference or `''`. This was not tested; the operator logs were not read.
- Nothing was changed for this failure: no assertion was weakened and no source was edited. It is open and listed as a risk for the final report. The run was repeated once on the same commit and passed.

## Not verified (T054)

- Traffic: the refusals are checked as GraphQL errors, cluster objects and task lists; no request was sent through an ingress controller.
- UI for the refusals: covered by Vitest only (`ConfigDiffDialog.test.tsx`, `DeployFormPage.test.tsx`, `UpgradeErrorAlert.test.tsx`), not by an end-to-end UI run, because the test is `api_only`.
- UI visuals (layout, colors) of the error alerts.
- The cause of the release-reference label difference above.
- The test ran on one machine (macOS, Docker); the CI matrix was not run.
