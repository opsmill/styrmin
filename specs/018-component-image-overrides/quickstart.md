# Quickstart: validate per-component image overrides

## Prerequisites

- `uv sync`, `cd frontend && pnpm install`
- Docker and `vcluster` on `PATH` (the E2E fixtures create their own cluster)
- `kubectl` with kustomize v5.7+ for the offline patch check

## 1. Offline patch check (seconds)

Render the patches the builder emits against a fixture workload and run them through Kustomize:

```bash
uv run pytest backend/tests/unit/services/component_container -v
```

Expected: the existing-container cases set the image (and env) on the component container only;
the missing-container case fails with an error containing
`styrmin.io~1component-container~1<component>~1<container>/image`; no case adds a container.

## 2. Unit and propagation tests

```bash
uv run pytest backend/tests/unit/services/image_overrides backend/tests/unit/agent -k "image or component_container" -v
uv run pytest backend/tests/functional/graphql -k image_override -v
cd frontend && pnpm test -- imageReference ComponentOverrides Upgrade
```

Expected: grammar vectors pass in both languages; the propagation tests in
[contracts/graphql-deltas.md](contracts/graphql-deltas.md) pass; the operator test turns a guard
HelmRelease message into `COMPONENT_CONTAINER_NOT_FOUND`.

## 3. End-to-end

```bash
sleep infinity | uv run pytest backend/tests/e2e/test_deployment_image_override.py -v -s --pdb 2>&1 | tee /tmp/image-override.log
```

Expected:

| Test | Variants | Proves |
|---|---|---|
| `test_override_then_clear` | api, ui | US1 + US3: `simple-app` container runs `registry.example/acme/simple-app-patched:0.1.0`, no extra container, init container and env untouched, read-back is `applied`; clearing restores `simple-app:0.1.0` |
| `test_token_follows_upgrade_and_action_job` | api, ui | US2 + FR-008 + FR-012: pinned override is listed before the upgrade; with the token, `server` runs `…-patched:0.2.0` after upgrading to 0.2.0 and the `<release>-job` action Job ran `…-patched:0.2.0` |
| `test_misnamed_container_never_added` | api | SC-005: the deployment fails within one reconcile with a message naming `server` and `wrong-name`; the live Deployment has only the `simple-app` container |

## 4. Manual spot check (optional, dev stack)

```bash
uv run invoke dev
styrminctl deployments apply -f - <<'EOF'
apiVersion: styrmin/v1
kind: Deployment
metadata: {name: img-demo}
spec:
  driver: simple-app
  version: 0.1.0
  environment: dev
  config:
    components:
      - name: server
        image: "simple-app:{{ app.version }}"
EOF
kubectl -n styrmin-<id> get deploy styrmin-simple-app -o jsonpath='{.spec.template.spec.containers[*].image}'
```

Then re-apply with `version: 0.2.0` and a literal-tag image to see the pinned warning on stderr.
