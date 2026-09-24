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
  ingress-controller tests, `apply` for manifest `apply` /
  `apply_files` tests.
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
  - `backup` (Velero / Garage) — simple-app + database backup/restore.
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

## Reuse before you boot

A new E2E test that only *reads* state is not free just because it consumes a
session-scoped fixture. Before adding one, run these checks:

1. **Does an existing test already boot the stack you need?** If so, add your
   assertion to that test (or a sibling in the same file that shares its session
   fixture) instead of creating a new test node. Prefer extending an existing
   E2E over adding a new one whenever the setup is shared and expensive — this
   is explicitly allowed by Constitution §V ("…or an existing one extended to
   cover the new behaviour").

2. **Does the session fixture you're about to depend on have an active,
   non-skipped consumer?** A session-scoped fixture is only booted when a test
   that actually runs requests it. If every current consumer is
   `@pytest.mark.skip`, your test becomes its *sole* consumer and silently pays
   the full boot cost — a heavy boot in disguise, not a reuse. Verify with
   `grep -rn <fixture_name> backend/tests/e2e/ | grep -v conftest` and confirm
   at least one consumer is not skipped.

3. **Is there a cheaper already-booted stack that exercises the same
   machinery?** Driver-format features (service discovery, computed FQDNs,
   ingress) are shared across driver variants that use the same subchart. If the
   community and enterprise variants both run the component under test, assert
   against whichever stack is *already* booted in the shard rather than booting
   a second one — adding the service/values to that variant's driver for parity
   if it is missing.

**Worked example (#273 / PR #308).** The Prefect-UI `task-manager` service was
added to the community `infrahub` driver, and the first draft added a new test
consuming `deployed_infrahub_app`. But that fixture's only other consumer is the
community backup test, which is skipped — so the community stack is never booted
in CI, and the new test would have resurrected a full second Infrahub boot in
`shard_infrahub` for four read-only assertions. The fix: declare the same
`task-manager` service on the enterprise driver (identical `prefect-server`
subchart) and assert against the already-booted `deployed_infrahub_enterprise_app`.
Net new heavy boots: zero.

## Decision tree

1. Does it touch the Infrahub stack (full Infrahub server + DB)? → Yes: `infrahub` (isolated).
2. Does it touch Velero or Garage? → Yes: `backup` (isolated).
3. Is it a config-drawer UI flow? → Yes: `configuration`.
4. Is it a manifest `apply` / `apply_files` flow? → Yes: `apply`.
5. Is it about env vars or environment updates? → Yes: `env`.
6. Is it about pod scheduling or the ingress controller? → Yes: `compute`.
7. Otherwise → `general`.

A `configuration` module does not create its own deployment. Declare it
at module level — `DRAWER_DEPLOYMENT = DrawerDeployment(name="drawer-…")`,
with `config=DeploymentConfigInput(...)` for a non-default baseline — and
take the `drawer_deployment` fixture. `configuration/conftest.py` creates
every selected, non-skipped module's environment + deployment
concurrently through the SDK, so a new module adds almost no wall-clock.
Seed the baseline through `config` rather than a follow-up
`deployments.update`: each update is another reconcile.

## Adding a new test

Every `@pytest.mark.ci` E2E test MUST carry exactly one bare-name
shard marker (`shard_general`, `shard_env`, `shard_compute`,
`shard_backup`, `shard_infrahub`, `shard_configuration`, or
`shard_apply`). The conftest collection hook (`enforce_shard_markers`)
rejects the suite if any test is missing the marker or carries more
than one.

Apply at module scope when all tests in the file share the same
shard:

```python
pytestmark = [
    pytest.mark.ci,
    pytest.mark.api_only(reason="..."),  # if applicable
    pytest.mark.shard_general,
]
```
