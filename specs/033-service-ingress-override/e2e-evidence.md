# End-to-end evidence: service ingress override (#598)

Task T033 (Constitution V). Test: T025, `backend/tests/e2e/test_service_ingress_override.py`.

## Result

This block is the current result. The runs below it are history and keep the commits they ran on.

- All five end-to-end runs of the review fixes passed on commit `3923471c8a5868d171cd7b12eeff73f6a59f2e3f`, with an empty `git status --short`: see the last section, "Review fixes". They cover the API and UI variants of `test_service_ingress_override_moves_only_the_overridden_service`, the refusals test, `test_deploy_generic_app` and `test_infrahub_services.py`.
- Before the review fixes, on commit `343e4072` (the commit that added the traffic checks): the same five runs passed, see "End-to-end runs on the final code".
- Run 4 of the API variant, on commit `55c002b32038b33ce330fffd283fce083a6b08c4`, and the UI variant of T048, on commit `7bcc9576441aba62b3e6f96604e46bb32cb9762f`, are the first passes of that test. Both ran before the traffic checks existed; they are superseded by the runs above.

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

- Traffic. The test asserts Kubernetes objects. No Tailscale ingress controller runs in the fixtures, so nothing proves that the overridden host answers. `test_infrahub_services.py` covers the Prefect UI through the dedicated Traefik; it was not run in this chunk. I read it: it looks for the host `task-manager-test-environment.styrmin.com` and sends traffic with that `Host` header through Traefik. The Ingress that Styrmin builds has that host, path `/`, and `kubernetes.io/ingress.class: traefik`, so the assertions look unchanged, but this is by reading. (Superseded: from commit `343e4072` the end-to-end tests send traffic through the dedicated Traefik; see the section "The end-to-end tests now send traffic (commit `343e4072`)".)
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

- T034: the namespace holds only `styrmin-svc-app`; its two hosts are the `primary_fqdn` and `human_readable_fqdn` that the deployment reports; the backend is service `app` on port 8080; the annotation keys are the five that the chart patch set on the former chart Ingress; the class is the dedicated controller's (`kubernetes.io/ingress.class: traefik`, no `spec.ingressClassName`); the host name annotation starts with the release reference; no `spec.tls`. Then `deployments.delete` and `wait_for_deployment_status(..., "deleted")`; the namespace then holds no Ingress. The assertion that the Ingress is gone passes also because the namespace is deleted with the deployment; it does not show that the operator deletes an Ingress on its own. (Review fix M6: the assertion that no Ingress is left after the deletion could not fail because of the way Styrmin deletes an Ingress, since the namespace goes with the deployment. It was removed from the test in the review fixes; the test still waits for the status `deleted`. The operator deletion of an Ingress is covered by unit tests, and not by this end-to-end test.)
- T038: the namespace of `simple-app` holds exactly one Ingress, `styrmin-simple-app` (the chart Ingress), and it has no `styrmin.io/service-name` label.

### Not verified

- Traffic to the generic-app host through the Ingress. The test asserts the object, and the existing check of the application through a port-forward to the Service is unchanged. (Superseded: from commit `343e4072` the end-to-end tests send traffic through the dedicated Traefik; see the section "The end-to-end tests now send traffic (commit `343e4072`)".)
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
- Traffic: the test reads objects on the vCluster; no ingress controller of class `tailscale` runs, and no request is sent to a host. (Superseded: from commit `343e4072` the end-to-end tests send traffic through the dedicated Traefik; see the section "The end-to-end tests now send traffic (commit `343e4072`)".)
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

- Traffic: the refusals are checked as GraphQL errors, cluster objects and task lists; no request was sent through an ingress controller. (Superseded: from commit `343e4072` the end-to-end tests send traffic through the dedicated Traefik; see the section "The end-to-end tests now send traffic (commit `343e4072`)".)
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

- The measurement found a defect in the Ingress that Styrmin builds. In an environment with a dedicated ingress controller, the controller does not serve it, so the host of the Prefect UI answers HTTP 404 through the controller as soon as the chart's Ingress is gone, and keeps doing so. It was not fixed in this chunk; commit `4b87a6f9` fixes it (see the last section of this file, "The label defect: fix, traffic checks and the upgrade measurement repeated"). The cause is proven by a live label change (section "Cause").
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
- Why the earlier end-to-end runs did not show it: `test_service_ingress_override.py` asserts Kubernetes objects and no traffic (the "Not verified" section above says so), and `test_infrahub_services.py`, which sends traffic through the dedicated Traefik, was not run in that chunk. (Superseded: from commit `343e4072` the end-to-end tests send traffic through the dedicated Traefik; see the section "The end-to-end tests now send traffic (commit `343e4072`)".)
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
| 6. Dedicated ingress controller | not run by hand; scenario 3 of the same end-to-end test runs it (objects only, no traffic) | "Final passing run (run 4)" (superseded: see "The end-to-end tests now send traffic (commit `343e4072`)") |
| 7. Existing Infrahub deployment | yes, twice (T062 above) | "T062" above |

- Quickstart text changed: step 1 (the extra commands and the separate CLI and SDK test runs) and step 7 (the steps of the measurement).
- Step 7 found a defect in the product, not in the text: the Ingress that Styrmin builds lacks the label `styrmin/environment_id`, which the dedicated Traefik requires, so the task manager host answers 404 through it. Steps 2, 3 and 6 pass because they check objects, not traffic. T065 is not marked done: the product has to be fixed first, and the walk-through repeated for step 7 (and for a request through the controller in steps 2, 3 and 6). (Done later: see the last section.)


---

# The label defect: fix, traffic checks and the upgrade measurement repeated (#598)

This section follows "T062" and "T063, T064 and T065". It supersedes the lines there that say the defect is "not fixed" and that T065 is "not marked done". Times are UTC. `<scratchpad>` is `/private/tmp/claude-503/-Users-Simon-styrmin-598-spec/2ab6e2fa-7180-493d-8211-590f003133bd/scratchpad`.

## Cause, with the evidence

Proven (read in the source of commit `3c5fb844`, before the fix):

- The dedicated Traefik starts with `--providers.kubernetesingress.labelselector=styrmin/environment_id={{ labels.environment_id }}` (`backend/styrmin_backend/services/ingress_controller/templates/chart_values.j2.yaml:14`). `driver/examples/generic-app/values.j2.yml:101,123` uses `styrmin/environment_id` in the `namespaceSelector` of the generic-app network policies, not as a label of an Ingress: it shows that the label is a namespace-level and object-level identity, not that the chart Ingress had it from that file. The chart Ingress gets the label from the post-render patch below.
- The chart Ingresses get their labels from the post-render patch: `ApplicationHelmReleaseBuilder.build` calls `build_target_for_label_patches(labels=self.context.labels, label_prefix=self.label_prefix)` (`builders/application.py:474-475`, patch built at `:287`), and `label_prefix` is `"styrmin"` in both callers (`agent/tasks/core.py:22`, `operator/pipeline.py:207`, default of the class). Every key of `context.labels` becomes `styrmin/<key>` on every object of the chart.
- `context.labels` has exactly two keys, `environment_id` and `deployment_id` (`backend/styrmin_backend/services/context.py:217-220`). Both are record ids (UUIDs).
- The builder of the Ingress set only `{SERVICE_NAME_LABEL: ...}` (`utilities/ingress.py:350` before the fix), and `UtilityResourceBuilder.build` adds three ownership labels (`managed-by`, `utility-kind`, `release-reference`; `builders/utility.py:38-44`). Nothing added `styrmin/environment_id`.
- The utility objects that `UtilityResourceBuilder` builds (NetworkPolicy, Secret, Middleware, Service) have only the three ownership labels, not the two deployment labels. They are not selected by label by any controller, so this was not changed. Only Ingresses are selected by the controller's label selector.

