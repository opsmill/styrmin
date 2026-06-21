# Tasks: Anonymous opt-out telemetry for `styrminctl`

**Input**: Design documents from `specs/015-styrminctl-telemetry/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: INCLUDED — the spec's Testing Decisions and Constitution §V require a full unit suite plus a
passing E2E.

**Organization**: Tasks are grouped by user story (US1 → US2 → US3) so each story is independently
implementable and testable. MVP = User Story 1.

## Path Conventions

CLI package lives at `cli/src/styrminctl/`; tests at `cli/tests/`. New telemetry code goes under
`cli/src/styrminctl/telemetry/`; new tests under `cli/tests/telemetry/` and `cli/tests/e2e/`.

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Create the telemetry package skeleton with empty/stub modules and docstrings in `cli/src/styrminctl/telemetry/`: `__init__.py`, `config.py`, `store.py`, `eligibility.py`, `event.py`, `errors.py`, `envelope.py`, `dispatch.py`, `runtime.py`
- [X] T002 [P] Promote `httpx` to a direct dependency of the CLI in `cli/pyproject.toml` (already transitive via `styrmin-sdk`; pin `>=0.27.0` to match the SDK) and run `uv sync` to confirm the lockfile is unchanged
- [X] T003 [P] Create test package dirs `cli/tests/telemetry/__init__.py` and `cli/tests/e2e/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared building blocks every user story depends on. MUST complete before Phase 3.

- [ ] T004 Implement telemetry configuration in `cli/src/styrminctl/telemetry/config.py`: the default production endpoint URL, `STYRMIN_TELEMETRY_ENDPOINT` override resolution, and a single tunable budget constant `TELEMETRY_BUDGET_MS = 200` (FR-003, FR-018)
- [ ] T005 Implement `TelemetryStore` in `cli/src/styrminctl/telemetry/store.py` mirroring `cli/src/styrminctl/auth/token_store.py`: path `${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/telemetry.json`, atomic temp-file write (`O_CREAT|O_EXCL|O_WRONLY`, mode `0o600`) + `chmod` + `rename`, parent dir `0o700`; lazy `install_id` (uuid4 hex) generated once; load/save `enabled`; absent file ⇒ enabled; unwritable dir ⇒ ephemeral in-memory `install_id`, never raises (FR-013, FR-017)
- [ ] T006 [P] Unit tests for `TelemetryStore` in `cli/tests/telemetry/test_store.py`: round-trip `{install_id, enabled}`, `install_id` stability across two loads, atomic write + strict perms (`0o600`/`0o700`), unwritable-dir ephemeral fallback (no raise), install_id persists when `enabled=false` (prior art: `cli/tests/auth/test_token_store.py`)

---

## Phase 3: User Story 1 — Telemetry rides along silently and is dropped on failure (Priority: P1) 🎯 MVP

**Goal**: One scrubbed, well-formed envelope is fire-and-forget POSTed per eligible invocation after the
outcome is known; the endpoint being slow/down/erroring never changes the command's output, exit code,
or perceptible speed (≤ 200 ms cap).

**Independent Test**: Run a real command against a local sink with telemetry at defaults → exactly one
well-formed scrubbed envelope; point at a hung/blackhole endpoint → command behaviour and timing
unchanged, nothing printed, event dropped.

### Tests for User Story 1

- [ ] T007 [P] [US1] Unit tests for event building + scrubber in `cli/tests/telemetry/test_event.py`: closed-set `data` keys in exact order, `command` ∈ known route set, `options` are canonical long names deduped+sorted with positionals/repeat-counts excluded, `event_id` composition (`install_id[:8]` + `-` + command with `_`), coarse `os_family`/`python_version`/`styrminctl_version`; **no forbidden values** with sensitive inputs (deployment name, file path, token); **`@file` option value is never opened/read** during name extraction (FR-007–FR-013, critique E1)
- [ ] T008 [P] [US1] Unit tests for `categorize_error` in `cli/tests/telemetry/test_errors.py`: each exception type → expected `(outcome, error_category)` per research.md R7 table; success ⇒ `("success", None)`; `SystemExit(0/None)` ⇒ success, non-zero ⇒ `("failure","usage")`; unknown ⇒ `("failure","unknown")`
- [ ] T009 [P] [US1] Unit tests for envelope + checksum in `cli/tests/telemetry/test_envelope.py`: envelope keys `{data, checksum, kind, payload_format}` with `kind="styrminctl"`, `payload_format="1.0"`; checksum equals `sha256(json.dumps(data))` with CPython defaults (insertion order, no `sort_keys`); fixed round-trip vector from `contracts/telemetry-wire-format.md` reproduces a pinned digest (SC-005)
- [ ] T010 [P] [US1] Unit tests for `dispatch` in `cli/tests/telemetry/test_dispatch.py`: against a hung endpoint the call returns within the budget (assert via injectable/mocked budget mechanism + a generous wall-clock guard — not a tight wall-clock assert; critique E3); refused/4xx/5xx are swallowed and never raise; **zero stderr bytes when the process/thread is torn down with an in-flight dispatch** (critique E2); at most one POST
- [ ] T011 [P] [US1] Unit tests for the runtime hook in `cli/tests/telemetry/test_runtime.py`: exactly one event per eligible invocation built after the outcome is known; stdout/stderr/exit-code byte-identical with telemetry enabled vs disabled on both success and failure paths (SC-003); a raising command emits `outcome:"failure"` then re-raises unchanged

