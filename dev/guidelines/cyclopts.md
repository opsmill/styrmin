# Cyclopts CLI Guidelines

## Parameter Annotations

All CLI parameters **must** use `Annotated[type, Parameter(...)]` for help text and validation. Do not use docstring `Args:` sections for parameter documentation.

```python
# Correct
@app.command
async def get(cluster_id: ClusterId) -> None:
    """Get a cluster by ID."""

# Correct (inline for one-off parameters)
@app.command
async def create(
    name: Annotated[str, Parameter(help="Name of the cluster.")],
    *,
    config: Annotated[str | None, Parameter(help="JSON config (inline or @filepath).")] = None,
) -> None:
    """Create a new cluster."""

# Wrong — do not use docstring Args
@app.command
async def create(name: str) -> None:
    """Create a new cluster.

    Args:
        name: Name of the cluster.
    """
```

## Type Aliases

Use shared type aliases from `cli/src/styrminctl/types.py` for repeated parameter patterns. This ensures consistent help text and validation across all commands.

| Alias | Type | Validator | Usage |
|-------|------|-----------|-------|
| `ClusterId` | `str` | `validate_uuid` | Cluster UUID parameters |
| `EnvironmentId` | `str` | `validate_uuid` | Environment UUID parameters |
| `DeploymentId` | `str` | `validate_uuid` | Deployment UUID parameters |
| `TaskId` | `str` | `validate_uuid` | Task UUID parameters |
| `BackupId` | `str` | `validate_uuid` | Backup UUID parameters |
| `BslId` | `str` | `validate_uuid` | Backup storage location UUID parameters |
| `RestoreId` | `str` | `validate_uuid` | Restore operation UUID parameters |
| `InstanceId` | `str` | `validate_uuid` | Application instance UUID parameters |
| `MaxWait` | `float` | `validate_positive` | Timeout duration in seconds |
| `PollInterval` | `float` | `validate_positive` | Polling interval in seconds |

Create a new alias when a parameter pattern (type + help + validator) appears in 2+ commands. For one-off parameters, use inline `Annotated[type, Parameter(help="...")]`.

## Validators

### Validator Signature

Cyclopts validators follow this signature:

```python
def validate_something(_type: Any, value: Any) -> None:
    """Raise ValueError if value is invalid."""
    if invalid_condition:
        raise ValueError(f"Descriptive error: {value!r}")
```

- First argument: the type hint (usually ignored, named `_type`)
- Second argument: the already-converted value
- Must raise `ValueError` on failure (cyclopts converts this to a user-friendly error)
- Must handle `None` gracefully for optional parameters

### Custom Validators

Defined in `cli/src/styrminctl/types.py`:

| Validator | Purpose |
|-----------|---------|
| `validate_uuid` | Validates UUID format using `uuid.UUID()` |
| `validate_positive` | Ensures numeric value > 0 |
| `validate_directory_exists` | Checks path exists and is a directory |

### Built-in Validators

Cyclopts provides `cyclopts.validators.Number` and `cyclopts.validators.Path`:

```python
from cyclopts import Parameter, validators

# Number range validation
port: Annotated[int, Parameter(validator=validators.Number(gte=1, lte=65535))]

# Path validation (only works with pathlib.Path type, not str)
config: Annotated[Path, Parameter(validator=validators.Path(exists=True, dir_okay=False))]
```

Note: `validators.Path` only works with `pathlib.Path` parameters. For `str` path parameters, use a custom validator.

### When NOT to Add Validators

- **JSON config parameters** — validated by `parse_json_argument()` in the function body
- **URLs** — server-side validation is sufficient for a thin client
- **Enum-like strings** (e.g., status filters) — server validates allowed values
- **Free-form names** — no format constraints to enforce

## Docstrings

Keep only the command description in docstrings. Parameter documentation belongs in `Parameter(help=...)`.

```python
@app.command
async def create(
    name: Annotated[str, Parameter(help="Name of the cluster.")],
) -> None:
    """Create a new cluster."""
```

## Command Registration

