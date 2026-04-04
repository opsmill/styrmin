"""Application driver management commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from cyclopts import App, Parameter

from styrminctl import client
from styrminctl.output import console, print_success, print_table, styrmin_error_handler
from styrminctl.types import validate_directory_exists

if TYPE_CHECKING:
    from typing import Any

drivers_app = App(name="drivers", help="Manage application drivers.")


def _print_version_details(version: Any) -> None:  # noqa: ANN401
    """Print driver version details (shared by load-version and load-local-version)."""
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


@drivers_app.command
async def create(name: Annotated[str, Parameter(help="Name of the application driver.")]) -> None:
    """Create a new application driver."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            driver = await sdk.drivers.create(name=name)  # type: ignore  # noqa: PGH003  # TODO: DriverResource.create() not yet in SDK

    print_success(f"Application driver '{driver.name}' created (id: {driver.id})")
    if driver.versions:
        rows = [
            {"id": str(v.id), "version": v.version, "supportedVersions": v.supported_versions} for v in driver.versions
        ]
        print_table(rows, columns=["id", "version", "supportedVersions"], title="Versions")


@drivers_app.command(name="load-version")
async def load_version(
    repository_url: Annotated[str, Parameter(help="Git repository URL of the driver.")],
    branch: Annotated[str, Parameter(help="Git branch to load from.")],
) -> None:
    """Load an application driver version from a remote git repository."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            version = await sdk.drivers.load_version(repository_url=repository_url, branch=branch)

    _print_version_details(version)


@drivers_app.command(name="load-local-version")
async def load_local_version(
    path: Annotated[
        str, Parameter(help="Local filesystem path to the driver directory.", validator=validate_directory_exists)
    ],
) -> None:
    """Load an application driver version from a local directory."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            version = await sdk.drivers.load_local_version(path=path)

    _print_version_details(version)