### Implementation for User Story 1

- [ ] T012 [US1] Implement environment facts + command/option extraction + `build_event()` + `event_id` in `cli/src/styrminctl/telemetry/event.py`: `os_family=platform.system()`, `python_version=platform.python_version()`, `styrminctl_version=version("cli")`; resolve `command` via `app.parse_commands(tokens)` (closed set); extract canonical long option names by token-scan + Cyclopts parameter metadata **without value conversion / file reads**; assemble ordered closed-set `data` (FR-007–FR-013, critique E1)
- [ ] T013 [US1] Implement `categorize_error(exc) -> (outcome, error_category)` in `cli/src/styrminctl/telemetry/errors.py`, type-keyed per research.md R7, reusing the existing hierarchy in `python_sdk/src/styrmin_sdk/exceptions.py` and `cli/src/styrminctl/errors.py`; no new exception classes (FR-011, Constitution §IV)
- [ ] T014 [US1] Implement `build_envelope(data)` + CPython-compatible SHA-256 checksum in `cli/src/styrminctl/telemetry/envelope.py` (FR-005, FR-006)
- [ ] T015 [US1] Implement best-effort `dispatch(envelope, endpoint, budget_ms)` in `cli/src/styrminctl/telemetry/dispatch.py`: spawn a daemon thread running a sync `httpx` POST with tight timeouts; main thread `join`s with `budget_ms`; on timeout abandon the daemon thread; **top-level catch-all in the thread target** swallows every error including at interpreter teardown (no stderr noise); no retry/batch/spool (FR-001–FR-004, critique E2)
- [ ] T016 [US1] Implement a baseline `should_emit()` in `cli/src/styrminctl/telemetry/eligibility.py` covering **command eligibility only** for the MVP: returns `False` for the `telemetry` group, `--version`/`version`, `--help`/`-h`, empty route, and the shell-completion command(s); `True` otherwise (FR-015; env/persisted/CI/TTY rungs added in US2/US3)
- [ ] T017 [US1] Implement the integration hook `run(...)` in `cli/src/styrminctl/telemetry/runtime.py`: best-effort resolve `(command, options, eligible)` (never raises) → run the inner app in `try/except/finally` → `categorize_error` on the outcome (incl. auth-boundary `SystemExit`) → if `should_emit` then `build_event`→`build_envelope`→`dispatch` → **re-raise the original exception unchanged**; the entire telemetry path is wrapped so any internal error is swallowed (FR-001, FR-004)
- [ ] T018 [US1] Wire `runtime.run(...)` into `_AuthBoundaryApp.__call__` in `cli/src/styrminctl/cli.py` so telemetry observes the final outcome around the auth error boundary without altering command behaviour

**Checkpoint**: US1 is independently shippable — eligible interactive commands emit one scrubbed event; failures/hung endpoints are isolated.

---

## Phase 4: User Story 2 — Operator opts out and verifies (Priority: P2)

**Goal**: An operator disables telemetry once (command or env var), confirms it stays off, and can
inspect the effective state and the reason.

**Independent Test**: `telemetry disable` then `telemetry status` reports disabled; a subsequent
eligible command emits zero requests; repeat for `STYRMIN_TELEMETRY=0` and `DO_NOT_TRACK=1` (env beats
persisted `enabled`).

### Tests for User Story 2

- [ ] T019 [P] [US2] Unit tests for the env/persisted rungs of `should_emit` in `cli/tests/telemetry/test_eligibility.py`: one assertion per rung — `STYRMIN_TELEMETRY=0`, `DO_NOT_TRACK=1`, persisted `enabled=false` each independently yield no emit; env opt-out overrides a persisted `enabled=true` (FR-014)
- [ ] T020 [P] [US2] Unit tests for the `telemetry` command in `cli/tests/telemetry/test_telemetry_command.py`: `disable`→`status` shows disabled-with-reason, `enable`→persists, set/read round-trip, status reason precedence (env beats persisted), `enable`/`disable`/`status` succeed under an unwritable dir (pattern: `cli/tests/commands/test_auth_commands.py`)

### Implementation for User Story 2

