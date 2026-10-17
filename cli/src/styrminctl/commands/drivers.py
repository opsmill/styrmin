"""Application driver management commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from cyclopts import App, Parameter

from styrminctl import client
from styrminctl.labels import format_driver_version_label
from styrminctl.output import console, print_success, print_table, print_warning, styrmin_error_handler

if TYPE_CHECKING:
    from typing import Any

drivers_app = App(name="drivers", help="Manage application drivers.")


def _print_version_details(version: Any) -> None:  # noqa: ANN401
    """Print driver version details (shared by load-version and load-local-version)."""
    content_hash = getattr(version, "content_hash", None)
    source_commit_sha = getattr(version, "source_commit_sha", None)
    label = format_driver_version_label(
        version=version.version,
        content_hash=content_hash,
        source_commit_sha=source_commit_sha,
    )
    print_success(f"Application driver version '{label}' loaded (id: {version.id})")
    for warning in getattr(version, "load_warnings", None) or []:
        print_warning(warning)
    console.print(f"  Driver ID: {version.application_driver_id}")
    console.print(f"  Supported versions: {version.supported_versions}")
    if content_hash:
        console.print(f"  Content hash: {content_hash}")
    elif source_commit_sha:
        console.print(f"  Commit SHA: {source_commit_sha}")
    # Local versions keep their folder in source_path too; only a git version has a repository.
    driver_directory = getattr(version, "source_path", None)
    if driver_directory and getattr(version, "source_repository", None):
        console.print(f"  Driver directory: {driver_directory}")

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
    *,
    driver_directory: Annotated[
        str | None,
        Parameter(
            name="--driver-directory",
            help=(
                "Folder of the repository that holds driver.styrmin.yml, relative to the repository root. "
                "Default: the repository root."
            ),
        ),
    ] = None,
) -> None:
    """Load an application driver version from a remote git repository."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            version = await sdk.drivers.load_version(
                repository_url=repository_url, branch=branch, driver_directory=driver_directory
            )

    _print_version_details(version)


@drivers_app.command(name="load-local-version")
async def load_local_version(
    path: Annotated[str, Parameter(help="Local filesystem path to the driver directory.")],
) -> None:
    """Load an application driver version from a local directory."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            version = await sdk.drivers.load_local_version(path=path)

    _print_version_details(version)
