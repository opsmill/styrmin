# Contract: Telemetry settings, Helm values and startup log line

**Feature**: `020-backend-telemetry`

## Settings

A new settings group `TelemetrySettings` in `backend/styrmin_backend/config.py`, mounted as `Settings.telemetry` and exposed as `SETTINGS.telemetry` (research D7).

| Environment variable | Settings file key | Type | Default | Meaning |
|---|---|---|---|---|
| `STYRMIN_TELEMETRY_ENABLED` | `[telemetry] enabled` | boolean | `true` | `false` (also `0`, `no`, `off`) turns telemetry off. |
| `STYRMIN_TELEMETRY_ENDPOINT` | `[telemetry] endpoint` | URL string | `https://telemetry.opsmill.cloud/styrmin` | Destination of the daily report. A blank value means the default. |
| `DO_NOT_TRACK` | none | string | unset | `1`, `true`, `yes` or `on`, in any case, turns telemetry off. Any other value has no effect. `styrminctl` accepts only `1`. |
| `STYRMIN_TELEMETRY` | none | string | unset | The `styrminctl` opt-out. `0`, `false`, `no` or `off`, in any case, turns telemetry off. Any other value has no effect. `styrminctl` accepts only `0`. |

`STYRMIN_TELEMETRY_ENDPOINT` has the same name as the `styrminctl` override. The two are read by different processes: `styrminctl` on the operator's workstation, the server in its pod.

The settings loader reads no `STYRMIN_<GROUP>` variable, such as `STYRMIN_TELEMETRY` or `STYRMIN_AGENT`, as a whole settings group. Each group reads its own `STYRMIN_<GROUP>_*` variables. Before this change, `STYRMIN_TELEMETRY=0` stopped the server with "Input should be a valid dictionary or instance of TelemetrySettings" (the code review of 2026-10-10, finding 2).

`styrmin config show` prints `enabled = false` when `DO_NOT_TRACK` or `STYRMIN_TELEMETRY` turns telemetry off, and does not print these two variables.

### Effective state

The settings group exposes one read-only answer, used by the daily flow and the startup log line:

| Settings | Telemetry | Setting that turned it off |
|---|---|---|
| defaults | on | none |
| `STYRMIN_TELEMETRY_ENABLED=false` | off | `STYRMIN_TELEMETRY_ENABLED=false` |
| `STYRMIN_TELEMETRY=0` (or `false`, `no`, `off`) | off | `STYRMIN_TELEMETRY=<value>` |
| `DO_NOT_TRACK=1` (or `true`, `yes`, `on`) | off | `DO_NOT_TRACK=<value>` |
| more than one | off | the first in this order: `STYRMIN_TELEMETRY_ENABLED=false`, `STYRMIN_TELEMETRY`, `DO_NOT_TRACK` |

The settings must reach both the server, which logs the startup line, and the task worker, which runs the daily flow and decides whether to send. The Helm value and the ConfigMap do this. An operator who sets `DO_NOT_TRACK` or `STYRMIN_TELEMETRY_ENABLED` by other means must set it on both containers; otherwise the server can log "off" while the task worker sends (critique E4).

The daily flow reads the effective state when it runs, not when the server starts. A change of setting takes effect after the pods restart with the new environment, which is the case for every other setting.

## Helm values (`helm/styrmin/values.yaml`)

```yaml
styrmin:
  telemetry:
    # -- Send one anonymous report a day to OpsMill. Set to false to turn telemetry off.
    enabled: true
    # -- Destination of the daily report. Leave empty for the OpsMill endpoint.
    endpoint: ""
```

- `styrmin.telemetry.enabled` renders `STYRMIN_TELEMETRY_ENABLED` into the shared ConfigMap, which both the server and the task worker load with `envFrom` (FR-004).
- `styrmin.telemetry.endpoint` renders `STYRMIN_TELEMETRY_ENDPOINT` only when it is not empty (research D11). The E2E suite uses it to send reports to its local sink (FR-011).
- The templates read both values with `dig`, with the defaults `true` and `""`. A release installed from a chart without `styrmin.telemetry` and upgraded with `helm upgrade --reuse-values` has no `styrmin.telemetry` map; without `dig`, the render failed with `nil pointer evaluating interface {}.enabled` (the code review of 2026-10-10, finding 4).
- `styrmin.telemetry.enabled` accepts the values the server accepts: `true`, `1`, `t`, `y`, `yes`, `on`, `false`, `0`, `f`, `n`, `no`, `off`, in any case. A value set with `--set-string`, such as `"false"`, gives the same answer in the install notes and in the server. Any other value stops the render with `styrmin.telemetry.enabled must be true or false`.
- `DO_NOT_TRACK` has no Helm value. The chart has no field for other environment variables, so `styrmin.telemetry.enabled` is the Helm way to turn telemetry off.

## Startup log line (FR-010)

The server logs exactly one line at INFO level on every start, after the settings are loaded and before it accepts requests:

- Telemetry on:

  ```text
  Telemetry is on: Styrmin sends one anonymous report a day to <endpoint>. To view it, run 'styrmin telemetry show' in the server container. To turn telemetry off, set STYRMIN_TELEMETRY_ENABLED=false (Helm value styrmin.telemetry.enabled=false) or DO_NOT_TRACK=1.
  ```

- Telemetry off:

  ```text
  Telemetry is off (<setting that turned it off>).
  ```

  where `<setting that turned it off>` is `STYRMIN_TELEMETRY_ENABLED=false`, `STYRMIN_TELEMETRY=<value>` or `DO_NOT_TRACK=<value>`, as in the table above.

The line is logged by the server process only. The task worker and the CLI do not log it.

## Daily flow log line (FR-008)

Each run of the daily flow logs one line at INFO level that says whether the report was sent (the code review of 2026-10-10, finding 7):

| Outcome | Line |
|---|---|
| Telemetry is off | `Telemetry is off (<setting that turned it off>); no report sent` |
| The run started more than one hour late | `No telemetry report sent: the run scheduled at <time> started more than 1:00:00 late` |
| The endpoint accepted the report | `Telemetry report sent to <endpoint>` |
| The send failed | `Telemetry report not sent to <endpoint>: <error type or HTTP status>` |

When the report cannot be built, for example because the database cannot be reached, the run logs one warning, `Could not build the telemetry report: <error>`, instead.

## Development and test installs (FR-011)

| Where | Setting |
|---|---|
| E2E Helm install | `styrmin.telemetry.endpoint` points at the in-cluster sink (research D12) |
| `docker-compose.yml` | `STYRMIN_TELEMETRY_ENABLED: "false"` |
| `invoke dev` | starts `docker-compose.yml`, so the same setting applies |
| local demo (`dev/local/demo-values.yaml`) | `styrmin.telemetry.enabled: false` (research D18) |

`docker-compose.yml` sets the variable on both the `server` and the `task-worker` services, because the daily flow runs in the task worker.
