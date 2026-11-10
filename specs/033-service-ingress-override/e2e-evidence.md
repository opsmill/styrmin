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
- The label `styrmin.io/release-reference: ""` on the Ingress that the operator builds. It is empty because of the same missing HelmRelease label. The kopf drift handlers on utility resources read that label to find the HelmRelease. This is the existing behavior of every Styrmin-built utility resource. It was a defect, fixed in commit `a0885121`; see the section "Release-reference label".
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
- Cause: found later, see the section "Release-reference label" at the end of this file. At the time of this run it was not proven. Observed in the source: the Ingress label comes from the `release_reference` passed to the builder (`builders/utility.py:39`). The StyrminDeployment timer passes the CRD's `releaseReference` (`operator/handlers/styrmin_deployment.py`, around line 990), and the HelmRelease timer passes the value of a HelmRelease label that a CRD-managed HelmRelease does not have, so it passes `''` (`operator/handlers/helmrelease.py:171,280`; the comment at `utilities/ingress.py:85` says so). The hypothesis is that, depending on which reconciler wrote last, the label is the real reference or `''`. This was not tested; the operator logs were not read.
- Nothing was changed for this failure: no assertion was weakened and no source was edited. It is open and listed as a risk for the final report. The run was repeated once on the same commit and passed.

## Not verified (T054)

- Traffic: the refusals are checked as GraphQL errors, cluster objects and task lists; no request was sent through an ingress controller.
- UI for the refusals: covered by Vitest only (`ConfigDiffDialog.test.tsx`, `DeployFormPage.test.tsx`, `UpgradeErrorAlert.test.tsx`), not by an end-to-end UI run, because the test is `api_only`.
- UI visuals (layout, colors) of the error alerts.
- (Resolved, see the section "Release-reference label".) The cause of the release-reference label difference above.
- The test ran on one machine (macOS, Docker); the CI matrix was not run.

## Release-reference label

Question: why was the label `styrmin.io/release-reference` of the Ingress `styrmin-svc-task-manager` `''` after the override was cleared, and `styrmin-<uuid>` before? Times are UTC. `<scratchpad>` is `/private/tmp/claude-503/-Users-Simon-styrmin-598-spec/2ab6e2fa-7180-493d-8211-590f003133bd/scratchpad`.

### Where a Styrmin-built object gets its label

Every Styrmin-built utility resource gets the label from `UtilityResourceBuilder.build` (`agent/service/kubernetes/resources/builders/utility.py`, the line `labels["styrmin.io/release-reference"] = release_reference` before the fix), from the `release_reference` argument. Nothing else writes that label (`grep -rn "release-reference" backend/styrmin_backend`). The HelmRelease that the StyrminDeployment pipeline creates carries only `app.kubernetes.io/managed-by` and `styrmin.io/operator-managed` (`ApplicationHelmReleaseBuilder.build`, `builders/application.py`, around line 436), so a HelmRelease never has the label.

| Code path | Release reference it passes to the builder | Label written before the fix | How it finds the object it reconciles |
|---|---|---|---|
| Prefect flows `install_utility` and `update_utility` (`agent/tasks/extra.py`, `orchestration.py`) | `context.instance.release_reference` | the real reference | not applicable (they apply what they render) |
| Pipeline phases 1 and 3 (`operator/pipeline.py`, `build_desired_resources_from_crd`) | `spec.releaseReference` of the StyrminDeployment, which `build_styrmin_deployment_body` receives as `context.instance.release_reference` | the real reference | not applicable |
| StyrminDeployment timer in phase Ready (`handlers/styrmin_deployment.py`, around line 990) | `spec.releaseReference` | the real reference | selector `managed-by=styrmin,release-reference=<real>` |
| HelmRelease timer (`handlers/helmrelease.py`, `kopf_helmrelease_timer`) | the label of the HelmRelease, which is never set, so `''` | `''` | selector `managed-by=styrmin,release-reference=` |
| Drift handlers for Ingress, Service, Secret and NetworkPolicy (`handlers/utility_resources.py`) | the label of the object that changed; they return at once when it is empty | not applicable | `_find_helmrelease_for_resource` selects a HelmRelease by that label, which a HelmRelease never has |
| HelmRelease create handler (`on_helmrelease_create`) | the label of the HelmRelease; it skips the HelmRelease when it is empty ("CRD-managed") | not applicable | not applicable |
| Update path (`reconcile_resources` to `apply_kubernetes_resource`) | none of its own: it applies the object that the caller built, `create`, and on HTTP 409 `replace` of the whole object | whatever the caller built | not applicable |

### Hypothesis

