from importlib.metadata import version

from cyclopts import App

from styrminctl.commands.backup_storage_locations import backup_storage_locations_app
from styrminctl.commands.backups import backups_app
from styrminctl.commands.clusters import clusters_app
from styrminctl.commands.deployments import deployments_app
from styrminctl.commands.drivers import drivers_app
from styrminctl.commands.environments import environments_app
from styrminctl.commands.tasks import tasks_app

app = App(name="styrminctl", help="Styrmin client CLI.", version=version("cli"))

app.command(clusters_app)
app.command(environments_app)
app.command(drivers_app)
app.command(deployments_app)
app.command(backups_app)
app.command(backup_storage_locations_app)
app.command(tasks_app)

app.register_install_completion_command()
