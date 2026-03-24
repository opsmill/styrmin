"""Main Styrmin CLI application."""

from importlib.metadata import version

from cyclopts import App

from styrmin_backend.cli.config_cmd import config_app
from styrmin_backend.cli.db import db_app
from styrmin_backend.cli.export import export_app
from styrmin_backend.cli.server import server_app

app = App(
    name="styrmin",
    help="Styrmin server management CLI.",
    version=version("styrmin-backend"),
)

# Register subcommand apps
app.command(server_app)
app.command(db_app)
app.command(config_app)
app.command(export_app)