Observed (section "T062" above): the Prefect UI host answered 404 for the rest of the run after the upgrade; adding the label by hand changed the answer to 200 within one second.

What would have shown the theory wrong, and what I checked: a Traefik that selects on something else (the Traefik log in the T062 run says `ingress label selector is: "styrmin/environment_id=..."`); a label that the chart Ingress has and the built one needs besides `environment_id` (the chart gets exactly the two keys of `context.labels`, so the set is the same two); a class problem (`kubernetes.io/ingress.class: traefik` is on both Ingresses).

## The fix and the choice of labels

- Commit `4b87a6f9`. `utilities/ingress.py` has a new function `_deployment_labels(context)`. It returns `build_namespace_labels(context.labels)` without the entries whose value is `None` or `""`, and the Ingress metadata is `{**_deployment_labels(context), SERVICE_NAME_LABEL: <driver service name>}`.
- Labels set: `styrmin/environment_id` and `styrmin/deployment_id`. `styrmin/environment_id` is the one the controller needs. `styrmin/deployment_id` is the other label that every chart object has, so a built Ingress has the same identity labels as the chart Ingress next to it. The function that adds the prefix is the one that builds the namespace labels (`context/namespace_labels.py:12`), whose prefix is `styrmin`, the same prefix as the post-render patch.
- Every built Ingress gets them, an overridden one too. An Ingress with the class `tailscale` stays unserved by Traefik because of its class annotation (new end-to-end assertion below), not because it lacks the label.
- Values: UUID strings, so they are valid Kubernetes label values (36 characters, letters, digits and hyphens). A `None` or empty value in `context.labels` would give the text `None` or an empty label; the function leaves such entries out (unit tests `test_an_empty_context_label_gives_no_label[None]` and `[]`). A context with no labels builds the Ingress with its own label only.
- Operator path: `compute_diff` compares only `kind`, name, namespace and `spec` (`operator/reconciler.py`, `_normalize_for_comparison`). A change of labels or annotations alone does not update an Ingress that already exists. This matters only for an Ingress that an earlier version built without the labels. No release contains such an Ingress: `git describe --tags --abbrev=0 origin/develop` is `v0.1.57`, `git tag --contains <first commit of the branch>` prints nothing, and `git grep "styrmin-svc-" origin/develop -- backend` finds nothing. So no towncrier fragment is added for the fix, and `598.added.md` and `598.changed.md` do not mention labels. Not run: whether the operator would write the labels onto an existing Ingress (by the code it would not).
- The two operator timers and the Prefect flows all build the Ingress through `UtilityResourceBuilder` and `IngressUtility.build_resources`, so they write the same labels (unit test `test_the_operator_builds_the_labels_next_to_the_ownership_labels`).

## Unit test: fails before, passes after

New file `backend/tests/unit/agent/test_service_ingress_labels.py` (8 tests). It reads the selector from the controller's chart values template, rendered with `GlobalContext.model_dump(exclude_none=True)` as the Jinja context, as production does, and compares it with the labels of the built Ingress. It also compares the built labels with the labels that the post-render patch of `ApplicationHelmReleaseBuilder` gives every chart object. If the template or the builder changes without the other, the test fails.

Before the fix (`<scratchpad>/labels-unit-before-fix.txt`):

```text
E  AssertionError: The dedicated controller selects styrmin/environment_id=00000000-0000-0000-0000-0000000000e1; the Ingress has {'styrmin.io/service-name': 'web'}
...
6 failed, 2 passed in 0.12s
```

The two that pass check the premise (the selector is the environment id) and the context without labels. After the fix (`<scratchpad>/labels-unit-after-fix.txt`): `8 passed in 0.06s`. The 505 unit tests selected by `-k "ingress or utility or label"` pass after the fix.

## The end-to-end tests now send traffic (commit `343e4072`)

The earlier tests read Kubernetes objects only, so none could see that the host answered 404. Changes:

- `test_service_ingress_override_moves_only_the_overridden_service`: asserts that the built Ingress has `styrmin/environment_id`; waits until the dedicated Traefik answers 200 for `task-manager-test-environment.styrmin.com` (path `/api/health`, header `Host`) before the override and again after it is cleared; with the override (class `tailscale`) waits until the Traefik stops answering 200 for the default host, which shows that it read the change, and then asserts that the overridden host `task-manager-test-environment.tailnet.example.ts.net` answers 404 through it. It uses the helper `traefik_service` of `tests/e2e/helpers/ingress.py`, `_portforward` and `_wait_for_http`, as `test_infrahub_services.py` does.
- `test_deploy_generic_app`: asserts the label, then that both hosts of the Ingress (`primary_fqdn`, `human_readable_fqdn`) answer 200 on `/health` through the dedicated Traefik of `scenario_environment_id`. The session cluster has `dedicated_ingress` (`conftest.py`, `styrmin_resources`), so the environment has a Traefik.
- Covered: a built Ingress without an override is served by the dedicated Traefik; an Ingress with class `tailscale` is not.
- Not covered: the overridden host through a Tailscale controller (none in the fixtures; Tailscale is not verified); the `infrahub` host through the controller (unchanged by this work); traffic on the `[ui-chromium]` variant is the same code as the API variant.

Control run: the test fails without the fix. On the committed test with two temporary edits (the line `**_deployment_labels(context)` removed from `ingress.py`, and the new label assertion in the test commented out so the traffic step is reached), started 2026-11-10T15:49:59Z, vCluster `pytest-39f24b3f-77ec-40e3-ad91-46f411d0810e`, kubeconfig `.../pytest-of-Simon/pytest-1456/vcluster0/kubeconfig`: `FAILED` at `test_service_ingress_override.py:449` through `_wait_until_traefik_serves` (`:349`):

```text
E       TimeoutError: http://localhost:24877/api/health did not return 200 after 120.0s
backend/tests/e2e/conftest.py:389: TimeoutError
```

`kubectl get ingress -A` at the pause showed `styrmin-svc-task-manager` with the labels `app.kubernetes.io/managed-by`, `styrmin.io/release-reference`, `styrmin.io/service-name` and `styrmin.io/utility-kind` only (`<scratchpad>/runs2/control-ingress-labels.txt`). Both edits were reverted, the vCluster deleted with `vcluster delete ... --driver docker`.

## End-to-end runs on the final code

