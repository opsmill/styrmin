"""Configuration management commands for Styrmin CLI."""

import json
import sys
from pathlib import Path
from typing import Literal, Optional

import toml
from cyclopts import App
from pydantic import ValidationError
from rich.console import Console

from styrmin_backend import config

config_app = App(name="config", help="Configuration management commands.")
console = Console()


@config_app.command
def show(
    format: Literal["json", "toml"] = "toml",
) -> None:
    """Display current configuration.

    Args:
        format: Output format (json or toml).
    """
    # Initialize settings with defaults if not already initialized
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    settings = config.SETTINGS.active_settings

    # Convert settings to dict
    settings_dict = settings.model_dump()

    if format == "json":
        console.print(json.dumps(settings_dict, indent=2, default=str))
    else:
        console.print(toml.dumps(settings_dict))


@config_app.command
def validate(
    config_file: Optional[Path] = None,
) -> None:
    """Validate a configuration file.

    Args:
        config_file: Path to configuration file (default: styrmin.toml).
    """
    file_path = str(config_file) if config_file else "styrmin.toml"

    console.print(f"Validating configuration file: {file_path}")

    try:
        config.load(config_file_name=file_path)
        console.print("[bold green]Configuration is valid.[/bold green]")
    except ValidationError as err:
        console.print(
            f"[bold red]Configuration not valid, found {len(err.errors())} error(s):[/bold red]"
        )
        for error in err.errors():
            error_locations = [str(location) for location in error["loc"]]
            console.print(
                f"  {'/'.join(error_locations)} | {error['msg']} ({error['type']})"
            )
        sys.exit(2)
    except FileNotFoundError:
        console.print(f"[bold red]Configuration file not found: {file_path}[/bold red]")
        sys.exit(2)
