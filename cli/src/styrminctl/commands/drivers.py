"""Application driver management commands."""

from __future__ import annotations

import typer
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminError

from styrminctl.async_typer import AsyncTyper as Typer
from styrminctl.config import SETTINGS
from styrminctl.output import console, print_error, print_success, print_table

app = Typer()


def _get_client() -> StyrminClient:
    return StyrminClient(
        server_address=SETTINGS.server_address,
        timeout=SETTINGS.timeout,
        headers=SETTINGS.additional_headers,
    )


@app.command()
async def create(
    name: str = typer.Argument(..., help="Name of the application driver"),
) -> None:
    """Create a new application driver."""
    async with _get_client() as client:
        try:
            driver = await client.drivers.create(name=name)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Application driver '{driver.name}' created (id: {driver.id})")
    if driver.versions:
        rows = [
            {"id": str(v.id), "version": v.version, "supportedVersions": v.supported_versions} for v in driver.versions
        ]
        print_table(rows, columns=["id", "version", "supportedVersions"], title="Versions")


@app.command(name="load-version")
async def load_version(
    repository_url: str = typer.Argument(..., help="Git repository URL of the driver"),
    branch: str = typer.Argument(..., help="Git branch to load from"),
) -> None:
    """Load an application driver version from a remote git repository."""
    async with _get_client() as client:
        try:
            version = await client.drivers.load_version(repository_url=repository_url, branch=branch)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Application driver version '{version.version}' loaded (id: {version.id})")
    console.print(f"  Driver ID: {version.application_driver_id}")
    console.print(f"  Supported versions: {version.supported_versions}")

    if version.component_configs:
        rows = [
            {"id": str(cc.id), "name": cc.name, "config": str(cc.config) if cc.config else ""}
            for cc in version.component_configs
        ]
        print_table(rows, columns=["id", "name", "config"], title="Component Configs")

    if version.actions:
        rows = [{"name": a.name, "location": a.location, "image": a.image or ""} for a in version.actions]
        print_table(rows, columns=["name", "location", "image"], title="Actions")

    if version.helm_chart:
        chart = version.helm_chart
        console.print(f"  Helm chart: {chart.name} v{chart.version} ({chart.repository})")


@app.command(name="load-local-version")
async def load_local_version(
    path: str = typer.Argument(..., help="Local filesystem path to the driver directory"),
) -> None:
    """Load an application driver version from a local directory."""
    async with _get_client() as client:
        try:
            version = await client.drivers.load_local_version(path=path)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    print_success(f"Application driver version '{version.version}' loaded (id: {version.id})")
    console.print(f"  Driver ID: {version.application_driver_id}")
    console.print(f"  Supported versions: {version.supported_versions}")

    if version.component_configs:
        rows = [
            {"id": str(cc.id), "name": cc.name, "config": str(cc.config) if cc.config else ""}
            for cc in version.component_configs
        ]
        print_table(rows, columns=["id", "name", "config"], title="Component Configs")

    if version.actions:
        rows = [{"name": a.name, "location": a.location, "image": a.image or ""} for a in version.actions]
        print_table(rows, columns=["name", "location", "image"], title="Actions")

    if version.helm_chart:
        chart = version.helm_chart
        console.print(f"  Helm chart: {chart.name} v{chart.version} ({chart.repository})")
