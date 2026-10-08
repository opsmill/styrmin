# Quickstart: Validate Driver Logo, Description and Links

Run from the repository root of this worktree. Contracts: [graphql.md](contracts/graphql.md), [driver-spec.md](contracts/driver-spec.md), [ui.md](contracts/ui.md).

## 1. Single migration head

```bash
uv run python -c '
from alembic import command
from styrmin_backend.cli.db import _get_alembic_config
command.heads(_get_alembic_config())
'
```

Expected: exactly one line, the new revision, marked `(head)`.

## 2. Backend unit and propagation tests

```bash
uv run pytest backend/tests/unit/services/driver -k "info" -v
uv run pytest backend/tests/unit/db -k "head or driver_info" -v
uv run pytest backend/tests/functional/graphql/test_application_driver_version_propagation.py -v
```

Expected: all pass, including:

- Validation rejects `xxxx`, `logo.svg`, `javascript:` and `data:` for `icon`, and a bad `links` entry, with an error that names the field.
- A loaded driver's `icon`, `description` and `links` reach the DB row and GraphQL.
- Reloading an unchanged driver fills in a pre-feature row with the same `id`.

## 3. Schema and generated types are current

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
git diff --exit-code schema.graphql python_sdk/src/styrmin_sdk/graphql/_generated frontend/src/generated
```

Expected: no diff after the implementation commits them.

## 4. Frontend tests

```bash
cd frontend && pnpm --ignore-workspace test -- DriverLogo DriverListPage DriverDetailPage driverList
```

Expected: the logo renders, falls back on error and on null, and resets on src change. The list header uses the latest version even when the filter hides it. Detail shows the description and links, and hides empty sections.

## 5. Manual check in the dev stack (optional)

```bash
uv run invoke dev
uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
```

Open `/drivers`: the `infrahub` group header shows the Infrahub logo and its description. Open the driver: the header shows the logo, the description appears above the tabs, and the Overview tab lists Homepage, Documentation and Github; each opens in a new tab. Load `/styrmin/drivers/simple-app`: it shows the generic package icon.

## 6. E2E (required, local PASS evidence per Constitution §V)

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_ui_smoke.py::test_driver_logo_description_and_links_render" -v -s --pdb 2>&1 | tee /tmp/e2e-020.log
```

Expected: `PASSED` for the `[ui-chromium]` node. Record the node ID, command, ISO 8601 timestamp, vcluster ID and kubeconfig path, and the verbatim `PASSED` line in the implementation report.

## 7. Format and lint

```bash
uv run invoke format lint
cd frontend && pnpm --ignore-workspace lint
```