Commit under test: `343e4072ec3dc746433f72f185ef83952ccffe68`, `git status --short` empty at the start of each run (`<scratchpad>/runs3/<name>/status` is empty). The commits after it change documents only (this file, the three pages, the quickstart, tasks, the glossary, a news fragment word). Each run: `uv run pytest <node id> [-k <variant>] -v -s --pdb` with the standard input of pytest held open by `sleep 86400` (macOS: `sleep infinity` exits at once), from the repository root, one run after the other. The kubeconfig of each run is `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-<N>/vcluster0/kubeconfig`; the directory numbers 1457 to 1461 are in the order of the runs (inferred from the sequence of directories and times; the success logs do not print the path) and the directories are deleted by pytest.

| Node id | Command argument | Started | vCluster | Dir | Result line |
|---|---|---|---|---|---|
| `backend/tests/e2e/test_infrahub_services.py` (whole file; the test is `api_only`, so `[ui-chromium]` is skipped) | the file | 2026-11-10T15:57:14Z | `pytest-2e5b2014-6543-4120-8c5f-931ddc3e96be` | 1457 | `PASSED` and `============= 1 passed, 1 skipped, 4 warnings in 283.70s (0:04:43) =============` |
| `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_moves_only_the_overridden_service[api-chromium]` | `-k api-chromium` | 2026-11-10T16:16:04Z | `pytest-9c10003c-0c09-455e-90f5-58380a31c89a` | 1458 | `PASSED17:20:50 info Removing vCluster container ...` and `=========== 1 passed, 1 deselected, 4 warnings in 291.59s (0:04:51) ============` |
| same, `[ui-chromium]` | `-k ui-chromium` | 2026-11-10T16:21:00Z | `pytest-fed2db8d-e89c-4cc6-a6a9-583d26f3cb50` | 1459 | `PASSED17:25:48 info Removing vCluster container ...` and `=========== 1 passed, 1 deselected, 4 warnings in 292.27s (0:04:52) ============` |
| `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_refusals_name_the_service[api-chromium]` | `-k api-chromium` | 2026-11-10T16:25:56Z | `pytest-7bf54357-1c23-4a38-aa40-7ee82f0e5bf4` | 1460 | `PASSED17:30:36 info Removing vCluster container ...` and `=========== 1 passed, 1 deselected, 4 warnings in 284.08s (0:04:44) ============` |
| `backend/tests/e2e/test_deploy_generic_app.py::test_deploy_generic_app[api-chromium]` | `-k api-chromium` | 2026-11-10T16:30:47Z | `pytest-567dff25-b7c4-4f18-bf30-7a791f44a02d` | 1461 | `PASSED17:33:34 info Removing vCluster container ...` and `=========== 1 passed, 1 deselected, 4 warnings in 169.70s (0:02:49) ============` |

Logs: `<scratchpad>/runs3/<name>/pdb.log`. The log times are local (UTC+1). No run reached a pdb prompt; every test passed on its first run on this commit. The first launch of this series used a runner whose exit detection hung after `test_infrahub_services.py` had already passed; that run is the one in the table, and the other four were started by a corrected runner. `test_infrahub_services.py` failed on the previous commit at the same Traefik check (section "T062", run 3) and passes now.

## The upgrade of a running Infrahub deployment, repeated with the fix (quickstart step 7)

Same throwaway test as in "T062" (`<scratchpad>/test_zz_throwaway_upgrade.py`, copied into `backend/tests/e2e/` for each run and deleted afterwards, so it is not in the repository), without the `LABELER` emulation: the label comes from the product. It deploys `infrahub-enterprise` 1.6.0 on driver version 4, loads driver version 5 (current `master`), calls `deployments.update_version`, and writes a timeline: the Ingresses every second, one request per second to `/api/health` through the dedicated Traefik with `Host: task-manager-test-environment.styrmin.com`, the deployment status every 2 seconds. The operator pass is `STYRMIN_OPERATOR_RECONCILE_INTERVAL` in `backend/tests/e2e/fixtures/styrmin-values.yaml` (`"5"` in the repository, set to `"60"`, the default of `SETTINGS.operator.reconcile_interval`, for the 60-second runs, and restored with `git checkout`). Commit `343e4072`, tree clean except the throwaway file and that value. Command, from the repository root (`<scratchpad>/run_up.sh` runs the four in order):

```bash
REPO_ROOT=$PWD TIMELINE_FILE=<scratchpad>/up/<run>/timeline.txt HOLD_FILE=<scratchpad>/up/<run>/hold \
  uv run pytest backend/tests/e2e/test_zz_throwaway_upgrade.py -k api-chromium -v -s < <(sleep 86400)
```

| Run | Pass | vCluster kubeconfig dir | Upgrade started | Probes | Probes without HTTP 200 | Time without HTTP 200 | Built Ingress first seen | Chart Ingress `styrmin-task-manager` gone |
|---|---|---|---|---|---|---|---|---|
| 5-1 | 5 s | `pytest-1462` | 16:38:28.1 | 112 | 0 | none | +5.9 s | first listing without it at +42.4 s |
| 60-1 | 60 s | `pytest-1463` | 16:45:07.5 | 126 | 12 (all HTTP 404) | 12 s (16:45:50.6 to 16:46:02.6) | +55.8 s (HTTP 200 again at +55.1 s) | +43.0 s |
| 5-2 | 5 s | `pytest-1464` | 16:51:31.6 | 118 | 0 | none | +7.3 s | first listing without it at +41.5 s |
| 60-2 | 60 s | `pytest-1465` | 16:57:49.5 | 120 | 7 (all HTTP 404) | 7 s (16:58:33.6 to 16:58:40.6) | +50.8 s (HTTP 200 again at +51.1 s) | +44.1 s |

Each run ended `1 passed, 1 deselected, 4 warnings` (371.31 s, 407.97 s, 370.53 s, 373.73 s); the test asserts nothing about the answers. The numbers are measured samples on one machine (macOS, Docker, one local vCluster), not guarantees. The time resolution is one second (one probe per second). "Built Ingress first seen" is the time of the first Ingress listing that has `styrmin-svc-task-manager`, taken once per second.

- At the 5-second pass, the operator built `styrmin-svc-task-manager` about 6 to 7 seconds after the update started, while the chart's Ingress still existed. Both Ingresses had the same host for about 30 seconds (16:38:39 to 16:39:10 in run 5-1, 16:51:43 to 16:52:13 in run 5-2), and no request failed in 230 probes. The first listing without the chart's Ingress is at 16:39:10.5 (+42.4 s) and 16:52:13.1 (+41.5 s); the listing before it, in each run, still had it. The listings are written when the set changes, taken once per second.
- At the 60-second pass, Helm removed the chart's Ingress at +43 s and +44 s, and the operator built the new one at +51 s and +55 s, which is the gap. This matches the earlier hand-labelled sample of "T062" (9 s). The length of the gap depends on when the next operator pass falls after the Helm upgrade, so it can be shorter or longer, up to about 60 seconds. Two samples do not give a distribution.
- Unexplained: in both 5-second runs, `styrmin-svc-task-manager` was built, deleted about 2 to 3 seconds later (the `uid` changed: `19e11248` to `9b464046` in run 5-1, `6309edcf` to `842f9028` in run 5-2) and built again about 3 seconds after that (16:38:33.9, 16:38:37.2, 16:38:39.4 and 16:51:38.8, 16:51:40.9, 16:51:43.9). It was not in the 60-second runs. No request failed, because the chart's Ingress still served the host. The cause is not known and was not investigated. The same sequence was seen in "T062", run 1.
- The `infrahub` Ingress `styrmin-infrahub-ingress` kept its `uid` in all four runs (`421e6e08`, `7abadf3b`, `4544769a`, `aaeed29a`, listed before and after). Its host was not probed.
- Not verified: the Prefect UI behaviour with a Tailscale class (no operator, no tailnet); the same measurement with `infrahub` driver version 5 to 6 (community driver, same service, not run); other intervals, clusters or machines.

