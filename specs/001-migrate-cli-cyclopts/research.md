# Research: Migrate styrminctl CLI from Typer to Cyclopts

**Feature**: 001-migrate-cli-cyclopts | **Date**: 2026-03-25

## R1: Cyclopts Command Registration Pattern (from Backend Reference)

**Decision**: Use `cyclopts.App` instances for each command group, registered via `app.command(sub_app)` on the root app.

**Rationale**: The backend `styrmin` CLI already establishes this pattern. Each command group (e.g., `clusters`, `deployments`) becomes a `cyclopts.App(name="...", help="...")` instance. Commands within the group use `@group_app.command` decorator. This mirrors the existing Typer pattern closely, minimizing migration complexity.

**Alternatives considered**:
- Single flat app with all commands: Rejected; loses command group hierarchy.
- Custom command registration: Rejected; Cyclopts' built-in pattern is sufficient and matches backend conventions.

**Backend reference pattern**:
```python
# Root app (cli.py)
from cyclopts import App
app = App(name="styrminctl", help="Styrmin client CLI.", version=version("cli"))

# Command group (commands/clusters.py)
clusters_app = App(name="clusters", help="Manage clusters.")

@clusters_app.command
async def create(name: str, ...) -> None:
    """Create a new cluster."""
    ...

# Registration (cli_commands.py or cli.py)
app.command(clusters_app)
```

## R2: Async Command Handling in Cyclopts

**Decision**: Use native async function support in Cyclopts. Commands are defined as `async def` directly — no wrapper needed.

**Rationale**: Cyclopts natively supports async command handlers (unlike Typer, which requires the custom `AsyncTyper` wrapper). When a command function is `async def`, Cyclopts automatically runs it in an event loop. This eliminates `async_typer.py` entirely.

**Alternatives considered**:
- Manual `asyncio.run()` wrapping (as backend does): Rejected; Cyclopts handles this natively, and all 35 styrminctl commands are already async. The backend uses sync functions with manual `asyncio.run()` because its commands were originally sync.
- Keep AsyncTyper as compatibility layer: Rejected; defeats purpose of migration and adds unnecessary code.

**Migration**: Delete `async_typer.py`. Change `from styrminctl.async_typer import AsyncTyper as Typer` to `from cyclopts import App` in all command files.

## R3: Exit Code Handling Migration

**Decision**: Replace all `raise typer.Exit(code=1)` calls with `raise SystemExit(1)`.

**Rationale**: The backend CLI uses `raise SystemExit(1)` and `sys.exit(1)` for error exits. Cyclopts treats `SystemExit` as the standard exit mechanism. Tests catch it with `pytest.raises(SystemExit)` and assert on `exc.value.code`. This is Python-standard and framework-agnostic.

**Alternatives considered**:
- `sys.exit(1)`: Equivalent to `raise SystemExit(1)` but less explicit in exception-handling contexts. Either works; prefer `raise SystemExit(1)` for consistency with backend pattern and clearer intent in `except` blocks.
- Custom exception type: Rejected; unnecessary abstraction.

**Migration pattern**:
```python
# Before (Typer)
except StyrminError as e:
    print_error(str(e))
    raise typer.Exit(code=1) from e

# After (Cyclopts)
except StyrminError as e:
    print_error(str(e))
    raise SystemExit(1) from e
```

## R4: Argument and Option Migration

**Decision**: Replace `typer.Argument()` and `typer.Option()` with Cyclopts' type-annotation-based parameter inference and `cyclopts.Parameter()` for customization.

**Rationale**: Cyclopts infers parameter types from function signatures. Positional parameters become CLI positional arguments; keyword parameters with defaults become options. `cyclopts.Parameter()` is used when custom help text, aliases, or other metadata is needed.

**Alternatives considered**:
- Annotated types only (no `Parameter()`): Would work for simple cases but loses help text on individual parameters. Docstring `Args:` sections provide parameter help in Cyclopts.

