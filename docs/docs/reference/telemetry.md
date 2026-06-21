---
title: CLI telemetry & privacy
sidebar_position: 5
description: What anonymous data styrminctl collects, why, and how to turn it off.
---

## CLI telemetry & privacy

`styrminctl` collects **anonymous, opt-out** usage telemetry so the Styrmin
maintainers can see which commands and options are actually used, on which
platforms, and where they fail — and prioritise the CLI accordingly.

- **On by default** on interactive workstations.
- **Silent in CI / non-interactive contexts** — no configuration needed.
- **No first-run prompt and no banner.** This page is the disclosure.

Dispatch is **best-effort and failure-isolated**: after each eligible command
finishes, the CLI fire-and-forgets a single anonymous event over HTTPS and then
exits. It never changes a command's output, exit code, or perceptible speed, and
it silently drops the event if the endpoint is slow or unreachable. The added
latency is hard-capped at **≤ 200 ms** for any endpoint state, including a hung
connection. There is no on-disk spool, no retry, and no batching.

### What is collected

One JSON event per eligible invocation, with **only** these fields:

| Field | Example | Notes |
|-------|---------|-------|
| `event_id` | `a1b2c3d4-deployments_update` | `install_id[:8]` + `-` + command (spaces → `_`) |
| `install_id` | `a1b2c3d4e5f6…` | a random anonymous id, generated once and persisted |
| `command` | `deployments update` | the resolved command route, from a **closed set** |
| `options` | `["--config", "--wait"]` | canonical **long option names** only, deduplicated and sorted |
| `outcome` | `success` / `failure` | — |
| `error_category` | `network` | `null` on success, else one of `auth`, `network`, `validation`, `not_found`, `server`, `usage`, `unknown` — bucketed by the error **type**, never a message |
| `styrminctl_version` | `0.1.0` | — |
| `python_version` | `3.14.0` | — |
| `os_family` | `Linux` | OS family only (`Linux` / `Darwin` / `Windows`) — never kernel/version detail |

The event is wrapped in the envelope
`{"data": {…}, "checksum": "<sha256 hex of data>", "kind": "styrminctl", "payload_format": "1.0"}`.
The `checksum` is the SHA-256 of the serialised `data`, so the server can
recompute and verify the canonical serialisation of the data (HTTPS already
covers transport integrity). The client never sends a timestamp or any network
identifier — the server adds those.

### What is **never** collected

Scrubbed by construction — these never appear anywhere in the payload:

- Server addresses, hostnames, usernames, IPs.
- Tokens or any credentials.
- Deployment, cluster, or environment names.
- **Argument and option values** — only option *names* are recorded.
- File paths. Deriving option names never reads or converts a value, so a
  `@file` option value is never opened and file contents can never leak.

### Why

`styrminctl` previously collected nothing, leaving roadmap and
developer-experience decisions blind. Anonymous reach signal — *which* commands
installs use and *where* they fail — lets the maintainers invest where it
matters. The trade-off for zero added latency is that events may be lost and
repeat-counts are dropped; the signal measures per-install reach, not raw call
frequency.

### How to opt out

Any **one** of these stops all emission:

| Lever | Effect |
|-------|--------|
| `styrminctl telemetry disable` | Persists an opt-out (survives `logout`); `styrminctl telemetry enable` reverts it. |
| `STYRMIN_TELEMETRY=0` | Disables emission for the process (overrides the persisted flag). |
| `DO_NOT_TRACK=1` | Honours the [community standard](https://consoledonottrack.com/). |
| Running in CI (`CI` set/truthy) | Auto-excluded. |
| `stderr` is not a TTY (piped / non-interactive) | Auto-excluded. |

Inspect the effective state and the reason at any time:

```bash
styrminctl telemetry status
# Telemetry: enabled (default; interactive terminal).
# Telemetry: disabled (DO_NOT_TRACK=1).
# Telemetry: disabled (persisted opt-out via 'telemetry disable').
```

The `telemetry` command group, `--version` / `version`, `--help` / `-h`, and the
shell-completion command never emit anything themselves.

### Endpoint and state

Telemetry POSTs to a fixed production endpoint by default; set
`STYRMIN_TELEMETRY_ENDPOINT=<url>` to redirect it (used by the test suite and a
local sink). State is `{install_id, enabled}` stored as JSON at
`${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/telemetry.json`, written
atomically with strict permissions (`0600` file, `0700` directory). The
`install_id` persists even when telemetry is disabled; an unwritable directory
falls back to an ephemeral in-memory id and never errors.