The two timers pass different release references for the same objects. Each timer lists the objects with its own reference, does not find the objects that the other timer last wrote, treats them as missing, and "creates" them. The create hits HTTP 409, so `apply_kubernetes_resource` replaces the object with a body that carries the caller's label. The label therefore flips on every pass. What the test reads depends on which timer wrote last. This predicts that the label of every Styrmin-built object flips, not only the Ingress.

What would prove it wrong: a flat label on the Service, Secret or NetworkPolicy, or the flip stopping when the HelmRelease carries the label.

### Observed on the real stack, before the fix

- Commit `83874cce` (clean tree), `[api-chromium]`, started 2026-11-10T14:00:24Z, vCluster `pytest-e24eed7b-d8c4-460b-b4c1-3789c55abb72`, kubeconfig `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1438/vcluster0/kubeconfig` (the vCluster was deleted afterwards). Command, from the repository root:

  ```bash
  sleep 86400 | uv run pytest "backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_moves_only_the_overridden_service" -k api-chromium -v -s --pdb > <scratchpad>/pdb-diag-before.log 2>&1
  ```

- Result: FAILED (the test stopped at the pdb prompt, so the vCluster stayed up). The failing assertion is the same as in "Failed run 1": `_comparable(task_manager_cleared) == _comparable(task_manager_before)`, with the label `''` against `'styrmin-a36fef25-499d-4d2d-8867-8118474ca801'` (`<scratchpad>/pdb-diag-before.log`, line 707).
- A read-only monitor (`<scratchpad>/label_monitor.sh`) ran `kubectl get ingress,svc,secret,networkpolicy -A -l app.kubernetes.io/managed-by=styrmin` every 2 seconds and wrote the label and the `resourceVersion` (`<scratchpad>/label-monitor-before.txt`, 1488 lines). Summary of `<scratchpad>/summarize_labels.sh`:

  ```text
  Ingress styrmin-svc-task-manager     samples=124 distinct_label_values=2 distinct_resourceVersions=66 last=(empty)
  NetworkPolicy default-deny-egress    samples=127 distinct_label_values=2 distinct_resourceVersions=71 last=(empty)
  Secret ingress-auth                  samples=127 distinct_label_values=2 distinct_resourceVersions=60 last=(empty)
  Service task-manager                 samples=125 distinct_label_values=2 distinct_resourceVersions=81 last=(empty)
  Service infrahub-enterprise          samples=125 distinct_label_values=2 distinct_resourceVersions=93 last=(empty)
  ```

  The Ingress flips between `''` and the real reference every 2 to 25 seconds from 14:04:02, for example `14:04:34 real, 14:04:36 empty, 14:04:39 real, 14:04:42 empty`.
- The operator log (`<scratchpad>/operator-before.log`) alternates two writers for the same object, each reporting a creation: `kopf.objects: Periodic reconciliation for <ns>/<release> (Ingress): created=1 updated=0 deleted=0 errors=0` (HelmRelease timer) at 14:08:04, 14:08:11 and 14:08:17, and `Drift reconciled for Ingress in <ns>/<ns>: +1 ~0 -0` (StyrminDeployment timer) at 14:08:01, 14:08:07 and 14:08:14. 73 lines `Created Ingress/styrmin-svc-task-manager` in the log.

### Refutation attempts

- Flat label on another kind: refuted. Service, Secret and NetworkPolicy flip the same way (table above), so the cause is not specific to the Ingress.
- The flip stops when the HelmRelease carries the label: confirmed in a throwaway copy of the unit test (not committed) that adds `styrmin.io/release-reference` to the HelmRelease handed to the timer. All six timer tests passed on the unfixed source.
- A different writer than the two timers: not found. `grep` shows no other place that writes the label. The Prefect flows and the pipeline phases also write the objects, with the real reference; the live monitor shows the flips continue for minutes after they have run, so they do not explain a repeating flip.
- Caused by the commits after the last green run: no. Commit `b5bf9399` of this feature added `Ingress` to both reconcile loops (`git show b5bf9399`), and the same loops already listed Service, Secret and NetworkPolicy, which flip on commit `83874cce` (monitor above). Not checked: whether those three kinds flipped on commits before this feature. Inferred: the test passed when the last writer before its read was the StyrminDeployment timer.

### Reproduction (unit tests that fail on the unfixed source)

New file `backend/tests/unit/test_ingress_release_reference_label.py`. It runs the real builder, the real `reconcile_resources` and both real timers against an in-memory cluster that selects objects by label like the API server (an object matches `key=value` only when it has the label with that value, an empty value included). The HelmRelease given to the HelmRelease timer has the labels that the pipeline gives it. The older timer tests in `test_ingress_operator_reconcile.py` gave the HelmRelease the label `styrmin.io/release-reference`, which a real HelmRelease never has, so they could not show this.