## 5 Whys

1. Why did the Prefect UI host answer HTTP 404 after the Infrahub upgrade? Because the dedicated Traefik of the environment did not serve `styrmin-svc-task-manager`, and the chart's Ingress for the same host was gone (proven: probes in "T062" run 1, 64 of 115 requests; the Traefik answered 200 within one second of adding the label by hand).
2. Why did Traefik not serve it? Because it starts with `--providers.kubernetesingress.labelselector=styrmin/environment_id=<id>` and the built Ingress had no `styrmin/environment_id` label (proven: `chart_values.j2.yaml:14`, the Traefik log line, `kubectl get ingress -o jsonpath` in both the T062 run and the control run of this section).
3. Why did the Ingress have no such label? Because the builder set only `styrmin.io/service-name`, and the Styrmin labels of the other objects come from a separate post-render patch of the chart that the built Ingress never passes through (proven: `utilities/ingress.py` before the fix, `builders/application.py:474-475`, `builders/utility.py:38-44`).
4. Why did the builder not copy those labels? Because the Ingress was first made equal to the chart Ingress in its annotations and class, with a shared function (`build_ingress_settings`), and the labels were not part of that list. The labels were not in the spec or the research either (proven for the files: `grep -rn environment_id specs/033-service-ingress-override/*.md` finds nothing outside this file and the quickstart text added with the fix; the reasoning behind the first design is not known).
5. Why did the first version pass its tests? Because the controller's label selector is outside the unit under test and no test read it: the unit tests asserted the labels that the builder set, and the end-to-end tests asserted Kubernetes objects. The one existing test that sends traffic through the controller, `test_infrahub_services.py`, was not run in the chunks that changed the Ingress (proven: "Not verified" in the T033 section; it failed on commit `772256e6` and passes on `343e4072`).
6. Why was it not detected earlier? Because the only check that could see it is a request through the controller, and the feature's own end-to-end tests did not send one. A measurement of the upgrade (T062) did. The fix adds a unit test that reads the selector from the template, and traffic checks to the override and generic-app end-to-end tests.

## T065: the quickstart walk-through

Commit `343e4072` for the runs; the text changes are in the documentation commit.

| Step | Run | Where |
|---|---|---|
| Prerequisites | yes (`vcluster`, `docker`, `uv`, `pnpm` on the PATH; the runs above created their own vClusters) | this section |
| 1. Unit and contract checks | yes, by hand: see "Final checks" below | this section |
| 2. One service moves, the other stays | not by hand. The end-to-end test `test_service_ingress_override_moves_only_the_overridden_service` runs it (API and UI variants), with the traffic check added. `ingressClassOverridden: true` is read by the functional test `test_service_ingress_propagation.py`, not by the end-to-end test | table above |
| 3. No override (`generic-app`) | not by hand. `test_deploy_generic_app` runs the generic-app part, with the traffic check added. The case of two external services (one Ingress carries the application address) is covered by unit tests only (`test_ingress_utility_service_ingress.py`), not run on a cluster | table above |
| 4. UI | not by hand. The `[ui-chromium]` variant runs it. The text of the step said "Configuration, Service overrides"; the UI is the Settings tab, the edit drawer, section Services, and Review & apply. The step now says so. The same wording was wrong in the news fragment `598.added.md`, the glossary, `spec.md` and `tasks.md`, and was changed there | table above |
| 5. Refused requests | not by hand. `test_service_ingress_override_refusals_name_the_service` runs it | table above |
| 6. Dedicated ingress controller | not by hand. Scenario 3 of the override test runs it, now with requests through the controller | table above |
| 7. Existing Infrahub deployment | yes, by hand, six times in total (two before the fix, four after) | previous section |

The product matched the text in steps 2, 3, 5 and 6 except for what the traffic check added; step 7 found and closed the label defect. Steps 2 to 6 were not walked by a person at the UI or the CLI: Playwright MCP is not available, and the end-to-end tests drive the same steps.

## Final checks (T064 again, after the fix)

Run on the working tree that holds commit `343e4072` plus the documentation changes of this section (no source change after `343e4072`).

| Command | Result |
|---|---|
| `uv run invoke format lint` | exit 0; `All checks passed!`, `283/283 .graphql files passed validation.` |
| `uv run invoke test` | exit 1; `FAILED tests/unit/services/telemetry/test_sender.py::test_send_report_returns_false_when_the_connection_is_refused - assert 7.858845833921805 < 2` and `1 failed, 6076 passed, 8 skipped, 41 warnings in 254.74s (0:04:14)`. This is the one failure known on the base commit; it is the only failure. |
| `cd frontend && pnpm test` | exit 0; `Test Files  104 passed (104)`, `Tests  1255 passed (1255)` |
| `pnpm lint` | exit 0; `All matched files use Prettier code style!` |
| `pnpm exec tsc -b` | exit 0, no output |
| `uv run styrmin export graphql-schema schema.graphql`, `uv run invoke generate`, `uv run invoke validate-graphql` | exit 0; `283/283 .graphql files passed validation.`; no file changed |
| `uv run rumdl check` | `Success: No issues found in 81 files` |
| `cd docs && pnpm build` | exit 0; `[SUCCESS] Generated static files in "build".` |

`cli/tests` and `python_sdk/tests` were not run again: no file of theirs or of the SDK changed.

# Review fixes (#598)

Six reviewers (code, tests, comments, errors, types, simplify) reported findings on `git diff 5de4af5d..HEAD` at commit `6050cf69`. Each finding was checked again before a fix: every one reproduced, so no finding was rejected. Times are UTC. `<scratchpad>` is `/private/tmp/claude-503/-Users-Simon-styrmin-598-spec/2ab6e2fa-7180-493d-8211-590f003133bd/scratchpad`. The kubeconfig files are deleted with each session.

## Tests that fail before a fix and pass after it

