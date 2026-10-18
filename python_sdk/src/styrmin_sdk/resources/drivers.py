"""Application driver resource operations."""

from __future__ import annotations

from typing import Any, overload

from styrmin_sdk._queries import load_query
from styrmin_sdk.exceptions import IncompatibleServerError
from styrmin_sdk.graphql._generated.list_application_drivers import (
    ListApplicationDrivers,
    ListApplicationDriversApplicationDrivers,
)
from styrmin_sdk.graphql._generated.load_local_application_driver_version import (
    LoadLocalApplicationDriverVersion,
    LoadLocalApplicationDriverVersionLoadLocalApplicationDriverVersion,
)
from styrmin_sdk.graphql._generated.load_remote_application_driver_version import (
    LoadRemoteApplicationDriverVersion,
    LoadRemoteApplicationDriverVersionLoadRemoteApplicationDriverVersion,
)
from styrmin_sdk.graphql._generated.load_version_with_driver_directory import (
    LoadVersionWithDriverDirectory,
    LoadVersionWithDriverDirectoryLoadRemoteApplicationDriverVersion,
)
from styrmin_sdk.resources._base import BaseResource

_DRIVER_DIRECTORY_UNKNOWN = "Unknown argument 'driverDirectory' on field 'Mutation.loadRemoteApplicationDriverVersion'"


def _raise_if_server_lacks_driver_directory(result: dict[str, Any]) -> None:
    """Raise :class:`IncompatibleServerError` when the server predates ``driverDirectory`` (#517)."""
    for error in result.get("errors") or []:
        if str(error.get("message", "")).startswith(_DRIVER_DIRECTORY_UNKNOWN):
            raise IncompatibleServerError(
                "this styrminctl or SDK sends a driver directory, which the Styrmin server does not accept: "
                "loadRemoteApplicationDriverVersion has no 'driverDirectory' argument before #517. "
                "Upgrade the Styrmin server, or load from the repository root without a driver directory.",
                "",
            )


class DriverResource(BaseResource):
    async def list(self) -> list[ListApplicationDriversApplicationDrivers]:
        """List the application drivers and their versions.

        Each version carries its source: ``source_type`` is ``git`` or ``local``. For a
        ``local`` version, ``source_path`` is the driver folder on the Styrmin server; for a
        ``git`` version, it is the driver directory, or ``None`` for a load from the
        repository root.
        """
        result = await self._transport.execute(load_query("list_application_drivers"))
        self._check_graphql_errors(result)
        data = ListApplicationDrivers.model_validate(result["data"])
        return data.application_drivers or []

    @overload
    async def load_version(
        self, repository_url: str, branch: str, driver_directory: None = None
    ) -> LoadRemoteApplicationDriverVersionLoadRemoteApplicationDriverVersion: ...

    @overload
    async def load_version(
        self, repository_url: str, branch: str, driver_directory: str
    ) -> LoadVersionWithDriverDirectoryLoadRemoteApplicationDriverVersion: ...

    async def load_version(
        self, repository_url: str, branch: str, driver_directory: str | None = None
    ) -> (
        LoadRemoteApplicationDriverVersionLoadRemoteApplicationDriverVersion
        | LoadVersionWithDriverDirectoryLoadRemoteApplicationDriverVersion
    ):
        """Load an application driver version from a branch of a git repository.

        Args:
            repository_url: URL of the git repository.
            branch: Branch to load from.
            driver_directory: Folder of the repository that holds ``driver.styrmin.yml``,
                relative to the repository root, such as ``drivers/infrahub``. ``None``
                loads from the repository root and works against older servers too. A
                driver directory needs a Styrmin server that accepts it (#517); an older
                server raises :class:`IncompatibleServerError`.

        Returns:
            The loaded driver version. With ``driver_directory``, it also carries the
            stored ``driver_directory``.
        """
        variables: dict[str, Any] = {"repositoryUrl": repository_url, "branch": branch}
        if driver_directory is None:
            result = await self._transport.execute(load_query("load_version"), variables)
            self._check_graphql_errors(result)
            return self._parse(
                LoadRemoteApplicationDriverVersion,
                result["data"],
                "load_remote_application_driver_version",
                LoadRemoteApplicationDriverVersionLoadRemoteApplicationDriverVersion,
            )
        variables["driverDirectory"] = driver_directory
        result = await self._transport.execute(load_query("load_version_with_driver_directory"), variables)
        _raise_if_server_lacks_driver_directory(result)
        self._check_graphql_errors(result)
        return self._parse(
            LoadVersionWithDriverDirectory,
            result["data"],
            "load_remote_application_driver_version",
            LoadVersionWithDriverDirectoryLoadRemoteApplicationDriverVersion,
        )

    async def load_local_version(self, path: str) -> LoadLocalApplicationDriverVersionLoadLocalApplicationDriverVersion:
        result = await self._transport.execute(
            load_query("load_local_version"),
            {"path": path},
        )
        self._check_graphql_errors(result)
        return self._parse(
            LoadLocalApplicationDriverVersion,
            result["data"],
            "load_local_application_driver_version",
            LoadLocalApplicationDriverVersionLoadLocalApplicationDriverVersion,
        )
