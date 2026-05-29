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

Backups and restores act on a deployment's **active application instance**, so
the `backups` commands take a **deployment** — by name or by `--id` — and
resolve the active instance for you. A raw `--instance-id` escape hatch is kept
for targeting a specific (non-active) instance.

```bash
# Back up a deployment's active instance (by name, by id, or a raw instance)
uv run styrminctl backups create my-app
uv run styrminctl backups create my-app --environment prod   # disambiguate a shared name
uv run styrminctl backups create --id <deployment-id> --wait
uv run styrminctl backups create --instance-id <instance-id> # escape hatch

# List a deployment's backups
uv run styrminctl backups list my-app

# Restore a specific backup into a deployment (in-place). The target namespace
# defaults to the deployment's namespace, so you usually don't pass it.
uv run styrminctl backups restore <backup-id> --target-deployment my-app

# Restore the most recent completed backup of a deployment, in-place
uv run styrminctl backups restore --last --target-deployment my-app
```

Name lookups search every environment by default; pass `--environment` when the
same deployment name exists in more than one. When you restore to a raw
`--target-instance-id`, `--target-namespace` is required (there is no deployment
to derive it from).

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
[`specs/011-styrminctl-auth/contracts/credential-precedence.md`](../specs/011-styrminctl-auth/contracts/credential-precedence.md)
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
