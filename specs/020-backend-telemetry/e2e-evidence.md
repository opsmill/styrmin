# E2E Local-PASS Evidence: spec 020 (Anonymous Daily Telemetry from the Styrmin Server)

Constitution §V requires each new or changed E2E test in this spec to pass locally at least
once before the spec is done. Each row records one passing run, following the "E2E evidence
rule" in [tasks.md](tasks.md): run with `--pdb`, `api-chromium` variant only, in a session
of its own.

| Pytest node ID | Exact command | Passing time (ISO 8601) | vCluster ID and kubeconfig path | Verbatim `PASSED` line |
|---|---|---|---|---|
| `backend/tests/e2e/test_server_telemetry.py::test_server_sends_daily_report[api-chromium]` (T046, final code at commit `71eca2e3`) | `export STYRMIN_IMAGE_VER=local-p5p4d-telemetry-final-1791504265 && docker compose build server && sleep infinity \| uv run pytest "backend/tests/e2e/test_server_telemetry.py::test_server_sends_daily_report" -k api-chromium -v -s --pdb 2>&1 \| tee <scratch>/e2e-final.log` | 2026-10-09T00:07:11Z (session started 2026-10-09T00:04:41Z; `1 passed, 1 deselected, 1 warning in 153.31s (0:02:33)`) | vCluster `pytest-89d7eec4-abd8-472c-ab77-c06847b1e9d7`; kubeconfig `/tmp/pytest-of-root/pytest-1054/vcluster0/kubeconfig` | `PASSED00:07:11 info Removing vCluster container vcluster.cp.pytest-89d7eec4-abd8-472c-ab77-c06847b1e9d7...` (pytest's `PASSED` and the teardown log share the line; ANSI colour codes removed) |
