# Quickstart: Validate the Cluster Config Update

**Feature**: [spec.md](spec.md) | **Contracts**: [contracts/graphql.md](contracts/graphql.md), [contracts/sdk-cli.md](contracts/sdk-cli.md)

## Prerequisites

- `uv sync` and `cd frontend && pnpm install --ignore-workspace` (emdash worktree).
- `vcluster` and `docker` on `PATH` for the E2E tests. Build the server image first: `docker compose build server`.

## 1. Unit and functional tests

```bash
uv run pytest backend/tests/unit/services/test_cluster_update.py \
  backend/tests/unit/services/test_cluster_config_fanout.py \
  backend/tests/unit/services/test_ingress_controller_ordering.py \
  backend/tests/unit/context/test_resolve_instance_config.py -v
uv run pytest backend/tests/functional/graphql/test_cluster_update_propagation.py -v
uv run pytest cli/tests/test_clusters.py -v
cd frontend && pnpm test EditClusterDialog
```

Expected: all pass. The fan-out suite covers the override rule, the resubmission after a forced dispatch failure, the skip rules and the log line; the ordering suite covers each row of the controller table in [research.md](research.md) D4 and the removal rule in D5.

## 2. Manual check with `styrminctl` (dev stack)

`uv run invoke start --build-image` brings up the dev stack: a vCluster, the Helm chart with an image built from this tree, and the bootstrap of a cluster `local` (FQDN suffix `local.styrmin.io`) and an environment `local`. Without `--build-image` it reuses an existing `registry.opsmill.io/opsmill/styrmin:latest` image, which does not contain this feature. The bootstrap deploys no application, so deploy one first.

```bash
uv run invoke start --build-image
export STYRMIN_ADDRESS=http://styrmin.local.styrmin.io:8080 STYRMIN_USERNAME=admin STYRMIN_PASSWORD=styrmin
styrminctl deployments create semaphore 2.16.47 local --cluster local --name semaphore-qs
styrminctl deployments get <deployment-id>   # wait for Status: running
COLUMNS=1000 styrminctl clusters get local
# copy the printed config JSON into /tmp/cluster.json, then change fqdn_suffix
styrminctl clusters update local --config @/tmp/cluster.json
styrminctl tasks list                        # one update_instance task for semaphore-qs
styrminctl deployments get <deployment-id>   # Status: deploying, then running
styrminctl clusters update local --config @/tmp/cluster.json   # second run, after the first task succeeded
kubectl logs deploy/styrmin-server -n styrmin | grep cluster_config_fanout
```

Expected:

- The first update prints the new config and the line `Follow their tasks with: styrminctl tasks list`. Each deployment that takes the cluster's FQDN suffix gets one `update_instance` task, and its ingress hosts move to the new suffix.
- The second run starts no task (SC-003).
- The server log has one `cluster_config_fanout` line per update with the counts: `dispatched=1` for the first update, `dispatched=0 skipped_noop=1` for the second.
- A file with `"fqdn_sufix"` is refused by the CLI before any request with `Error: Unknown config key(s): fqdn_sufix`.

## 3. E2E (local pass evidence required)

Run each variant in its own session (memory note: one variant per session):

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_cluster_update.py" -k api-chromium -v -s --pdb 2>&1 | tee /tmp/cluster-update-api.log
sleep infinity | uv run pytest "backend/tests/e2e/test_cluster_update.py" -k ui-chromium -v -s --pdb 2>&1 | tee /tmp/cluster-update-ui.log
```

Expected: `test_cluster_update_redeploys_and_moves_dedicated_ingress[api-chromium] PASSED` and `test_edit_cluster_config_from_detail_page[ui-chromium] PASSED`. Record node id, command, ISO 8601 timestamp, vcluster id with kubeconfig path, and the `PASSED` line (constitution V).

Then run the whole shard once, so the restore and the convergence wait are checked against the tests that follow:

```bash
uv run pytest backend/tests/e2e -m shard_compute -k api-chromium -v
```

## 4. Documentation check

- `docs/docs/reference/styrminctl.md` documents `clusters update`.
- `docs/docs/concepts-and-architecture/ingress-and-networking.md` describes the order when `dedicated_ingress` changes at the cluster.
- `docs/docs/concepts-and-architecture/reconciliation.md` names the cluster config fan-out.
- `dev/knowledge/architecture.md` §3.5, `dev/knowledge/backend/data-models.md`, `CONTEXT.md` (**Config fan-out**), `dev/adr/0065-cluster-config-fanout.md` and a `changelog/423.added.md` fragment are present.
