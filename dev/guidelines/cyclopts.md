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

## Key Files

| File | Purpose |
|------|---------|
| `cli/src/styrminctl/types.py` | Shared validators and type aliases |
| `cli/src/styrminctl/output.py` | Output formatting utilities |
| `cli/src/styrminctl/cli_commands.py` | Root app and command group registration |
| `cli/src/styrminctl/commands/*.py` | Command implementations |
| `cli/tests/test_types.py` | Validator unit tests |