Without the fix (`git apply -R` of the source change; `<scratchpad>/unit-before-fix.txt`):

```text
FAILED ...::TestTheBuilderLabel::test_an_empty_release_reference_still_labels_with_the_one_of_the_instance
FAILED ...::TestTheTimersAgree::test_the_helmrelease_timer_creates_the_ingress_with_the_instance_reference[asyncio]
FAILED ...::TestTheTimersAgree::test_the_helmrelease_timer_leaves_the_label_of_the_deployment_timer[asyncio]
FAILED ...::TestTheTimersAgree::test_the_deployment_timer_leaves_the_label_of_the_helmrelease_timer[asyncio]
FAILED ...::TestTheTimersAgree::test_alternating_passes_write_the_ingress_once_and_keep_one_label[asyncio]
FAILED ...::TestTheTimersAgree::test_the_helmrelease_timer_deletes_an_ingress_that_is_no_longer_desired[asyncio]
FAILED ...::TestTheTimersAgree::test_an_ingress_with_an_empty_label_is_relabelled_once[asyncio]
7 failed, 2 passed in 0.22s
```

The failures have the right reason: `assert '' == 'styrmin-00000000-0000-0000-0000-0000000000aa'`, `assert {'', 'styrmin-...'} == {'styrmin-...'}` and `assert 2 == 1` (the Ingress written twice). With the fix: `9 passed in 0.19s` (`<scratchpad>/unit-after-fix.txt`). With only the builder change (no timer change), 4 tests still fail: the timers still do not see each other's objects, rewrite them on every pass, and the HelmRelease timer never deletes an Ingress that the StyrminDeployment timer wrote.

### Fix (commit `a0885121a21c592a4a271fc56f0490033b906e63`)

- `operator/handlers/helmrelease.py`, `kopf_helmrelease_timer`: `release_reference = release_reference or context.instance.release_reference`, after the context is fetched. This is the root cause. The instance's reference is the value that the StyrminDeployment timer and the Prefect flows already use.
- `agent/service/kubernetes/resources/builders/utility.py`: the builder applies the same fallback, so no caller can write an empty label. This alone is not enough (see above).
- A news fragment `changelog/+operator-release-reference-label.fixed.md`.
- The fix is the same cause for Service, Secret and NetworkPolicy. It was not asked for separately; the one change in the timer covers all four kinds, because the timer uses one release reference for all of them.
- The update path (`apply_kubernetes_resource`) was not changed: it replaces the object with the body of the caller, so it keeps the label that the builder wrote. An object that an earlier version left with an empty label is not listed by the real selector, is created again once with the real label, and stays (test `test_an_ingress_with_an_empty_label_is_relabelled_once`).

### End-to-end runs on the fix commit

All runs started on commit `a0885121a21c592a4a271fc56f0490033b906e63` with an empty `git status --short`, run one after the other by `<scratchpad>/run_all.sh`. Each used the command below, from the repository root, with `<node id>` and `<expr>` from the table. The label monitor ran in each run (`<scratchpad>/runs/<name>/labels.txt`). The kubeconfig files are deleted with each session.

```bash
sleep 86400 | uv run pytest "<node id>" -k "<expr>" -v -s --pdb > <scratchpad>/runs/<name>/pdb.log 2>&1
```

| Run | Node id, `-k` | Started | vCluster | Kubeconfig directory (`.../T/pytest-of-Simon/<dir>/vcluster0/kubeconfig`) | Result |
|---|---|---|---|---|---|
| api-1 | `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_moves_only_the_overridden_service`, `api-chromium` | 2026-11-10T14:15:11Z | `pytest-3c6fa79a-7a23-433a-9184-56cc281f7ae4` | `pytest-1440` | passed |
| api-2 | same | 2026-11-10T14:20:20Z | `pytest-aba3720e-bea8-42d5-94f0-a3ff40b677ae` | `pytest-1441` | passed |
| api-3 | same | 2026-11-10T14:25:18Z | `pytest-b52191a3-e980-4660-94a5-84122c0fe462` | `pytest-1442` | passed |
| ui-1 | same, `ui-chromium` | 2026-11-10T14:30:17Z | `pytest-a7b7a894-eb12-4ca6-8cdb-17f4a1e0e733` | `pytest-1443` | passed |
| refusals | `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_refusals_name_the_service`, `api-chromium` | 2026-11-10T14:35:46Z | `pytest-cd6ce5d0-bab0-4685-ae3b-17a4037ddce8` | `pytest-1444` | passed |
| generic | `backend/tests/e2e/test_deploy_generic_app.py::test_deploy_generic_app`, `api-chromium` | 2026-11-10T14:41:24Z | `pytest-73e0c977-c48e-488b-8e05-0f376ffc7d34` | `pytest-1445` | passed |

