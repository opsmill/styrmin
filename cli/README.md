# `styrminctl`

The command-line interface for [Styrmin](../README.md). A thin client over
the Styrmin GraphQL API: every operator-facing action (deploy, list,
authenticate, etc.) is implemented as a wrapper around the
[`styrmin-sdk`](../python_sdk/).

## Install

`styrminctl` is part of the workspace and is installed by `uv sync` at the
repo root. After that:

```bash
uv run styrminctl --help
```

## Managing deployments

`styrminctl deployments update <deployment-id> --config '<json>'` takes a JSON
`UpdateDeploymentInput` payload (inline or `@filepath`; snake_case or camelCase
keys accepted). Because the payload is the full typed input, per-component
container `command` / `args` overrides
(014-component-container-overrides) ride through with no extra flags — set them
under `components`:

```bash
uv run styrminctl deployments update <deployment-id> --config '{
  "components": [
    {
      "name": "server",
      "command": ["uvicorn", "simple_app.main:app"],
      "args": ["--host", "0.0.0.0", "--port", "8000", "--log-level", "debug"]
    }
  ]
}'
```

`command`/`args` are independent, optional lists. Under full-replacement
semantics, omitting a field from a component block **clears** it (the chart /
image default flows through) — clearing is never an empty list `[]`, which is
rejected with `INVALID_CONTAINER_COMMAND` / `INVALID_CONTAINER_ARGS`. An
override targeting a component the driver does not declare is rejected with
`UNKNOWN_COMPONENT_CONTAINER_OVERRIDE` before any redeploy.

## Backups and restores

The `backups` commands take a deployment: `create` and `list` by name or by
`--id`. `restore` takes a backup id, or `--last` with `--target-deployment`,
`--target-deployment-id` or `--target-instance-id`.

- `backups create` backs up the deployment's active instance.
- `backups list` lists the deployment's backup history: the backups of every
  instance the deployment has had, newest first. Its `application_version`
  column shows the application version each backup was taken at. Backups taken
  before an upgrade, a config edit or an environment config change stay in the
  list.
- `backups restore --last` restores the newest completed backup in that
  history that has not expired. The backup can belong to the active instance
  or to an earlier instance of the deployment. For a backup of an earlier
  instance, or one taken at another application version, the command shows the
  backup's application version and the deployment's current one, and asks for
  confirmation. Pass `--yes` to skip the
  question; without a terminal, the command refuses unless you pass `--yes`.
  The restore puts the earlier instance's `StyrminDeployment` and `HelmRelease`
  back in the namespace, and the deployment keeps its active instance.

A raw `--instance-id` (`--target-instance-id` on `restore`) targets one
instance instead: `create` backs up that instance, `list` lists only its
backups, and `restore --last` chooses from its backups only. When that instance
is an earlier instance of its deployment, `restore --last` asks for
confirmation in the same way, and `--yes` skips the question.

```bash
# Back up a deployment's active instance (by name, by id, or a raw instance)
uv run styrminctl backups create my-app
uv run styrminctl backups create my-app --environment prod   # disambiguate a shared name
uv run styrminctl backups create --id <deployment-id> --wait
uv run styrminctl backups create --instance-id <instance-id> # escape hatch

# List a deployment's backup history, with the application version of each backup
uv run styrminctl backups list my-app

# List the backup history of a deleted deployment (the name lookup does not find it).
# The id is the last part of the deleted deployment's page URL in the web UI.
uv run styrminctl backups list --id <deployment-id>

# List the backups of one instance only
uv run styrminctl backups list --instance-id <instance-id>

# Restore a specific backup: restores the backup into the deployment it was taken of
uv run styrminctl backups restore <backup-id>

# Restore the newest completed backup in a deployment's history, in-place
uv run styrminctl backups restore --last --target-deployment my-app

# The same in a script: restore a backup of an earlier instance without the question
uv run styrminctl backups restore --last --yes --target-deployment my-app
```

A deleted deployment's backups cannot be restored: the server refuses the
restore with `OPERATION_DENIED`.

Name lookups search every environment by default; pass `--environment` when the
same deployment name exists in more than one.

