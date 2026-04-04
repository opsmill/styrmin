"""Database management commands for Styrmin CLI."""

from pathlib import Path
from typing import Optional

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from cyclopts import App
from rich.console import Console

from styrmin_backend import config

db_app = App(name="db", help="Database management commands.")
console = Console()


def _get_alembic_config() -> AlembicConfig:
    """Create an Alembic Config object pointing to the project's alembic.ini."""
    backend_dir = Path(__file__).resolve().parent.parent.parent
    ini_path = backend_dir / "alembic.ini"
    alembic_cfg = AlembicConfig(str(ini_path))
    # Ensure script_location is resolved relative to backend_dir.
    alembic_cfg.set_main_option(
        "script_location",
        str(backend_dir / "styrmin_backend" / "db" / "migrations"),
    )
    return alembic_cfg


@db_app.command
def init(
    config_file: Optional[Path] = None,
) -> None:
    """Initialize the database by applying all migrations.

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
        alembic_cfg = _get_alembic_config()
        alembic_command.upgrade(alembic_cfg, "head")
        console.print("[bold green]Database initialized successfully.[/bold green]")
    except Exception as exc:
        console.print(f"[bold red]Failed to initialize database: {exc}[/bold red]")
        raise SystemExit(1) from exc


@db_app.command
def migrate(
    config_file: Optional[Path] = None,
) -> None:
    """Apply all pending database migrations.

    Args:
        config_file: Path to configuration file.
    """
    if config_file:
        config.SETTINGS.initialize(str(config_file))
    else:
        config.SETTINGS.initialize()

    console.print("[bold blue]Applying pending migrations...[/bold blue]")

    try:
        alembic_cfg = _get_alembic_config()
        alembic_command.upgrade(alembic_cfg, "head")
        console.print("[bold green]All migrations applied successfully.[/bold green]")
    except Exception as exc:
        console.print(f"[bold red]Migration failed: {exc}[/bold red]")
        raise SystemExit(1) from exc


@db_app.command
def downgrade(
    config_file: Optional[Path] = None,
) -> None:
    """Rollback the most recent database migration.

    Args:
        config_file: Path to configuration file.
    """
    if config_file:
        config.SETTINGS.initialize(str(config_file))
    else:
        config.SETTINGS.initialize()

    console.print("[bold blue]Rolling back last migration...[/bold blue]")

    try:
        alembic_cfg = _get_alembic_config()
        alembic_command.downgrade(alembic_cfg, "-1")
        console.print("[bold green]Migration rolled back successfully.[/bold green]")
    except Exception as exc:
        console.print(f"[bold red]Downgrade failed: {exc}[/bold red]")
        raise SystemExit(1) from exc


@db_app.command
def status(
    config_file: Optional[Path] = None,
) -> None:
    """Show current database migration version.

    Args:
        config_file: Path to configuration file.
    """
    if config_file:
        config.SETTINGS.initialize(str(config_file))
    else:
        config.SETTINGS.initialize()

    try:
        alembic_cfg = _get_alembic_config()
        alembic_command.current(alembic_cfg, verbose=True)
    except Exception as exc:
        console.print(f"[bold red]Failed to get migration status: {exc}[/bold red]")
        raise SystemExit(1) from exc


@db_app.command
def stamp(
    config_file: Optional[Path] = None,
) -> None:
    """Stamp the database at the latest migration version without running migrations.

    Use this to transition an existing database (created with create_all)
    to Alembic-managed migrations.

    Args:
        config_file: Path to configuration file.
    """
    if config_file:
        config.SETTINGS.initialize(str(config_file))
    else:
        config.SETTINGS.initialize()

    console.print(
        "[bold blue]Stamping database at latest migration version...[/bold blue]"
    )

    try:
        alembic_cfg = _get_alembic_config()
        alembic_command.stamp(alembic_cfg, "head")
        console.print("[bold green]Database stamped at latest version.[/bold green]")
    except Exception as exc:
        console.print(f"[bold red]Failed to stamp database: {exc}[/bold red]")
        raise SystemExit(1) from exc
