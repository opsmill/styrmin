"""Shared output formatting and parsing utilities for styrminctl."""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from styrmin_sdk.exceptions import StyrminError

console = Console()


def parse_json_argument(value: str | None) -> Any | None:  # noqa: ANN401
    """Parse a JSON argument that can be either a file path (prefixed with @) or inline JSON.

    Args:
        value: The raw string from the CLI argument. None if not provided.

    Returns:
        Parsed JSON as a Python object, or None.

    Raises:
        ValueError: If the JSON is invalid or file cannot be read.
    """
    if value is None:
        return None

    if value.startswith("@"):
        file_path = Path(value[1:])
        if not file_path.exists():
            raise ValueError(f"Config file not found: {file_path}")
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in file {file_path}: {e}") from e

    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e


def print_table(rows: list[dict[str, Any]], columns: list[str], title: str = "") -> None:
    """Print a list of objects as a Rich table."""
    table = Table(title=title)
    for col in columns:
        table.add_column(col, style="cyan")
    for row in rows:
        table.add_row(*[str(row.get(col, "")) for col in columns])
    console.print(table)


def print_error(message: str) -> None:
    """Print an error message in red."""
    console.print(f"[red]Error:[/red] {message}")


def print_success(message: str) -> None:
    """Print a success message in green."""
    console.print(f"[green]Success:[/green] {message}")


def print_warning(message: str) -> None:
    """Print a warning message in yellow."""
    console.print(f"[yellow]Warning:[/yellow] {escape(message)}")


@contextmanager
def styrmin_error_handler() -> Generator[None]:
    """Catch StyrminError and ValueError, print a friendly message, and exit."""
    try:
        yield
    except (StyrminError, ValueError) as e:
        print_error(str(e))
        raise SystemExit(1) from e