`restore` always restores a backup into the deployment it was taken of, in that
deployment's namespace, also when the deployment has no active instance.
`--target-deployment`, `--target-deployment-id`, `--target-instance-id` and
`--environment` work only with `--last`: they choose which backups the newest
completed backup is picked from, not where it is restored. The command refuses a
backup id combined with one of these options, before it contacts the server,
and exits with status 1. Run it again with the backup id alone.

## Environment-level backups

`env-backups` is the coordinated counterpart one level up: one action captures
the environment config plus one constituent backup per eligible deployment, all
grouped under a single snapshot. Target the environment by name (cluster-scoped
with `--cluster` / `--cluster-id`) or by `--id`.

```bash
# Snapshot a whole environment
uv run styrminctl env-backups create prod
uv run styrminctl env-backups create prod --cluster edge --name nightly
uv run styrminctl env-backups create --id <environment-id> --wait

# List an environment's snapshots (newest first), with ok/failed/total counts
# (ok = constituents whose backup completed; failed = never got a backup row)
uv run styrminctl env-backups list prod

# Inspect one snapshot, including per-constituent outcomes
uv run styrminctl env-backups get <environment-backup-id>
```

The snapshot `status` is **derived** from its constituents on every read, so it
can never contradict them: `COMPLETED` (all constituents completed), `PARTIAL`
(some did not), `FAILED`, or a non-terminal `PENDING` / `IN_PROGRESS`. An
environment with no eligible deployments yields a config-only snapshot that is
`COMPLETED` immediately. `--wait` polls until the derived status is terminal and
exits non-zero on `PARTIAL` or `FAILED`, printing the deployment name and reason
for every constituent that did not complete.

Because the status is derived synchronously, `create` and `restore` can come
back already terminal — a fan-out where every constituent was busy, or a restore
where every constituent was skipped. Both commands report that outcome and exit
non-zero straight away, with or without `--wait`.

### Restoring an environment snapshot

`env-backups restore` is the coordinated counterpart of `backups restore`: it
reverts the environment config to the captured value and restores every usable
constituent backup in place, into its existing deployment. It never creates or
deletes deployments. Restoring requires the **ADMIN** role, because reverting
the environment config carries the same privilege as editing it.

```bash
# Restore a whole environment snapshot in place
uv run styrminctl env-backups restore <environment-backup-id>
uv run styrminctl env-backups restore <environment-backup-id> --wait

# Inspect one restore, or list every restore made from a snapshot (newest first)
uv run styrminctl env-backups restore-get <environment-restore-id>
uv run styrminctl env-backups restore-list <environment-backup-id>
```

Only a `COMPLETED` or `PARTIAL` snapshot can be restored; anything else is
refused. Every constituent that is **not** restored is printed with its
deployment name and reason — a backup that failed at creation, never completed,
was deleted, or expired; a deployment that no longer exists; or a deployment
already busy with another restore. There are no silent skips. Like
`create --wait`, `restore --wait` exits non-zero on `PARTIAL` as well as
`FAILED`.

## Authentication

`styrminctl` supports three credential flows. Pick one per environment.

### 1. Interactive login (operator workstation)

Run `login` once. The CLI prompts for the password (hidden), authenticates
against the backend, and persists the resulting token to disk so every
subsequent command picks it up automatically.

```bash
export STYRMIN_ADDRESS=http://prod:8000
uv run styrminctl login --username alice
# Authenticating against http://prod:8000 …
# Logged in to http://prod:8000 as alice

uv run styrminctl whoami
# Username: alice
# Display name: Alice Example
# Role: PLATFORM_ENGINEER
# Authenticated via: token file (/home/alice/.local/share/styrminctl/token)

uv run styrminctl logout
# Logged out of http://prod:8000
```

### 2. Static token via `STYRMIN_TOKEN`

Set `STYRMIN_TOKEN` in the shell or CI job; the CLI uses it directly and
never writes anything to disk. This is the recommended pattern for CI when
the platform can mint a short-lived token for the job.

```bash
export STYRMIN_ADDRESS=http://prod:8000
export STYRMIN_TOKEN="$CI_STYRMIN_TOKEN"   # injected by the CI platform
uv run styrminctl deployments list
```

