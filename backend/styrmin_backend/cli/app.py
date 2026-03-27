"""Main Styrmin CLI application."""

from importlib.metadata import version

from cyclopts import App

app = App(
    name="styrmin",
    help="Styrmin server management CLI.",
    version=version("styrmin-backend"),
)

app.command("styrmin_backend.cli.server:server_app", name="server")
app.command("styrmin_backend.cli.db:db_app", name="db")
app.command("styrmin_backend.cli.config_cmd:config_app", name="config")
app.command("styrmin_backend.cli.export:export_app", name="export")
