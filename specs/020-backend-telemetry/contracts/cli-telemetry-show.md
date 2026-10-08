# Contract: `styrmin telemetry show`

**Feature**: `020-backend-telemetry`

A new command group `telemetry` in the server management CLI `styrmin` (`backend/styrmin_backend/cli/`), with one command, `show`. Operators run it inside the server pod, for example `kubectl exec deploy/<release>-styrmin-server -- styrmin telemetry show`. It is not a `styrminctl` command and it does not use the GraphQL API (spec "Out of Scope").

## Synopsis

```text
styrmin telemetry show [--config-file PATH]
```

- `--config-file`: path to the settings file, with the same meaning as in `styrmin db migrate`. When omitted, the command loads the settings the same way the server does (`STYRMIN_CONFIG`, then `styrmin.toml`, then environment variables).

## Behaviour

- Reads the install ID and the counts from the database configured in the settings, through the same payload builder the daily flow uses (research D2), and prints the `data` object of the next report.
- Creates the install ID when the database has none yet, in the same way as a server start (FR-014). This is the only write.
- Sends nothing. The command never calls the telemetry sender, whatever the settings say (FR-013).
- Works whether telemetry is on or off (spec User Story 3, scenario 3).

## Output

- Standard output: the `data` object only, as JSON with 2-space indentation and the key order of the [wire format](telemetry-report-wire-format.md). No envelope, no checksum, no other text, so the output parses with `json.loads` and compares equal to the `data` the endpoint receives when the database did not change in between.
- Standard error: nothing on success.
- Exit code `0` on success.

## Errors

- The settings are not valid: the validation errors are printed and the exit code is `1`, as for `styrmin db` commands.
- The database cannot be reached or the query fails: one line `Could not read the telemetry report: <error>` on standard error, exit code `1`. The command does not retry.