```python
from cyclopts import App

# Command group
clusters_app = App(name="clusters", help="Manage clusters.")

# Individual command — use @app.command (no parentheses) for default behavior
@clusters_app.command
async def create(...) -> None: ...

# Named command — use name= when the CLI name differs from the function name
@clusters_app.command(name="list")
async def list_clusters() -> None: ...
```

## Lazy Loading

Register sub-apps using Cyclopts lazy loading so the root CLI module only imports `cyclopts`, not every command module and its transitive dependencies. This keeps `--help`, `--version`, and shell completion fast.

### Pattern

```python
# Root app (cli_commands.py / app.py)
app.command("mypackage.commands.clusters:clusters_app", name="clusters", help="Manage clusters.")
```

The string `"mypackage.commands.clusters:clusters_app"` is resolved only when the `clusters` subcommand is actually invoked. The `name=` and `help=` parameters are registered immediately so they appear in the parent `--help` output without importing the target module.

### Rules

- **Always provide `name=`** — this registers the subcommand name so it appears in parent `--help` output.
- **Always provide `help=`** — lazy-loaded sub-apps do not propagate help text from the target `App()` instance into the parent help output. The `help=` kwarg must be passed at registration time for descriptions to appear in `--help`. Keep this string in sync with the `help=` in the target module's `App()` declaration.
- **Do not change command modules** — each module still creates its own `App()` and registers commands with `@app.command` as usual.

### Caveats

- Import errors in a lazy module surface at execution time (when the subcommand runs), not at CLI startup.
- Group validators defined only inside a lazy module won't apply until the module is resolved.

## Defaults

Specify defaults at the function signature level, not inside `Parameter()`. Cyclopts displays defaults in `--help` automatically.

```python
# Correct
max_wait: MaxWait = 300

# Wrong
max_wait: Annotated[float, Parameter(help="...", default=300)]
```

## Positional vs Keyword Arguments

- **Positional arguments** (before `*`): become CLI positional args
- **Keyword arguments** (after `*`): become CLI `--option` flags

```python
@app.command
async def create(
    name: Annotated[str, Parameter(help="...")],       # positional: styrminctl create <name>
    *,
    config: Annotated[str | None, Parameter(help="...")] = None,  # option: --config
) -> None: ...
```

## Error Handling

Use `raise SystemExit(1)` for error exits (not `sys.exit(1)` or framework-specific exceptions):

```python
except StyrminError as e:
    print_error(str(e))
    raise SystemExit(1) from e
```

<!-- Extracted from specs/011-styrminctl-auth on 2026-08-04 -->

### One line, never a traceback

Every error a user can provoke renders as **a single line on stderr plus a
non-zero exit**. A traceback reaching a user is a bug.

- Own the wording in the command module or the top-level boundary — not in the
  layer that raised. `whoami` formats the `TokenSource`; the resolver returns the
  enum. `TokenStore` raises with the file path in the message; it does not print.
- Errors that can surface from *any* command belong in the top-level boundary in
  `cli.py`, not repeated in each command. `_AuthBoundaryApp` catches
  `StyrminAuthenticationError`, `TokenStoreError`, and
  `AsymmetricEnvCredentialsError`, prints `str(exc)`, and raises `SystemExit(1)`.
  Adding a command inherits that for free.
- Name the actionable thing. A missing credential says
  ``Not logged in. Run `styrminctl login` or set STYRMIN_TOKEN.``; a store problem
  names the file path; an asymmetric env-var pair names the *missing* variable.

### CLI-local errors are not service-layer errors

Define CLI control-flow errors in `cli/src/styrminctl/errors.py` as plain
`Exception` subclasses. Constitution §IV's typed-error rule is about the backend
service layer — "the token file is corrupt" or "you set `STYRMIN_USERNAME` without
`STYRMIN_PASSWORD`" are not service concerns and must not be modelled as
`ServiceError`s or given backend-style error codes.

Do **not** invent new exception types to carry information an existing typed error
already carries. `styrminctl`'s telemetry buckets failures by exception **type**
using the SDK hierarchy plus `styrminctl.errors` as-is; adding classes for
categorisation would be a governance gate for no benefit.

