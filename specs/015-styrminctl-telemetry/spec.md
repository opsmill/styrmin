# Feature Specification: Anonymous opt-out telemetry for `styrminctl`

**Feature Branch**: `015-styrminctl-telemetry`

**Created**: 2026-06-21

**Status**: Draft

**Input**: User description: "Anonymous opt-out telemetry for `styrminctl`" (PRD from https://github.com/opsmill/styrmin/issues/275#issuecomment-4762258122)

## Problem & Solution Overview

`styrminctl` collects no usage data today, so the maintainers make CLI roadmap and developer-experience decisions blind — they don't know which commands are used, which options are exercised, on which platforms, or where commands fail. Operators have no way to know what (if anything) the CLI would phone home, and no simple lever to turn it off.

This feature adds **anonymous, opt-out telemetry** to `styrminctl`: on by default on interactive workstations, silent in CI / non-interactive contexts. After each eligible command finishes, the CLI fire-and-forgets a single anonymous event — the command path, which option *names* were used, the outcome, and coarse environment facts — to a fixed public endpoint. There is no first-run prompt. Dispatch is best-effort and failure-isolated: it never changes a command's output, exit code, or perceptible speed, and it silently drops the event if the endpoint is slow or unreachable. Operators can opt out via an environment variable or a persisted `styrminctl telemetry` command, and the documentation describes exactly what is collected.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Telemetry rides along silently and is dropped on failure (Priority: P1)

An operator runs everyday commands on an interactive workstation. Each eligible invocation fire-and-forgets one anonymous, scrubbed event to the endpoint, adding no perceptible delay, and silently drops the event when the endpoint is slow or down.

**Why this priority**: This is the core value of the feature — without the silent, safe, scrubbed dispatch path there is no telemetry signal at all. It must never degrade the operator's experience, or the feature is unshippable.

**Independent Test**: Run a real command against a local sink with telemetry at defaults and assert exactly one well-formed, scrubbed envelope is received; then point at a hung/blackhole endpoint and assert the command's behaviour and timing are unchanged and nothing is printed.

**Acceptance Scenarios**:

1. **Given** an interactive operator with telemetry at defaults, **When** they run `styrminctl deployments update my-app --config @secrets.json -w` against a reachable endpoint, **Then** the command behaves exactly as today and one envelope is POSTed whose `data` is `{event_id, install_id, command:"deployments update", options:["--config","--wait"], outcome:"success", error_category:null, styrminctl_version, python_version, os_family}` — containing no deployment name, no config payload, and no file path.
2. **Given** the same command, **When** the endpoint hangs or is unreachable, **Then** the command's exit is delayed by no more than 200 ms versus telemetry-disabled, the event is dropped, and nothing is printed.
3. **Given** a command that raises an uncaught exception, **When** it fails, **Then** one event with `outcome:"failure"` is emitted and the original error and exit code reach the user unchanged.

---

### User Story 2 - Operator opts out and verifies (Priority: P2)

An operator disables telemetry once and confirms it stays off, with a clear way to inspect the current state and the reason for it.

**Why this priority**: Trust is a precondition for shipping opt-out telemetry. A reliable, persistent, inspectable opt-out is independently shippable and valuable on its own.

**Independent Test**: Run `styrminctl telemetry disable`, then `styrminctl telemetry status`, and assert it reports disabled; run a subsequent eligible command against a local sink and assert zero outbound requests. Repeat for each env-var lever.

**Acceptance Scenarios**:

1. **Given** any operator, **When** they run `styrminctl telemetry disable` (or set `STYRMIN_TELEMETRY=0` or `DO_NOT_TRACK=1`), **Then** `styrminctl telemetry status` reports disabled and no subsequent invocation emits any outbound request.
2. **Given** the persisted flag is `enabled`, **When** `STYRMIN_TELEMETRY=0` is set, **Then** the environment variable wins and no event is emitted.
3. **Given** any state, **When** the operator runs `styrminctl telemetry status`, **Then** it reports the effective state and the reason it is on or off.

---

### User Story 3 - Automation context is excluded by default (Priority: P3)

The same commands run in CI or non-interactive contexts emit nothing without anyone configuring it.

**Why this priority**: Prevents pipelines from emitting noise or leaking anything without an owner's involvement. Independently shippable and a safety guarantee in its own right.

**Independent Test**: Run an eligible command with `CI=true` set, and again with `stderr` redirected to a non-TTY, against a local sink; assert zero outbound requests in both cases.

**Acceptance Scenarios**:

1. **Given** a non-interactive context (`CI=true` or `stderr` is not a TTY), **When** any command runs, **Then** no telemetry request is emitted.

---

### Edge Cases

- **Endpoint refuses, hangs, DNS-fails, or host offline** → event dropped silently within the ≤ 200 ms budget; nothing printed.
- **Endpoint returns 4xx/5xx** → ignored silently; never surfaced to the user.
- **Telemetry data directory unwritable** (read-only home, locked-down image) → fall back to an ephemeral in-memory install ID, still best-effort, no error.
- **A command raises an uncaught exception** → emit `outcome:"failure"`, `error_category:"unknown"`, then re-raise unchanged (the real error and exit code are untouched).
- **The telemetry code itself raises** (build/checksum/dispatch bug) → swallowed; command behaviour unchanged.
- **Two concurrent invocations race to create `telemetry.json`** → atomic write; both get a valid identifier; last write wins (acceptable; the install ID is anonymous either way).
- **`STYRMIN_TELEMETRY=0` set while the persisted flag is `enabled`** → env wins; no event.
- **Ineligible commands** (`telemetry`, `version`, `--help`/`-h`, shell completion) → emit nothing.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST emit at most one telemetry event per eligible invocation, after the command outcome is known, via HTTPS POST to the telemetry endpoint.
- **FR-002**: Dispatch MUST be best-effort and loss-tolerant — no on-disk spool, no retry, no batching.
- **FR-003**: Telemetry MUST NOT delay command exit by more than 200 ms (p99) versus telemetry-disabled, for **all** endpoint states including a hung connection; the budget MUST be a single tunable constant.
- **FR-004**: Telemetry MUST be failure-isolated — it MUST NOT alter exit code, stdout, or stderr; any telemetry-internal error MUST be swallowed.
- **FR-005**: The POST body MUST be the shared envelope `{data, checksum, kind, payload_format}` with `kind = "styrminctl"` and `payload_format = "1.0"` (a string).
- **FR-006**: `checksum` MUST equal the SHA-256 hex digest of the CPython-default JSON serialization of `data` (separators `", "` / `": "`, insertion key order, no key sorting), so the server can recompute and verify it.
- **FR-007**: `data` MUST contain only these keys: `event_id`, `install_id`, `command`, `options`, `outcome`, `error_category`, `styrminctl_version`, `python_version`, `os_family`.
- **FR-008**: `data` MUST exclude server address, hostnames, usernames, tokens, deployment/cluster/environment names, argument and option **values**, file paths, and IPs.
- **FR-009**: `command` MUST be the resolved command-route token from a closed set (e.g. `"deployments update"`), derived from the dispatched route, never from raw process arguments.
- **FR-010**: `options` MUST be the canonical long-form names of explicitly-passed options, deduplicated and sorted, with positionals excluded and repeat-counts dropped.
- **FR-011**: `outcome` MUST be `"success"` or `"failure"`; `error_category` MUST be `null` on success and otherwise one of `auth | network | validation | not_found | server | usage | unknown`, bucketed by the typed-error class — never derived from a human-readable message.
- **FR-012**: `event_id` MUST be `<first 8 chars of install_id>` + `"-"` + `command` with spaces replaced by `_` (e.g. `a1b2c3d4-deployments_update`).
- **FR-013**: `install_id` MUST be a random anonymous identifier generated once and persisted; `styrminctl_version`, `python_version`, and `os_family` MUST be coarse (OS family only, e.g. `Linux` / `Darwin` / `Windows` — never kernel/version detail).
- **FR-014**: Telemetry MUST emit only if ALL of the following hold: the command is eligible **and** `STYRMIN_TELEMETRY` ≠ `0` **and** `DO_NOT_TRACK` ≠ `1` **and** the persisted flag is not `disabled` **and** `CI` is unset/falsey **and** `stderr` is a TTY.
- **FR-015**: The `telemetry`, `version`, `--help`/`-h`, and shell-completion commands MUST emit nothing.
- **FR-016**: Users MUST be able to run `styrminctl telemetry enable | disable | status`; `enable`/`disable` persist the flag and `status` reports the effective state and the reason it is on/off.
- **FR-017**: System MUST persist `{install_id, enabled}` as JSON at `${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/telemetry.json` with atomic writes and strict permissions (the existing token-store pattern); the install ID MUST persist even when telemetry is disabled; an unwritable directory MUST fall back to an ephemeral in-memory install ID without erroring.
- **FR-018**: The endpoint URL MUST default to the production telemetry endpoint and be overridable via `STYRMIN_TELEMETRY_ENDPOINT`.

### Key Entities

- **CLI / styrminctl** (existing): gains its first outbound call to a destination other than the Styrmin GraphQL API (anonymous telemetry). No change to deployment, cluster, environment, driver, or instance behaviour.
- **Telemetry event** *(new, ephemeral)*: the envelope plus the `data` object defined above; never persisted by the CLI, dispatched best-effort, owned by the CLI process for the duration of one invocation.
- **Telemetry state** *(new, persisted)*: `{install_id, enabled}` JSON stored next to the token store; owned by the operator's user account; lifecycle independent of credentials (survives `logout`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Command exit adds ≤ 200 ms (p99) versus telemetry-disabled across all endpoint states, including a hung endpoint.
- **SC-002**: Zero forbidden values appear in any emitted payload when commands are run with known-sensitive inputs (deployment names, file paths, tokens, addresses).
- **SC-003**: Exit code, stdout, and stderr are byte-identical with telemetry enabled vs disabled, on both success and failure paths.
- **SC-004**: Every opt-out / exclusion lever (env var, `DO_NOT_TRACK`, persisted disable, `CI`, non-TTY, ineligible command) independently yields zero outbound requests.
- **SC-005**: A server reproducing the CPython-default JSON serialization of `data` plus SHA-256 recomputes a checksum identical to the client's for a fixed payload vector (the format is verifiable end-to-end).

## Out of Scope

- On-disk spooling, retries, batching, sampling, or rate limiting.
- A first-run interactive consent prompt (explicitly none).
- The server side of the telemetry endpoint — ingestion, storage, dashboards, and endpoint configuration.
- Any backend GraphQL mutation or third-party analytics SDK.
- Telemetry from the SDK, backend, agent, or frontend (this is `styrminctl`-only).

## Assumptions

- The CLI payload format must match what the ingestion endpoint expects; this spec defines the client-side format authoritatively, and the endpoint is assumed to accept anonymous, unauthenticated POSTs of this envelope.
- The CLI's existing HTTP client dependency is reused for dispatch; no new dependency is introduced.
- Coarse roadmap signal is the goal — event loss and dropped repeat-counts are acceptable trade-offs for zero added latency.
- The server adds the ingestion timestamp and any geo/IP enrichment; the client never sends a timestamp or any network identifier.
- `payload_format` is the string `"1.0"` (the server treats it as an opaque string; resolved from the PRD open question).
- This is the first time `styrminctl` calls a destination other than the Styrmin GraphQL API; a `CONTEXT.md` glossary update and a short ADR recording the external fire-and-forget call are warranted.

## Dependencies

- Reuses the persisted token-store pattern (`specs/011-styrminctl-auth`) for `telemetry.json` (atomic write, strict permissions).
- Reuses the existing typed-error hierarchy for `error_category` bucketing (no new error classes).
