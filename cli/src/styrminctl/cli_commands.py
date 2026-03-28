from importlib.metadata import version

from cyclopts import App

app = App(name="styrminctl", help="Styrmin client CLI.", version=version("cli"))

app.command("styrminctl.commands.clusters:clusters_app", name="clusters")
app.command("styrminctl.commands.environments:environments_app", name="environments")
app.command("styrminctl.commands.drivers:drivers_app", name="drivers")
app.command("styrminctl.commands.deployments:deployments_app", name="deployments")
app.command("styrminctl.commands.backups:backups_app", name="backups")
app.command("styrminctl.commands.backup_storage_locations:backup_storage_locations_app", name="backup-locations")
app.command("styrminctl.commands.tasks:tasks_app", name="tasks")

app.register_install_completion_command()
