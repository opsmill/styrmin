# Contract: Telemetry settings, Helm values and startup log line

**Feature**: `020-backend-telemetry`

## Settings

A new settings group `TelemetrySettings` in `backend/styrmin_backend/config.py`, mounted as `Settings.telemetry` and exposed as `SETTINGS.telemetry` (research D7).

| Environment variable | Settings file key | Type | Default | Meaning |
|---|---|---|---|---|
| `STYRMIN_TELEMETRY_ENABLED` | `[telemetry] enabled` | boolean | `true` | `false` (also `0`, `no`, `off`) turns telemetry off. |
| `STYRMIN_TELEMETRY_ENDPOINT` | `[telemetry] endpoint` | URL string | `https://telemetry-endpoints.cloudflare-096.workers.dev/styrmin` | Destination of the daily report. A blank value means the default. |
| `DO_NOT_TRACK` | none | string | unset | Exactly `1` turns telemetry off, as in `styrminctl`. Any other value has no effect. |

`STYRMIN_TELEMETRY_ENDPOINT` has the same name as the `styrminctl` override. The two are read by different processes: `styrminctl` on the operator's workstation, the server in its pod.

### Effective state

The settings group exposes one read-only answer, used by the daily flow and the startup log line:

| Settings | Telemetry | Setting that turned it off |
|---|---|---|
| defaults | on | none |
| `STYRMIN_TELEMETRY_ENABLED=false` | off | `STYRMIN_TELEMETRY_ENABLED=false` |
| `DO_NOT_TRACK=1` | off | `DO_NOT_TRACK=1` |
| both | off | `STYRMIN_TELEMETRY_ENABLED=false` (checked first) |

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
- `DO_NOT_TRACK` has no Helm value. The chart has no field for other environment variables, so `styrmin.telemetry.enabled` is the Helm way to turn telemetry off.

## Startup log line (FR-010)

The server logs exactly one line at INFO level on every start, after the settings are loaded and before it accepts requests:

- Telemetry on:

  ```text
  Telemetry is on: Styrmin sends one anonymous report a day to <endpoint>. To view it, run 'styrmin telemetry show'. To turn telemetry off, set STYRMIN_TELEMETRY_ENABLED=false (Helm value styrmin.telemetry.enabled=false) or DO_NOT_TRACK=1.
  ```

- Telemetry off:

  ```text
  Telemetry is off (<setting that turned it off>).
  ```

  where `<setting that turned it off>` is `STYRMIN_TELEMETRY_ENABLED=false` or `DO_NOT_TRACK=1`, as in the table above.

The line is logged by the server process only. The task worker and the CLI do not log it.

## Development and test installs (FR-011)

| Where | Setting |
|---|---|
| E2E Helm install | `styrmin.telemetry.endpoint` points at the in-cluster sink (research D12) |
| `docker-compose.yml` | `STYRMIN_TELEMETRY_ENABLED: "false"` |
| `invoke dev` | starts `docker-compose.yml`, so the same setting applies |
| local demo (`dev/local/demo-values.yaml`) | `styrmin.telemetry.enabled: false` (research D18) |

`docker-compose.yml` sets the variable on both the `server` and the `task-worker` services, because the daily flow runs in the task worker.
