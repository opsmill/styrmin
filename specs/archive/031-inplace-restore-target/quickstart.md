# Quickstart: Validate That an In-Place Restore Lands in Its Backup's Deployment

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Contracts**: [graphql-api.md](contracts/graphql-api.md), [sdk-and-cli.md](contracts/sdk-and-cli.md), [internal-interfaces.md](contracts/internal-interfaces.md)

## Prerequisites

- `uv sync`, and `cd frontend && pnpm install` (needed before `uv run invoke generate`, which also runs the frontend codegen).
- For the E2E run: `vcluster` and `docker` on `PATH`. Set a unique image tag for this worktree, because other worktrees build `styrmin:latest` on the same Docker daemon:

  ```bash
  export STYRMIN_IMAGE_VER=inplace-restore-$(git rev-parse --short HEAD)
  ```

## 1. Regenerate the schema and the clients

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke validate-graphql
uv run invoke generate
git diff --stat schema.graphql python_sdk/src/styrmin_sdk/graphql/_generated frontend/src/generated
```

Expected: `createRestore(backupId: UUID!): Restore @requiresRole` in `schema.graphql`; every `.graphql` file passes validation; the generated SDK client's `create_restore` takes only `backup_id`; `CreateRestoreMutationVariables` holds only `backupId`.

## 2. Unit and functional tests

```bash
uv run pytest backend/tests/unit/services/backup/test_restore.py -q
uv run pytest backend/tests/functional/graphql/test_create_restore.py -q
uv run pytest backend/tests/unit/services/backup backend/tests/functional/graphql/test_environment_clone.py backend/tests/functional/graphql/test_environment_backup.py -q
uv run pytest cli/tests/test_backups.py -q
uv run pytest python_sdk/tests/test_backups.py -q
cd frontend && pnpm exec tsc -b && pnpm lint && pnpm test deployment-detail
```

Run one pytest session per package. `backend/tests`, `cli/tests` and `python_sdk/tests` each have a `tests/conftest.py`, so a session that collects two of them stops at collection with `ImportPathMismatchError`. `backend/tests/unit` and `backend/tests/functional` belong to one package and can share a session.

Expected:

- The restore target tests pass for the in-place, earlier-instance, no-active-instance and cross-target cases (FR-001, FR-004, FR-009).
- The functional test records `styrmin-<deployment id>` and the active instance, and refuses each removed argument with `Unknown argument ...` (FR-002, FR-004).
- The CLI refuses a backup id with each target option without calling the SDK, and rejects `--target-namespace` (FR-006, FR-007); the `--last` tests pass (FR-008).
- The SDK sends only `backupId` (FR-003).
- The frontend compiles with the regenerated types.

## 3. E2E

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" -v -s --pdb 2>&1 | tee /tmp/e2e-031.log
```

The node runs as `[api-chromium]` and `[ui-chromium]`. Expected for each: `PASSED`, with the new assertions that the completed restore records `styrmin-<deployment id>` and the deployment's active 0.2.0 instance, although the backup was taken of the 0.1.0 instance (FR-001, FR-004, ADR-063).

Record the evidence that Constitution §V requires for each variant: node id, command, ISO 8601 time of the passing run, vcluster id and kubeconfig path, and the verbatim `PASSED` line.

## 4. Manual check with `styrminctl` (optional, against `uv run invoke dev`)

```bash
uv run styrminctl backups restore <backup id> --target-deployment other-app
# Error: --target-deployment, --target-deployment-id and --target-instance-id work only with --last ...

uv run styrminctl backups restore <backup id> --target-namespace styrmin-x
# Cyclopts reports an unknown option.

uv run styrminctl backups restore <backup id> --wait
uv run styrminctl backups restore-get <restore id>
# Target namespace: styrmin-<id of the backup's deployment>
# Target instance ID: <that deployment's active instance>

uv run styrminctl backups restore --last --target-deployment my-app
# Selected the newest completed backup: ...
```

## 5. Lint and docs

```bash
uv run invoke format lint
git grep -n -E "target-namespace|targetNamespace: \\$|target_namespace=" -- docs cli/README.md dev/knowledge
```

Expected: lint passes; the `git grep` finds no instruction to pass a namespace to a restore (SC-003). `changelog/532.removed.md` and `changelog/532.fixed.md` exist.
