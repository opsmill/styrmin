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
cd frontend && pnpm test -- EditClusterDialog
```

Expected: all pass. The fan-out suite covers the override rule, the resubmission after a forced dispatch failure, the skip rules and the log line; the ordering suite covers each row of the controller table in [research.md](research.md) D4 and the removal rule in D5.

## 2. Manual check with `styrminctl` (dev stack)

```bash
uv run invoke dev            # dev stack with one cluster, environment and app
styrminctl clusters get default
# copy the printed config into /tmp/cluster.json (the file used with clusters create), then change fqdn_suffix
styrminctl clusters update default --config @/tmp/cluster.json
styrminctl deployments list   # the apps that take fqdn_suffix are DEPLOYING
styrminctl clusters update default --config @/tmp/cluster.json   # second run
```

Expected:

- The first update prints the new config. Each application that takes the cluster's FQDN suffix gets one `UPDATE_INSTANCE` task.
- The second run starts no task (SC-003).
- The server log has one `cluster_config_fanout` line per update with the counts.
- A file with `"fqdn_sufix"` is refused by the CLI before any request, naming the key.

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