### 3. Non-interactive auto-login via `STYRMIN_USERNAME` + `STYRMIN_PASSWORD`

For CI platforms that can only inject credentials (not a token), export
both variables. The CLI performs an in-process `login` round-trip on every
invocation; the token is held in memory for the lifetime of the process and
**never persisted** to disk.

```bash
export STYRMIN_ADDRESS=http://prod:8000
export STYRMIN_USERNAME=ci-bot
export STYRMIN_PASSWORD="$CI_STYRMIN_PASSWORD"
uv run styrminctl deployments list
```

### Precedence ladder

When more than one credential source is present, the CLI resolves them in
this fixed order — highest rung wins (see
[`specs/archive/011-styrminctl-auth/contracts/credential-precedence.md`](../specs/archive/011-styrminctl-auth/contracts/credential-precedence.md)
and [ADR-051](../dev/adr/0051-styrminctl-credential-resolution-and-token-store.md)
for the authoritative version):

| Rung | Condition | Action | Source label |
|------|-----------|--------|--------------|
| 1 | `STYRMIN_TOKEN` is set and non-empty | use it directly | `env` |
| 2 | rung 1 false; token store has an entry for the canonical server URL | use it directly | `file` |
| 3 | rungs 1 & 2 false; **both** `STYRMIN_USERNAME` and `STYRMIN_PASSWORD` set and non-empty | call `auth.login` in-process; do NOT persist | `auto-login` |
| 4 | exactly one of `STYRMIN_USERNAME` / `STYRMIN_PASSWORD` is set | raise `AsymmetricEnvCredentialsError` (single-line stderr, non-zero exit) | — |
| 5 | none of the above | no token; commands that require auth fail with `Not logged in. …` | `none` |

Notes:

- Empty strings are treated as unset for `STYRMIN_TOKEN`, `STYRMIN_USERNAME`,
  and `STYRMIN_PASSWORD` — this guards against CI templates that produce
  empty values when a secret is missing.
- `whoami` prints an `Authenticated via: <source>` line so you can confirm
  at a glance which rung is currently active.

### Token store: file path and permissions

The on-disk token store lives at
`${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/token`.

- Parent directory mode: `0700` (reasserted on every save).
- File mode: `0600` (reasserted on every save).
- Format: JSON, `{"schema_version": 1, "tokens": {<canonical-url>: <token>, …}}`.
- Saves are **atomic** (temp file + `os.rename`) so two concurrent `login`s
  against different canonical URLs cannot lose entries.
- `logout` removes the entry for the current canonical URL but keeps the
  file (with the entry removed) so subsequent commands have an
  always-present, always-valid file to read.

### Auto-login network cost

Rung 3 (`STYRMIN_USERNAME` + `STYRMIN_PASSWORD`) performs a fresh
`auth.login` GraphQL round-trip **on every `styrminctl` invocation**. There
is no in-CLI cache. For a CI job that fans out across many `styrminctl`
calls this can add up — every call pays one HTTP round-trip plus password
verification on the backend.

If that latency or the backend load matters for your pipeline, handle it at
the job level rather than expecting the CLI to cache:

- Run `styrminctl login` once at job start (the token is then on disk for
  the rest of the job).
- Or fetch a token up front and export it as `STYRMIN_TOKEN` (rung 1) so
  subsequent calls go through the no-network path.
- Set sensible retry / timeout policy on the job runner; the CLI does not
  retry transient network errors and surfaces them as
  `Could not reach <address>: <error class>.`.

### `STYRMIN_PASSWORD` trade-offs

`STYRMIN_PASSWORD` is convenient but carries real risks worth calling out:

- The variable is visible to anything that can read `/proc/<pid>/environ`
  on the host — on shared CI runners that is a broader audience than you
  might expect.
- A misconfigured CI step (`set -x`, `env` in a log, a crash dump) can
  trivially leak the value into job output and from there into log
  aggregation.
- The password is long-lived; a leaked token bounded to a short TTL is
  far less dangerous than a leaked password.

