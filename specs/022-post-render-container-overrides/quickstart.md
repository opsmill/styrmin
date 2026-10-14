# Quickstart: Validate Container `command` and `args` Overrides Applied by Post-Render

**Feature**: [spec.md](spec.md) | **Contracts**: [contracts/](contracts/)

## Prerequisites

- `uv sync`, and `cd frontend && pnpm install` (needed by `uv run invoke generate`).
- `kubectl` with kustomize v5 and `helm` on `PATH` for the integration and contract tests.
- `docker` and `vcluster` on `PATH` for the E2E. The E2E fixtures create their own cluster; `uv run invoke dev` is not needed.
- Node 22 for the frontend tests.

## 1. Unit and contract tests

```bash
uv run pytest backend/tests/unit/services/component_container/ \
  backend/tests/unit/agent/test_render_value_template_container_overrides.py \
  backend/tests/unit/agent/test_container_env_patch.py \
  backend/tests/unit/services/driver/ \
  backend/tests/unit/services/test_container_overrides_validator.py \
  backend/tests/unit/db/ -q
```

Expected (file names may be renamed during implementation, see `tasks.md`):

- a template that calls `component_command` or `component_args` raises `RETIRED_TEMPLATE_FILTER` with the filter name and `.../docs/drivers/migrating-container-overrides`;
- a driver file with `spec.container_overrides` fails to load like any unknown key;
- a component with only `args` set gets a merge patch and a guard; a cleared override gets none;
- the migration revision drops and restores `applicationdriverversion.container_overrides`, and there is one Alembic head.

## 2. Integration tests on real kustomize (FR-002, FR-004)

```bash
uv run pytest backend/tests/integration/test_component_container_kustomize.py -q
```

Expected: `args`-only keeps the chart `command`; other containers and init containers unchanged; a wrong container name with only `args` set fails at the guard key.

## 3. Old template versus migrated driver (SC-005)

```bash
uv run pytest backend/tests/integration/test_container_override_migration_parity.py -q
```

Expected: for `simple-app`, `infrahub` and `infrahub-enterprise`, the same stored `command`/`args` produce the same component container `command`/`args` with the pre-migration template and with the migrated driver plus post-render patches.

## 4. GraphQL propagation

```bash
uv run pytest backend/tests/functional/graphql/test_container_overrides_propagation.py -q
```

Expected: `isApplicable` true / false (no container) / false (orphaned); `COMPONENT_CONTAINER_NOT_DECLARED` with `override: "command"` and `override: "args"` on `updateDeployment` and `deploy`; a removal on a containerless component is accepted.

## 5. Frontend

```bash
cd frontend && pnpm test -- ComponentOverridesSection
```

Expected: no Command or Args editor on a component without a component container; a stored value there shows read-only with a "not applied" badge and can be removed.

## 6. E2E on `simple-app` (P1, FR-001, FR-003, SC-003)

Run the `shard_configuration` shard's container override tests, API variant, with `--pdb`:

```bash
sleep infinity | uv run pytest \
  "backend/tests/e2e/test_deployment_container_overrides.py" \
  -k "api-chromium" -v -s --pdb 2>&1 | tee /tmp/e2e-022.log
```

Expected:

- `test_us1`: after setting `args: ["--host", "0.0.0.0", "--port", "8000"]` on `server`, the `simple-app` container of the `server` Deployment has exactly those `args`;
- `test_us2`: `command` and `args` both land, and changing `command` lands after the next reconcile;
- `test_us3`: after the clear, the container's `command` and `args` equal the values captured before any override was set (the chart's own values);
- `test_us4`: invalid lists are rejected with the typed codes;
- `test_us6_driver_declares_overridable_component` no longer exists.

To view the live pod while pytest is paused:

```bash
export KUBECONFIG=$(ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1)
kubectl get deploy -A -l app.kubernetes.io/name=simple-app -o jsonpath='{.items[*].spec.template.spec.containers[0]}'
```

## 7. Manual check of the retired filters

Load a copy of the pre-migration `simple-app` driver (version 2, which calls `component_command`) and create a deployment on it. Expected: the deployment message reads `Failed to create HelmRelease: The 'component_command' template filter was removed ... Migration guide: https://styrmin.pages.dev/docs/drivers/migrating-container-overrides`, and no HelmRelease is applied.

## 8. Lint, types and generated files

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
uv run invoke validate-graphql
uv run invoke format lint
```
