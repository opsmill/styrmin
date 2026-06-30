# Phase 1 Data Model: Anonymous opt-out telemetry for `styrminctl`

**Feature**: `015-styrminctl-telemetry` | **Date**: 2026-06-21

Two persisted/structured shapes and one transient wire shape. No database, no GraphQL schema.

## Entity: Telemetry state (persisted)

On-disk JSON at `${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/telemetry.json`.

| Field | Type | Rules |
|---|---|---|
| `install_id` | string | Random anonymous id (uuid4 hex). Generated once, lazily, on first access. Persists even when telemetry is disabled. |
| `enabled` | boolean | The persisted opt-in/out flag. Absent file ⇒ treated as enabled (default-on). |

- **Persistence**: atomic temp-file write (`O_CREAT|O_EXCL|O_WRONLY`, mode `0o600`) + `chmod` +
  `rename`; parent dir `0o700`. Mirrors `TokenStore`.
- **Unwritable directory**: fall back to an ephemeral in-memory `install_id`; never raise.
- **Concurrency**: last-write-wins; both racers get a valid uuid4 (anonymous either way).
- **Lifecycle**: independent of credentials — survives `logout`.

## Entity: Telemetry event `data` (transient, the scrubbed payload)

Built per eligible invocation, after the outcome is known. **Closed key set** in this exact insertion
order (order is load-bearing for the checksum):

| Key | Type | Rules |
|---|---|---|
| `event_id` | string | `<install_id[:8]>` + `"-"` + `command.replace(" ", "_")`. e.g. `a1b2c3d4-deployments_update`. |
| `install_id` | string | From telemetry state. |
| `command` | string | Resolved command-route token from the closed set (e.g. `"deployments update"`), via `parse_commands`. |
| `options` | string[] | Canonical long-form names of explicitly-passed options, deduplicated and sorted; positionals & repeat-counts excluded; **no values**. e.g. `["--config","--wait"]`. |
| `outcome` | string | `"success"` or `"failure"`. |
| `error_category` | string \| null | `null` on success; else one of `auth\|network\|validation\|not_found\|server\|usage\|unknown` (type-bucketed). |
| `styrminctl_version` | string | `importlib.metadata.version("cli")`. |
| `python_version` | string | `platform.python_version()` (e.g. `3.14.0`). |
| `os_family` | string | `platform.system()` ∈ {`Linux`,`Darwin`,`Windows`} — coarse, never kernel/version. |

- **Forbidden anywhere in `data`** (FR-008, SC-002): server address, hostnames, usernames, tokens,
  deployment/cluster/environment names, argument and option **values**, file paths, IPs.
- **Never persisted** by the CLI; lives only for one invocation.

## Entity: Telemetry envelope (transient, the POST body)

| Key | Type | Value |
|---|---|---|
| `data` | object | The `data` object above. |
| `checksum` | string | `sha256(json.dumps(data)).hexdigest()` — CPython defaults, insertion order, no `sort_keys`. |
| `kind` | string | Constant `"styrminctl"`. |
| `payload_format` | string | Constant `"1.0"`. |

## Configuration inputs (read, not stored)

| Input | Source | Effect |
|---|---|---|
| `STYRMIN_TELEMETRY` | env | `0` ⇒ disabled (overrides persisted flag). |
| `DO_NOT_TRACK` | env | `1` ⇒ disabled. |
| `STYRMIN_TELEMETRY_ENDPOINT` | env | Overrides the default production endpoint URL. |
| `CI` | env | Truthy ⇒ disabled (non-interactive). |
| `stderr.isatty()` | runtime | False ⇒ disabled (non-interactive). |
| persisted `enabled` | `telemetry.json` | `false` ⇒ disabled. |

**Precedence** (FR-014): emit iff *all* of — eligible command ∧ `STYRMIN_TELEMETRY≠0` ∧
`DO_NOT_TRACK≠1` ∧ persisted flag not disabled ∧ `CI` falsey ∧ `stderr` is a TTY. Env opt-out beats a
persisted `enabled`.

## State transitions (telemetry `enabled`)

```
absent file ──(first eligible run)──> {install_id, enabled:true}   (default-on)
enabled ──`telemetry disable`/persist──> disabled
disabled ──`telemetry enable`/persist──> enabled
(env STYRMIN_TELEMETRY=0 / DO_NOT_TRACK=1 / CI / non-TTY): effective=disabled for that run only;
    persisted flag unchanged.
```