| Finding | Test (new) | Line that fails on the old code | After the fix |
|---|---|---|---|
| F1 | `test_ingress_utility_service_ingress.py::TestContextStoredBeforeThisRelease` (3 tests) | `KeyError: 'scope'` (three times) | pass |
| F1 | `test_ingress_operator_reconcile.py::...::test_the_deployment_timer_reconciles_a_context_stored_before_this_release` | `assert ['Failed to b...y-deployment'] == []` (the timer logged "Failed to build desired resources for drift check") | pass |
| F1 | the three tests of the timer logs in the same file | `assert 0 == 1` (no `logger.exception`), and `assert False` for the reconciliation errors in both timers | pass |
| F2 | `test_apply_utility_resources.py` (6 tests) | `Failed: DID NOT RAISE <class 'kubernetes_asyncio.client.exceptions.ApiException'>` for an Ingress with status 403, 422 and 500 and for a custom kind with 422; `assert '404' in '... the CRD type may not be installed yet'` | 6 passed |
| F3 | `TestDeploymentWithoutAnyFqdnSuffix::test_a_class_only_override_without_any_suffix_raises` | `Failed: DID NOT RAISE <class 'ValueError'>` (the builder returned no Ingress) | pass; the two other cases (every service overridden with a suffix: no error; one overridden and one not: error) pass before and after |
| F4 | `test_service_ingress_validation.py` (`tcp_or_udp` tests, 8 cases) | `assert 'errors' in {'data': {'updateDeployment': {'id': ...}}}` (the write was accepted) | pass |
| F4 | frontend: `ServiceOverridesSection.test.tsx`, `DeployFormPage.test.tsx`, `NetworkingSummary.test.tsx` | `expected <input ...> to be null`, `expected <div role="group" ...> to be null` (3 tests) | pass |
| F5 | `python_sdk/tests/test_deployments.py` (`service_row` tests) | `StopIteration` (the mutation was sent) and `Regex pattern did not match` (the Pydantic error text) | 384 passed |
| M1 | `test_service_ingress_propagation.py::test_a_stored_services_key_with_no_block_reads_as_no_override[null]` | `'errors': [{'extensions': {'code': 'INTERNAL_ERROR'}, ... 'path': ['deployment', 'deployedServices']}]` | pass |
| M2 | `test_the_context_and_the_graphql_read_agree_on_which_service_an_override_applies_to` (`external-tcp`, `external-udp`, `internal-http`) | `assert True is False` (three times) | pass |
| M3 | `UpgradeErrorAlert.test.tsx` (4 tests) | `Unable to find an element by: [data-testid="upgrade-dropped-ingress-override"]` | 8 passed |
| M4 | `TestKopfRegistrationOfTheIngressHandlers`, `TestAChartsIngressIsLeftAlone` | see the mutation checks below | pass on the unmutated code |

M5 is a test that pins the behavior of the first release (`test_no_application_address_when_the_first_declared_service_is_external_tcp_or_udp`). It passes on the old code by design.

## Mutation checks of M4

Run in a throwaway git worktree under `<scratchpad>/mut1`, with the modified test file copied in; the worktree was removed afterwards and the repository was never mutated.

| Mutation | Result |
|---|---|
| `labels={LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE}` removed from both Ingress drift handlers | `2 failed, 30 passed`: `assert None == {'app.kubernetes.io/managed-by': 'styrmin'}` for `kopf_on_ingress_update` and `kopf_on_ingress_delete` |
| `plural="ingresses"` changed to `plural="ingress"` on the update handler | `1 failed, 31 passed`: `At index 2 diff: 'ingress' != 'ingresses'` |
| `label_selector = ""` in `list_managed_resources` (the selector matches every object) | 4 failed, among them `TestAChartsIngressIsLeftAlone`: `assert ['my-chart-in...in-svc-stale'] == ['styrmin-svc-stale']` (the chart Ingress is listed, and would be deleted) |
| the release-reference part removed from the selector | `2 failed, 30 passed` (`test_returns_the_ingresses_of_the_deployment`, `test_a_helm_ingress_is_not_listed_for_the_deployment`, both existing tests) |

The Ingress of a chart in these tests has the labels that Helm sets (`app.kubernetes.io/managed-by: Helm`, `helm.sh/chart`) and none of the Styrmin ownership labels. The fake Kubernetes API applies the label selector that the real `list_managed_resources` builds, so the selector is under test. The existing in-memory cluster of `test_ingress_release_reference_label.py` re-implements the selector in the fake, so a mutation of the real selector would not fail there; the new tests are in `test_ingress_operator_reconcile.py` for that reason.

## Checks on the final commit

Commit `3923471c8a5868d171cd7b12eeff73f6a59f2e3f`.

| Check | Result |
|---|---|
| `uv run invoke format lint` | exit 0, `283/283 .graphql files passed validation`, generated types up to date (`git status --short` empty) |
| `uv run invoke test` | `1 failed, 6131 passed, 8 skipped, 41 warnings in 365.91s (0:06:05)`. The one failure is the known one: `tests/unit/services/telemetry/test_sender.py::test_send_report_returns_false_when_the_connection_is_refused - assert 7.847563917050138 < 2` |
| `cd frontend && pnpm test` | `Test Files 105 passed (105)`, `Tests 1269 passed (1269)` |
| `pnpm lint`, `pnpm exec tsc -b`, `pnpm build` | 0 errors (35 warnings; one of them, `react-refresh/only-export-components` in `ServiceOverridesSection.tsx` line 55, is in a file that this review changed; the export is `serviceOverridesSchema`, which exists at the base commit `5de4af5d` (line 50); the other 34 warnings were not compared with the base commit); `tsc` exit 0; build succeeded |
| `uv run pytest python_sdk/tests -q` | `384 passed` |
| `uv run pytest cli/tests -q` | `416 passed` |
| `cd docs && pnpm build`, `rumdl check .` | `[SUCCESS] Generated static files in "build".`, `Success: No issues found in 81 files` |
| `uv run styrmin export graphql-schema schema.graphql`, `uv run invoke generate` | no diff |
| `uv run towncrier build --draft --version x` | builds; three fragments |

## End-to-end runs on commit `3923471c8a5868d171cd7b12eeff73f6a59f2e3f`

`git status --short` was empty at the start of each run. The runs ran one after the other by `<scratchpad>/run_all.sh` (`<scratchpad>/run_one.sh`). Each used this command from the repository root, with `<node id>` and `<expr>` from the table (the first run has no `-k`):

```bash
sleep 86400 | uv run pytest "<node id>" -k "<expr>" -v -s --pdb > <scratchpad>/review-runs/<name>/pdb.log 2>&1
```

| Name | Node id, `-k` | Started (UTC) | vCluster | Kubeconfig |
|---|---|---|---|---|
| infrahub-services | `backend/tests/e2e/test_infrahub_services.py` (whole file; the `ui-chromium` variant is skipped, the test is `api_only`) | 2026-11-10T17:50:16Z | `pytest-b3710848-06fc-43a3-8dff-002acdbf5e1b` | `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1484/vcluster0/kubeconfig` |
| override-api | `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_moves_only_the_overridden_service`, `api-chromium` | 2026-11-10T17:56:18Z | `pytest-d5325d9a-027b-43d8-88bc-10029855a443` | `.../pytest-of-Simon/pytest-1485/vcluster0/kubeconfig` |
| override-ui | same, `ui-chromium` | 2026-11-10T18:03:01Z | `pytest-a90d92a6-2d32-46e4-9b95-ca39a3283bed` | `.../pytest-1486/vcluster0/kubeconfig` |
| refusals | `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_refusals_name_the_service`, `api-chromium` | 2026-11-10T18:08:13Z | `pytest-02b7e762-b0f9-4b05-b6f9-2377821decf0` | `.../pytest-1487/vcluster0/kubeconfig` |
| generic | `backend/tests/e2e/test_deploy_generic_app.py::test_deploy_generic_app`, `api-chromium` | 2026-11-10T18:12:54Z | `pytest-ae3e2f62-a77c-4e78-b05f-5b3a7b852db8` | `.../pytest-1488/vcluster0/kubeconfig` |