Verbatim result lines (ANSI colors removed; `-s` puts the vCluster log in front of `PASSED`):

```text
api-1    PASSED15:19:48 info Removing vCluster container vcluster.cp.pytest-3c6fa79a-7a23-433a-9184-56cc281f7ae4...
         =========== 1 passed, 1 deselected, 4 warnings in 282.21s (0:04:42) ============
api-2    PASSED15:24:51 info Removing vCluster container vcluster.cp.pytest-aba3720e-bea8-42d5-94f0-a3ff40b677ae...
         =========== 1 passed, 1 deselected, 4 warnings in 277.21s (0:04:37) ============
api-3    PASSED15:29:49 info Removing vCluster container vcluster.cp.pytest-b52191a3-e980-4660-94a5-84122c0fe462...
         =========== 1 passed, 1 deselected, 4 warnings in 276.02s (0:04:36) ============
ui-1     PASSED15:35:16 info Removing vCluster container vcluster.cp.pytest-a7b7a894-eb12-4ca6-8cdb-17f4a1e0e733...
         =========== 1 passed, 1 deselected, 4 warnings in 303.48s (0:05:03) ============
refusals PASSED15:40:50 info Removing vCluster container vcluster.cp.pytest-cd6ce5d0-bab0-4685-ae3b-17a4037ddce8...
         =========== 1 passed, 1 deselected, 4 warnings in 309.82s (0:05:09) ============
generic  PASSED15:44:29 info Removing vCluster container vcluster.cp.pytest-73e0c977-c48e-488b-8e05-0f376ffc7d34...
         =========== 1 passed, 1 deselected, 4 warnings in 187.11s (0:03:07) ============
```

Label of the Ingress `styrmin-svc-task-manager` and of the other Styrmin-built objects on the live stack, every 2 seconds for the whole run (`summarize_labels.sh`):

```text
api-1    Ingress samples=43 distinct_label_values=1 distinct_resourceVersions=7   (Secret 1 value, NetworkPolicy 1 value, Services 1 value)
api-2    Ingress samples=50 distinct_label_values=1 distinct_resourceVersions=6
api-3    Ingress samples=49 distinct_label_values=1 distinct_resourceVersions=8
ui-1     Ingress samples=52 distinct_label_values=1 distinct_resourceVersions=8
refusals Ingress samples=60 distinct_label_values=1 distinct_resourceVersions=10
```

In `api-2` the `resourceVersion` of the Ingress is 1706 from 14:22:42 to 14:24:06 (84 seconds, about 16 timer passes of 5 seconds) and changes only when the test sets or clears the override (2391, 2409, 2475) and at 2630 and 2669 (the cause of those two changes was not checked). The label has one value in every sample, before the override, with it, after clearing it, and in the minute after.

### Not verified, and what remains

- The label was read by the monitor and by the test's own assertion; no pdb prompt was reached in any of the six runs, so no pdb log shows the label value. The test passed, so its assertion `_comparable(task_manager_cleared) == _comparable(task_manager_before)` holds, and it includes the label.
- Three passes of a test that failed once in two do not prove that it cannot fail again. The proof is the unit test and the flat label in the monitor of five runs.
- Services are still rewritten about every 5 seconds after the fix (`distinct_resourceVersions` 23 to 37 per run, label unchanged). Not investigated, not caused by the label, not changed. The Ingress is not rewritten, so it is a different cause that applies to Services only. Not verified: whether it was there before the fix (the before-fix monitor cannot tell, the label also changed).
- The Ingress drift handlers (`kopf_on_ingress_update` and `kopf_on_ingress_delete`) now receive the real label instead of `''`, so they no longer return at once. They call `_find_helmrelease_for_resource`, which selects a HelmRelease by that label; a HelmRelease never has it, so they log `No HelmRelease found ... skipping reconciliation` and do nothing. The same holds for the Service, Secret and NetworkPolicy handlers. Not changed: giving the HelmRelease the label is a larger change and not needed for this defect. The number of such log lines in a run was not counted.
- `on_helmrelease_delete` still passes the label of the HelmRelease (empty) to `cleanup_operator_resources`. After the fix the operator-managed NetworkPolicies carry the real reference, so that cleanup selects none of them. `_teardown_owned_resources` deletes them by the real reference and the namespace is deleted, so nothing stays behind in the runs; a HelmRelease deleted alone (not through the deployment) was not tested.
- The Service `app` that `generic` lists with `<none>` is a Service in another namespace without the label (an alias, ADR-073); it is a different object and its `resourceVersion` never changed.
- The tests ran on one machine (macOS, Docker); the CI matrix was not run.