<!-- Extracted from specs/011-deployment-backup-history on 2026-10-10 -->

## Confirm before acting on a target the operator did not name

When a command chooses the thing it acts on (for example `backups restore --last`, which picks a
backup from the deployment's history), and that choice can change the deployment in a way the
operator may not expect, print what will happen and ask before acting:

- Print the facts the operator needs to decide, such as the backup's application version and the
  deployment's current one.
- Ask with `rich.prompt.Confirm.ask(..., default=False)`, so pressing Enter cancels.
- Add a `--yes` / `-y` flag with `negative=""` that skips the question.
- When standard input is not a terminal and `--yes` is not passed, refuse with a one-line error
  that names `--yes`. Do not wait for input that cannot arrive.
- Ask no question when the operator named the target exactly, for example by passing a backup id.

```python
yes: Annotated[
    bool,
    Parameter(name=["--yes", "-y"], negative="", help="... without asking for confirmation."),
] = False

if yes:
    return
if not sys.stdin.isatty():
    raise ValueError("Not restoring this backup without confirmation. Pass --yes to restore it.")
if not Confirm.ask("Restore this backup?", console=console, default=False):
    raise ValueError("Restore cancelled.")
```

Only `backups restore --last` uses this today
(`_confirm_backup_of_earlier_instance` in `cli/src/styrminctl/commands/backups.py`). See
[ADR-063](../adr/0063-restore-of-earlier-instance-backup.md).

## CLI-local persisted state

Both the token store and the telemetry store follow one contract. Copy it for any
new file the CLI writes; do not invent a second scheme.

- **Path**: `${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/<name>`. Never
  `~/.styrminctl`, never next to the config.
- **Permissions**: file `0600`, parent directory `0700`, **reasserted on every
  save** (chmod after open). A save that cannot reassert them fails rather than
  proceeding — a credential file that silently became world-readable is worse than
  a failed write.
- **Atomic writes**: serialise → write a temp file in the *same directory* with the
  target mode → `os.rename()` over the target. `os.rename()` is atomic on POSIX, so
  a reader sees the old or the new content, never a partial file. Include pid +
  random in the temp name so two concurrent writers do not collide on it.

  ```python
  tmp = path.with_suffix(f".tmp.{os.getpid()}.{secrets.token_hex(4)}")
  # open with O_CREAT|O_EXCL|O_WRONLY at 0o600, write, close, chmod
  os.rename(tmp, path)
  ```

- **Version the shape**: store an integer `schema_version` and check it on load.
  An unrecognised value is an error naming the file — never a best-effort guess at
  the shape. One integer now beats shape-sniffing heuristics later.
- **Missing file is not an error.** Absent means "empty" / "default", and the file
  is created on first write. Emptying a store rewrites it with an empty collection
  rather than unlinking it.
- **Corrupt content raises**, naming the path, so the user can inspect or delete
  it. Do not silently reset a file the user may want to look at.
- **Degrade, do not crash, when the directory is unwritable** — but only where the
  data is genuinely optional. The telemetry store falls back to an ephemeral
  in-memory `install_id`; the token store raises, because silently not saving a
  token the user just obtained would be a lie.

See [ADR-051](../adr/0051-styrminctl-credential-resolution-and-token-store.md) and
[`dev/knowledge/cli/overview.md`](../knowledge/cli/overview.md).

## Key Files

| File | Purpose |
|------|---------|
| `cli/src/styrminctl/types.py` | Shared validators and type aliases |
| `cli/src/styrminctl/output.py` | Output formatting utilities |
| `cli/src/styrminctl/cli_commands.py` | Root app and command group registration |
| `cli/src/styrminctl/commands/*.py` | Command implementations |
| `cli/src/styrminctl/cli.py` | Entry point; top-level error boundary + telemetry wrapper |
| `cli/src/styrminctl/errors.py` | CLI-local exception types |
| `cli/src/styrminctl/client.py` | `get_client()` — the single credential chokepoint |
| `cli/src/styrminctl/auth/token_store.py` | Reference implementation of the persisted-state contract |
| `cli/tests/test_types.py` | Validator unit tests |
