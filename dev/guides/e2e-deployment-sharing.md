# E2E Deployment-Sharing Policy

E2E tests fall into one of three sharing tiers. Each tier maps to one
or more CI shards (see `e2e-parallelism.md` for the shard scheme).

## Tiers

### Read-only

The test asserts on state already produced by the session-scoped
`styrmin_resources` + a session-scoped `deployed_simple_app` (or
equivalent). It MUST NOT create, modify, or delete deployments.

- **Shard:** `readonly`
- **Examples:** `test_service_discovery`, `test_pod_component_attribution`,
  `test_ui_smoke`, `test_driver_detail`, `test_deployment_timeline` (read
  variants), the cli-auth and admin-user/group suites.
- **Review rule:** A read-only test that creates its own deployment is a
  review-blocker. Refactor to consume the shared fixture.

### Isolated mutation

The test creates and tears down its own deployment with a unique name.
Multiple isolated-mutation tests can run in the same shard but each one
must not depend on another's state.

- **Shard:** `mutation_small` (short tests), `mutation_large` (long
  tests like env-vars matrix, environment_update, pod_scheduling), or
  `ingress` (the standalone ingress-controller suite).
- **Examples:** `test_deploy_app`, `test_delete_deployment_*`,
  `test_environment_update`.
- **Review rule:** Reuse `deployed_simple_app` if your test only reads —
  do not create a fresh deployment just for an isolated assertion.

### Heavy / exclusive

The test depends on cluster-wide infrastructure that conflicts with
other tests: Velero backups, MinIO, the Infrahub stack. It MUST live in
its own file and its own shard.

- **Shard:** `backup` (Velero / MinIO) or `infrahub` (the Infrahub
  app stack).
- **Examples:** `test_backup_restore`, `test_backup_restore_databases`.
- **Review rule:** Adding a new "heavy" test category? Open an ADR
  first — the matrix YAML in `.github/workflows/ci.yml` needs a new
  shard entry.

## Decision tree

1. Does the test mutate state? → No: `readonly`.
2. Does it touch Velero, MinIO, or Infrahub? → Yes: `backup` or
   `infrahub`.
3. Is it an ingress-controller test? → Yes: `ingress`.
4. Is it expected to run for >2 minutes? → Yes: `mutation_large`,
   otherwise `mutation_small`.

## Adding a new test

Every `@pytest.mark.ci` E2E test MUST carry exactly one bare-name
shard marker (`shard_readonly`, `shard_mutation_small`,
`shard_mutation_large`, `shard_ingress`, `shard_backup`, or
`shard_infrahub`). The conftest collection hook
(`enforce_shard_markers`) rejects the suite if any test is missing
the marker or carries more than one.

Apply at module scope when all tests in the file share the same
shard:

```python
pytestmark = [
    pytest.mark.ci,
    pytest.mark.api_only(reason="..."),  # if applicable
    pytest.mark.shard_readonly,
]
```
