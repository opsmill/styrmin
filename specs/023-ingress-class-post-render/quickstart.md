# Quickstart: Validate the Ingress Class Set Only After the Chart Renders

**Feature**: [spec.md](spec.md) | **Contracts**: [contracts/](contracts/) | **Data model**: [data-model.md](data-model.md)

## Prerequisites

- `uv sync`.
- `kubectl` with Kustomize v5 and `helm` on `PATH` for the integration test. Without them the test is skipped, which does not count as a pass.
- `docker` and `vcluster` on `PATH` for the E2E tests. The E2E fixtures create their own cluster; `uv run invoke dev` is not needed.

## 1. Unit tests

```bash
uv run pytest backend/tests/unit/agent/test_utility_resources.py \
  backend/tests/unit/agent/test_render_value_template_ingress_class.py -q
```

Expected ([contracts/post-render-patch.md](contracts/post-render-patch.md), [contracts/template-data.md](contracts/template-data.md)):

- `IngressClassNameRemovalPatch.render_value()` parses to an Ingress strategic merge patch with `spec: {ingressClassName: null}`;
- dedicated mode: one `IngressClassNameRemovalPatch` targeted at `kind: Ingress`, no `ingressClassName` `SpecPatch`, annotation `kubernetes.io/ingress.class: traefik`;
- shared mode with `ingress_class: nginx`: the `SpecPatch` and the annotation set to `nginx`, no removal patch;
- shared mode with no class: no class patch, no annotation entry, no removal patch;
- in dedicated mode the template reads the resolved `ingress_class` in the `instance`, `cluster`, `environment` and `deployment` sections.

## 2. Integration test on real `helm template` and `kubectl kustomize`

```bash
uv run pytest backend/tests/integration/test_ingress_class_post_render.py -v
```

Expected, for the `simple-app` chart (see the rule table in [data-model.md](data-model.md)):

| Chart `className` | Mode | `spec.ingressClassName` | `kubernetes.io/ingress.class` |
|-------------------|------|-------------------------|-------------------------------|
| `""`, `traefik`, `nginx` | dedicated | absent | `traefik` |
| `""`, `traefik`, `nginx` | shared, `ingress_class: traefik` | `traefik` | `traefik` |
| `nginx` | shared, no class resolved | `nginx` | not set by Styrmin |

The migrated `simple-app/values.j2.yml` gives the same Ingress as the case `className: ""` in both modes. No test is reported as `SKIPPED`.

## 3. Example drivers and documentation contain no Ingress class value (SC-001)

```bash
grep -n "ingress_class\|className" driver/examples/{simple-app,semaphore,slurpit}/values.j2.yml \
  | grep -v storage_class
grep -n "ingress_class\|className" docs/docs/drivers/creating-a-driver.md docs/docs/drivers/context.md
```

Expected: the first command prints nothing. The second prints only lines that read `ingress_class` in an action example or say that Styrmin sets the class, not a `className:` line in a values template example.

## 4. Existing E2E tests (FR-001, FR-002, FR-004, SC-002)

Pre-build the server image, then run each test in its own pytest session (`shard_compute`, API variant):

```bash
export STYRMIN_IMAGE_VER=e2e-471-<suffix>
docker compose build server
sleep infinity | uv run pytest \
  "backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress" \
  -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-471-cluster-update.log
sleep infinity | uv run pytest \
  "backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress" \
  -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-471-traffic.log
```

Expected:

- `test_cluster_update_redeploys_and_moves_dedicated_ingress` passes: every Ingress of the `simple-app` deployment has `spec.ingressClassName` and the annotation set to `traefik`, then to `nginx`, without a dedicated ingress controller, although the driver template sets no class.
- `test_traffic_routes_through_dedicated_ingress` passes: the application answers `200` through the dedicated ingress controller.

Stop each paused session by PID, not with `pkill -f`. Record for each test, in `e2e-evidence.md`: the pytest node ID, the exact command, the ISO 8601 time of the passing run, the vcluster fixture ID and kubeconfig path, and the verbatim `PASSED` line (Constitution §V).

## 5. Format, lint and the full backend suite

```bash
uv run invoke format lint
uv run invoke test
```

Expected: both pass.
