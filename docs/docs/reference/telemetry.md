---
title: Telemetry & privacy
sidebar_position: 5
description: What anonymous data the styrminctl CLI and the Styrmin server send to OpsMill, why, and how to turn each one off.
---

## Telemetry & privacy

Styrmin sends anonymous telemetry from two places. Each one has its own
settings, read by a different process, and its own endpoint:

| | [CLI telemetry](#cli-telemetry) | [Server telemetry](#server-telemetry) |
|---|---|---|
| Sent by | `styrminctl`, on your workstation | The task worker of the Styrmin server, in your cluster |
| What is sent | One event after each eligible command | One report a day about the install |
| Endpoint | `https://telemetry-endpoints.cloudflare-096.workers.dev/styrminctl` | `https://telemetry.opsmill.cloud/styrmin` |
| Setting that turns only this one off | `styrminctl telemetry disable` | Helm value `styrmin.telemetry.enabled: false` |

To turn telemetry off:

- On your workstation, run `styrminctl telemetry disable`, or set
  `DO_NOT_TRACK=1` or `STYRMIN_TELEMETRY=0`.
- In your cluster, set the Helm value `styrmin.telemetry.enabled: false`. See
  [Turning server telemetry off](#turning-server-telemetry-off) for the other
  settings.

Turning one off does not turn the other off. `DO_NOT_TRACK=1` and
`STYRMIN_TELEMETRY=0` turn off either one, but only in the environment where
they are set.

### CLI telemetry

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

#### What is collected

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

#### What is **never** collected

Scrubbed by construction — these never appear anywhere in the payload:

- Server addresses, hostnames, usernames, IPs.
- Tokens or any credentials.
- Deployment, cluster, or environment names.
- **Argument and option values** — only option *names* are recorded.
- File paths. Deriving option names never reads or converts a value, so a
  `@file` option value is never opened and file contents can never leak.

#### Why

`styrminctl` previously collected nothing, leaving roadmap and
developer-experience decisions blind. Anonymous reach signal — *which* commands
installs use and *where* they fail — lets the maintainers invest where it
matters. The trade-off for zero added latency is that events may be lost and
repeat-counts are dropped; the signal measures per-install reach, not raw call
frequency.

#### How to opt out

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

#### Endpoint and state

Telemetry POSTs to
`https://telemetry-endpoints.cloudflare-096.workers.dev/styrminctl` by default;
set `STYRMIN_TELEMETRY_ENDPOINT=<url>` to redirect it (used by the test suite and a
local sink). State is `{install_id, enabled}` stored as JSON at
`${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/telemetry.json`, written
atomically with strict permissions (`0600` file, `0700` directory). The
`install_id` persists even when telemetry is disabled; an unwritable directory
falls back to an ephemeral in-memory id and never errors.

### Server telemetry

The Styrmin server sends one anonymous report a day to an OpsMill endpoint.
OpsMill maintainers use the reports to count how many installs run each Styrmin
version, and how many installs use each application driver and driver version.
Without these counts, decisions about how long to support a Styrmin version and
which drivers to work on are made without data.

Telemetry is on by default. It sends nothing about your applications other than
the counts and driver names listed below.

#### Keys in the daily report

The report data contains these keys, in this order, and no others:

| Key | Example | Meaning |
|-----|---------|---------|
| `install_id` | `0b6f4f0e-6d0e-4a55-9a51-2f8c3f7c9f0d` | A random ID for the install. See [Install ID](#install-id). |
| `styrmin_version` | `0.1.47` | The Styrmin release version, or `unknown` when the server cannot read it. |
| `python_version` | `3.14.0` | The Python version that Styrmin runs on. |
| `os_family` | `Linux` | The operating system family. |
| `arch` | `x86_64` | The processor architecture, for example `x86_64` or `aarch64`. |
| `cluster_count` | `1` | The number of clusters. |
| `environment_count` | `3` | The number of environments. |
| `deployment_count` | `5` | The number of deployments that are not deleted (tombstoned). It includes the deployments that Styrmin creates itself, such as the ingress controller of an environment. |
| `drivers` | see below | One entry for each loaded application driver version, including versions that no deployment uses. |

Each entry in `drivers` contains these keys, and no others:

| Key | Example | Meaning |
|-----|---------|---------|
| `name` | `infrahub` | The application driver name, exactly as it is written in the driver. |
| `version` | `1.2.0` | The driver version. |
| `source_type` | `git` | Where the driver version was loaded from: `git`, `local`, or `internal` for the ingress controller driver that Styrmin includes. |
| `deployment_count` | `2` | The number of deployments that use this driver version and are not deleted. `0` when no deployment uses it. |

Driver versions that have the same name, version and source type, and were
loaded from different repositories, branches or paths, are reported as one entry
with their deployment counts added. The entries are sorted by name, version and
source type.

The report data is sent inside the same envelope as the CLI events, with
`kind: "styrmin"`. A complete report looks like this:

```json
{
  "data": {
    "install_id": "0b6f4f0e-6d0e-4a55-9a51-2f8c3f7c9f0d",
    "styrmin_version": "0.1.47",
    "python_version": "3.14.0",
    "os_family": "Linux",
    "arch": "x86_64",
    "cluster_count": 1,
    "environment_count": 3,
    "deployment_count": 5,
    "drivers": [
      {"name": "infrahub", "version": "1.2.0", "source_type": "git", "deployment_count": 2},
      {"name": "semaphore", "version": "0.4.1", "source_type": "local", "deployment_count": 0},
      {"name": "styrmin-ingress-controller", "version": "1.0.0", "source_type": "internal", "deployment_count": 3}
    ]
  },
  "checksum": "<SHA-256 hex digest of the serialised data>",
  "kind": "styrmin",
  "payload_format": "1.0"
}
```

#### Driver names can identify your organisation

Driver names are sent exactly as they are written, because the reports must
show which drivers installs use. If you write your own drivers and their names
contain the name of your organisation, for example `acme-billing`, the report
can identify your organisation to OpsMill. If that is not acceptable, turn
telemetry off.

#### Data the server never sends

The report never contains:

- the source repository URL, branch or path of a driver
- the provenance fingerprint of a driver version (its content hash or Git
  commit)
- the names of clusters, environments or deployments
- host names, IP addresses or user names
- tokens, passwords or other credentials
- configuration values or parameters

The endpoint receives the public IP address that the request comes from, as any
HTTP server does. Styrmin does not add it to the report. The report has no
timestamp; the endpoint records when it received the report.

#### When the server sends the report

- The task worker runs the Prefect flow `send_telemetry_report` once a day at
  02:43 UTC. The first report is sent at the first 02:43 UTC after the server
  starts for the first time.
- Each run sends one request, with no retry. A report that the endpoint does not
  receive is lost.
- When the task worker is down at 02:43 UTC, or the run starts more than one
  hour late, no report is sent that day. A missed report is not sent later.
- Server restarts and extra server or task worker replicas do not cause extra
  reports, because Prefect creates one scheduled run a day and gives it to one
  worker.
- A send attempt stops after 10 seconds. When the endpoint cannot be reached,
  does not answer or returns an error status, the flow run ends `Completed`. An
  install without internet access therefore has no failed flow runs and no
  warnings from telemetry.
- When the report cannot be built, for example because the database cannot be
  reached, the flow logs one warning,
  `Could not build the telemetry report: <error>`, and the flow run ends
  `Completed`.

#### Checking whether telemetry is on

On every start, the server logs one line at INFO level. With telemetry on and
the default endpoint, the line is:

```text
Telemetry is on: Styrmin sends one anonymous report a day to https://telemetry.opsmill.cloud/styrmin. To view it, run 'styrmin telemetry show' in the server container. To turn telemetry off, set STYRMIN_TELEMETRY_ENABLED=false (Helm value styrmin.telemetry.enabled=false) or DO_NOT_TRACK=1.
```

With telemetry off, the line names the setting that turned it off, for example
`Telemetry is off (DO_NOT_TRACK=1).` The install notes that `helm install` and
`helm upgrade` print also say whether telemetry is on.

Each run of the `send_telemetry_report` flow logs one line at INFO level that
says whether the report was sent. You can read it in the logs of the flow run in
the Prefect UI:

| Outcome | Line |
|---|---|
| Telemetry is off | `Telemetry is off (DO_NOT_TRACK=1); no report sent` |
| The report was sent | `Telemetry report sent to https://telemetry.opsmill.cloud/styrmin` |
| The endpoint was not reached or returned an error | `Telemetry report not sent to https://telemetry.opsmill.cloud/styrmin: ConnectError` |
| The run started more than one hour late | `No telemetry report sent: the run scheduled at <time> started more than 1:00:00 late` |

#### Turning server telemetry off

Any one of these settings turns server telemetry off:

- The Helm value `styrmin.telemetry.enabled: false`:

  ```yaml
  styrmin:
    telemetry:
      enabled: false
  ```

- The environment variable `STYRMIN_TELEMETRY_ENABLED=false`. The values `0`,
  `no` and `off` also turn telemetry off.
- The environment variable `DO_NOT_TRACK=1`. The values `true`, `yes` and `on`
  also turn server telemetry off; other values, such as `0`, have no effect.
  `styrminctl` accepts only `1`.
- The environment variable `STYRMIN_TELEMETRY=0`, which also turns off
  `styrminctl` telemetry. The values `false`, `no` and `off` also turn server
  telemetry off; other values have no effect. `styrminctl` accepts only `0`.
- `enabled = false` in the `[telemetry]` section of the Styrmin settings file
  (`styrmin.toml`).

`styrmin config show` prints `enabled = false` in the `[telemetry]` section when
any of these settings turns telemetry off.

The Helm value `styrmin.telemetry.enabled` accepts `true` and `false`, and the
other values that the server accepts, such as `"false"` set with
`--set-string`. Any other value stops `helm install` and `helm upgrade` with an
error. An upgrade with `--reuse-values` from a chart version that has no
`styrmin.telemetry` values keeps telemetry on.

The setting must reach two processes: the server, which logs whether telemetry
is on, and the task worker, which runs the daily flow and decides whether to
send the report. The Helm value does this: it sets `STYRMIN_TELEMETRY_ENABLED`
in the ConfigMap that the server and the task worker both load, and a
`helm upgrade` that changes the value restarts both. If you set
`STYRMIN_TELEMETRY_ENABLED`, `DO_NOT_TRACK` or `STYRMIN_TELEMETRY` by other
means, set it on both containers. Otherwise the server can log that telemetry is
off while the task worker still sends reports. To check that a report is no
longer sent, read the INFO line of the next `send_telemetry_report` flow run.

The Helm value `styrmin.workflow.enable` does not stop the reports. Use one of
the settings above.

The development installs in the Styrmin repository send no reports:
`docker-compose.yml` and the local demo values (`dev/local/demo-values.yaml`)
turn telemetry off.

#### Viewing the report with `styrmin telemetry show`

Run `styrmin telemetry show` in the server container to print the data of the
next report. Outside the server container, the command does not find the
Styrmin database:

```shell
kubectl exec --namespace styrmin deploy/styrmin-server -c styrmin-server -- styrmin telemetry show
```

The namespace and the Deployment name depend on your Helm release. The install
notes print the command for your release.

The command:

- prints the `data` object as JSON, without the envelope, to standard output,
  so it is the same as the data the endpoint receives when nothing in the
  install changes in between
- prints one line to standard error that says whether telemetry is on in the
  settings of the server container, and to which endpoint the task worker sends
  the report, for example
  `Telemetry is on in this container. With the same settings, the task worker sends this report once a day to https://telemetry.opsmill.cloud/styrmin.`
  The task worker reads its own settings; the Helm chart gives both containers
  the same settings.
- sends nothing, whether telemetry is on or off, so you can check the report
  before you turn telemetry on
- creates the install ID when the database has none yet, which is the only
  change it makes
- prints
  `Could not read the telemetry report: <error>. Check that you run this command in the server container.`
  to standard error and exits with code `1` when it cannot read the database

#### Endpoint and proxy

The server sends the report as an HTTPS `POST` request with a JSON body, without
authentication headers or cookies, to
`https://telemetry.opsmill.cloud/styrmin`.

To send the report to another address, for example to your own relay, set the
Helm value `styrmin.telemetry.endpoint` or the environment variable
`STYRMIN_TELEMETRY_ENDPOINT`. An empty value means the default endpoint. The CLI
reads a variable with the same name; the two are read by different processes,
the CLI on your workstation and the task worker in your cluster.

The task worker uses the standard proxy environment variables: when
`HTTPS_PROXY` is set, the request to an `https://` endpoint goes through that
proxy, and `NO_PROXY` lists the hosts that bypass it. The Helm chart has no
value for these variables, so add them to the task worker container by other
means.

#### Install ID

The install ID lets OpsMill count distinct installs without knowing who they
are. One install is one Styrmin database:

- The server creates a random UUID the first time it starts with a database, and
  stores it in that database. It creates the ID whether telemetry is on or off,
  so the ID does not change when you turn telemetry on later.
- Restarts, upgrades and extra server replicas keep the same install ID, because
  they use the same database.
- When you restore a dump of the database into a second install, both installs
  report the same install ID.
- When you rebuild the database from scratch, the install reports a new install
  ID, and OpsMill counts it as a new install.

The server install ID is not linked to the install ID of `styrminctl`, which is
stored on your workstation.
