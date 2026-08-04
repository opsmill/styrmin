"""Database management commands for Styrmin CLI."""

from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.util.exc import CommandError
from cyclopts import App
from rich.console import Console

from styrmin_backend import config

db_app = App(name="db", help="Database management commands.")
console = Console()

#: Default downgrade target: one revision back.
RELATIVE_ONE_STEP = "-1"


def _get_alembic_config() -> AlembicConfig:
    """Create an Alembic Config object programmatically (no .ini file)."""
    alembic_cfg = AlembicConfig()
    migrations_dir = Path(__file__).resolve().parent.parent / "db" / "migrations"
    alembic_cfg.set_main_option("script_location", str(migrations_dir))
    return alembic_cfg


@db_app.command
def init(
    config_file: Path | None = None,
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
    config_file: Path | None = None,
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
    revision: str = RELATIVE_ONE_STEP,
    config_file: Path | None = None,
) -> None:
    """Rollback database migrations to a target revision.

    Args:
        revision: Target revision to downgrade to. Defaults to ``-1`` (roll
            back a single revision). A relative target cannot be resolved
            across a merge revision — a merge has more than one predecessor,
            so Alembic raises ``Ambiguous walk``. Pass an explicit target in
            that case: one of the merge's parent revisions to un-apply only
            the merge, or ``base`` to un-apply the whole chain.
        config_file: Path to configuration file.
    """
    if config_file:
        config.SETTINGS.initialize(str(config_file))
    else:
        config.SETTINGS.initialize()

    if revision == RELATIVE_ONE_STEP:
        console.print("[bold blue]Rolling back last migration...[/bold blue]")
    else:
        console.print(f"[bold blue]Downgrading to {revision}...[/bold blue]")

    try:
        alembic_cfg = _get_alembic_config()
        alembic_command.downgrade(alembic_cfg, revision)
        console.print("[bold green]Migration rolled back successfully.[/bold green]")
    except CommandError as exc:
        console.print(f"[bold red]Downgrade failed: {exc}[/bold red]")
        if "ambiguous walk" in str(exc).lower():
            console.print(
                "[yellow]The database is at a merge revision, which has more "
                "than one predecessor. Name the target explicitly, e.g. "
                "'styrmin db downgrade <parent-revision>' to un-apply only the "
                "merge, or 'styrmin db downgrade base' to un-apply "
                "everything.[/yellow]"
            )
        raise SystemExit(1) from exc
    except Exception as exc:
        console.print(f"[bold red]Downgrade failed: {exc}[/bold red]")
        raise SystemExit(1) from exc


@db_app.command
def status(
    config_file: Path | None = None,
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
    config_file: Path | None = None,
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
