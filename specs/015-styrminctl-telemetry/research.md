# Phase 0 Research: Anonymous opt-out telemetry for `styrminctl`

**Feature**: `015-styrminctl-telemetry` | **Date**: 2026-06-21

All unknowns from the Technical Context are resolved below. Each entry records the decision, the
rationale, and the alternatives rejected.

## R1 — Where to hook telemetry into the CLI lifecycle

- **Decision**: Wrap the existing outer callable in `cli/src/styrminctl/cli.py`
  (`_AuthBoundaryApp.__call__`). The telemetry integration sits **around** the auth error boundary so
  it observes the *final* outcome (including the `SystemExit(1)` the boundary raises for credential
  failures). Flow per invocation: resolve `(command, options, eligible)` from the tokens (best-effort,
  never raises) → run the inner app inside a `try/except/finally` → classify the outcome/exception →
  if `should_emit()`, build + dispatch one event → re-raise the original exception unchanged.
- **Rationale**: This is the single chokepoint every invocation already passes through. It already
  catches typed exceptions, so it is the natural place to read the outcome without touching individual
  command modules. Keeping command modules untouched satisfies the "failure-isolated, no behaviour
  change" requirement (FR-004, SC-003).
- **Alternatives rejected**:
  - *Per-command decorators* — would touch every command module, easy to forget on new commands, and
    risks altering command behaviour.
  - *Cyclopts `meta` app / converters* — more invasive, couples telemetry to Cyclopts internals, and
    still would not cleanly see the auth-boundary `SystemExit`.

## R2 — Resolving the closed-set `command` token (FR-009)

- **Decision**: Use Cyclopts `app.parse_commands(tokens)` (Cyclopts 4.10.1), which returns
  `(command_tokens, apps, unused)`. Join `command_tokens` with single spaces to produce `command`
  (e.g. `("deployments", "update")` → `"deployments update"`). This is derived from the dispatched
  route, **never** from `sys.argv` string slicing.
- **Rationale**: `parse_commands` is side-effect-free and returns the resolved route from the
  registered command tree — a closed set by construction. The value is therefore always a member of the
  known command set (satisfies FR-009 and its verification).
- **Alternatives rejected**: parsing `sys.argv` for the first non-dash tokens — fragile against
  abbreviations, aliases, and global options; explicitly forbidden by FR-009.

## R3 — Extracting canonical long-form option names (FR-010)

- **Decision**: Resolve the dispatched command's Cyclopts argument collection (via the sub-`App`
  returned by `parse_commands`), then scan the raw token list for option-like tokens (leading `-`),
  mapping each to its canonical long name (`--config`, `--wait`) through the command's parameter
  metadata. Deduplicate, drop repeat counts, exclude positionals (no leading dash by construction), and
  sort. Values are never read — only the presence of the option name matters.
- **Rationale**: Mapping short→long via the command's declared parameters guarantees each emitted name
  is a member of that command's declared option set and that **no value** is captured (FR-008, FR-010).
  Scanning tokens for presence (rather than diffing `BoundArguments` against defaults) avoids the
  false-negative where a user explicitly passes a value equal to the default.
- **Hard constraint (critique E1)**: name extraction MUST NOT trigger Cyclopts value **conversion**.
  Materializing full `BoundArguments` can invoke converters — e.g. a `@file` value convention would
  cause Cyclopts to **read the referenced file** (`--config @secrets.json`). Extraction therefore uses
  token-scan + parameter metadata only; values/files are never read. A unit test passes a secret /
  `@file` option and asserts the file is never opened and no value appears in the payload.
- **Alternatives rejected**:
  - *Diffing `BoundArguments` against signature defaults* — a user passing the default value looks
    "unset"; brittle.
  - *Emitting raw flag tokens* — would leak short/long inconsistencies and possibly attached values
    (`--config=secret`).

## R4 — Best-effort dispatch within a hard ≤200 ms budget (FR-002, FR-003, SC-001)

- **Decision**: Dispatch on a **daemon thread** running a synchronous `httpx` POST with tight
  connect/write/read timeouts. The main thread `join()`s the daemon thread with a timeout equal to the
  single tunable budget constant (default 200 ms). If the join times out, the main thread abandons the
  thread and continues to exit; because the thread is a daemon, the interpreter does not wait for it on
  exit. No retry, no batching, no on-disk spool.
- **Rationale**: A bounded `join` guarantees the *added* latency is ≤ budget for **every** endpoint
  state, including a hung connection (a sync timeout alone cannot bound a TCP connect that hangs past
  the budget; the daemon-thread + bounded-join pattern can). Daemon-thread abandonment makes a hung POST
  cost nothing at exit. This is the canonical "fire-and-forget with a hard wall-clock cap" pattern.
- **Alternatives rejected**:
  - *Plain sync POST with a timeout* — httpx timeouts are per-phase, not a single wall-clock cap; a
    slow-but-progressing or connect-hanging endpoint can exceed 200 ms total.
  - *asyncio task* — the CLI has no persistent loop at the outer layer; spinning one up adds startup
    cost and complexity, and cancelling a hung socket is not simpler than abandoning a daemon thread.
  - *`os.fork`/subprocess detach* — heavyweight, platform-fragile (no `fork` on Windows), overkill for
    a single small POST.

## R5 — HTTP client choice & dependency posture

- **Decision**: Use `httpx.Client` (synchronous) for the dispatch POST. `httpx` (0.28.1) is already
  present transitively via `styrmin-sdk` (`httpx>=0.27.0`). Add `httpx` as a **direct** dependency of
  the `cli` package in `cli/pyproject.toml` for hygiene (declaring an already-present transitive dep is
  not a new dependency in the governance sense, and no new package enters the lockfile).
