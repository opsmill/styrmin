# Implementation Report: Anonymous opt-out telemetry for `styrminctl`

**Status**: ✅ COMPLETE

## 1. Header

- **Feature**: Anonymous opt-out telemetry for `styrminctl` (015)
- **Spec dir**: `specs/015-styrminctl-telemetry/`
- **Branch**: `015-styrminctl-telemetry`
- **Base commit** (start of implement): `ca417c8`
- **Head commit** (end): `63222eb`
- **Implementation commits**: 8 (7 chunk commits + 1 review-fix commit)
- **Tests**: 94 unit + 9 E2E = **103 passing**; Python `ruff`/`ty` clean.

## 2. Chunk-by-chunk ledger

| # | Chunk (phase) | Tasks | Outcome | Commit | Notes |
|---|---|---|---|---|---|
| 1 | Phase 1: Setup | T001–T003 (3) | ✅✅✅ | `9eae7bc` | `httpx` promoted to direct dep → `uv.lock` gained only a 2-line dependency-edge (no new package). No tests (n/a). |
| 2 | Phase 2: Foundational | T004–T006 (3) | ✅✅✅ | `1a0dac7` | `TelemetryStore` intentionally never raises (returns `bool` on write) — diverges from `TokenStore` per FR-013/FR-017. 10 store tests. |
| 3 | US1 core builders | T007,T008,T009,T012,T013,T014 (6) | ✅×6 | `ef3db19` | Option extraction via `assemble_argument_collection().match()` — no value conversion / `@file` read. 35 tests. |
| 4 | US1 dispatch + wiring | T010,T011,T015,T016,T017,T018 (6) | ✅×6 | `777f4df` | Daemon-thread bounded-join dispatch; `cli.py` split into `_call_with_auth_boundary` + `runtime.run`. Suite 57. |
| 5 | US2 opt-out | T019–T023 (5) | ✅×5 | `bf9d053` | Shared `effective_state()` reason helper; `telemetry enable/disable/status` registered. Suite 69. |
| 6 | US3 CI exclusion | T024,T025 (2) | ✅✅ | `94c9f66` | CI + non-TTY rungs folded into `effective_state`; added `tests/telemetry/conftest.py` (autouse `_stderr_is_tty=True`). Suite 83. |
| 7 | Phase 6: Polish | T026–T032 (7) | ✅×7 | `e294ed6` | E2E run to PASS (real subprocess + pty + `http.server` sink, no vCluster); docs, ADR-0047, CONTEXT.md; final gate. Suite 83 + 9 E2E. |
| — | Review fixes | (review) | ✅ | `63222eb` | SC-001 budget test, FR-015 eligibility test, concurrent-write test, doc-wording, os_family tightening. Suite → 94. |

All chunks ran sequentially (never in parallel). No ❌ blocked, no retries needed.

## 3. Tasks not completed

None. All 32 tasks in `tasks.md` are `[X]`.

## 4. Local-pass evidence (REQUIRED)

All tests were observed to PASS locally. Aggregated per test module (node IDs available in chunk reports). Environment for all rows: Python 3.14.5, pytest 9.0.2, Linux, uv-managed venv; unit tests need no cluster; the E2E uses a real `styrminctl` subprocess + `pty` + a stdlib `ThreadingHTTPServer` sink (no vCluster/backend).

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---|---|---|---|---|---|
| `tests/telemetry/test_store.py` (incl. `test_concurrent_writers_keep_file_valid`) | unit | `cd cli && uv run pytest tests/telemetry/test_store.py -v` | 2026-06-21T18:08:34Z | uid 1000 (non-root; unwritable-dir fallback genuinely exercised) | part of `94 passed in 0.85s` |
| `tests/telemetry/test_event.py` | unit | `cd cli && uv run pytest tests/telemetry/test_event.py -v` | 2026-06-21T17:30:56Z | n/a | part of `94 passed` |
| `tests/telemetry/test_errors.py` | unit | `cd cli && uv run pytest tests/telemetry/test_errors.py -v` | 2026-06-21T17:30:56Z | n/a | part of `94 passed` |
| `tests/telemetry/test_envelope.py` (pinned checksum vector, SC-005) | unit | `cd cli && uv run pytest tests/telemetry/test_envelope.py -v` | 2026-06-21T17:30:56Z | n/a | part of `94 passed` |
| `tests/telemetry/test_dispatch.py` (incl. `test_default_budget_is_200ms`, `test_hung_endpoint_at_default_budget_returns_promptly`) | unit | `cd cli && uv run pytest tests/telemetry/test_dispatch.py -v` | 2026-06-21T18:08:34Z | n/a | part of `94 passed` |
| `tests/telemetry/test_runtime.py` (SC-003 byte-identical) | unit | `cd cli && uv run pytest tests/telemetry/test_runtime.py -v` | 2026-06-21T17:40:36Z | n/a | part of `94 passed` |
| `tests/telemetry/test_eligibility.py` (incl. `test_ineligible_routes_return_false`, FR-015) | unit | `cd cli && uv run pytest tests/telemetry/test_eligibility.py -v` | 2026-06-21T18:08:34Z | n/a | part of `94 passed` |
| `tests/telemetry/test_telemetry_command.py` | unit | `cd cli && uv run pytest tests/telemetry/test_telemetry_command.py -v` | 2026-06-21T17:50:00Z | n/a | part of `94 passed` |
| **Full unit suite** | unit | `cd cli && uv run pytest tests/telemetry -q` | 2026-06-21T18:11Z (final) | Linux, Py 3.14.5 | `94 passed in 0.85s` |
| `tests/e2e/test_styrminctl_telemetry.py` (9 tests: 1-envelope+checksum, no-forbidden-values, hung-endpoint exit/no-stderr, 3× env opt-out, non-TTY, persisted disable) | e2e | `cd cli && uv run pytest tests/e2e/test_styrminctl_telemetry.py -v` | 2026-06-21T18:01:03Z (re-confirmed 18:11Z) | real `styrminctl` subprocess + `pty.openpty()` + `ThreadingHTTPServer` on `127.0.0.1:0`; no vCluster | `9 passed in 24.52s` |

