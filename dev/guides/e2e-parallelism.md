# E2E Parallelism: Matrix Sharding

## Overview

E2E tests run in a 9-shard × 2-entrypoint CI matrix. Each cell is a
GitHub Actions job that boots its own vcluster, installs styrmin via
Helm, and runs only the tests carrying its shard marker.

The nine shards:

| Shard | Marker | Purpose | Sample tests |
|---|---|---|---|
| `general` | `shard_general` | Readonly readers + short-mutation tests (deploy, delete, admin, auth, smoke) | `test_ui_smoke`, `test_deploy_app`, `test_admin_*`, `test_service_discovery` |
| `env` | `shard_env` | `test_deployment_env_vars.py` + `test_environment_update.py` (env-var precedence and env-level fan-out) | `test_us1_deployment_level_env_var`, `test_us1_environment_update_fans_out_to_all_deployments` |
| `compute` | `shard_compute` | `test_pod_scheduling.py` + `test_ingress_controller.py` (scheduling / ingress) | `test_scheduling_end_to_end`, `test_ingress_controller` |
| `backup` | `shard_backup` | Deployment-level backup/restore on Velero + Garage; cluster-wide state (kept isolated to avoid cross-test pollution) | `test_backup_and_restore_lifecycle`, `test_restore_lifecycle_transitions`, `test_backup_restore_databases` |
| `env_backup` | `shard_env_backup` | Environment-level backup/restore and environment clone on Velero + Garage (split out of `backup`, where the two tests made the cell about twice as long as any other) | `test_environment_backup_and_restore_lifecycle`, `test_environment_clone_lifecycle` |
| `infrahub` | `shard_infrahub` | Infrahub-stack backup/restore (boots full Infrahub server + DB; isolated from `shard_backup` so simple-app backup tests aren't blocked by Infrahub boot) | `test_infrahub_backup_restore` |
| `configuration` | `shard_configuration` | `backend/tests/e2e/configuration/` — unified config-drawer UI flows | `test_drawer_env_vars_edit`, `test_drawer_scheduling_edit` |
| `apply` | `shard_apply` | `test_deployments_apply.py` — manifest `apply` / `apply_files` flows (all `api_only`, each test deploys fresh simple-apps; split out of `general`, where it was the bulk of the run) | `test_apply_creates_updates_then_noops`, `test_apply_files_batch_continues_past_failure` |
| `task_steps` | `shard_task_steps` | `test_task_steps.py` — failed-step scenarios on one `failing-actions` deployment; the HelmRelease scenario waits out the operator's readiness timeout and FluxCD's rollback (split out of `general`, where it was ~40% of the run) | `test_prerequisite_failure_shows_attempts`, `test_helmrelease_failure_shows_fluxcd_reason` |

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
                                             # shard_backup, shard_env_backup,
                                             # shard_infrahub,
                                             # shard_configuration,
                                             # shard_apply, shard_task_steps
   ]
   ```

3. Run `uv run pytest --collect-only backend/tests/e2e -q` locally.
   The `enforce_shard_markers` hook in conftest will reject your test
   if the shard marker is missing or names an unknown shard.

### Tests that change the cluster config

A cluster config change redeploys every deployment of the session
cluster, including the shared deployments of other tests in the shard.
Mark such a test with `@pytest.mark.changes_cluster_config`, restore
the original config and wait for `wait_for_cluster_settled` before the
test ends. The conftest hook `run_cluster_config_changes_first` runs the
marked tests before every other test of the session, whatever their
file names, so no shared deployment exists yet when they change the
config. `test_cluster_update.py` in `shard_compute` uses it.

## Debugging — `--pdb` still works

Matrix sharding does NOT change the per-test debugging recipe.
AGENTS.md's `--pdb` workflow continues to apply. Run the wrapper from
the repository root:

```bash
scripts/e2e-pdb.sh backend/tests/e2e/<node_id>
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

Before reaching for any of that, check the four things that dominate a
shard's wall-clock — reshuffling tests between shards only moves time
around, it does not remove it:

- **Is `STYRMIN_OPERATOR_RECONCILE_INTERVAL` reaching the agent pod?**
  It is set to `5` in `backend/tests/e2e/fixtures/styrmin-values.yaml`
  via the agent subchart's `agent.extraEnv`. At its 60s production
  default, every create / upgrade / delete in the shard sleeps a full
  ~60s after Kubernetes has already finished, because the kopf timer is
  the only path that advances a deployment to `Running` or `Deleted`.
  This one value is worth ~50% of the shard.
- **Does a test wait for a timeout or a retry?** The same `agent.extraEnv`
  lowers the operator's retry delay after a temporary error
  (`STYRMIN_OPERATOR_RETRY_DELAY`, 30s → 5s), its readiness timeout
  (270s → 210s) and FluxCD's HelmRelease timeout (300s → 240s). A test
  that fails a rollout on purpose waits for these, whatever the host;
  give it its own shard rather than adding it to a busy one.
- **Is `PREFECT_WORKER_QUERY_SECONDS` reaching the agent pod?** Same
  file, same `agent.extraEnv`, set to `1`. At Prefect's 10s default
  every agent flow run (a create chains three) starts ~9s late; the
  value is worth ~15-25% of a shard.
- **How many deploy / upgrade / delete cycles does the shard perform?**
  Each deploy is ~30s and each full delete-to-tombstone ~25-60s, and
  that is irreducible. Cutting cycles (per the read-only tier in
  [`e2e-deployment-sharing.md`](e2e-deployment-sharing.md)) is the only
  other real lever. Environment fixtures are *not* a lever — the
  per-environment dedicated-ingress controller is dispatched
  asynchronously and overlaps the application install.

See [`dev/knowledge/backend/e2e-testing.md`](../knowledge/backend/e2e-testing.md)
(§ "Where the wall-clock actually goes") for the measurements behind
all four, including two environment-sharing optimisations that were
measured and rejected.