### 5 Whys

1. Why did the test fail once? Because the label of the Ingress read after clearing the override was `''` and the one read before was `styrmin-<uuid>` (proven: `pdb-diag-before.log` line 707, and the same difference in "Failed run 1").
2. Why did the label change without any user action? Because two operator timers rewrite the same Ingress every few seconds, one with the real reference and one with `''` (proven: monitor flips every 2 to 25 seconds; the operator log shows both timers reporting `created=1` for the Ingress in turn).
3. Why does each timer rewrite what the other wrote? Because each lists the objects by `release-reference=<its value>`, finds none of the other's, "creates" them, gets HTTP 409 and replaces the object with a body that carries its own label (proven: `list_managed_resources` selector, `apply_kubernetes_resource` 409 branch, the unit tests with the in-memory cluster).
4. Why do the timers use different values? Because the HelmRelease timer reads the value from a label of the HelmRelease, and the pipeline creates the HelmRelease without that label (proven: `ApplicationHelmReleaseBuilder.build` sets two other labels; no other writer of the label; the unit tests pass when the label is added to the HelmRelease).
5. Why was this written that way? Because the operator was designed when HelmReleases carried the label (the archived `001-k8s-operator` data model says so), and the StyrminDeployment pipeline later created HelmReleases without it; the handlers kept reading the label (inferred from the archived specs and the comment "CRD-managed" in `on_helmrelease_create`; not verified in the history).
6. Why was it not detected earlier? Because the unit tests of the timer gave the HelmRelease the label that a real one never has, no test ran the two timers against one cluster, and the flip leaves no error: the objects are always present and valid. The first symptom was a wrong host name annotation in this feature's first end-to-end runs, which was fixed in the annotation (`build_ingress_settings`) and not traced back to the empty reference (proven by "Run 2" of the first section and the comment in `ingress.py`).


---

# T062: upgrade of a running Infrahub deployment, Tailscale, and the default timer interval (#598)

Task T062, quickstart step 7, spec SC-005 and the edge case on existing Infrahub deployments. These are manual measurements with a throwaway test, not a test of the repository.

## Result

- The measurement found a defect in the Ingress that Styrmin builds. In an environment with a dedicated ingress controller, the controller does not serve it, so the host of the Prefect UI answers HTTP 404 through the controller as soon as the chart's Ingress is gone, and keeps doing so. It is not fixed in this chunk. The cause is proven by a live label change (section "Cause").
- With the label added by hand at the moment the Ingress appears (an emulation of a fix, not a fix), the host answered 404 for 9 seconds while the operator timer ran at its default of 60 seconds.
- The tailnet access is not verified: no Tailscale operator and no tailnet exist in the fixtures.

## The throwaway test

- File: `/private/tmp/claude-503/-Users-Simon-styrmin-598-spec/2ab6e2fa-7180-493d-8211-590f003133bd/scratchpad/test_zz_throwaway_upgrade.py`. It is copied into `backend/tests/e2e/` for each run and removed afterwards, so it is not in the repository.
- What it does, with the session fixtures (`vcluster`, `git_server`, `styrmin_resources`):
  1. Builds the driver version 4 of `infrahub-enterprise` from `git show ad1e5673^:driver/examples/infrahub-enterprise/{driver.styrmin.yml,values.j2.yml}`, pushes it as the branch `old-build` to the in-cluster git server and loads it.
  2. Deploys `infrahub-enterprise` 1.6.0 on that driver version through the SDK (`deployments.create(..., driver_version_id=...)`) and waits until the deployment is running.
  3. Loads the current `master` (driver version 5), starts three loops (an Ingress listing every second, a request every second to `http://localhost:<port>/api/health` with the header `Host: task-manager-test-environment.styrmin.com` through a port-forward to the dedicated Traefik, the deployment status every 2 seconds), and calls `deployments.update_version(deployment_id, "1.6.0", driver_version_id=<driver version 5>)`.
  4. Stops when the deployment is running, `styrmin-svc-task-manager` exists, and the Ingress list has not changed for 60 seconds.