Prefer `STYRMIN_TOKEN` (rung 1) with a **short-lived** token whenever your
CI platform can mint one for the job. Use `STYRMIN_USERNAME` /
`STYRMIN_PASSWORD` only when the platform cannot, and rotate the password
on a cadence that matches your threat model.

## Telemetry

`styrminctl` collects **anonymous, opt-out** usage telemetry so the
maintainers can see which commands and options are actually used, on which
platforms, and where they fail — and prioritise the CLI accordingly. It is
**on by default on interactive workstations** and **silent in CI /
non-interactive contexts**. There is no first-run prompt and no banner; this
section is the disclosure.

Dispatch is **best-effort and failure-isolated**: after each eligible command
finishes, the CLI fire-and-forgets a single anonymous event over HTTPS and
then exits. It never changes a command's output, exit code, or perceptible
speed, and it silently drops the event if the endpoint is slow or unreachable
(hard cap: **≤ 200 ms** added latency for any endpoint state, including a hung
connection). There is no on-disk spool, no retry, and no batching.

### Exactly what is collected

One JSON event per eligible invocation, with **only** these fields:

| Field | Example | Notes |
|-------|---------|-------|
| `event_id` | `a1b2c3d4-deployments_update` | `install_id[:8]` + `-` + command (spaces → `_`) |
| `install_id` | `a1b2c3d4e5f6…` | random anonymous id, generated once and persisted |
| `command` | `deployments update` | resolved command route from a **closed set** |
| `options` | `["--config", "--wait"]` | canonical **long option names** only, deduped + sorted |
| `outcome` | `success` / `failure` | — |
| `error_category` | `network` | `null` on success, else one of `auth`, `network`, `validation`, `not_found`, `server`, `usage`, `unknown` — bucketed by error **type**, never a message |
| `styrminctl_version` | `0.1.0` | — |
| `python_version` | `3.14.0` | — |
| `os_family` | `Linux` | OS family only (`Linux` / `Darwin` / `Windows`) — never kernel/version detail |

It is wrapped in the envelope
`{"data": {…}, "checksum": "<sha256 hex of data>", "kind": "styrminctl", "payload_format": "1.0"}`,
where `checksum` is the SHA-256 of the JSON-serialised `data` so the server can
recompute and verify the canonical serialisation of the data (HTTPS already
covers transport integrity). The client never sends a timestamp or any network
identifier; the server adds those.

**What is never collected** (scrubbed by construction): server addresses,
hostnames, usernames, tokens, deployment / cluster / environment names,
**argument and option values**, file paths, and IPs. Deriving the option
names never reads or converts a value — in particular a `@file` option value
is never opened, so file contents can never leak onto the telemetry path.

### Opting out

Any **one** of these stops all emission:

| Lever | Effect |
|-------|--------|
| `styrminctl telemetry disable` | Persists an opt-out (survives `logout`); `enable` reverts it. |
| `STYRMIN_TELEMETRY=0` | Disables emission for the process (overrides the persisted flag). |
| `DO_NOT_TRACK=1` | Honours the [community standard](https://consoledonottrack.com/). |
| Running in CI (`CI` set/truthy) | Auto-excluded — no configuration needed. |
| `stderr` is not a TTY (non-interactive / piped) | Auto-excluded. |

Inspect the effective state and the reason at any time:

```bash
uv run styrminctl telemetry status
# Telemetry: enabled (default; interactive terminal).
# Telemetry: disabled (DO_NOT_TRACK=1).
# Telemetry: disabled (persisted opt-out via 'telemetry disable').
```

The `telemetry` command group, `--version` / `version`, `--help` / `-h`, and
the shell-completion command never emit anything themselves.

### Endpoint override

Telemetry POSTs to a fixed production endpoint by default. Set
`STYRMIN_TELEMETRY_ENDPOINT=<url>` to redirect it — used by the test suite and
a local sink, and available if you want to point it at your own collector.

### State file

State is `{install_id, enabled}` stored as JSON at
`${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/telemetry.json` (the same
atomic-write, `0600`-file / `0700`-dir pattern as the token store). The
`install_id` persists even when telemetry is disabled; an unwritable directory
falls back to an ephemeral in-memory id and never errors.
