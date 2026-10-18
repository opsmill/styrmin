# styrminctl Internals

<!-- Extracted from specs/011-styrminctl-auth and specs/015-styrminctl-telemetry on 2026-08-04 -->

## Overview

`styrminctl` is a thin client over the Styrmin GraphQL API. It holds no business
logic: commands resolve arguments, call a `styrmin-sdk` resource method, and
render the result. Everything platform-semantic — validation, no-op detection,
name resolution — lives server-side.

One exception: `clusters update` checks the config for unknown keys before it
connects, through the SDK (see [Cluster config update](#cluster-config-update)).
The SDK's generated input models ignore unknown keys, so without this check a
misspelled key would be dropped before the request, and the stored value it
meant to keep would be removed, because the update replaces the whole config.

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

Three things do belong to the CLI, and they are what this page documents: how
credentials are resolved and persisted, how errors reach the user, and the
telemetry wrapper that observes each invocation's outcome.

For the user-facing command reference see [`cli/README.md`](../../../cli/README.md)
and `docs/docs/reference/styrminctl.md`. For authoring conventions see
[`dev/guidelines/cyclopts.md`](../../guidelines/cyclopts.md).

## Package layout

```text
cli/src/styrminctl/
├── cli.py                  # entry point: _AuthBoundaryApp wraps the Cyclopts app
├── cli_commands.py         # the Cyclopts App; registers each command sub-app
├── client.py               # get_client() / get_auth_context() — the credential chokepoint
├── config.py               # Settings (pydantic-settings): server_address, timeout
├── errors.py               # CLI-local exception types
├── output.py               # table / field rendering helpers
├── resolve.py              # id-or-name argument resolution helpers
├── labels.py               # driver-version label rendering (mirrors the backend helper)
├── auth/
│   ├── resolver.py         # CredentialResolver — the precedence ladder
│   ├── token_store.py      # TokenStore — on-disk token persistence
│   └── types.py            # TokenSource, AuthContext
├── commands/               # one module per resource group (+ auth, telemetry)
└── telemetry/
    ├── runtime.py          # run(): the wrapper around the whole invocation
    ├── eligibility.py      # should_emit() — the opt-out ladder
    ├── event.py            # command/option-name extraction, data assembly
    ├── errors.py           # categorize_error(exc) -> (outcome, error_category)
    ├── envelope.py         # data + checksum + kind + payload_format
    ├── dispatch.py         # daemon-thread POST with a bounded join
    ├── store.py            # TelemetryStore — install_id + enabled flag
    └── config.py           # env-var inputs
```

## The invocation pipeline

Every invocation passes through two nested wrappers before Cyclopts dispatches
anything. `cli.py` composes them:

```text
telemetry.runtime.run(...)                 # outermost — observes the final outcome
  └── _call_with_auth_boundary(...)        # renders credential failures, raises SystemExit(1)
        └── the Cyclopts App               # parses and dispatches the command
              └── command function
                    └── get_client()       # credentials resolved here, once
                          └── StyrminClient (SDK)
```

**Telemetry sits outside the auth boundary on purpose.** The boundary converts a
credential failure into `SystemExit(1)`; telemetry wrapping it from the outside is
what lets that exit be classified as the invocation's outcome. Telemetry then
re-raises the original exception unchanged — it never alters stdout, stderr, or
the exit code.

### The auth error boundary

`_AuthBoundaryApp._call_with_auth_boundary` catches exactly three types —
`StyrminAuthenticationError` (from the SDK), `TokenStoreError`, and
`AsymmetricEnvCredentialsError` (both CLI-local) — prints `str(exc)` to stderr,
and raises `SystemExit(1)`. No traceback ever reaches a user for a credential
problem.

`_AuthBoundaryApp` is a proxy, not a subclass: `__getattr__` forwards every other
attribute to the wrapped Cyclopts `App`, so introspecting callers (shell-completion
generation, for instance) keep working.

## Credentials

`client.py::get_client()` is the **single** place credentials enter the CLI. Every
command module calls it; none of them knows where the token came from.

`auth/resolver.py::resolve(settings, env, token_store)` returns
`(token, TokenSource)` in this effective precedence order:

| Precedence | Source | `TokenSource` |
|---|---|---|
| 1 | non-empty `STYRMIN_TOKEN` | `"env"` |
| 2 | `STYRMIN_USERNAME` + `STYRMIN_PASSWORD` — one in-process login, token **not** persisted | `"auto-login"` |
| 3 | token-store entry for the canonical server URL | `"file"` |
| 4 | nothing; only `login` and `--help` can succeed | `"none"` |

Exactly one of `STYRMIN_USERNAME` / `STYRMIN_PASSWORD` is a hard
`AsymmetricEnvCredentialsError` naming the missing variable — never a
fall-through to the disk token. An empty `STYRMIN_TOKEN` counts as unset.

> The resolver's inline comments number these rungs 1/3/2/5 to match the original
> contract document. The numbering is nominal; the table above is evaluation
> order. Explicit env credentials always beat disk.

**The resolved token is passed explicitly to `StyrminClient(token=...)`.** The SDK
can read `STYRMIN_TOKEN` itself, and the CLI deliberately never relies on that —
two independent readers of one variable is how documented precedence becomes a
lie.

`get_client() -> StyrminClient` keeps a token-free signature so command modules
need no auth awareness. A sibling `get_auth_context() -> AuthContext` carries the
`TokenSource`; `whoami` is its only consumer and owns the wording
(`Authenticated via: token file (<path>)`). The resolver returns the enum only —
it knows nothing about rendering, and `token_store.py` knows nothing about
`whoami`.

### Token store

`${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/token`, mode `0600`, parent
`0700`, both reasserted on every save.

```json
{ "schema_version": 1, "tokens": { "<canonical_url>": "<opaque token>" } }
```

- **`schema_version`** is checked on load; an unrecognised value raises
  `TokenStoreError` rather than guessing at the shape. A future `--profile` flag
  bumps it to `2` and nests under a `_default` profile.
- **Keys are canonicalised** by `TokenStore.canonicalise()`: lowercase scheme and
  host, **port preserved verbatim** (default ports are not collapsed), trailing
  slash stripped. `http://prod:8000` and `http://prod:8001` stay distinct.
- **Saves are atomic**: temp file at `0600` in the same directory → `os.rename()`.
  Two concurrent `login`s against different servers cannot clobber each other.
- An **empty-string token is never valid** — refused on write, treated as absent
  on read.
- `logout` rewrites `tokens: {}` rather than removing the file, and a token the
  server rejected is **not** auto-deleted.

`TokenStore` (persistence) and `CredentialResolver` (policy) are separate modules
that change for different reasons; the resolver's tests inject a `Mapping` for the
environment and a stubbed store, touching no filesystem.

Rationale and alternatives:
[ADR-051](../../adr/0051-styrminctl-credential-resolution-and-token-store.md).
Server-side session semantics:
[ADR-016](../../adr/0016-authentication-and-sessions.md).

## Errors

Two distinct error populations meet in the CLI:

- **SDK / backend errors** — the typed hierarchy in
  `python_sdk/src/styrmin_sdk/exceptions.py`, carrying the backend's structured
  error codes.
- **CLI-local errors** — `styrminctl/errors.py`. These are *not* service-layer
  errors in the Constitution §IV sense; they describe CLI control flow (a corrupt
  token file, an unknown `schema_version`, a chmod failure, asymmetric env vars).

Both render as a **single line plus a non-zero exit**, never a traceback.
Formatting is centralised so the top-level handler can `except` → print → exit.
Conventions in [`dev/guidelines/cyclopts.md`](../../guidelines/cyclopts.md).

## Telemetry

Anonymous, opt-out, fire-and-forget. After each *eligible* invocation — once the
outcome is known — the CLI POSTs one scrubbed event and exits.

- **Closed key set.** `event_id`, `install_id`, `command`, `options`, `outcome`,
  `error_category`, `styrminctl_version`, `python_version`, `os_family`. Nothing
  else can be carried.
- **`command`** comes from Cyclopts `parse_commands()` — the resolved route from
  the registered command tree, a closed set by construction, never `sys.argv`
  slicing.
- **`options`** are canonical long-form *names* only, deduplicated and sorted.
  Extraction is a token scan against the command's declared parameter metadata
  and **must never trigger Cyclopts value conversion** — materialising
  `BoundArguments` can invoke converters, and a `@file` option value would be
  read off disk. Scrub-by-construction, not scrub-by-filter.
- **`error_category`** is bucketed by exception **type** (`auth`, `network`,
  `validation`, `not_found`, `server`, `usage`, `unknown`) via
  `categorize_error()`. Never by message text; no new exception classes were
  added.
- **Dispatch is a daemon thread** running a sync `httpx` POST, joined with a
  single budget constant (`TELEMETRY_BUDGET_MS = 200`). On timeout the main
  thread abandons the daemon, which cannot block interpreter exit — so a hung
  endpoint costs at most the budget. A per-phase HTTP timeout could not guarantee
  this. No retry, no batching, no spool.
- **Opt-out ladder** (`eligibility.should_emit()`): emit only if the command is
  eligible **and** `STYRMIN_TELEMETRY ≠ 0` **and** `DO_NOT_TRACK ≠ 1` **and** the
  persisted flag is not disabled **and** `CI` is falsey **and** `stderr` is a TTY.
  The `telemetry` group, `--version`, help screens, and shell-completion commands
  are never eligible.
- **State** lives at `.../styrminctl/telemetry.json` (`{install_id, enabled}`) and
  reuses the token store's write contract exactly — atomic temp + rename,
  `0600`/`0700`. It survives `logout`; an unwritable directory falls back to an
  ephemeral in-memory `install_id` and never raises.

Full rationale, wire format, and the privacy argument:
[ADR-047](../../adr/0047-styrminctl-anonymous-fire-and-forget-telemetry.md).

## Declarative apply

`styrminctl deployments apply -f <path>` is the CLI's one non-trivial
orchestration, and even that lives in the SDK
(`DeploymentResource.apply_files()`) so non-CLI consumers get it too. The CLI
supplies flag overrides, streams one result line per manifest, prints the
`N created, M updated, K failed` summary, and exits non-zero if anything failed.

See [ADR-048](../../adr/0048-declarative-apply-client-side-orchestration.md) and
[ADR-049](../../adr/0049-styrmin-v1-manifest-contract.md).

<!-- Extracted from specs/018-component-image-overrides on 2026-10-05 -->

**Pinned image warning.** When a manifest changes an existing deployment's application version,
`_apply_update` computes the components whose effective `image` override has no
`{{ app.version }}` token: the manifest's `components` when it sets them (they replace the stored
blocks), else the stored config. It returns them as `ApplyOutcome.pinned_image_components`, with
`ApplyOutcome.target_version` set. The CLI prints one `warning:` line per affected deployment on
stderr, after its outcome line, and keeps the exit code. `apply` reads only the raw config, so it
also lists overrides that do not currently apply; the UI upgrade dialog lists only applicable ones.
See [ADR-058](../../adr/0058-image-overrides-and-component-container-guard.md) §7.

**One mutation per existing deployment.** `_apply_update` sends `updateDeploymentVersion` with the
manifest's config and parameters as `input`, also when the version is unchanged, so the backend
validates the config against the driver version the manifest resolves to and one task reconciles
it. A `null` result is `unchanged`. A rejected call is `failed` with `ApplyOutcome.error_code`, and
the CLI prints the code in brackets at the end of the `failed` line. After an `updated` outcome
whose manifest sets component env vars, images, `command`, `args` or replica counts,
`_apply_update` reads `isApplicable` back (`get_deployment_override_applicability.graphql`) and
lists, per component, the kinds it set that are not applied in
`ApplyOutcome.inapplicable_overrides` (`env_vars`, `image`, `command`, `args`, `replicas`;
`command` and `args` share the `componentContainerOverrides` row, `replicas` reads
`componentReplicas`), with the component names in `ApplyOutcome.inapplicable_components`. The CLI
prints one stderr warning per component that names those kinds and the two fixes (remove them from
the manifest, or load a driver version that declares the component container), like the
pinned-image warning. See [ADR-065](../../adr/0065-apply-writes-config-with-the-version.md).

<!-- Extracted from specs/023-per-component-replicas on 2026-10-16 -->

A failed read back never fails the apply. `_inapplicable_overrides` returns no components and the
error text, which `_apply_update` stores in `ApplyOutcome.applicability_check_error`. The CLI then
prints a stderr warning that says overrides that are stored but not applied are not listed, and
gives the error. Before spec 023, a failed read listed nothing and printed nothing.

**Server compatibility.** `update_version()` sends `input` in its own operation
(`update_deployment_version_with_input.graphql`), so a call without `input`, such as
`deployments update-version` without `--config`, still works with a server that predates #388.
With `input`, such a server answers `Unknown argument 'input'`, and the SDK raises
`IncompatibleServerError`, which says to upgrade the server.

**Clearing config.** The `input` replaces the stored config with the submitted one, as
`updateDeployment` does, except when the submitted config is empty: the resolver then passes `None`
and the stored config is kept.
An omitted or empty `spec.config` therefore changes nothing. To clear the last per-component
override, a manifest writes `components: []`.

## Replica counts

<!-- Extracted from specs/023-per-component-replicas on 2026-10-16 -->

Design rationale: [ADR-070](../../adr/0070-replica-overrides-and-retired-parameters.md).

**Whole-number check before Pydantic.** `check_replica_counts(config, source=...)`
(`styrmin_sdk/resources/deployments.py`) raises `ManifestValidationError` when a
`components[].replicas` is a `bool`, a string, a float or another type that is not an `int`.
Pydantic would otherwise turn `true` into 1 and `"3"` into 3 before the server sees the value. The
SDK runs it on the `spec.config` of each manifest in `apply`, and the CLI runs it on the `--config`
JSON of `deployments update` and `deployments update-version`. The server checks the count range
(`INVALID_REPLICA_COUNT`, `REPLICA_COUNT_ABOVE_MAXIMUM`).

**`deployments scale`.** `styrminctl deployments scale <deployment> <component> <count>` sets a
replica override, and `--clear` removes it; the command requires exactly one of the two. It calls
the SDK's `deployments.scale(deployment_id, component, replicas)`, which reads the deployment,
turns each stored `config.components` block into a `ComponentConfigInput`
(`_stored_component_inputs`), changes only `replicas` on the named component, and sends all blocks
back with `updateDeployment`. `components` replaces every stored block, so resending them keeps the
env vars, image, `command` and `args` of every component. A block left with no override after
`--clear` is not sent. A write by someone else between the read and the update is overwritten.
`None` from `update` means nothing changed, and the CLI prints that the deployment is already up to
date. There is no scale mutation in the API.

**`deployments get`.** `get_deployment.graphql` selects `componentReplicas`, and the Components
table has a `replicas` column built by `_replicas_cell`:

| Row | Cell |
|-----|------|
| Override applies | `3 (override)` |
| Driver default | `2 (driver default)`, or `1 (driver default, singleton)` |
| No source | `chart` (Styrmin does not read the chart's count) |
| Stored override not applied | the cell above, then `, override N not applied` |
| Stopped component | the cell above, then `, stopped: 0 pods` |
| Override on a component the driver version no longer declares | an extra row: `N (override, not applied: no longer declared)` |

**Server compatibility.** `GetDeployment` selects `componentReplicas`, so `deployments get` of this
release fails against a server from before spec 023. The SDK and `styrminctl` are upgraded with the
server.

## Task steps

<!-- Extracted from specs/019-task-steps on 2026-10-08 -->

The steps of a task, its task result and the tasks its hook steps started come from the SDK's
`TaskResource` (`python_sdk/src/styrmin_sdk/resources/tasks.py`). The CLI only formats them. The
GraphQL side is described in [api.md](../backend/api.md#step), and the decisions in
[ADR-060](../../adr/0060-steps-and-derived-task-result.md).

**SDK reads.**

- `tasks.get(task_id)` reads the task with `result`, `steps`, `startedBy` and `startedTasks`. The
  query (`get_task.graphql`) leaves out `Step.output`, because output can be long; each step has
  `has_output` instead.
- `tasks.step_output(step_id)` reads the output of one step with `Query.step`.
- `tasks.failed_step(task_id)` returns the first failed step of the task, else of the tasks it
  started, nearest first, as a `FailedStep` (name, task id, newest error). It reads the task, then
  each started task, breadth-first, and returns `None` when no step has failed.

**`styrminctl tasks get <id>`** prints three parts:

1. The task table, with a `result` column next to `status`.
2. A "Steps" table with the columns `step`, `status`, `duration`, `attempts` and `error`. The
   duration reads `running` while the step runs, and otherwise uses the deployment page's format
   (`45s`, `1m 05s`, `1h 02m`). The error cell lists the error of each failed attempt as
   `attempt <n>: <message>`, oldest first, then FluxCD's detail, then `output: <last line>`. The
   command calls `tasks.step_output()` once for each step whose `has_output` is true. Errors and
   output are escaped, so Rich does not read `[...]` in them as markup. A task without steps
   prints "No steps recorded for this task." instead of the table.
3. A "Started tasks" table (id, type, result), only when the task started tasks.

**`styrminctl deployments apply --wait`.** When the deployment ends failed, the SDK's
`_wait_for_terminal` sets `failure_reason` from `tasks.failed_step(outcome.task_id)`:
`step "<name>" failed: <error>`. It keeps `deployment reconciliation failed (status: <status>)`
when there is no task, no failed step, or the read raises a `StyrminError`, for example against a
server without steps. It reads the failed step in the same poll that saw the failure, because a
later status report can change that step. The CLI prints the reason on the `failed` line. The wait
lasts 600 seconds by default (`WAIT_TIMEOUT_SECONDS`, `--max-wait`, SDK `max_wait`); a wait that
runs out reports `wait timeout` instead of the failed step.

## Driver load warnings

<!-- Extracted from specs/020-driver-info-display on 2026-10-13 -->

`drivers load-version` and `drivers load-local-version` print the loaded driver version with
`_print_version_details` (`commands/drivers.py`). After the success line, it prints each entry of
the version's `load_warnings` as a `Warning:` line (`print_warning`). The load mutations fill
`loadWarnings` when the driver file sets an invalid `spec.info.icon` or `spec.info.links` value,
which the load drops instead of failing. Styrmin does not store the warnings, so loading the same
file again prints them again. See
[ADR-068](../../adr/0068-invalid-driver-info-dropped-with-load-warning.md).

## Loading a driver from a driver directory

<!-- Extracted from specs/028-git-driver-directory on 2026-10-18 -->

`styrminctl drivers load-version REPOSITORY_URL BRANCH --driver-directory PATH` loads the driver
from a folder of the repository, given relative to the repository root. Without
`--driver-directory`, the load reads the repository root. The server stores the value in one form
and refuses unsafe values; the CLI does not check it and prints the server's message through
`styrmin_error_handler`. After the `Commit SHA:` line, `_print_version_details` prints
`Driver directory: <path>` when the loaded version has one.

**Server compatibility.** `drivers.load_version()` in the SDK sends `driverDirectory` in its own
operation, `load_version_with_driver_directory.graphql`, and only when a driver directory is
given. A load from the repository root still uses `load_version.graphql`, so it works with a
server that predates #517. A server that predates #517 answers a driver directory with
`Unknown argument 'driverDirectory'`, and the SDK raises `IncompatibleServerError`, which says to
upgrade the server or to load from the repository root. `update_version()` does the same for #388
(see "Server compatibility" above).

## Cluster config update

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

`styrminctl clusters update` replaces the whole config of a cluster and redeploys the deployments
that take a changed value. The server side is described in
[ADR-066](../../adr/0066-cluster-config-fanout.md).

**Reading the config.** `--config` takes the whole config as inline JSON or `@filepath`, parsed
with `parse_json_argument`. A value that is not a JSON object is refused. A key left out is removed
from the stored config.

**Checking the keys before connecting.** The command calls the SDK's `cluster_update_input`
(`python_sdk/src/styrmin_sdk/resources/clusters.py`) before it opens a client. That function:

- refuses every key that is not a field name or alias of `UpdateClusterInput`, at any depth, and
  names its path (`Unknown config key(s): dedicated_ingress.servce`), through
  `validate_input_strict` in `_input_checks.py`. This includes `scheduling`, which a cluster does
  not take (#482);
- accepts snake_case or camelCase keys;
- converts stored enum values, such as `http` and `NodeExternalIP`, to the GraphQL enum names, such
  as `HTTP` and `NODE_EXTERNAL_IP`, through `to_graphql_enum_names`. A config printed by
  `clusters get --json` can therefore be edited and passed back.

`ClusterResource.update` runs the same check again, so SDK callers get it too.

**Waiting for the answer.** The server starts one redeploy for each changed deployment before it
answers, so `ClusterResource.update` waits up to 600 seconds (`UPDATE_CLUSTER_TIMEOUT_SECONDS`,
passed as `request_timeout`) instead of the SDK's default timeout. When the request fails with a
`StyrminTransportError`, the command adds to the message that the server may still be saving the
config and starting the redeploys, and that the operator should check the config with
`styrminctl clusters get` before running the command again.

**Output.** `--dry-run` saves nothing and lists what saving would do. The command lists:

- the deployments that are redeployed, with their task ids (not in a dry run);
- the deployments that wait for their environment's dedicated ingress controller;
- the deployments that are not redeployed because a restore runs;
- one row per dedicated ingress controller action (`create`, `redeploy`, `remove`);
- the deployments that could not be redeployed and the environments that could not be evaluated,
  followed by "Run this command again to retry them. The config is saved." outside a dry run;
- the number of deployments that already run with this config.

**Reading the config back.** `clusters get --json` prints only the config, as indented JSON with
sorted keys, to edit and pass to `clusters update --config @FILE`. `clusters get` and
`clusters list` show the config as JSON in a table cell.