- Commit under test: `772256e64697d29fd587e6c9f6f2904403f5023f`, working tree clean except the throwaway test file (and, in run 2, the value of `STYRMIN_OPERATOR_RECONCILE_INTERVAL` in `backend/tests/e2e/fixtures/styrmin-values.yaml`, changed from `"5"` to `"60"` for that run and restored with `git checkout`).
- Command, from the repository root (`sleep 86400` instead of `sleep infinity`, as in the sections above):

  ```bash
  REPO_ROOT=$PWD TIMELINE_FILE=<scratchpad>/timeline1.txt HOLD_FILE=<scratchpad>/hold1 \
    sleep 86400 | uv run pytest backend/tests/e2e/test_zz_throwaway_upgrade.py -k api-chromium -v -s --pdb
  ```

  Run 2 adds `LABELER=1`, which patches `styrmin/environment_id` onto `styrmin-svc-task-manager` within 0.25 seconds of its creation.
- Timelines kept in the scratchpad: `timeline1.txt` (run 1), `timeline2.txt` (run 2), logs `run1.log`, `run2.log`, `run3.log`.

## Run 1: operator timer 5 seconds (the fixture value), no label change

- Started 2026-11-10T15:09:51Z. vCluster `pytest-db1e7e52-0723-43da-a3ec-96816d03b7aa`. Kubeconfig `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1448/vcluster0/kubeconfig`. Namespace `styrmin-b7fe4176-71c8-4241-9000-9ceaf4888af8`. Result `1 passed, 1 deselected, 4 warnings in 456.85s (0:07:36)` (the test asserts nothing about the answers; it writes the timeline).
- Before the upgrade (driver version 4), verbatim from the timeline:

  ```text
  15:13:52.572624Z BEFORE ingresses {"styrmin-infrahub-ingress": [["infrahub-enterprise-b7fe4176-71c8-4241-9000-9ceaf4888af8.styrmin.com", "infrahub-test-environment.styrmin.com"], "98afe240"], "styrmin-task-manager": [["task-manager-test-environment.styrmin.com"], "8d08997c"]}
  15:13:53.809046Z PROBE task-manager-test-environment.styrmin.com/api/health -> HTTP 200
  ```

  The chart's Prefect Ingress is `styrmin-task-manager`, with the host `task-manager-test-environment.styrmin.com`.
- During the upgrade (the update started at 15:14:01Z):

  ```text
  15:14:08.046056Z INGRESSES {... "styrmin-svc-task-manager": [["task-manager-test-environment.styrmin.com"], "50934798"], "styrmin-task-manager": [["task-manager-test-environment.styrmin.com"], "8d08997c"]}
  15:14:13.150781Z INGRESSES {... "styrmin-task-manager": [["task-manager-test-environment.styrmin.com"], "8d08997c"]}
  15:14:19.795214Z INGRESSES {... "styrmin-svc-task-manager": [[...], "473c2d7b"], "styrmin-task-manager": [[...], "8d08997c"]}
  15:14:44.303825Z PROBE task-manager-test-environment.styrmin.com/api/health -> HTTP 404
  15:14:45.193553Z INGRESSES {"styrmin-infrahub-ingress": [...], "styrmin-svc-task-manager": [[...], "473c2d7b"]}
  15:14:49.881983Z DEPLOYMENT status=running driver_version=4ad9ebaf-a5b4-4fce-86c8-e9f13d07874f
  15:15:47.955806Z UPGRADE end after 106.7s (settled=True)
  15:15:48.750632Z PROBE total=115 non200=64
  ```

- What this shows:
  - The operator created `styrmin-svc-task-manager` 7 seconds after the update started, while the chart's Ingress still existed. Two Ingresses with the same host existed together for about 36 seconds (15:14:08 to 15:14:45), with a gap of about 6 seconds in the middle (15:14:13 to 15:14:19) during which the Styrmin-built Ingress did not exist. The uid changed (`50934798` then `473c2d7b`), so Styrmin's Ingress was deleted and created again. Why it was deleted is not known.
  - The chart's Ingress `styrmin-task-manager` was removed at 15:14:45Z, one second after the first 404.
  - From 15:14:44Z until the end of the run (106 seconds after the update started, 64 requests), every request to the host answered HTTP 404. The answer did not come back.

## Cause