Verbatim result lines (ANSI colors removed; `-s` puts the vCluster log in front of the result line; the local time in those lines is UTC+1):

```text
infrahub-services  PASSED   (the line after `PASSED` is the next test, SKIPPED: `...[ui-chromium] SKIPPED18:55:56 info Removing vCluster container vcluster.cp.pytest-b3710848-06fc-43a3-8dff-002acdbf5e1b...`)
                   ============= 1 passed, 1 skipped, 4 warnings in 351.47s (0:05:51) =============
override-api       PASSED19:02:39 info Removing vCluster container vcluster.cp.pytest-d5325d9a-027b-43d8-88bc-10029855a443...
                   =========== 1 passed, 1 deselected, 4 warnings in 390.30s (0:06:30) ============
override-ui        PASSED19:08:00 info Removing vCluster container vcluster.cp.pytest-a90d92a6-2d32-46e4-9b95-ca39a3283bed...
                   =========== 1 passed, 1 deselected, 4 warnings in 303.28s (0:05:03) ============
refusals           PASSED19:12:38 info Removing vCluster container vcluster.cp.pytest-02b7e762-b0f9-4b05-b6f9-2377821decf0...
                   =========== 1 passed, 1 deselected, 4 warnings in 270.35s (0:04:30) ============
generic            PASSED19:15:39 info Removing vCluster container vcluster.cp.pytest-ae3e2f62-a77c-4e78-b05f-5b3a7b852db8...
                   =========== 1 passed, 1 deselected, 4 warnings in 166.41s (0:02:46) ============
```

Every test passed on its first run on this commit; no pdb prompt was reached. After the runs, no vCluster, container of a vCluster or `sleep 86400` process of this session remained (`vcluster list --driver docker` is empty).

What these runs do not show: the assertion that no Ingress is left after the deletion was removed from `test_deploy_generic_app` (M6), so no end-to-end test shows that the operator deletes an Ingress on its own. The Tailscale controller is still not verified. The tests ran on one machine (macOS, Docker); the CI matrix was not run. The three fixes in the Ingress builder and the apply task (F1 to F3) were not run against a deployment that has a context stored before this release; that case is covered by unit tests only.

## Findings and decisions

Reviewer: code (C), tests (T), comments (K), errors (E), types (Y), simplify (S).

| Finding (reviewer, severity, location) | Decision | Commit or reason |
|---|---|---|
| F1 `KeyError: 'scope'` in the builder for a stored context (C, E, Y; critical; `ingress.py` 269-371) | fixed: `.get`; an entry without `scope` or `driver_service_name` is not external; timer logs `logger.exception` and the reconciliation errors | `ad2ed03d` |
| F2 `apply_utility_resources` swallows every `ApiException` (E; critical; `agent/tasks/application.py` 58-71) | fixed for Ingress (raises) and custom kinds (404 only, status and reason logged); NetworkPolicy still skipped on any error, status and reason logged. Narrowed later in the code-review gate: only the Ingress raises, every other kind is skipped on any error and logged with the status and reason | `7eb7434e`; NetworkPolicy left open (ADR open points) |
| F3 `if not unique_hosts: continue` skips an Ingress silently (E; high; `ingress.py` 324) | fixed: same `ValueError` text for both callers, naming the deployment and the service | `ad2ed03d` |
| F4 validator ignores `kind` (E; high; `validator.py` 81, `deployment.py` 419) | fixed: `DeclaredService(scope, kind)`; one rule `service_gets_ingress`; `reason` is a `Literal`; frontend excludes tcp and udp | `d0bb6e17` |
| F5 SDK ignores a misspelled `services` key (E; high; `deployments.py` 251-281) | fixed: `check_service_rows` raises `ManifestValidationError`; `apply` reports it as a failed outcome | `f03a0cea` |
| F6 reference page lists four labels (K; high; `styrmindeployment.md` 57-59) | fixed: six labels, and the dedicated controller rule | `7256c1a7` |
| M1 three readers of `config["services"]` (C, Y, E) | fixed: `parse_service_overrides`; a stored null raised `INTERNAL_ERROR` | `d9f4c8c0` |
| M2 context and resolver apply an override to different services (Y, C) | fixed: one rule `service_gets_ingress` in the context, the resolver and the builder | `d9f4c8c0` |
| M3 Upgrade dialog cannot clear an override (frontend, S, Y, E) | fixed: alert with the steps (Settings, Update Settings, Services, Clear, Review and apply) | `3cdfe562` |
| M4 kopf registration and chart Ingress untested (T 1, 8) | fixed: tests, with mutation checks above | `4ad7280e` |
| M5 first declared service is external tcp (T 4) | pinned; the spec is silent (FR-002 and research D-006 do not cover it); behavior not changed | `029dafde` |
| M6 (a) deletion assertion cannot fail (T 3) | fixed: assertion and claims removed | `029dafde` |
| M6 (b) 404 through Traefik does not isolate the class (T 5) | fixed: docstring and comment say what the 404 shows | `029dafde` |
| M6 (c) evidence contradicts itself; wrong section titles in the ADR, quickstart, tasks (T 6) | fixed: older lines marked superseded, top block rewritten, titles corrected | `029dafde`, `c01438b9`, this section |
| M7 false or unsupported statements, glossary terms, writing rules (K) | fixed: changelog fragment, three claims in `service-ingress-overrides.md`, bold lead-ins, idioms, labels in CONTEXT and the data model, the Services section name, the application address rule, handler docstring; terms "readable host" and "application address" added | `c01438b9`, `3923471c` |
| Code, medium: class-only override on the first service removes the application address | recorded (research D-003); effect stated in the docs | `c3014f26` |
| Code, medium: `_service_overrides_by_deployment` reads every peer deployment on each context generation | recorded; not measured | `c3014f26` |
| Code, low: default IngressClass may add `spec.ingressClassName` with `dedicated_ingress` | recorded; plausible, not verified | `c3014f26` |
| Errors, medium: `list_managed_resources` returns no Ingress when the list fails; drift handlers return without a log when the label is missing | recorded | `c3014f26` |
| Errors, low: `_deployment_labels` drops a label with no value silently | recorded | `c3014f26` |
| Simplify: unread `ingress_class` key, unreachable fallback, `importlib` and "planned symbol" comments, duplicated fixtures, history comments, twin helpers, names, unused constants | recorded; the optional comment cleanups were not done | `c3014f26` |
| Types, medium: suffix and class rules in two languages without shared cases; untyped `deployed_services` | recorded | `c3014f26` |
| Tests: kopf details beyond M4, join test of `compute_service_address` and the builder, FR-005, FR-011 and FR-014 (documentation only), SC-005, no test reads an override back through the CLI | recorded | `c3014f26` |
| Errors: `apply_utility_resources` swallow for NetworkPolicy; the `ValueError` for a missing suffix reaches Prefect as a plain exception | recorded (the text improved) | `c3014f26` |

