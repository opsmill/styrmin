# E2E Parallelism: Matrix Sharding

## Overview

E2E tests run in a 7-shard × 2-entrypoint CI matrix. Each cell is a
GitHub Actions job that boots its own vcluster, installs styrmin via
Helm, and runs only the tests carrying its shard marker.

The seven shards:

| Shard | Marker | Purpose | Sample tests |
|---|---|---|---|
| `general` | `shard_general` | Readonly readers + short-mutation tests (deploy, delete, admin, auth, smoke) | `test_ui_smoke`, `test_deploy_app`, `test_admin_*`, `test_service_discovery` |
| `env` | `shard_env` | `test_deployment_env_vars.py` + `test_environment_update.py` (env-var precedence and env-level fan-out) | `test_us1_deployment_level_env_var`, `test_us1_environment_update_fans_out_to_all_deployments` |
| `compute` | `shard_compute` | `test_pod_scheduling.py` + `test_ingress_controller.py` (scheduling / ingress) | `test_scheduling_end_to_end`, `test_ingress_controller` |
| `backup` | `shard_backup` | Velero + MinIO; cluster-wide state (kept isolated to avoid cross-test pollution) | `test_backup_restore`, `test_backup_restore_databases` |
| `infrahub` | `shard_infrahub` | Infrahub-stack backup/restore (boots full Infrahub server + DB; isolated from `shard_backup` so simple-app backup tests aren't blocked by Infrahub boot) | `test_infrahub_backup_restore` |
| `configuration` | `shard_configuration` | `backend/tests/e2e/configuration/` — unified config-drawer UI flows | `test_drawer_env_vars_edit`, `test_drawer_scheduling_edit` |

The two entrypoints (`api`, `ui`) continue as before — each shard runs
twice unless every test in it carries `@pytest.mark.api_only` or
`@pytest.mark.ui_only`. See `dev/guides/e2e-deployment-sharing.md` for
the marker rules.

## Adding a new test

1. Pick a shard using the decision tree in
   `dev/guides/e2e-deployment-sharing.md`.
2. Add module-scope markers to your file:

   ```python
   pytestmark = [
       pytest.mark.ci,
       pytest.mark.api_only(reason="..."),  # or ui_only, or omit for dual
       pytest.mark.shard_general,           # one of shard_general,
                                             # shard_env, shard_compute,
                                             # shard_backup, shard_infrahub,
                                             # shard_configuration
   ]
   ```

3. Run `uv run pytest --collect-only backend/tests/e2e -q` locally.
   The `enforce_shard_markers` hook in conftest will reject your test
   if the shard marker is missing or names an unknown shard.

## Debugging — `--pdb` still works

Matrix sharding does NOT change the per-test debugging recipe.
AGENTS.md's `--pdb` workflow continues to apply:

```bash
sleep infinity | uv run pytest backend/tests/e2e/<node_id> -v -s --pdb 2>&1 | tee /tmp/pdb.log
```

Each shard still runs single-threaded inside its CI job — no
pytest-xdist, no stdin trapping. The `e2e-troubleshoot` skill keeps
working without modification.

## Why matrix sharding (and not pytest-xdist)?

See ADR for matrix-sharding (in `dev/adr/`).

## Tuning a slow shard

If one shard becomes the wall-clock bottleneck (visible in the GitHub
Actions UI as the cell that takes longer than its siblings):

1. Identify the heaviest test(s) in that shard (`--durations=0` in the
   pytest output of that cell).
2. Either move the heaviest test to a new shard (update `pyproject.toml`
   marker list, conftest `_VALID_SHARDS`, CI matrix `shard:` list, and
   the test's `@pytest.mark.shard_*` marker), or split the shard in half.
3. Re-run; confirm the new slowest cell is faster than the old one.

Before reaching for any of that, check the two things that dominate a
shard's wall-clock — reshuffling tests between shards only moves time
around, it does not remove it:

- **Is `STYRMIN_OPERATOR_RECONCILE_INTERVAL` reaching the agent pod?**
  It is set to `5` in `backend/tests/e2e/fixtures/styrmin-values.yaml`
  via the agent subchart's `agent.extraEnv`. At its 60s production
  default, every create / upgrade / delete in the shard sleeps a full
  ~60s after Kubernetes has already finished, because the kopf timer is
  the only path that advances a deployment to `Running` or `Deleted`.
  This one value is worth ~50% of the shard.
- **How many deploy / upgrade / delete cycles does the shard perform?**
  Each deploy is ~40s and each full delete-to-tombstone ~25-60s, and
  that is irreducible. Cutting cycles (per the read-only tier in
  [`e2e-deployment-sharing.md`](e2e-deployment-sharing.md)) is the only
  other real lever. Environment fixtures are *not* a lever — the
  per-environment dedicated-ingress controller is dispatched
  asynchronously and overlaps the application install.

See [`dev/knowledge/backend/e2e-testing.md`](../knowledge/backend/e2e-testing.md)
(§ "Where the wall-clock actually goes") for the measurements behind
both points, including two environment-sharing optimisations that were
measured and rejected.