- **Rationale**: The CLI is otherwise async-only via the SDK transport, but telemetry runs on its own
  short-lived daemon thread with no event loop, so a sync client is the simplest correct choice. No new
  package is introduced (PRD constraint honoured).
- **Alternatives rejected**: `urllib.request` — works without httpx but loses connection/timeout
  ergonomics and consistency with the rest of the codebase; `httpx.AsyncClient` — needs a loop on the
  worker thread for no benefit.

## R6 — Telemetry state persistence (FR-017)

- **Decision**: Mirror `cli/src/styrminctl/auth/token_store.py` exactly: store
  `{install_id, enabled}` JSON at `${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/telemetry.json`,
  written via the temp-file + `O_CREAT|O_EXCL|O_WRONLY` at mode `0o600` + `chmod` + atomic `rename`
  pattern, with the parent dir at `0o700`. Lazily generate and persist `install_id` (uuid4 hex) on
  first access. On an unwritable directory, fall back to an **ephemeral in-memory** install ID and do
  not raise.
- **Rationale**: `TokenStore` is battle-tested prior art for exactly these guarantees (atomic write,
  strict perms, concurrent-safe last-write-wins). Reusing the pattern minimises risk and review burden
  and satisfies FR-017 directly.
- **Alternatives rejected**: a brand-new persistence scheme — needless divergence; using the token file
  itself — couples telemetry lifecycle to credentials (FR: telemetry state must survive `logout`).

## R7 — Error → `(outcome, error_category)` mapping (FR-011)

- **Decision**: A pure `categorize_error(exc) -> (outcome, error_category)` function keyed on the
  exception **type**, using the existing hierarchy in `python_sdk/src/styrmin_sdk/exceptions.py` and
  `cli/src/styrminctl/errors.py`:

  | Exception type | `error_category` |
  |---|---|
  | `StyrminAuthenticationError`, `StyrminAuthorizationError` | `auth` |
  | `StyrminTransportError` | `network` |
  | `ResourceNotFoundError` | `not_found` |
  | `ResourceAlreadyExistsError`, `StyrminGraphQLError`, `AsymmetricEnvCredentialsError` | `validation` |
  | `OperationFailedError`, `DeploymentRestoringError`, `TokenStoreError` | `server` |
  | `SystemExit` with non-zero code (Cyclopts usage / arg errors) | `usage` |
  | any other `Exception` | `unknown` |

  `outcome` is `"success"` when no exception propagates or `SystemExit` carries code `0`/`None`;
  otherwise `"failure"`. `error_category` is `null` exactly when `outcome == "success"`.
- **Rationale**: Type-keyed bucketing (never string-matching messages) is robust and satisfies FR-011's
  explicit prohibition on parsing human-readable text. Reuses existing typed errors → no new error
  classes (Constitution §IV).
- **Alternatives rejected**: deriving category from message text — forbidden by FR-011; introducing new
  exception subclasses — unnecessary and a governance gate (Ask First) for no benefit.

## R8 — Eligibility ladder (FR-014, FR-015)

- **Decision**: `should_emit(...)` returns `True` only if **all** hold: command is eligible (route not
  in the ineligible set) **and** `STYRMIN_TELEMETRY` ≠ `0` **and** `DO_NOT_TRACK` ≠ `1` **and** the
  persisted flag ≠ `disabled` **and** `CI` is unset/falsey **and** `sys.stderr.isatty()`. The ineligible
  set is: the `telemetry` command group, the `--version`/`version` path, any invocation with
  `--help`/`-h` or an empty route (help screen), and the shell-completion command(s) registered by
  `register_install_completion_command()`.
- **Rationale**: Encodes FR-014/FR-015 as one pure predicate with one assertion per rung (matches the
  spec's verification recipe). Pure → trivially unit-testable.
- **Alternatives rejected**: scattering the checks across the hook — harder to test each rung in
  isolation.

## R9 — Coarse environment facts (FR-013)

- **Decision**: `os_family = platform.system()` (`Linux`/`Darwin`/`Windows`);
  `python_version = platform.python_version()` (e.g. `3.14.0`);
  `styrminctl_version = importlib.metadata.version("cli")`. No kernel string, no build, no arch.
- **Rationale**: `platform.system()` is exactly the coarse OS family the spec asks for; the CLI already
  obtains its version via `importlib.metadata.version("cli")`.
- **Alternatives rejected**: `platform.platform()`/`uname()` — leaks kernel/version detail (forbidden).

## R10 — Checksum reproducibility (FR-006, SC-005)

- **Decision**: `checksum = hashlib.sha256(json.dumps(data).encode("utf-8")).hexdigest()`, where
  `json.dumps(data)` uses CPython defaults (separators `", "`/`": "`, insertion key order, **no**
  `sort_keys`, `ensure_ascii=True`). `data` is built as an ordered dict in the FR-007 key order so the
  serialization is deterministic.
- **Rationale**: A server reproducing `pythonJsonStringify(data)` + SHA-256 recomputes the identical
  digest (SC-005). Building `data` with fixed insertion order removes nondeterminism.
- **Alternatives rejected**: `sort_keys=True` — diverges from the agreed server contract; canonical/JCS
  JSON — unnecessary and not what the endpoint expects.

## Resolved clarifications

- `payload_format` is the **string** `"1.0"` (server treats it as opaque) — resolved in spec
  Assumptions per the PRD's stated resolution.
