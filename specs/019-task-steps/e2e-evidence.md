# E2E Evidence: Steps and Failure Causes for Tasks, Backups and Restores

Constitution §V requires every new or changed E2E node of spec 019 to pass locally before the work is done. Each row below records one passing run, as the "E2E evidence rule" in [tasks.md](tasks.md) describes. A node that was only skipped, or never ran against a vCluster, has no row.

Run each node with `--pdb`. In a non-interactive shell, use `sleep infinity | uv run pytest <node> -v -s --pdb 2>&1 | tee /tmp/pdb.log`.

## Passing runs

| Node id | Command | Passing time (ISO 8601, UTC) | vCluster id and kubeconfig | PASSED line |
|---|---|---|---|---|
| `backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_has_entries[api-chromium]` | `sleep infinity \| uv run pytest "backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_has_entries[api-chromium]" -v -s --pdb 2>&1 \| tee e2e-api-1.log` | 2026-10-06T13:53:20Z | `pytest-3b8385b2-4c45-46a8-b795-4abb0b89b033`, `/tmp/pytest-of-root/pytest-618/vcluster0/kubeconfig` | `PASSED` (after the node id, interleaved with `-s` output); `1 passed, 1 warning in 144.96s (0:02:24)` |
| `backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_has_entries[ui-chromium]` | `sleep infinity \| uv run pytest "backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_has_entries[ui-chromium]" -v -s --pdb 2>&1 \| tee e2e-ui-1.log` | 2026-10-06T13:56:14Z | `pytest-9fa4b77f-ad05-4a1c-be1a-28ecec6060c2`, `/tmp/pytest-of-root/pytest-619/vcluster0/kubeconfig` | `PASSED` (after the node id, interleaved with `-s` output); `1 passed, 1 warning in 150.67s (0:02:30)` |
