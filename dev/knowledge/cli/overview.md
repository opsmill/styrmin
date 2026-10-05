# styrminctl Internals

<!-- Extracted from specs/011-styrminctl-auth and specs/015-styrminctl-telemetry on 2026-08-04 -->

## Overview

`styrminctl` is a thin client over the Styrmin GraphQL API. It holds no business
logic: commands resolve arguments, call a `styrmin-sdk` resource method, and
render the result. Everything platform-semantic — validation, no-op detection,
name resolution — lives server-side.

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

**Clearing config.** `updateDeployment` replaces the stored config with the submitted one, except
when the submitted config is empty: the resolver then passes `None` and the stored config is kept.
An omitted or empty `spec.config` therefore changes nothing. To clear the last per-component
override, a manifest writes `components: []`.
