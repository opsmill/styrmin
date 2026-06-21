# Contract: `styrminctl telemetry` command group

**Feature**: `015-styrminctl-telemetry`

A new Cyclopts command group registered on the root app. The group itself is **ineligible** for
telemetry emission (FR-015).

## `styrminctl telemetry status`

- **Exit code**: `0`.
- **Output (stdout)**: the effective state and the reason it is on/off. Examples:
  - `Telemetry: enabled (default; interactive terminal).`
  - `Telemetry: disabled (STYRMIN_TELEMETRY=0).`
  - `Telemetry: disabled (persisted opt-out via 'telemetry disable').`
  - `Telemetry: disabled (DO_NOT_TRACK=1).`
  - `Telemetry: disabled (non-interactive: CI detected).`
  - `Telemetry: disabled (non-interactive: stderr is not a TTY).`
- **Reason precedence**: report the first failing rung in FR-014 order (eligibility is N/A here since
  `status` is itself ineligible — it reports the state that *would* apply to eligible commands).
- **Side effects**: none beyond a lazy `install_id` read (does not flip `enabled`).

## `styrminctl telemetry disable`

- Persists `enabled = false` to `telemetry.json` (atomic write, strict perms; creates the file and a
  lazy `install_id` if absent).
- **Exit code**: `0`. **Output**: confirmation, e.g. `Telemetry disabled.`
- Idempotent: disabling when already disabled succeeds and changes nothing observable.

## `styrminctl telemetry enable`

- Persists `enabled = true` to `telemetry.json`.
- **Exit code**: `0`. **Output**: confirmation, e.g. `Telemetry enabled.`
- Note: env opt-outs (`STYRMIN_TELEMETRY=0`, `DO_NOT_TRACK=1`) still suppress emission at runtime even
  after `enable`; `status` reflects that.

## Environment variables (documented in `cli/README.md`)

| Variable | Effect |
|---|---|
| `STYRMIN_TELEMETRY=0` | Disable emission (overrides persisted `enabled`). |
| `DO_NOT_TRACK=1` | Disable emission (honours the community standard). |
| `STYRMIN_TELEMETRY_ENDPOINT=<url>` | Override the destination endpoint (used by tests/local sink). |

## Error handling

- An unwritable telemetry directory MUST NOT make `enable`/`disable`/`status` crash: the command still
  succeeds, using an ephemeral in-memory install ID, and `status` may note the persistence fallback.
