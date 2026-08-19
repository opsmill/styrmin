from importlib.metadata import version

from cyclopts import App

from styrminctl.commands.auth import auth_app, login, logout, whoami
from styrminctl.commands.telemetry import telemetry_app

app = App(name="styrminctl", help="Styrmin client CLI.", version=version("cli"))

app.command("styrminctl.commands.clusters:clusters_app", name="clusters", help="Manage clusters.")
app.command("styrminctl.commands.environments:environments_app", name="environments", help="Manage environments.")
app.command("styrminctl.commands.drivers:drivers_app", name="drivers", help="Manage application drivers.")
app.command("styrminctl.commands.deployments:deployments_app", name="deployments", help="Manage deployments.")
app.command("styrminctl.commands.backups:backups_app", name="backups", help="Manage backups and restores.")
app.command(
    "styrminctl.commands.environment_backups:environment_backups_app",
    name="env-backups",
    help="Manage environment-level backups and restores.",
)
app.command(
    "styrminctl.commands.environment_clones:environment_clones_app",
    name="env-clones",
    help="Clone environments and track clone operations.",
)
app.command(
    "styrminctl.commands.backup_storage_locations:backup_storage_locations_app",
    name="backup-locations",
    help="Manage backup storage locations.",
)
app.command("styrminctl.commands.tasks:tasks_app", name="tasks", help="View tasks.")
app.command(auth_app)
# Telemetry opt-out group. Registered under the name ``telemetry`` so it matches
# the ineligible route in ``telemetry.eligibility._INELIGIBLE_ROOT_COMMANDS`` and
# never emits an event itself (FR-015).
app.command(telemetry_app)

# Top-level shorthand: ``styrminctl login`` / ``logout`` / ``whoami``
# mirror the same functions registered under the ``auth`` subapp so users
# don't have to type ``auth`` for the three most common credential commands.
app.command(login, name="login")
app.command(logout, name="logout")
app.command(whoami, name="whoami")

app.register_install_completion_command()