- The dedicated Traefik of the environment starts with the argument `--providers.kubernetesingress.labelselector=styrmin/environment_id=<environment id>` (`backend/styrmin_backend/services/ingress_controller/templates/chart_values.j2.yaml`, line 14; the Traefik log of run 1 says `ingress label selector is: "styrmin/environment_id=48f36ebf-fa3e-4139-8552-21622a04cb93"`).
- The chart's Ingress carries the labels `styrmin/environment_id` and `styrmin/deployment_id`. The Ingress that Styrmin builds carries only `app.kubernetes.io/managed-by`, `styrmin.io/release-reference`, `styrmin.io/service-name` and `styrmin.io/utility-kind` (`kubectl get ingress -o jsonpath='{.metadata.labels}'`, saved in `run1-ingress-labels.txt`). The builder sets `"labels": {SERVICE_NAME_LABEL: ...}` in `backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py`, around line 350.
- So the dedicated Traefik ignores the Styrmin-built Ingress.
- Proof on the vCluster of run 1, 2026-11-10T15:16:49Z, with a port-forward to the Traefik pod: the request with `Host: task-manager-test-environment.styrmin.com` answered `404`. After `kubectl label ingress styrmin-svc-task-manager styrmin/environment_id=48f36ebf-fa3e-4139-8552-21622a04cb93` it answered `200 200 200 200 200` in the next five seconds, and the label was still on the object two minutes later.
- The builder is the same for every external service, so the same cause is expected for every external service of any driver in an environment with `dedicated_ingress`, including `generic-app`. This is inferred from the code and was not run.
- Why the earlier end-to-end runs did not show it: `test_service_ingress_override.py` asserts Kubernetes objects and no traffic (the "Not verified" section above says so), and `test_infrahub_services.py`, which sends traffic through the dedicated Traefik, was not run in that chunk.
- Run 3, to check this with the existing test: `backend/tests/e2e/test_infrahub_services.py -k api-chromium`, started 2026-11-10T15:36:49Z at commit `772256e6`, vCluster `pytest-52f69e56-477c-421a-bb8e-995e847ce162`. It failed at line 241, the request through Traefik:

  ```text
  E       TimeoutError: http://localhost:54269/api/health did not return 200 after 120.0s
  backend/tests/e2e/conftest.py:389: TimeoutError
  ```

  On that stack the chart's Ingress carries `styrmin/environment_id` and `styrmin-svc-task-manager` does not (jsonpath count 1 and 0). Whether this test passed on the base commit was not run here.

## Run 2: operator timer 60 seconds (the default), label added on creation (emulating a fix)

- Started 2026-11-10T15:20:52Z. vCluster `pytest-86e09c8f-31be-4778-8526-33c28134d68e`. Kubeconfig `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1449/vcluster0/kubeconfig`. Result `1 passed, 1 deselected, 4 warnings in 416.23s (0:06:56)`.
- Verbatim from the timeline (the update started at 15:25:18.8Z):

  ```text
  15:26:00.868706Z PROBE task-manager-test-environment.styrmin.com/api/health -> HTTP 404
  15:26:01.461437Z INGRESSES {"styrmin-infrahub-ingress": [...]}
  15:26:09.779779Z INGRESSES {"styrmin-infrahub-ingress": [...], "styrmin-svc-task-manager": [[...], "84f76ddc"]}
  15:26:09.783855Z LABELER set styrmin/environment_id on styrmin-svc-task-manager uid=84f76ddc
  15:26:09.876504Z PROBE task-manager-test-environment.styrmin.com/api/health -> HTTP 200
  15:27:12.780562Z PROBE total=121 non200=9
  ```

- What this shows:
  - With the default interval, the operator created `styrmin-svc-task-manager` 51 seconds after the update started, which is after Helm removed the chart's Ingress (15:26:01Z at the latest). The host answered 404 from 15:26:00.87Z to 15:26:09.88Z: 9 requests, about 9 seconds.
  - This is one sample. The length of the gap depends on when the operator's next pass falls after the Helm upgrade, so it can be shorter or longer, up to about the interval. Other lengths were not measured.
  - With the 5-second interval of run 1 the Styrmin-built Ingress existed before the chart's Ingress was removed, so a gap of this kind did not occur in that run (the 404 there came from the missing label).
  - Creation delay of the Styrmin-built Ingress after the update started: 7 seconds at the 5-second interval (run 1), 51 seconds at the 60-second interval (run 2).

## Tailscale

- Not verified. Checked with `kubectl get pods -A`, `kubectl get ns` and `kubectl get ingressclass` on the vCluster of run 1: no Tailscale pod, no Tailscale namespace and no ingress class. `grep -ril tailscale backend/tests/e2e/` finds only `test_service_ingress_override.py`, which uses `tailscale` as a class name. No tailnet is available to the fixtures. Nothing was set up.

## Not verified

