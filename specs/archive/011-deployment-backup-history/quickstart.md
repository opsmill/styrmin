# Quickstart: Validate a Deployment's Backup History

**Feature**: [spec.md](spec.md) | **Contracts**: [contracts/](contracts/)

## Prerequisites

```bash
uv sync
cd frontend && pnpm install --ignore-workspace && cd ..
```

After the GraphQL change, regenerate the schema and the client types:

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
uv run invoke validate-graphql
```

Expected: `schema.graphql` shows the `backups(deploymentId: UUID = null, instanceId: UUID = null, status: BackupStatus = null)` signature from [contracts/graphql.md](contracts/graphql.md), and `validate-graphql` passes for every operation file, including the existing ones that declare `$instanceId: UUID!`.

## 1. Unit and functional tests

```bash
uv run pytest backend/tests/unit/repository/backup/test_backup_repository.py -v
uv run pytest backend/tests/unit/services/backup/test_backup_service.py -v
uv run pytest backend/tests/functional/graphql/test_backup_history_propagation.py -v
uv run pytest python_sdk/tests/test_backups.py cli/tests/test_backups.py -v
cd frontend && pnpm test -- BackupExpiry && cd ..
```

Expected: all pass. The functional module has one case per operation (upgrade, config edit, refresh, environment config change), each asserting that the active instance changed and that `backups(deploymentId:)` still returns the earlier backup with its application version (SC-001, SC-002).

## 2. E2E, both variants, one per session

Run each variant in its own pytest session:

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" \
  -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-backup-history-api.log

sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" \
  -k ui-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-backup-history-ui.log
```

Expected: both `PASSED`. In each run, after the config edit:

- the active instance id differs from the one the backup was taken of
- `scenario_driver.list_backups(deployment_id=...)` contains the backup with `application_version == "0.1.0"`
- the restore and the delete of that backup succeed

Record the evidence Constitution §V requires (node id, command, timestamp, vcluster id and kubeconfig path, `PASSED` line) for each variant.

## 3. Manual check against a dev stack (optional)

With `uv run invoke dev` running and a deployment `my-app` that has one completed backup:

```bash
uv run styrminctl backups list my-app                 # backup listed, application_version column filled
uv run styrminctl deployments update-version <deployment-id> <newer>  # or edit its config
uv run styrminctl backups list my-app                 # the same backup is still listed
uv run styrminctl backups restore --last --target-deployment my-app   # restore starts
```

On the deployment page, the Backups tab lists the same backups with an **Application version** column.

API check in GraphiQL:

```graphql
query { backups(deploymentId: "<deployment-id>") { id status instance { applicationVersion } } }
query { backups(deploymentId: "<deployment-id>", instanceId: "<instance-id>") { id } }  # VALIDATION_ERROR
```

## 4. Lint and format

```bash
uv run invoke format lint
cd frontend && pnpm lint && pnpm build && cd ..   # build runs tsc -b
```
