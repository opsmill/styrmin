# E2E Evidence: Steps and Failure Causes for Tasks, Backups and Restores

Constitution §V requires every new or changed E2E node of spec 019 to pass locally before the work is done. Each row below records one passing run, as the "E2E evidence rule" in [tasks.md](tasks.md) describes. A node that was only skipped, or never ran against a vCluster, has no row.

Run each node with `--pdb`. In a non-interactive shell, use `sleep infinity | uv run pytest <node> -v -s --pdb 2>&1 | tee /tmp/pdb.log`.

## Passing runs

| Node id | Command | Passing time (ISO 8601, UTC) | vCluster id and kubeconfig | PASSED line |
|---|---|---|---|---|