- Whether the Prefect UI answers during the upgrade when the Ingress carries the label. Run 2 emulates it with a label added by hand, one sample, at the 60-second interval; it was not run at the 5-second interval.
- Why the operator deleted and created `styrmin-svc-task-manager` again at 15:14:13Z in run 1.
- The Infrahub server address (`infrahub-test-environment.styrmin.com`): not probed during the upgrade. The chart's Ingress `styrmin-infrahub-ingress` kept its uid (`98afe240`) in both runs, so it was not recreated.
- Whether `test_infrahub_services.py` passes on the base commit (`origin/develop`): not run.
- The migration guide (`docs/docs/drivers/migrating-external-service-ingress.md`), the page `service-ingress-overrides.md` and ADR-090 still say that the upgrade interruption and the delay at the default interval are not known. They are not changed in this chunk, because the result depends on the fix of the defect above.

---

# T063, T064 and T065: final checks and the quickstart walk-through (#598)

Commit under test: `772256e64697d29fd587e6c9f6f2904403f5023f`. Started 2026-11-10T15:30:17Z.

## T063: no Alembic revision

`git rev-parse origin/develop` gives `5abe5647ad60b6633d31ae60f602b0eca88ff5b7`, and `git merge-base HEAD origin/develop` gives the same commit. `git diff origin/develop -- backend/styrmin_backend/db/models.py backend/styrmin_backend/db/migrations` printed nothing (0 lines).

## T064: checks

| Command | Result |
|---|---|
| `uv run invoke format lint` | exit 0; `1062 files left unchanged`, `All checks passed!`, `283/283 .graphql files passed validation.` |
| `uv run invoke test` | exit 1; `FAILED tests/unit/services/telemetry/test_sender.py::test_send_report_returns_false_when_the_connection_is_refused - assert 7.790900083025917 < 2` and `1 failed, 6068 passed, 8 skipped, 41 warnings in 265.46s (0:04:25)`. This failure is the known one that also fails on the base commit (confirmed in an earlier chunk in a temporary worktree). Not repeated here. |
| `cd frontend && pnpm test` | exit 0; `Test Files  104 passed (104)`, `Tests  1255 passed (1255)` |
| `pnpm lint` | exit 0; `All matched files use Prettier code style!` |
| `pnpm exec tsc -b` | exit 0, no output |
| `pnpm build` | exit 0; `built in 224ms` |
| `uv run styrmin export graphql-schema schema.graphql` | exit 0; `GraphQL schema exported to schema.graphql` |
| `uv run invoke generate` | exit 0; `Generate outputs` for the SDK and `Generate to src/generated/graphql.ts` |
| `uv run invoke validate-graphql` | exit 0; `283/283 .graphql files passed validation.` |
| `uv run pytest cli/tests -q` | exit 0; `416 passed in 22.75s` |
| `uv run pytest python_sdk/tests -q` | exit 0; `363 passed in 0.56s` |

- `git status --short` was empty after the export, the generation and the validation: the schema, SDK and frontend types need no change.
- `uv run pytest cli/tests python_sdk/tests -q` in one run fails at collection (`ImportPathMismatchError` on `tests.conftest`: both folders have a `tests/conftest.py`). The two folders pass when run separately, so the quickstart now lists them as two commands.

## T065: quickstart walk-through

| Step | Run here | Where the result is |
|---|---|---|
| Prerequisites | yes: `vcluster` and `docker` are on the PATH, the e2e runs above created their own vClusters | this file |
| 1. Unit and contract checks | yes, every command, see T064 above | this file |
| 2. One service moves, the other stays | not run by hand; the end-to-end test `test_service_ingress_override_moves_only_the_overridden_service[api-chromium]` runs it | "Final passing run (run 4)" at the top of this file |
| 3. No override (`generic-app`, two external services) | not run by hand; the `generic-app` test and the unit tests run it | "End-to-end evidence: generic-app has one Ingress" above |
| 4. UI | not run by hand; the `[ui-chromium]` variant runs it | "T048" above |
| 5. Refused requests | not run by hand; `test_service_ingress_override_refusals_name_the_service` runs it | "T054" above |
| 6. Dedicated ingress controller | not run by hand; scenario 3 of the same end-to-end test runs it (objects only, no traffic) | "Final passing run (run 4)" |
| 7. Existing Infrahub deployment | yes, twice (T062 above) | "T062" above |

- Quickstart text changed: step 1 (the extra commands and the separate CLI and SDK test runs) and step 7 (the steps of the measurement).
- Step 7 found a defect in the product, not in the text: the Ingress that Styrmin builds lacks the label `styrmin/environment_id`, which the dedicated Traefik requires, so the task manager host answers 404 through it. Steps 2, 3 and 6 pass because they check objects, not traffic. T065 is not marked done: the product has to be fixed first, and the walk-through repeated for step 7 (and for a request through the controller in steps 2, 3 and 6).
