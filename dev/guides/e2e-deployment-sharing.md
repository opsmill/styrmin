# E2E Deployment-Sharing Policy

E2E tests fall into one of three sharing tiers. Each tier maps to one
or more CI shards (see `e2e-parallelism.md` for the shard scheme).

## Tiers

### Read-only

The test asserts on state already produced by the session-scoped
`styrmin_resources` + a session-scoped `deployed_simple_app` (or
equivalent). It MUST NOT create, modify, or delete deployments.

- **Shard:** `general` (lumped together with isolated-mutation tests
  because read-only assertions are cheap and don't warrant their own
  shard).
- **Examples:** `test_service_discovery`, `test_pod_component_attribution`,
  `test_ui_smoke`, `test_deployment_timeline`, the cli-auth and
  admin-user/group suites.
- **Review rule:** A read-only test that creates its own deployment is a
  review-blocker. Refactor to consume the shared fixture.

### Isolated mutation

The test creates and tears down its own deployment with a unique name.
Multiple isolated-mutation tests can run in the same shard but each one
must not depend on another's state.

- **Shard:** `general` for most short mutation tests, `env` for
  env-var / env-update tests, `compute` for pod-scheduling or
  ingress-controller tests.
- **Examples:** `test_deploy_app`, `test_delete_deployment_*`,
  `test_environment_update`.
- **Review rule:** Reuse `deployed_simple_app` if your test only reads —
  do not create a fresh deployment just for an isolated assertion.

### Heavy / exclusive

The test depends on cluster-wide infrastructure that conflicts with
other tests, or on a heavy product stack whose boot time would
starve a shared shard. It MUST live in its own file and its own
shard.

- **Shards:**
  - `backup` (Velero / MinIO) — simple-app + database backup/restore.
  - `infrahub` (Infrahub stack) — boots a full Infrahub server + DB;
    split out of `backup` so debug iteration on the simple-app backup
    tests doesn't pay for the Infrahub boot.
- **Examples:** `test_backup_restore`, `test_backup_restore_databases`
  (in `shard_backup`); `test_infrahub_backup_restore` (in
  `shard_infrahub`).
- **Review rule:** Adding another "heavy" test category? Open an ADR
  first — the matrix YAML in `.github/workflows/ci.yml` needs a new
  shard entry alongside updates to `_VALID_SHARDS` (conftest),
  `pyproject.toml` markers, and both e2e guides.

## Decision tree

1. Does it touch the Infrahub stack (full Infrahub server + DB)? → Yes: `infrahub` (isolated).
2. Does it touch Velero or MinIO? → Yes: `backup` (isolated).
3. Is it a config-drawer UI flow? → Yes: `configuration`.
4. Is it about env vars or environment updates? → Yes: `env`.
5. Is it about pod scheduling or the ingress controller? → Yes: `compute`.
6. Otherwise → `general`.

## Adding a new test

Every `@pytest.mark.ci` E2E test MUST carry exactly one bare-name
shard marker (`shard_general`, `shard_env`, `shard_compute`,
`shard_backup`, `shard_infrahub`, or `shard_configuration`). The
conftest collection hook (`enforce_shard_markers`) rejects the suite
if any test is missing the marker or carries more than one.

Apply at module scope when all tests in the file share the same
shard:

```python
pytestmark = [
    pytest.mark.ci,
    pytest.mark.api_only(reason="..."),  # if applicable
    pytest.mark.shard_readonly,
]
```