**Migration pattern**:
```python
# Before (Typer)
async def create(
    name: str = typer.Argument(help="Name of the cluster"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="JSON configuration"),
) -> None:

# After (Cyclopts) - help from docstring Args section
@clusters_app.command
async def create(name: str, *, config: str | None = None) -> None:
    """Create a new cluster.

    Args:
        name: Name of the cluster.
        config: JSON configuration.
    """
```

**Key differences**:
- Short aliases (`-c`): Use `Annotated[str, Parameter(name=["-c", "--config"])]` or Cyclopts' automatic short-name inference
- Help text: Moves from `typer.Option(help=...)` to docstring `Args:` section (Cyclopts convention)
- Required vs optional: Determined by presence/absence of default value (same as Typer)

## R5: Shell Completion Support

**Decision**: Leverage Cyclopts' built-in shell completion support for bash, zsh, and fish.

**Rationale**: Cyclopts provides automatic shell completion generation. No existing completions existed for styrminctl, so this is purely additive. The backend CLI gets completions from the same mechanism.

**Alternatives considered**:
- Manual completion scripts: Rejected; unnecessary when framework provides them.
- Third-party completion tool (e.g., `shtab`): Rejected; Cyclopts built-in is sufficient.

## R6: Help Text Formatting

**Decision**: Follow Cyclopts default help formatting, consistent with backend `styrmin` CLI style.

**Rationale**: Per spec clarification, exact Typer help layout match is not required. Cyclopts generates help from the App `help` parameter and command docstrings. This aligns with the backend CLI and satisfies FR-004.

**Key differences from Typer**:
- No Rich-formatted help by default (Cyclopts uses plain text help)
- Panel/group layout differs
- Boolean flags don't auto-generate `--no-<flag>` variants (documented breaking change per spec)

## R7: Testing Strategy

**Decision**: Write tests alongside migration using pytest, following backend CLI test patterns.

**Rationale**: No existing tests exist for styrminctl (SC-002 requires 100% command coverage). The backend CLI tests provide an established pattern: invoke `app(argv)`, catch `SystemExit`, capture output with `capsys`, and assert on both exit codes and output content.

**Test pattern**:
```python
def test_clusters_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["clusters", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "list" in output

@pytest.mark.asyncio
async def test_clusters_create(mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    mocker.patch("styrminctl.commands.clusters._get_client")
    # ... test command execution
```

**Dependency mocking**: All commands call `_get_client()` to get a `StyrminClient`. Mock this function in tests to avoid real API calls.

## R8: Migration Order Strategy

**Decision**: Migrate command groups one at a time, writing tests for each before moving to the next.

**Rationale**: Incremental migration reduces risk and makes each step reviewable. Order by complexity (simplest first):

1. **Root app + entry point** (`cli.py`, `cli_commands.py`) — framework swap, no commands yet
2. **tasks** (2 commands) — smallest group, good for validating the pattern
3. **clusters** (4 commands) — simple CRUD, establishes the standard pattern
4. **environments** (4 commands) — similar to clusters
5. **drivers** (3 commands) — slightly different (file operations)
6. **backup_storage_locations** (6 commands) — medium complexity
7. **backups** (9 commands) — largest non-deployment group
8. **deployments** (10 commands) — largest and most complex group
9. **Cleanup** — delete `async_typer.py`, remove Typer from deps, add shell completions

## R9: Dependency Changes

**Decision**: Replace `typer>=0.16.0,<0.22.0` with `cyclopts>=3.0.0` in `cli/pyproject.toml`.

**Rationale**: Cyclopts is already a project-level dependency (used by backend). The CLI package needs it as a direct dependency. Rich remains (used for output formatting, independent of CLI framework). Pydantic-settings and styrmin-sdk are unchanged.

**Updated dependencies**:
```toml
dependencies = [
    "styrmin-sdk",
    "cyclopts>=3.0.0",
    "rich>=13.0.0",
    "pydantic-settings>=2.12.0",
]
```