No `MISSING` rows. No `deferred — local E2E not supported` rows (the E2E runs locally).

## 5. Review findings

Dual-pass review (code, tests, errors, types, comments) over `ca417c8..HEAD`. High-risk guarantees independently confirmed sound by reviewers: FR-004 failure isolation, FR-003 bounded join (incl. hung connect), no teardown stderr noise, `@file` never read, FR-006 checksum determinism, FR-014 precedence, FR-011 type-keyed categorization.

| Severity | Area | File | Summary | Disposition |
|---|---|---|---|---|
| 🔴 Critical | tests | `test_dispatch.py` | SC-001 200 ms budget number never asserted; no hung-dispatch test at real default | **Fixed inline** (`63222eb`): `test_default_budget_is_200ms` + `test_hung_endpoint_at_default_budget_returns_promptly` |
| 🟠 Important | tests | `test_eligibility.py` | FR-015 command-eligibility rung had no direct test | **Fixed inline** (`63222eb`): parametrized `is_eligible_command` test |
| 🟠 Important | tests | `test_store.py` | No concurrent-write test for `telemetry.json` (FR-017 edge case) | **Fixed inline** (`63222eb`): 8-thread `test_concurrent_writers_keep_file_valid` |
| 🟠 Important | types | `event.py`/`envelope.py`/`runtime.py` | `data`/envelope are `dict[str, Any]`; a `TypedDict` + `Literal` outcome/category would enforce the closed-key/order invariant at check time | **Deferred** — quality-only; code is correct and `ty`-clean. See §6. |
| 🟡 Suggestion | docs | `README.md`, `docs/.../telemetry.md` | Checksum framed as transit-integrity; it's a recompute/determinism contract | **Fixed inline** (`63222eb`) |
| 🟡 Suggestion | tests | `test_event.py` | `os_family` assertion allowed `""` | **Fixed inline** (`63222eb`): tightened to closed set |
| 🟡 Suggestion | code | `eligibility.py` | CI falsey set not casefolded (`CI=FALSE` treated as CI) | **Deferred** — suppression is the safe direction; low impact |
| 🟡 Suggestion | code | `commands/telemetry.py` | `enable`/`disable` swallow a persistence failure silently (contract-compliant) | **Deferred** — optional stderr advisory; see §6 |
| 🟡 Suggestion | comments | `eligibility.py` | Docstring references task IDs that may rot once `tasks.md` is archived | **Deferred** — cosmetic |

## 6. Autonomous decisions

- **Chunking**: split User Story 1 (12 tasks) into two chunks (core builders / dispatch+wiring) so each chunk pairs its tests with the code that makes them green — a test-only chunk could never satisfy the per-chunk local-pass policy.
- **E2E architecture**: implemented entirely against the real `styrminctl` subprocess. The positive-emit + forbidden-values cases use a real `pty.openpty()` to honestly satisfy the `stderr.isatty()` rung; opt-out/CI/non-TTY/hung cases run as plain subprocesses. No in-process fallback was needed. The E2E exercises `clusters list` against an unreachable backend (fails fast, emits `outcome:"failure"`) and asserts a non-null bucketed `error_category` rather than pinning the exact bucket (a `ConnectError` surfaces via Cyclopts as `SystemExit` → `usage`); the precise type→category mapping is covered by the unit suite.
- **Latency assertion split**: the tight per-mechanism 200 ms bound is asserted in the unit suite (injectable budget + the new real-default test); the E2E uses a generous wall-clock guard to avoid process-spawn flakiness (critique E3).
- **`httpx` direct dependency**: promoting an existing transitive dep added only a 2-line edge to `uv.lock`, no new package — treated as not triggering the "new dependency" governance gate (consistent with the plan).
- **Deferred review items**: the TypedDict/`Literal` refactor and two minor code suggestions were recorded rather than applied, to keep the review tail from turning into a refactor; the code is correct and type-clean as shipped.

## 7. Suggested next steps

1. **Open a PR** for `015-styrminctl-telemetry` → `develop` (branch is rebased on latest `develop`).
2. (Optional, recommended) Apply the deferred **TypedDict + `Literal`** type hardening for the `data`/envelope contract and the `outcome`/`error_category` closed sets — the one review item that materially raises compile-time safety.
3. (Optional) Consider casefolding the `CI` falsey comparison and adding a one-line stderr advisory when `telemetry enable/disable` cannot persist (unwritable dir).
4. Confirm the production telemetry endpoint URL in `config.py` (`https://telemetry-endpoints.cloudflare-096.workers.dev/styrminctl`) matches the actual ingestion endpoint before release.
5. Run `speckit.opsmill.extract` when ready to fold durable knowledge (the ADR is already in place at `dev/adr/0047`).
