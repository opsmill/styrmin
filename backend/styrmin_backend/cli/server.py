"""Server management commands for Styrmin CLI."""

from pathlib import Path
from typing import Optional

import uvicorn
from cyclopts import App
from rich.console import Console

from styrmin_backend import config

server_app = App(name="server", help="Server management commands.")
console = Console()


@server_app.command
def start(
    host: str = "0.0.0.0",
    port: int = 8000,
    workers: int = 1,
    reload: bool = False,
    config_file: Optional[Path] = None,
) -> None:
    """Start the Styrmin server.

    Args:
        host: Host to bind to.
        port: Port to bind to.
        workers: Number of worker processes.
        reload: Enable auto-reload for development.
        config_file: Path to configuration file.
    """
    # Load configuration if provided
    if config_file:
        config.SETTINGS.initialize(str(config_file))
    else:
        config.SETTINGS.initialize()

    console.print(f"[bold green]Starting Styrmin server on {host}:{port}[/bold green]")

    if reload:
        console.print("[yellow]Auto-reload enabled (development mode)[/yellow]")

    uvicorn.run(
        "styrmin_backend.server.app:app",
        host=host,
        port=port,
        workers=workers if not reload else 1,  # Workers not supported with reload
        reload=reload,
    )