# Code-review gate fixes (#598)

The pre-PR code review of commit `0e19b30f` reported seven findings graded IMPORTANT (I1 to I7). Each was checked against the code before it was changed. Times are UTC. `<scratchpad>` is `/private/tmp/claude-503/-Users-Simon-styrmin-598-spec/2ab6e2fa-7180-493d-8211-590f003133bd/scratchpad`.

| Finding | Decision | Commit |
|---|---|---|
| I1 The Review dialog text for `services[*].fqdnSuffix` says an external DNS record is republished, but an overridden Ingress has no external-dns annotation | Defect confirmed (`utilities/ingress.py` 373-376, FR-004). Text rewritten for both service rules; a Vitest assertion pins it | `47b454f3` |
| I2 No warning that an override drops the allow-list, the external DNS record and the application address | Confirmed. One sentence in `ServiceIngressFields.tsx` (shared by the drawer and the deploy form), the Review dialog text of I1, a Vitest assertion, and an open point in ADR-090 (no write-time warning when `ip_whitelist` is set) | `47b454f3` |
| I3 `apply` with config keys and no `services` clears the stored overrides without a warning | Confirmed. `ApplyOutcome.dropped_service_overrides` and a `warning:` line on stderr; SDK and CLI tests; docs updated | `630cd948` |
| I4 The HelmRelease timer does not catch the `ValueError` of the builder | Confirmed by a test that failed with the escaping `ValueError`. The timer logs with `logger.exception` and returns | `5b7a644e` |
| I5 `apply_utility_resources` now fails the flow for any custom kind refused with a status other than 404 | Confirmed against `origin/develop`, which logged and skipped every `ApiException`. Only an Ingress error raises; every other kind is skipped and logged with the status and reason. ADR-090, the implementation report and this file corrected | `57bf1060` |
| I6 Changelog, beta status and ADR do not name the affected drivers, the HTTP 404 window or the failure mode | Fragments rewritten in short sentences; affected drivers read again from `driver/examples/*/driver.styrmin.yml` (only `generic-app`, `infrahub` and `infrahub-enterprise` declare `scope: external`; versions 2, 6 and 5). beta-status and ADR-090 follow | `2e67cbac` |
| I7 The release-reference fragment ends with an internal sentence | Rewritten for release notes readers | `2e67cbac` |

## Tests that fail before the fix and pass after it

| Finding | Test | Before | After |
|---|---|---|---|
| I1 | `config-impact.test.ts` "states that an overridden Ingress carries only the ingress class" | `AssertionError: expected 'Ingress of this service will be recre…' to contain 'only the ingress class'` | passed |
| I2 | `ServiceOverridesSection.test.tsx` "says that an overridden Ingress carries only the ingress class" | `Unable to find an element by: [data-testid="service-ingress-override-note"]` | passed |
| I3 SDK | `python_sdk/tests/test_deployments.py` (5 new tests on `dropped_service_overrides`) | `AttributeError: 'ApplyOutcome' object has no attribute 'dropped_service_overrides'` (5 failed, 1 passed in the selection) | 142 passed |
| I3 CLI | `cli/tests/test_deployments.py` (4 new tests) | `assert [] == ['warning: my...s to keep it']` | 420 passed |
| I4 | `test_ingress_release_reference_label.py::TestTheHelmReleaseTimerSurvivesAContextThatCannotBeBuilt` | `ValueError: FQDN suffix is required to build the Ingress of deployment 00000000-0000-0000-0000-0000000000aa (application 'testapp'): ...` | 42 passed in the two operator test files |
| I5 | `test_apply_utility_resources.py::test_a_custom_kind_other_than_ingress_is_skipped_whatever_the_status[403, 422, 500]` | `kubernetes_asyncio.client.exceptions.ApiException: (403)`, `(422)`, `(500)`; 3 failed, 5 passed | 8 passed |

The Ingress cases (403, 422, 500 raise) and the 404 case (skipped, logged with status and reason) were already in the file and pass unchanged.

## Checks on the final code commit `2e67cbac`

- `uv run invoke format lint`: exit 0 (ruff, rumdl "No issues found in 81 files", `283/283 .graphql files passed validation`, generated types up to date).
- `uv run invoke test`: `1 failed, 6134 passed, 8 skipped, 41 warnings in 268.44s (0:04:28)`. The one failure is the known one, `tests/unit/services/telemetry/test_sender.py::test_send_report_returns_false_when_the_connection_is_refused` (`assert 7.7986050840700045 < 2`).
- `pnpm test`: `Test Files 105 passed (105)`, `Tests 1271 passed (1271)`. `pnpm lint`: 0 errors, 35 warnings. `pnpm exec tsc -b`: no output. `pnpm build`: built.
- `python_sdk/tests`: 389 passed. `cli/tests`: 420 passed. `docs` build: `Generated static files in "build"`.
- `uv run styrmin export graphql-schema schema.graphql` and `uv run invoke generate`: no diff. `uv run towncrier build --draft --version x`: renders the three fragments.
- `src/__tests__/deploy-form/DeployFormPage.test.tsx` "shows the same formatted label on the trigger when a version is selected" failed in 5 of 5 runs of that file alone with this change and in 1 of 2 runs without it (`Unable to perform pointer interaction as the element has pointer-events: none`). The test selects a driver version with `services: []`, so the component of I2 renders nothing there. It passed in the full run. It is timing dependent and not caused by this change; the cause is not investigated.

## End-to-end runs on `2e67cbac`

Tree clean at the start of each run (`<scratchpad>/gate/<name>.status` is empty). Command, from the repository root, one run after the other (`sleep 86400` held standard input open through a process substitution, because a pipe waited for `sleep`; the runner is `<scratchpad>/gate/run_e2e.sh`):

```bash
uv run pytest "<node id>" -k api-chromium -v -s --pdb < <(sleep 86400) > <scratchpad>/gate/<name>.log 2>&1
```

| Node id | Started | vCluster | Kubeconfig | Result line |
|---|---|---|---|---|
| `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_moves_only_the_overridden_service` | 2026-11-10T18:45:10Z | `pytest-fbf9db71-efce-40bc-a000-2eadb9e1a8cf` | `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1499/vcluster0/kubeconfig` | `PASSED19:51:12 info Removing vCluster container vcluster.cp.pytest-fbf9db71-efce-40bc-a000-2eadb9e1a8cf...` and `=========== 1 passed, 1 deselected, 4 warnings in 366.73s (0:06:06) ============` |
| `backend/tests/e2e/test_deploy_generic_app.py::test_deploy_generic_app` | 2026-11-10T18:51:20Z | `pytest-e5f7c94e-5203-4106-9d89-1ff0473f7dc5` | `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1500/vcluster0/kubeconfig` | `PASSED19:54:13 info Removing vCluster container vcluster.cp.pytest-e5f7c94e-5203-4106-9d89-1ff0473f7dc5...` and `=========== 1 passed, 1 deselected, 4 warnings in 174.70s (0:02:54) ============` |

