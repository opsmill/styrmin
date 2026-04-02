# Quickstart: Migrate styrminctl CLI from Typer to Cyclopts

**Feature**: 001-migrate-cli-cyclopts | **Date**: 2026-03-25

## Prerequisites

- Python 3.12+
- `uv` package manager
- Repository cloned and on `001-migrate-cli-cyclopts` branch

## Setup

```bash
# Install all dependencies (includes cyclopts from project root)
uv sync --all-groups
uv sync --all-packages

# Verify backend CLI works (reference implementation)
uv run styrmin --help
```

## Migration Recipe (per command group)

### Step 1: Convert the command group file

Replace Typer imports and patterns with Cyclopts equivalents:

```python
# BEFORE (e.g., commands/clusters.py)
from styrminctl.async_typer import AsyncTyper as Typer
import typer

app = Typer(help="Manage clusters.")

@app.command()
async def create(
    name: str = typer.Argument(help="Name of the cluster"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="JSON configuration"),
) -> None:
    """Create a new cluster."""
    try:
        client = _get_client()
        result = await client.clusters.create(name=name, config=parse_json_argument(config))
        print_table(...)
    except StyrminError as e:
        print_error(str(e))
        raise typer.Exit(code=1) from e
```

```python
# AFTER
from cyclopts import App

clusters_app = App(name="clusters", help="Manage clusters.")

@clusters_app.command
async def create(name: str, *, config: str | None = None) -> None:
    """Create a new cluster.

    Args:
        name: Name of the cluster.
        config: JSON configuration (inline or @filepath).
    """
    try:
        client = _get_client()
        result = await client.clusters.create(name=name, config=parse_json_argument(config))
        print_table(...)
    except StyrminError as e:
        print_error(str(e))
        raise SystemExit(1) from e
```

### Step 2: Update command registration

```python
# cli_commands.py (or cli.py)
from cyclopts import App
from styrminctl.commands.clusters import clusters_app

app = App(name="styrminctl", help="Styrmin client CLI.", version=version("cli"))
app.command(clusters_app)
```

### Step 3: Write tests

```python
# tests/test_clusters.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from styrminctl.cli import app

def test_clusters_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["clusters", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "list" in output

def test_clusters_create(mocker, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client = MagicMock()
    mock_client.clusters.create = AsyncMock(return_value={"id": "123", "name": "test"})
    mocker.patch("styrminctl.commands.clusters._get_client", return_value=mock_client)

    app(["clusters", "create", "test-cluster"])

    mock_client.clusters.create.assert_called_once()
    output = capsys.readouterr().out
    assert "test" in output
```

### Step 4: Verify

```bash
# Run tests for this command group
cd cli && uv run pytest tests/test_clusters.py -v

# Run the actual command
uv run styrminctl clusters --help

# Format and lint
uv run invoke format lint
```

## Key Differences Cheat Sheet

| Typer | Cyclopts |
|-------|----------|
| `Typer(help="...")` | `App(name="...", help="...")` |
| `@app.command()` | `@app.command` |
| `typer.Argument(help="...")` | Positional param + docstring `Args:` |
| `typer.Option(None, "--flag", "-f", help="...")` | Keyword param with default + docstring `Args:` |
| `raise typer.Exit(code=1)` | `raise SystemExit(1)` |
| `from styrminctl.async_typer import AsyncTyper as Typer` | `from cyclopts import App` |
| `app.add_typer(sub, name="...")` | `app.command(sub_app)` |

## Validation Checklist

After migrating each command group:

- [ ] `uv run styrminctl <group> --help` shows all commands
- [ ] Each command in the group executes correctly
- [ ] Error cases return exit code 1
- [ ] Tests pass for all commands in the group
- [ ] `uv run invoke format lint` passes
