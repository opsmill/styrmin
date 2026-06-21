# Implementation Plan: Anonymous opt-out telemetry for `styrminctl`

**Branch**: `015-styrminctl-telemetry` | **Date**: 2026-06-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/015-styrminctl-telemetry/spec.md`

## Summary

Add anonymous, opt-out telemetry to `styrminctl`. After each *eligible* invocation (interactive
workstation, not opted out, not CI/non-interactive, eligible command), the CLI fire-and-forgets a
single scrubbed event — resolved command route, canonical option names, outcome + error category, and
coarse environment facts — to a fixed public endpoint. Dispatch is best-effort, loss-tolerant, and
hard-capped at ≤ 200 ms added latency for all endpoint states via a daemon-thread + bounded-join
pattern. State (`{install_id, enabled}`) is persisted next to the token store using the proven
`TokenStore` atomic-write/strict-perms pattern. A `styrminctl telemetry enable|disable|status` command
group plus `STYRMIN_TELEMETRY`, `DO_NOT_TRACK`, and `STYRMIN_TELEMETRY_ENDPOINT` env vars give
operators a one-step, inspectable opt-out. All new code is CLI-layer; no GraphQL, no DB, no new
package.

## Technical Context

**Language/Version**: Python 3.14+

**Primary Dependencies**: Cyclopts 4.10.1 (CLI framework), `httpx` 0.28.1 (already transitive via
`styrmin-sdk`; promoted to a direct `cli` dependency), stdlib `hashlib`/`json`/`platform`/`threading`/
`importlib.metadata`.

**Storage**: One JSON file at `${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/telemetry.json`. No
database, no GraphQL schema.

**Testing**: `pytest` (unit, under `cli/tests/telemetry/`); one `api_only` E2E against a local sink.

**Target Platform**: Operator workstations — Linux / macOS / Windows.

**Project Type**: CLI client (thin client over the Styrmin GraphQL API; telemetry is a side-channel).

**Performance Goals**: ≤ 200 ms (p99) added command-exit latency vs telemetry-disabled across **all**
endpoint states (single tunable budget constant). One POST per eligible invocation.

**Constraints**: Failure-isolated (byte-identical stdout/stderr/exit code vs disabled); zero forbidden
values in any payload; best-effort (no spool/retry/batch); no new package in the lockfile.

**Scale/Scope**: ~6 new CLI modules + 1 command module + 1 integration hook; ~7 unit test modules + 1
E2E; docs (`cli/README.md`, `docs/` privacy note, `CONTEXT.md`, 1 ADR).

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| §I Declarative State Reconciliation | ✅ N/A | Telemetry is a side-channel observation; no desired/current state, no reconciliation. |
| §II Driver-Based Deployment | ✅ N/A | No driver or component behaviour changes. |
| §III Layered Architecture | ✅ Pass | All new code is CLI-layer; no reach into service/repository/DB; no cross-layer calls. |
| §IV Type Safety & Typed Errors | ✅ Pass | Full type hints; `error_category` derives from the existing typed-error hierarchy; **no new `ServiceError` subclasses**. |
| §V Test-First / E2E required | ✅ Pass | Named `api_only` E2E against a local sink + full unit suite; E2E must PASS locally with recorded evidence. |
| §V GraphQL↔DB propagation tests | ✅ N/A | No schema change. |
| §VI Format & Lint | ✅ Pass | `uv run invoke format lint` before commit; 120-col. |
| §VII Documentation Accuracy | ✅ Pass | `cli/README.md` + `docs/` privacy note + `CONTEXT.md` + ADR ship in this change. |

**Governance gates** (Ask First): DB schema ❌none · GraphQL schema ❌none · **New dependency** —
`httpx` is already present transitively; promoting it to a direct `cli` dep adds nothing to the
lockfile (not a new-dependency gate) · CI/CD ❌none · Auth/authz ❌none.

**Flagged (not a standard gate)**: first `styrminctl` outbound call to a destination other than the
Styrmin GraphQL API → warrants a `CONTEXT.md` glossary update and a short ADR (both included in tasks).

→ **Constitution Check PASS** (pre- and post-design). No entries in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/015-styrminctl-telemetry/
├── plan.md              # This file
├── spec.md              # Phase: specify
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── telemetry-wire-format.md
│   └── cli-telemetry-command.md
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
cli/
├── src/styrminctl/
│   ├── cli.py                      # MODIFIED: telemetry integration around the auth boundary
│   ├── telemetry/                  # NEW package (CLI-layer)
│   │   ├── __init__.py
│   │   ├── store.py                # TelemetryStore (mirrors auth/token_store.py)
│   │   ├── eligibility.py          # should_emit() pure resolver (FR-014/FR-015)
│   │   ├── event.py                # build_event() + option/command extraction + event_id
│   │   ├── errors.py               # categorize_error() type→(outcome, error_category)
│   │   ├── envelope.py             # build_envelope() + CPython-compatible sha256 checksum
│   │   ├── dispatch.py             # daemon-thread bounded best-effort POST (≤200ms)
│   │   ├── runtime.py              # integration hook: resolve→run→classify→build→dispatch
│   │   └── config.py               # endpoint default + STYRMIN_TELEMETRY_ENDPOINT, budget constant
│   └── commands/
│       └── telemetry.py            # NEW: `telemetry` command group (enable|disable|status)
├── tests/telemetry/                # NEW unit tests (one module per unit above + command tests)
├── pyproject.toml                  # MODIFIED: add httpx as a direct dependency
└── README.md                       # MODIFIED: telemetry/privacy section

backend/tests/e2e/ (or cli E2E home)
└── test_styrminctl_telemetry.py    # NEW api_only E2E against a local sink

docs/                               # MODIFIED: privacy note
CONTEXT.md                          # MODIFIED: Telemetry glossary entry + CLI entry amendment
dev/adr/                            # NEW ADR: external fire-and-forget telemetry call
```

**Structure Decision**: Single new CLI-layer package `cli/src/styrminctl/telemetry/` with one module
per pure unit (store, eligibility, event, errors, envelope, dispatch, runtime, config), wired in at the
single chokepoint `cli/src/styrminctl/cli.py`. This keeps each FR independently unit-testable and the
command modules untouched (failure isolation).

## Design highlights (from Phase 0 research)

- **Hook** (R1): extend `_AuthBoundaryApp.__call__` to delegate to `telemetry.runtime.run(...)`, which
  resolves command/options/eligibility *before* invoking, runs the inner app, classifies the outcome
  (incl. the auth-boundary `SystemExit`), and dispatches one event — re-raising everything unchanged.
- **Command route** (R2): `app.parse_commands(tokens)` → space-joined closed-set token.
- **Options** (R3): resolve the dispatched command's argument collection; map supplied `-`-prefixed
  tokens to canonical long names; dedupe + sort; values never read.
- **Dispatch** (R4): daemon thread runs a sync `httpx` POST; main thread `join`s with the budget; on
  timeout it abandons the (daemon) thread → hard ≤ 200 ms cap for every endpoint state.
- **State** (R6): `TelemetryStore` mirrors `TokenStore` (atomic write, `0o600`/`0o700`, ephemeral
  fallback, lazy uuid4 install_id).
- **Errors** (R7): pure `categorize_error` keyed on exception **type** (mapping table in research.md).
- **Eligibility** (R8): one pure predicate over all FR-014/FR-015 rungs.
- **Env facts** (R9): `platform.system()`, `platform.python_version()`, `version("cli")`.
- **Checksum** (R10): `sha256(json.dumps(data))` with CPython defaults + insertion order (server-
  reproducible).

## Testing strategy

- **Unit** (`cli/tests/telemetry/`): per the spec — `TelemetryStore` (round-trip, atomic, strict
  perms, unwritable-dir fallback, install_id stability), `should_emit()` (one assertion per rung),
  `build_event()` + scrubber (closed-set keys, no forbidden values, sorted/deduped options,
  `event_id` composition), `categorize_error()` (each exception type → pair), `build_envelope()` +
  fixed checksum round-trip vector, `dispatch()` (hung-endpoint latency budget + failure isolation),
  and the `telemetry` command (set/read round-trip + env-overrides-persisted precedence).
- **E2E** (`api_only`, Constitution §V): local-sink scenario asserting (a) one well-formed envelope
  with server-verifiable checksum, (b) no forbidden values with known-sensitive inputs, (c) ≤ 200 ms
  added latency / unchanged exit behaviour incl. hung endpoint, (d) zero requests under each opt-out
  lever. Must be observed to PASS locally with recorded evidence (node id, command, timestamp, cluster
  id, verbatim `PASSED` line).
- **GraphQL propagation**: N/A — no schema change.

## Documentation deliverables (§VII, in this change)

- `cli/README.md`: a telemetry section — exactly what is collected, opt-out levers, env vars.
- `docs/`: a privacy note mirroring the README section.
- `CONTEXT.md`: a **Telemetry** glossary entry and an amendment to the **CLI / styrminctl** entry
  noting its first non-GraphQL outbound call.
- `dev/adr/`: an ADR recording the external fire-and-forget telemetry call and its constraints.

## Complexity Tracking

No constitution violations — table intentionally empty.
