"""Application driver resource operations."""

from __future__ import annotations

from styrmin_sdk._queries import load_query
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
from styrmin_sdk.resources._base import BaseResource


class DriverResource(BaseResource):
    async def list(self) -> list[ListApplicationDriversApplicationDrivers]:
        result = await self._transport.execute(load_query("list_application_drivers"))
        self._check_graphql_errors(result)
        data = ListApplicationDrivers.model_validate(result["data"])
        return data.application_drivers or []

    async def load_version(
        self, repository_url: str, branch: str
    ) -> LoadRemoteApplicationDriverVersionLoadRemoteApplicationDriverVersion:
        result = await self._transport.execute(
            load_query("load_version"),
            {"repositoryUrl": repository_url, "branch": branch},
        )
        self._check_graphql_errors(result)
        return self._parse(
            LoadRemoteApplicationDriverVersion,
            result["data"],
            "load_remote_application_driver_version",
            LoadRemoteApplicationDriverVersionLoadRemoteApplicationDriverVersion,
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
