# Quickstart: Validate Loading a Driver from a Driver Directory

How to check, after implementation, that an admin can load, deploy and run a driver from a driver directory of a git repository, and that loads from the repository root are unchanged. Behaviour is in [contracts/](contracts/); stored values are in [data-model.md](data-model.md).

## Prerequisites

- `uv sync`; `cd frontend && pnpm --ignore-workspace install`.
- For E2E: Docker running, `vcluster` on PATH, the server image built once with `docker compose build server` before the session.
- Run each E2E shard in its own pytest session, and `api-chromium` and `ui-chromium` in separate sessions. From a non-interactive shell, prefix the command with `sleep infinity |` so `--pdb` keeps the cluster alive on failure.

## 1. Path rule, provider and loader

```bash
uv run pytest backend/tests/unit/services/driver/test_driver_directory.py \
  backend/tests/unit/services/driver/test_provider.py \
  backend/tests/unit/services/driver/test_loaders_git_commit_sha.py -v
```

Expected:

- Every form in [research.md R-005](research.md#r-005-one-stored-form-of-a-driver-directory-and-the-values-refused-before-the-clone) normalises or is refused as listed.
- The git provider, against a local repository built in `tmp_path`, yields the driver directory; refuses a driver directory symlinked to `/etc`; refuses a root `driver.styrmin.yml` symlinked to a file outside the clone; and names the driver directory, repository, branch and commit when the directory or its `driver.styrmin.yml` is missing.
- Storage records `source_path = "drivers/a"` for a driver directory load, `NULL` for a root load, and returns the existing row on a reload written as `./drivers/a/`.

## 2. Action deployments

```bash
uv run pytest backend/tests/unit/workflows/test_git_source_commit_pinning.py \
  backend/tests/unit/workflows/test_action_driver_directory.py \
  backend/tests/unit/workflows/test_user_action_registration.py \
  backend/tests/unit/services/reconciliation/test_remediation.py -v
```

Expected: pull steps, names, tags and lookups as in [contracts/action-deployments.md](contracts/action-deployments.md). The Prefect import test shows that a sibling module imports and a module outside the driver directory does not.

## 3. GraphQL propagation, SDK and CLI

```bash
uv run styrmin export graphql-schema schema.graphql && git diff --stat schema.graphql
npm_config_ignore_workspace=true uv run invoke generate
uv run pytest backend/tests/functional/graphql/test_application_driver_version_propagation.py \
  python_sdk/tests/test_drivers.py cli/tests/test_drivers.py -v
```

Expected: `schema.graphql` shows the new `driverDirectory` argument only. The propagation test reads `source_path = "drivers/a"` from the database and `sourcePath: "drivers/a"` from the query. The CLI test prints `Driver directory: drivers/a`.

## 4. Frontend

Run in a Node 22 container (the host Node cannot run Vitest for this frontend):

```bash
cd frontend
pnpm --ignore-workspace exec vitest run src/__tests__/drivers/LoadDriverDrawer.test.tsx \
  src/__tests__/driver-detail/DriverDetailPage.test.tsx
pnpm --ignore-workspace exec tsc -b --noEmit
```

Expected: the drawer sends `driverDirectory` only when the field is filled; the Overview tab shows the "Driver directory" row for a git version with `sourcePath` and no row without.

## 5. E2E (both variants, `shard_general`)

```bash
sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_general" -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-api.log
sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_general" -k ui-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-ui.log
```

Expected:

- `styrmin_resources` loads `simple-app` from `driver-collection` with driver directory `drivers/simple-app`, and the session deployment reaches Running, which needs its setup actions to succeed.
- `test_driver_version_reselection` passes in both variants, including the `sourcePath == "drivers/simple-app"` check and the `set_working_directory` step check.
- `test_driver_detail_inspects_versions_via_tabs` (UI) reads `drivers/simple-app` from the Overview tab.
- The session fixture change reaches every shard. CI runs all shards; locally, `shard_general` covers the load and the setup actions in every session. `test_driver_version_reselection` also runs the upgrade action of the binding it pins back to, which is the session driver version when no earlier test in the session moved the binding.
- Record the evidence that Constitution §V asks for (node id, command, timestamp, cluster id, `PASSED` line) in `e2e-evidence.md`.

## 6. Manual check (optional)

With the dev stack from `uv run invoke dev`, load a driver from a folder of a repository that holds two drivers:

```bash
uv run styrminctl drivers load-version https://github.com/your-org/styrmin-drivers.git main \
  --driver-directory drivers/infrahub
uv run styrminctl drivers load-version https://github.com/your-org/styrmin-drivers.git main \
  --driver-directory ../etc   # refused before the clone
```
