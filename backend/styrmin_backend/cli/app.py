"""Main Styrmin CLI application."""

from importlib.metadata import version

from cyclopts import App

app = App(
    name="styrmin",
    help="Styrmin server management CLI.",
    version=version("styrmin-backend"),
)

app.command(
    "styrmin_backend.cli.server:server_app",
    name="server",
    help="Server management commands.",
)
app.command(
    "styrmin_backend.cli.db:db_app", name="db", help="Database management commands."
)
app.command(
    "styrmin_backend.cli.config_cmd:config_app",
    name="config",
    help="Configuration management commands.",
)
app.command(
    "styrmin_backend.cli.export:export_app",
    name="export",
    help="Export commands (schemas, data).",
)
app.command(
    "styrmin_backend.cli.agent:agent_app",
    name="agent",
    help="Agent and operator management commands.",
)
app.command(
    "styrmin_backend.cli.telemetry:telemetry_app",
    name="telemetry",
    help="Telemetry commands.",
)
