from styrminctl.async_typer import AsyncTyper as Typer
from styrminctl.commands.backup_storage_locations import app as bsl_app
from styrminctl.commands.backups import app as backups_app
from styrminctl.commands.clusters import app as clusters_app
from styrminctl.commands.deployments import app as deployments_app
from styrminctl.commands.drivers import app as drivers_app
from styrminctl.commands.environments import app as environments_app
from styrminctl.commands.tasks import app as tasks_app

app = Typer(name="Styrmin CLI", pretty_exceptions_show_locals=False)

app.add_typer(clusters_app, name="clusters", help="Manage clusters")
app.add_typer(environments_app, name="environments", help="Manage environments")
app.add_typer(drivers_app, name="drivers", help="Manage application drivers")
app.add_typer(deployments_app, name="deployments", help="Manage deployments")
app.add_typer(backups_app, name="backups", help="Manage backups and restores")
app.add_typer(bsl_app, name="backup-locations", help="Manage backup storage locations")
app.add_typer(tasks_app, name="tasks", help="View tasks")
