# Quickstart: Validate Anonymous Daily Telemetry

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

How to prove the feature works, from unit tests to the E2E test that closes the definition of done (Constitution §V).

## Prerequisites

```bash
uv sync
uv run invoke pre-commit-install
```

E2E tests need `docker` and `vcluster` on `PATH` (see [`dev/knowledge/backend/e2e-testing.md`](../../dev/knowledge/backend/e2e-testing.md)). The Helm ConfigMap tests need `helm` on `PATH`.

## 1. Migration

```bash
STYRMIN_DB_TYPE=postgres STYRMIN_DB_NAME=styrmin uv run styrmin db migrate
uv run styrmin db status
uv run styrmin db downgrade -1
uv run styrmin db migrate
```

For a PostgreSQL server that is not on `localhost:5432` without a password, also set `STYRMIN_DB_HOST`, `STYRMIN_DB_PORT`, `STYRMIN_DB_USERNAME` and `STYRMIN_DB_PASSWORD`.

Expected:

- `styrmin db status` prints the new `add_installation` revision as head.
- `styrmin db downgrade -1` removes the `installation` table and returns to `c2ff6dba5ffd`.
- The second `styrmin db migrate` creates the table again.
- The migration unit test runs the same round trip on PostgreSQL and SQLite.

`schema.graphql` does not change: `uv run styrmin export graphql-schema schema.graphql && git diff --exit-code schema.graphql`.

## 2. Unit tests

```bash
uv run pytest backend/tests/unit -k "telemetry or installation" -v
uv run invoke test
uv run invoke format lint
```

Expected, among others:

- The payload builder test asserts the exact FR-006 key set, a driver version with `deployment_count: 0`, a tombstoned deployment that is not counted, merged and sorted driver entries, and no repository URL, branch or path.
- The sender tests cover 2xx, 4xx, 5xx, connection refused and a server that never answers, and each one ends within 10 seconds without raising.
- The flow tests show no HTTP request with `STYRMIN_TELEMETRY_ENABLED=false`, with `DO_NOT_TRACK=1`, and for a run that starts more than one hour late.
- The checksum test computes the same digest as `styrminctl.telemetry.envelope.checksum`.
- The Helm test renders `STYRMIN_TELEMETRY_ENABLED: "false"` for `--set styrmin.telemetry.enabled=false`, and renders `STYRMIN_TELEMETRY_ENDPOINT` only when `styrmin.telemetry.endpoint` is set.

## 3. Manual check against a local stack

```bash
uv run invoke dev
docker compose logs server | grep Telemetry
```

Expected: `Telemetry is off (STYRMIN_TELEMETRY_ENABLED=false).`, because `docker-compose.yml` turns telemetry off.

View the report without sending it:

```bash
docker compose exec server styrmin telemetry show
```

Expected: one JSON object with exactly the keys `install_id`, `styrmin_version`, `python_version`, `os_family`, `arch`, `cluster_count`, `environment_count`, `deployment_count`, `drivers`. Running it twice prints the same `install_id`.

On a Helm install:

```bash
kubectl -n styrmin exec deploy/styrmin-server -c styrmin-server -- styrmin telemetry show
kubectl -n styrmin logs deploy/styrmin-server -c styrmin-server | grep Telemetry
```

## 4. E2E test (definition of done)

```bash
uv run pytest "backend/tests/e2e/test_server_telemetry.py" -v -s --pdb -k "api-chromium"
```

From a non-interactive shell, keep pdb's standard input open:

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_server_telemetry.py" -v -s --pdb -k "api-chromium" 2>&1 | tee /tmp/telemetry-e2e.log
```

Expected: `PASSED`. The test:

1. Reads the server pod's log and finds one line that starts with `Telemetry is on`.
2. Prints `styrmin telemetry show` in the server pod and parses the JSON.
3. Reads the number of reports the in-cluster sink holds.
4. Starts `send_telemetry_report/send_telemetry_report` through the Prefect API and waits for `COMPLETED`.
5. Asserts the sink holds exactly one new report, with `kind: "styrmin"`, `payload_format: "1.0"`, a checksum that matches its `data`, and `data` equal to the output of step 2, including the simple-app driver with at least one deployment and a `styrmin_version` other than `"unknown"`.

Record the evidence that Constitution §V requires: node ID, command, ISO 8601 time of the passing run, vcluster ID and kubeconfig path, and the `PASSED` line.

## 5. Documentation

- [`docs/docs/reference/telemetry.md`](../../docs/docs/reference/telemetry.md) is titled "Telemetry & privacy" and has a server section.
- `helm/styrmin/README.md` lists `styrmin.telemetry.enabled` and `styrmin.telemetry.endpoint`, and `helm template helm/styrmin` shows the telemetry lines in the install notes.
- The new ADR is in `dev/adr/`, and `CONTEXT.md` has the extended **Telemetry** entry and the new **Install ID** entry.
- A towncrier fragment exists in `changelog/`.
- `cd docs && pnpm build` succeeds.
