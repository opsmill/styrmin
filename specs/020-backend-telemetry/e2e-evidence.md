# E2E Local-PASS Evidence: spec 020 (Anonymous Daily Telemetry from the Styrmin Server)

Constitution §V requires each new or changed E2E test in this spec to pass locally at least
once before the spec is done. Each row records one passing run, following the "E2E evidence
rule" in [tasks.md](tasks.md): run with `--pdb`, `api-chromium` variant only, in a session
of its own.

| Pytest node ID | Exact command | Passing time (ISO 8601) | vCluster ID and kubeconfig path | Verbatim `PASSED` line |
|---|---|---|---|---|
| `backend/tests/e2e/test_server_telemetry.py::test_server_sends_daily_report[api-chromium]` (T046, final code at commit `71eca2e3`) | `export STYRMIN_IMAGE_VER=local-p5p4d-telemetry-final-1791504265 && docker compose build server && sleep infinity \| uv run pytest "backend/tests/e2e/test_server_telemetry.py::test_server_sends_daily_report" -k api-chromium -v -s --pdb 2>&1 \| tee <scratch>/e2e-final.log` | 2026-10-09T00:07:11Z (session started 2026-10-09T00:04:41Z; `1 passed, 1 deselected, 1 warning in 153.31s (0:02:33)`) | vCluster `pytest-89d7eec4-abd8-472c-ab77-c06847b1e9d7`; kubeconfig `/tmp/pytest-of-root/pytest-1054/vcluster0/kubeconfig` | `PASSED00:07:11 info Removing vCluster container vcluster.cp.pytest-89d7eec4-abd8-472c-ab77-c06847b1e9d7...` (pytest's `PASSED` and the teardown log share the line; ANSI colour codes removed) |
| `backend/tests/e2e/test_server_telemetry.py::test_server_sends_daily_report[api-chromium]` (after the rebases onto `develop`, with `down_revision = "69b12221e5df"`, commit `6917d973`) | `export STYRMIN_IMAGE_VER=local-p5p4d-telemetry-final2-1791534115 && docker compose build server && sleep infinity \| uv run pytest "backend/tests/e2e/test_server_telemetry.py::test_server_sends_daily_report" -k api-chromium -v -s --pdb 2>&1 \| tee <scratch>/e2e-final2.log` | 2026-10-09T08:24:30Z (session started 2026-10-09T08:22:02Z; `1 passed, 1 deselected, 1 warning in 151.42s (0:02:31)`) | vCluster `pytest-0a4a3518-3e03-490b-9ac0-cd28de63ba90`; kubeconfig `/tmp/pytest-of-root/pytest-1075/vcluster0/kubeconfig` | `PASSED08:24:30 info Removing vCluster container vcluster.cp.pytest-0a4a3518-3e03-490b-9ac0-cd28de63ba90...` |
