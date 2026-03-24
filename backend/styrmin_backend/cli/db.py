"""Database management commands for Styrmin CLI."""

import asyncio
from pathlib import Path
from typing import Optional

from cyclopts import App
from rich.console import Console

from styrmin_backend import config
from styrmin_backend.db.utils import init_db

db_app = App(name="db", help="Database management commands.")
console = Console()


@db_app.command
def init(
    config_file: Optional[Path] = None,
) -> None:
    """Initialize the database.

    Args:
        config_file: Path to configuration file.
    """
    # Load configuration
    if config_file:
        config.SETTINGS.initialize(str(config_file))
    else:
        config.SETTINGS.initialize()

    console.print("[bold blue]Initializing database...[/bold blue]")

    try:
        asyncio.run(init_db())
        console.print("[bold green]Database initialized successfully.[/bold green]")
    except Exception as exc:
        console.print(f"[bold red]Failed to initialize database: {exc}[/bold red]")
        raise SystemExit(1) from exc