The pytest directory of each run is inferred from the modification time of the kubeconfig files (19:45 and 19:51 local time, UTC+1); the logs do not print the path. Both runs ended at the first attempt, with no pause at `pdb`. Afterwards `pgrep` found no `sleep 86400`, `pytest` or `vcluster` process and `docker ps` listed no vCluster container.

Not covered by these runs: the warning of I3 (a unit-level and CLI-level change, not run against a live server) and the log text of I5 (unit tests only).

## Review comments of Fatih on PR 602 (2026-11-13)

Fatih approved the PR and left six inline comments. This section records what changed and how it was checked.

### What changed

| Comment | Change |
|---|---|
| `generic-app/values.j2.yml` line 26, a reaction on the removed host code | No change. It asks for nothing. |
| `generic-app/values.j2.yml` line 71, "let's remove this comment" | The three-line comment about the missing `ingress:` block is removed. |
| `infrahub/driver.styrmin.yml` and `infrahub-enterprise/driver.styrmin.yml` line 110, "Remove" | The five-line comment about the `task-manager` service is removed. The original one-line comment stays. |
| `infrahub/values.j2.yml` line 70 and `infrahub-enterprise/values.j2.yml` line 72, "Remove" | The `prefect-server.ingress` block (`enabled: false`) and its comment are removed from both drivers. |

The last row relies on the chart default. The `prefect-server` subchart of `infrahub` 4.33.2 and of `infrahub-enterprise` 4.19.2 sets `ingress.enabled: false` (`values.yaml` line 539, and the template renders an Ingress only when it is `true`). Neither Infrahub chart overrides it. Both charts were read on 2026-11-13 with `helm pull oci://registry.opsmill.io/opsmill/chart/<chart> --version <version>`. A later chart version that changes the default is not checked.

Text that said the driver "turns the chart's Prefect Ingress off" was corrected in `migrating-external-service-ingress.md`, `creating-a-driver.md`, ADR-090, `spec.md` (FR-013), `plan.md`, `research.md`, `tasks.md` (T024 and T031) and in two end-to-end comments and one assertion message. The unit test `test_the_chart_prefect_ingress_is_off` became `test_the_driver_does_not_enable_the_chart_prefect_ingress`. It accepts a missing key or `false`, and fails when the driver sets `true`: re-adding `enabled: true` in a scratch change made it fail for `infrahub`, and the file was restored.

### Rendered values before and after

A script rendered `values.j2.yml` of each driver from commit `6496a07f` and from the working tree and compared the parsed results.

- `infrahub` and `infrahub-enterprise`: the only difference is `- /prefect-server/ingress = {"enabled": false}`. The parsed `driver.styrmin.yml` is equal before and after.
- `generic-app`: `values.j2.yml` is equal when comment lines and blank lines are ignored.

### Checks

| Check | Result |
|---|---|
| `uv run invoke lint` | exit 0 |
| `uv run invoke test` | `1 failed, 6134 passed, 8 skipped in 663.97s`. The one failure is the known `services/telemetry/test_sender.py::test_send_report_returns_false_when_the_connection_is_refused`. |
| `cd docs && pnpm build` | exit 0 |

### End-to-end runs

The runs started on the working tree that became the commit of this change. No tracked file changed after the first run started: only Helm chart archives that the fixture downloads, which git ignores. Base commit `6496a07f`. Command: `uv run pytest <node> [-k <variant>] -v -s --pdb` with its standard input held open by `sleep 86400`. On macOS this works with `< <(sleep 86400)`: a pipe from `sleep` made my wrapper wait for the 24-hour `sleep` after pytest had finished.

| Node | Started (UTC) | vCluster | Kubeconfig directory (inferred from run order) | Result |
|---|---|---|---|---|
| `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_moves_only_the_overridden_service`, `-k api-chromium` | 2026-11-13T10:50:08Z | `pytest-95a28b5c-6834-4f3b-819b-924c071690f0` | `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1976/vcluster0/kubeconfig` | `1 passed, 1 deselected, 4 warnings in 387.83s (0:06:27)` |
| `backend/tests/e2e/test_infrahub_services.py` (whole file) | 2026-11-13T11:15:41Z | `pytest-8e66f206-4a6e-4ea7-8433-b03a3821fad3` | `.../pytest-1977/vcluster0/kubeconfig` | `1 passed, 1 skipped, 4 warnings in 338.42s (0:05:38)` |

The override test asserts that exactly one Ingress besides `styrmin-svc-task-manager` exists in the Infrahub namespace, and `test_infrahub_services.py` sends a request through the dedicated Traefik to the Prefect UI host. Both passed with the setting removed.

### A first attempt that did not finish

A first attempt, started at 2026-11-13T08:12Z (vCluster `pytest-4d90b261-e01e-41b9-bb54-eccb5f47da46`), paused at a failure in fixture setup: `StyrminTransportError: ReadTimeout: request to POST http://localhost:12277/graphql timed out after 30.0s`. It never reached the Ingress assertions, so it says nothing about this change.

- What was seen on the paused cluster: the Styrmin server and the Infrahub pods were `Running`. Several pods showed restarts about 118 minutes before the check (infrahub server 7, helm-controller 6, source-controller 7). `localhost:12277` did not answer, with no answer after 10 seconds.
- What the machine was doing: Docker's VM used about 320% CPU for containers of another project (`infrahubstorageencryption-*`), and the load average was 7 to 8.
- Cause: not proven. Machine load is the likely cause and was not isolated. The re-runs above passed under a similar load of 6.8 to 7.4.
- Evidence kept from that paused cluster, read with `kubectl` before it was deleted: in the namespace of the Infrahub Enterprise deployment there were exactly two Ingresses, `styrmin-infrahub-ingress` (hosts `infrahub-enterprise-232c58df-daf9-4f51-84d6-cb5231a847d4.styrmin.com` and `infrahub-enterprise-test-environment.styrmin.com`) and `styrmin-svc-task-manager` (host `task-manager-test-environment.styrmin.com`, label `styrmin.io/service-name: task-manager`). The HelmRelease values had no `prefect-server.ingress` key (`prefect-server` keys: `enabled`, `fullnameOverride`, `global`, `postgresql`, `server`). The cluster was deleted with `vcluster delete ... --driver docker`.

### Not verified

- The override and generic-app end-to-end tests with the UI variant, and `test_deploy_generic_app`, were not run again. The `generic-app` driver differs only in comments, which the comparison above shows.
- An upgrade of a running deployment from the old driver version was not run again. The measurement in the earlier section used driver versions 4 to 5. With the key removed, the rendered values of the new version differ only by the removed `ingress` key.
- No release check of other chart versions.
