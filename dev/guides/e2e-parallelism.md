# E2E Parallelism: Matrix Sharding

## Overview

E2E tests run in a 6-shard × 2-entrypoint CI matrix. Each cell is a
GitHub Actions job that boots its own vcluster, installs styrmin via
Helm, and runs only the tests carrying its shard marker.

The six shards:

| Shard | Marker | Purpose | Sample tests |
|---|---|---|---|
| `readonly` | `shard_readonly` | Tests that only read shared state | `test_ui_smoke`, `test_admin_*` |
| `mutation_small` | `shard_mutation_small` | Short tests that create/delete their own deployment | `test_deploy_app`, `test_delete_deployment_*`, `test_service_discovery` |
| `env_vars` | `shard_env_vars` | `test_deployment_env_vars.py` (env-var precedence matrix, all api_only) | `test_us1_deployment_level_env_var`, `test_us2_environment_level_env_var_propagates` |
| `env_update` | `shard_env_update` | `test_environment_update.py` (env-level fan-out) | `test_us1_environment_update_fans_out_to_all_deployments` |
| `pod_scheduling` | `shard_pod_scheduling` | `test_pod_scheduling.py` (affinity / anti-affinity, all api_only) | `test_scheduling_end_to_end`, `test_pod_anti_affinity_cross_deployment_via_graphql` |
| `ingress` | `shard_ingress` | Ingress-controller scenarios (its own LB / IP allocation) | `test_ingress_controller` |
| `backup` | `shard_backup` | Velero + MinIO; cluster-wide state | `test_backup_restore*` |

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
       pytest.mark.shard_readonly,          # one of shard_readonly,
                                             # shard_mutation_small,
                                             # shard_env_vars,
                                             # shard_env_update,
                                             # shard_pod_scheduling,
                                             # shard_ingress, shard_backup
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
