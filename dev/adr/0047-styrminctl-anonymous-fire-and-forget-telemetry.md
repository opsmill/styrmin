# ADR-047: Anonymous fire-and-forget telemetry from `styrminctl`

**Status**: Accepted
**Date**: 2026-06-21
**Source**: feature — `specs/015-styrminctl-telemetry/` (PRD: opsmill/styrmin#275)

## Context

`styrminctl` collected no usage data, so the maintainers made CLI roadmap and
developer-experience decisions blind: they did not know which commands are run,
which options are exercised, on which platforms, or where commands fail.

Adding telemetry to a CLI carries three standing risks that any design has to
neutralise before it is acceptable: (1) it must never degrade the operator's
experience — output, exit code, or perceptible speed; (2) it must never leak
anything sensitive (names, paths, values, tokens, addresses); and (3) operators
must be able to turn it off trivially and verifiably. This is also the **first
time `styrminctl` makes an outbound call to a destination other than the Styrmin
GraphQL API** — until now the CLI was a pure thin client over `/graphql`, so a
new egress to a public ingestion endpoint is a notable change in the CLI's
network posture and warrants a recorded decision.

## Decision

Add **anonymous, opt-out, fire-and-forget** telemetry, entirely in the CLI layer
(no GraphQL, no DB, no new package — `httpx` was already transitive). After each
*eligible* invocation, once the outcome is known, the CLI POSTs a single scrubbed
event to a fixed public endpoint and exits.

The decision rests on five hard constraints, each enforced by construction:

- **Anonymous.** `data` is a closed key set — `event_id`, `install_id`,
  `command`, `options`, `outcome`, `error_category`, `styrminctl_version`,
  `python_version`, `os_family`. `install_id` is a random uuid4 generated once;
  `command` comes from Cyclopts `parse_commands` (a closed route set, never raw
  `sys.argv`); `options` are canonical long *names* only; `error_category` is
  bucketed by the existing typed-error **class**, never a message; `os_family`
  is the OS family only. No server address, hostname, username, token, resource
  name, **argument/option value**, file path, or IP is ever included.
- **Scrub-by-construction, not scrub-by-filter.** Option-name extraction is a
  token-scan plus Cyclopts parameter metadata — it never triggers value
  conversion, so a `@file` option value is never opened and file contents can
  never reach the telemetry path. There is no allow/deny list to keep in sync
  and no value that has to be redacted after the fact.
- **Best-effort.** No on-disk spool, no retry, no batching. Event loss and
  dropped repeat-counts are accepted — the signal measures per-install *reach*,
  not call frequency.
- **≤ 200 ms, hard cap, all endpoint states.** Dispatch runs a synchronous
  `httpx` POST on a **daemon thread**; the main thread `join`s it with a single
  tunable budget constant (`TELEMETRY_BUDGET_MS = 200`) and, on timeout, returns
  and abandons the daemon. A daemon thread never blocks interpreter exit, so a
  hung or black-holed endpoint adds at most the budget — a per-phase HTTP
  timeout alone could not guarantee this (a stalled TCP connect can exceed it).
  The worker's body is wrapped in `try/except BaseException` so a dying/abandoned
  worker can never print `Exception ignored in thread …` at teardown, which would
  break the byte-identical-output guarantee.
- **Default-on, opt-out, no prompt.** Telemetry is on by default on interactive
  workstations and **silent** — no first-run prompt, no banner. Trust is provided
  instead by (a) a one-step persistent opt-out (`telemetry disable`) plus
  `STYRMIN_TELEMETRY=0` and `DO_NOT_TRACK=1`, (b) automatic exclusion of CI and
  non-TTY contexts, and (c) explicit documentation (`cli/README.md` and a `docs/`
  privacy note describing exactly what is collected).

The wrapper that observes the outcome lives at the single chokepoint
`_AuthBoundaryApp.__call__` (`cli/src/styrminctl/cli.py`): it runs the inner app
inside `try/except/finally`, classifies the outcome (including the auth
boundary's `SystemExit`), dispatches at most one event, and **re-raises the
original exception unchanged**. The entire telemetry path is wrapped so any
internal telemetry error is swallowed — exit code, stdout, and stderr stay
byte-identical to a telemetry-disabled run.

## Consequences

- **First non-GraphQL egress.** `styrminctl` now talks to a second destination.
  Recorded here and in `CONTEXT.md` (Telemetry glossary entry; amended CLI
  entry). The endpoint defaults to the production ingestion URL and is
  overridable via `STYRMIN_TELEMETRY_ENDPOINT` (used by the E2E's local sink).
- **Failure isolation is a tested guarantee, not a hope.** The unit suite
  asserts byte-identical output with telemetry on vs off and **zero stderr
  bytes** with an in-flight/hung dispatch at teardown; the `api_only` E2E
  (`cli/tests/e2e/test_styrminctl_telemetry.py`) runs the real CLI subprocess
  against a real local HTTP sink and asserts one well-formed checksum-verifiable
  envelope, no forbidden values, the ≤ 200 ms / unchanged-exit behaviour against
  a hung endpoint, and zero requests under each opt-out lever.
- **Reach, not frequency.** Server-side de-duplication on
  `event_id = (install_id[:8], command)` plus best-effort loss means the signal
  is "how many installs used command X", not raw invocation counts. This is the
  intended trade-off for zero added latency.
- **No new error classes.** `error_category` reuses the existing typed-error
  hierarchy (`python_sdk` exceptions + `styrminctl.errors`), keeping Constitution
  §IV intact.
- **Server side is out of scope.** Ingestion, storage, dashboards, and endpoint
  provisioning are not part of this decision; the CLI defines the wire format
  authoritatively (`contracts/telemetry-wire-format.md`) and assumes the endpoint
  accepts anonymous unauthenticated POSTs.

## Alternatives Considered

- **First-run consent prompt / banner.** Rejected: a prompt on a thin
  automation-adjacent CLI is hostile to scripted use and the opt-out pattern
  (with `DO_NOT_TRACK`, CI exclusion, and documentation) is the established norm
  for comparable developer tools. The silent-plus-documented stance is a
  deliberate product choice.
- **Synchronous POST with only a per-phase HTTP timeout.** Rejected: a hanging
  TCP connect can exceed the budget, and a slow endpoint would still delay exit.
  The daemon-thread + bounded-join gives a hard wall-clock cap for every endpoint
  state.
- **Async/background spool with retry or batching.** Rejected: contradicts the
  best-effort / zero-latency goal, adds on-disk state and a flush lifecycle, and
  is unnecessary for a coarse reach signal.
- **Scrub-by-filter (collect rich data, redact sensitive fields before send).**
  Rejected: any denylist rots and a single miss leaks. A closed key set built
  from route + option *names* only cannot carry a value in the first place.
- **Opt-in telemetry.** Rejected: opt-in yields a heavily biased, near-empty
  sample that does not support roadmap decisions; the privacy risk is already
  driven to ~zero by the scrub-by-construction design, so opt-out is acceptable.