- [ ] T021 [US2] Extend `should_emit()` in `cli/src/styrminctl/telemetry/eligibility.py` with the env + persisted rungs: `STYRMIN_TELEMETRY ≠ 0` ∧ `DO_NOT_TRACK ≠ 1` ∧ persisted flag ≠ disabled, with env opt-out taking precedence; expose a helper that returns the effective state **and the reason** for `status` (FR-014, FR-016)
- [ ] T022 [US2] Implement the `telemetry` command group (`enable|disable|status`) in `cli/src/styrminctl/commands/telemetry.py` per `contracts/cli-telemetry-command.md`, persisting via `TelemetryStore`; `status` prints effective state + reason; never crashes on an unwritable dir (FR-016)
- [ ] T023 [US2] Register the `telemetry` command group on the root app in `cli/src/styrminctl/cli_commands.py` (and ensure the route is in the ineligible set from T016)

**Checkpoint**: US2 is independently shippable — a complete, inspectable, persistent opt-out.

---

## Phase 5: User Story 3 — Automation context excluded by default (Priority: P3)

**Goal**: Commands in CI / non-interactive contexts emit nothing without any configuration.

**Independent Test**: With `CI=true`, and separately with `stderr` redirected to a non-TTY, an eligible
command against a local sink emits zero requests.

### Tests for User Story 3

- [ ] T024 [P] [US3] Unit tests for the CI + non-TTY rungs of `should_emit` in `cli/tests/telemetry/test_eligibility.py`: `CI=true` (and other truthy values) yields no emit; `stderr.isatty()` false yields no emit; both restored ⇒ emit (FR-014)

### Implementation for User Story 3

- [ ] T025 [US3] Extend `should_emit()` in `cli/src/styrminctl/telemetry/eligibility.py` with the `CI` (unset/falsey) and `sys.stderr.isatty()` rungs and fold them into the `status` reason reporting (FR-014)

**Checkpoint**: All three stories complete — full FR-014/FR-015 eligibility ladder enforced.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T026 [US1] Write the E2E in `cli/tests/e2e/test_styrminctl_telemetry.py` marked `@pytest.mark.api_only(reason=...)`: spin up a real local HTTP sink, run the **real `styrminctl` subprocess** with `STYRMIN_TELEMETRY_ENDPOINT` pointed at it (NO vCluster fixture), and assert (a) exactly one well-formed envelope with a server-verifiable checksum, (b) no forbidden values with known-sensitive inputs, (c) ≤ 200 ms added latency + unchanged exit behaviour incl. hung endpoint, (d) zero requests under each opt-out lever (Constitution §V)
- [ ] T027 [US1] Run the E2E to a PASS locally and record the §V evidence (node id, exact pytest command, ISO-8601 timestamp, verbatim `PASSED` line) in the PR/summary
- [ ] T028 [P] Document telemetry in `cli/README.md`: exactly what is collected, the envelope shape, all opt-out levers (`STYRMIN_TELEMETRY`, `DO_NOT_TRACK`, `telemetry disable`, CI/non-TTY), and `STYRMIN_TELEMETRY_ENDPOINT` (Constitution §VII)
- [ ] T029 [P] Add a privacy note under `docs/` mirroring the README section (what is collected, why, how to opt out) (Constitution §VII)
- [ ] T030 [P] Update `CONTEXT.md`: add a **Telemetry** glossary entry and amend the **CLI / styrminctl** entry to note its first non-GraphQL outbound call
- [ ] T031 [P] Add an ADR under `dev/adr/` recording the external fire-and-forget telemetry call, its constraints (anonymous, best-effort, ≤200 ms, scrub-by-construction), and the default-on/opt-out stance
- [ ] T032 Run `uv run invoke format lint` and fix any findings; then run the full telemetry unit suite (`cd cli && uv run pytest tests/telemetry -v`) to green

---

## Dependencies & Execution Order

- **Setup (Phase 1)** → **Foundational (Phase 2)** → **User Stories (Phases 3–5)** → **Polish (Phase 6)**.
- **US1 (P1)** depends only on Foundational; it is the MVP and includes the baseline `should_emit`.
- **US2 (P2)** depends on Foundational (`TelemetryStore`) and US1's `eligibility.py` baseline (extends the same file).
- **US3 (P3)** extends US2's `eligibility.py` (sequential on that file).
- The E2E (T026/T027) depends on US1–US3 being wired (it exercises dispatch + opt-out levers end-to-end).

## Parallel Opportunities

- Phase 1: T002 and T003 run in parallel (different files); T001 first.
- Phase 2: T006 (tests) parallel with downstream once T005 exists.
- US1: all test tasks T007–T011 are `[P]` (distinct files); implementation T012–T014 touch distinct modules and can parallelize, while T016→T017→T018 are sequential (runtime depends on event/envelope/dispatch/eligibility; cli.py wiring last).
- US2 tests T019/T020 `[P]`; US3 test T024 `[P]`.
- Polish docs T028–T031 are all `[P]` (distinct files); T032 runs last.

## Implementation Strategy

Ship US1 first as the MVP (silent, scrubbed, failure-isolated dispatch for eligible interactive
commands). Layer US2 (opt-out + inspection) and US3 (CI/non-interactive exclusion) on top. Finish with
the mandatory E2E (run to PASS with recorded evidence), documentation, and `format lint`.
