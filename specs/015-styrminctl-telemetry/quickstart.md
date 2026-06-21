# Quickstart / Validation: Anonymous opt-out telemetry for `styrminctl`

**Feature**: `015-styrminctl-telemetry`

This guide validates the feature end-to-end. Implementation detail lives in `tasks.md`; this is a
run/verify guide.

## Prerequisites

- `uv sync` complete; working in the repo root.
- The `styrminctl` console script available via `uv run styrminctl ...`.

## Unit tests (fast loop)

```bash
cd cli && uv run pytest tests/telemetry -v
```

Expected coverage (see `tasks.md`): `TelemetryStore`, `should_emit()`, `build_event()` +
`categorize_error()`, `build_envelope()` + checksum round-trip vector, `dispatch()` (hung-endpoint
latency + failure isolation), and the `telemetry` command group.

## Manual local-sink walkthrough (mirrors the E2E)

1. **Start a local sink** that records POST bodies (a tiny HTTP server on `127.0.0.1:<port>` that
   returns `200` and appends the JSON body to a list).
2. **Point the CLI at it and run an eligible command interactively:**

   ```bash
   STYRMIN_TELEMETRY_ENDPOINT=http://127.0.0.1:<port> uv run styrminctl deployments update my-app --config @secrets.json -w
   ```

   - **Expect**: exactly **one** recorded envelope. Its `data.command == "deployments update"`,
     `data.options == ["--config","--wait"]`, `data.outcome == "success"`, `error_category == null`,
     and `kind/payload_format == "styrminctl"/"1.0"`.
   - **Expect**: `checksum` recomputes from `json.dumps(data)` + sha256 (SC-005).
   - **Expect (SC-002)**: none of `my-app`, `secrets.json`, the file contents, the server address, or
     any token appears anywhere in the body.

3. **Hung endpoint / latency (SC-001):** point `STYRMIN_TELEMETRY_ENDPOINT` at a blackhole
   (`http://127.0.0.1:1`/a sink that never responds) and re-run. **Expect**: the command exits with the
   same code/output, delayed by ≤ 200 ms vs telemetry-disabled, and nothing is printed; no event
   recorded.

4. **Failure path (SC-003):** run a command that fails (e.g. bad target). **Expect**: one event with
   `outcome:"failure"` and a bucketed `error_category`; the original error and exit code reach the user
   unchanged; stdout/stderr byte-identical to the telemetry-disabled run.

## Opt-out / exclusion matrix (SC-004 — each yields zero outbound requests)

```bash
# persisted disable
uv run styrminctl telemetry disable && uv run styrminctl telemetry status   # -> "disabled (...)"
STYRMIN_TELEMETRY_ENDPOINT=http://127.0.0.1:<port> uv run styrminctl clusters list   # -> 0 requests
uv run styrminctl telemetry enable

# env levers
STYRMIN_TELEMETRY=0   ... clusters list     # -> 0 requests
DO_NOT_TRACK=1        ... clusters list     # -> 0 requests
CI=true               ... clusters list     # -> 0 requests (non-interactive)
... clusters list 2>/dev/null   # stderr not a TTY -> 0 requests

# ineligible commands
... telemetry status      # -> 0 requests
... --version             # -> 0 requests
... --help                # -> 0 requests
```

## E2E (Constitution §V, non-negotiable)

A single `api_only` E2E in `backend/tests/e2e/` (or the CLI's E2E location) runs `styrminctl` against a
local sink via `STYRMIN_TELEMETRY_ENDPOINT` and asserts:

- (a) exactly one well-formed envelope with a server-verifiable checksum,
- (b) no forbidden values in the payload (run with known-sensitive inputs),
- (c) ≤ 200 ms added latency and unchanged exit behaviour (incl. hung endpoint),
- (d) zero requests under each opt-out lever.

Marked `@pytest.mark.api_only` — the flow is entirely CLI/HTTP with no UI surface.

## Docs to verify updated

- `cli/README.md` — a telemetry section listing exactly what is collected and the opt-out levers.
- A `docs/` privacy note covering the same.
- `CONTEXT.md` — new **Telemetry** glossary entry; amended **CLI / styrminctl** entry.
- A new ADR recording the external fire-and-forget telemetry call.
